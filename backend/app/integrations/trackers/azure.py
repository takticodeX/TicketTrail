"""Azure DevOps (Boards) REST client over httpx (spec section 6).

Every request goes through `_send`, which holds a concurrency slot for the
organization, retries throttling (429/503) with Retry-After or exponential
backoff with jitter, slows down when Azure sends X-RateLimit-Delay, and turns
responses into the tracker errors the engine understands.
"""

import base64
import logging
import random
import time
from collections.abc import Callable, Iterable
from typing import Any
from urllib.parse import quote

import httpx

from app.integrations.trackers.base import (
    TrackerAuthError,
    TrackerComment,
    TrackerError,
    TrackerNotFoundError,
    TrackerTransientError,
)
from app.integrations.trackers.limits import ConcurrencyLimiter, NoLimit

logger = logging.getLogger(__name__)

API_VERSION = "7.1"
# The comments API is still in preview; keep its version in this one place.
COMMENTS_API_VERSION = "7.1-preview.4"

AUTH_ERROR_MESSAGE = "PAT invalid, expired or missing scope (needs Work Items: Read & Write)."

MAX_ATTEMPTS = 5
MAX_BACKOFF_SECONDS = 60.0
EXISTENCE_BATCH = 200
RETRY_STATUSES = {429, 503}


def _auth_header(pat: str) -> str:
    return "Basic " + base64.b64encode(f":{pat}".encode()).decode()


def _header_seconds(response: httpx.Response, name: str) -> float | None:
    try:
        value = float(response.headers[name])
    except (KeyError, ValueError):
        return None
    return max(0.0, value)


class AzureBoardsClient:
    def __init__(
        self,
        organization_url: str,
        project: str,
        pat: str,
        *,
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
        limiter: ConcurrencyLimiter | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        self._org_url = organization_url.rstrip("/")
        self._project = project
        self._project_path = quote(project, safe="")
        self._limiter = limiter or NoLimit()
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._delay_next = 0.0
        self._http = httpx.Client(
            headers={"Authorization": _auth_header(pat), "Accept": "application/json"},
            timeout=timeout,
            follow_redirects=False,  # a redirect means "go sign in": treat as auth failure
            transport=transport,
        )

    def __enter__(self) -> "AzureBoardsClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    # --- Transport -----------------------------------------------------------------------

    def _backoff(self, attempt: int, response: httpx.Response | None) -> float:
        if response is not None:
            retry_after = _header_seconds(response, "Retry-After")
            if retry_after is not None:
                return min(retry_after, MAX_BACKOFF_SECONDS)
        base = min(2.0 ** (attempt - 1), MAX_BACKOFF_SECONDS)  # 1, 2, 4, 8 ... 60
        return min(base * random.uniform(0.8, 1.2), MAX_BACKOFF_SECONDS)  # noqa: S311

    def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        for attempt in range(1, self._max_attempts + 1):
            if self._delay_next:
                self._sleep(self._delay_next)
                self._delay_next = 0.0
            response: httpx.Response | None = None
            try:
                with self._limiter.slot():
                    response = self._http.request(method, url, **kwargs)
            except httpx.TimeoutException:
                failure = "Azure DevOps did not answer in time."
            except httpx.HTTPError as exc:
                failure = f"Could not reach Azure DevOps ({type(exc).__name__})."
            else:
                # Azure asks clients it is about to throttle to slow down.
                delay = _header_seconds(response, "X-RateLimit-Delay")
                if delay:
                    self._delay_next = min(delay, MAX_BACKOFF_SECONDS)
                if response.status_code not in RETRY_STATUSES:
                    return response
                failure = f"Azure DevOps is throttling requests (HTTP {response.status_code})."
            if attempt < self._max_attempts:
                wait = self._backoff(attempt, response)
                logger.info("Azure request failed (%s); retrying in %.1f s", failure, wait)
                self._sleep(wait)
        raise TrackerTransientError(f"{failure} Gave up after {self._max_attempts} attempts.")

    def _json(self, method: str, url: str, **kwargs: Any) -> Any:
        response = self._send(method, url, **kwargs)
        # Azure answers a bad PAT with 401/403, or with 203 / a redirect to a sign-in page.
        if response.status_code in (401, 403, 203) or response.is_redirect:
            raise TrackerAuthError(AUTH_ERROR_MESSAGE)
        if response.status_code == 404:
            raise TrackerNotFoundError("Not found.")
        if response.status_code >= 500:
            raise TrackerTransientError(f"Azure DevOps answered HTTP {response.status_code}.")
        if response.status_code >= 400:
            raise TrackerError(f"Azure DevOps refused the request (HTTP {response.status_code}).")
        if "json" not in response.headers.get("content-type", ""):
            raise TrackerAuthError(AUTH_ERROR_MESSAGE)
        return response.json()

    # --- Calls ---------------------------------------------------------------------------

    def test_connection(self) -> str:
        url = f"{self._org_url}/_apis/projects/{self._project_path}"
        try:
            body = self._json("GET", url, params={"api-version": API_VERSION})
        except TrackerNotFoundError as exc:
            raise TrackerNotFoundError(
                f"Project {self._project!r} was not found in this organization."
            ) from exc
        name = body.get("name") if isinstance(body, dict) else None
        if not isinstance(name, str):
            raise TrackerError("Unexpected answer from Azure DevOps.")
        return name

    def existing_work_items(self, ids: Iterable[int]) -> set[int]:
        wanted = sorted(set(ids))
        found: set[int] = set()
        url = f"{self._org_url}/{self._project_path}/_apis/wit/workitems"
        for start in range(0, len(wanted), EXISTENCE_BATCH):
            batch = wanted[start : start + EXISTENCE_BATCH]
            params = {
                "ids": ",".join(map(str, batch)),
                "fields": "System.Id,System.Title,System.WorkItemType",
                "errorPolicy": "omit",  # missing IDs come back as null instead of failing
                "api-version": API_VERSION,
            }
            try:
                body = self._json("GET", url, params=params)
            except TrackerNotFoundError:
                continue  # every ID in the batch is missing
            for item in body.get("value", []) if isinstance(body, dict) else []:
                if isinstance(item, dict) and isinstance(item.get("id"), int):
                    found.add(item["id"])
        return found

    def _comments_url(self, work_item_id: int) -> str:
        return f"{self._org_url}/{self._project_path}/_apis/wit/workItems/{work_item_id}/comments"

    def add_comment(self, work_item_id: int, text: str) -> int:
        body = self._json(
            "POST",
            self._comments_url(work_item_id),
            params={"format": "markdown", "api-version": COMMENTS_API_VERSION},
            json={"text": text},
        )
        comment_id = body.get("id") if isinstance(body, dict) else None
        if not isinstance(comment_id, int):
            raise TrackerError("Azure DevOps did not return the new comment's ID.")
        return comment_id

    def list_comments(self, work_item_id: int) -> list[TrackerComment]:
        comments: list[TrackerComment] = []
        params: dict[str, str] = {"api-version": COMMENTS_API_VERSION, "$top": "200"}
        while True:
            body = self._json("GET", self._comments_url(work_item_id), params=params)
            for comment in body.get("comments", []) if isinstance(body, dict) else []:
                if isinstance(comment, dict) and isinstance(comment.get("id"), int):
                    comments.append(TrackerComment(comment["id"], str(comment.get("text") or "")))
            token = body.get("continuationToken") if isinstance(body, dict) else None
            if not token:
                return comments
            params = {**params, "continuationToken": str(token)}
