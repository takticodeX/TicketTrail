"""Azure DevOps (Boards) REST client over httpx.

Milestone 3 covers the connection test. Work-item lookups and comments come in
Milestone 5.
"""

import base64
from typing import Any
from urllib.parse import quote

import httpx

from app.integrations.trackers.base import TrackerAuthError, TrackerError, TrackerNotFoundError

API_VERSION = "7.1"
# The comments API is still in preview; keep its version in this one place.
COMMENTS_API_VERSION = "7.1-preview.4"

AUTH_ERROR_MESSAGE = "PAT invalid, expired or missing scope (needs Work Items: Read & Write)."


def _auth_header(pat: str) -> str:
    return "Basic " + base64.b64encode(f":{pat}".encode()).decode()


class AzureBoardsClient:
    def __init__(
        self,
        organization_url: str,
        project: str,
        pat: str,
        *,
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._org_url = organization_url.rstrip("/")
        self._project = project
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

    def _get_json(self, url: str, params: dict[str, str]) -> Any:
        try:
            response = self._http.get(url, params=params)
        except httpx.TimeoutException as exc:
            raise TrackerError("Azure DevOps did not answer in time.") from exc
        except httpx.HTTPError as exc:
            raise TrackerError(f"Could not reach Azure DevOps ({type(exc).__name__}).") from exc

        # Azure answers a bad PAT with 401/403, or with 203 / a redirect to a sign-in page.
        if response.status_code in (401, 403) or response.status_code == 203:
            raise TrackerAuthError(AUTH_ERROR_MESSAGE)
        if response.is_redirect:
            raise TrackerAuthError(AUTH_ERROR_MESSAGE)
        if response.status_code == 404:
            raise TrackerNotFoundError("Not found.")
        if response.status_code >= 400:
            raise TrackerError(f"Azure DevOps answered HTTP {response.status_code}.")
        if "json" not in response.headers.get("content-type", ""):
            raise TrackerAuthError(AUTH_ERROR_MESSAGE)
        return response.json()

    def test_connection(self) -> str:
        url = f"{self._org_url}/_apis/projects/{quote(self._project, safe='')}"
        try:
            body = self._get_json(url, {"api-version": API_VERSION})
        except TrackerNotFoundError as exc:
            raise TrackerNotFoundError(
                f"Project {self._project!r} was not found in this organization."
            ) from exc
        name = body.get("name") if isinstance(body, dict) else None
        if not isinstance(name, str):
            raise TrackerError("Unexpected answer from Azure DevOps.")
        return name
