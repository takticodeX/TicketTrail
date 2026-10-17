"""AzureBoardsClient: work items, comments, retries and throttling (Azure mocked with respx)."""

import json
from collections.abc import Iterator
from contextlib import contextmanager

import httpx
import pytest
import respx

from app.integrations.trackers.azure import COMMENTS_API_VERSION, AzureBoardsClient
from app.integrations.trackers.base import (
    TrackerAuthError,
    TrackerError,
    TrackerNotFoundError,
    TrackerTransientError,
)

ORG = "https://dev.azure.com/acme"
ITEMS = f"{ORG}/Web%20App/_apis/wit/workitems"
COMMENTS = f"{ORG}/Web%20App/_apis/wit/workItems/12/comments"


class Sleeps(list[float]):
    def __call__(self, seconds: float) -> None:
        self.append(seconds)


@pytest.fixture
def sleeps() -> Sleeps:
    return Sleeps()


@pytest.fixture
def azure(sleeps: Sleeps) -> Iterator[AzureBoardsClient]:
    with AzureBoardsClient(ORG, "Web App", "pat", sleep=sleeps) as client:
        yield client


# --- Work items ------------------------------------------------------------------------------


@respx.mock
def test_existing_work_items_omits_missing_ones(azure: AzureBoardsClient) -> None:
    route = respx.get(ITEMS).mock(
        return_value=httpx.Response(200, json={"count": 3, "value": [{"id": 1}, None, {"id": 3}]})
    )
    assert azure.existing_work_items([3, 1, 2, 1]) == {1, 3}
    params = route.calls.last.request.url.params
    assert params["ids"] == "1,2,3"
    assert params["errorPolicy"] == "omit"
    assert params["fields"] == "System.Id,System.Title,System.WorkItemType"
    assert params["api-version"] == "7.1"


@respx.mock
def test_existence_is_checked_in_batches_of_200(azure: AzureBoardsClient) -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        ids = [int(i) for i in request.url.params["ids"].split(",")]
        return httpx.Response(200, json={"value": [{"id": i} for i in ids]})

    route = respx.get(ITEMS).mock(side_effect=answer)
    assert azure.existing_work_items(range(1, 451)) == set(range(1, 451))
    assert [len(c.request.url.params["ids"].split(",")) for c in route.calls] == [200, 200, 50]


@respx.mock
def test_no_ids_means_no_request(azure: AzureBoardsClient) -> None:
    route = respx.get(ITEMS)
    assert azure.existing_work_items([]) == set()
    assert not route.called


@respx.mock
def test_existence_check_with_bad_pat(azure: AzureBoardsClient) -> None:
    respx.get(ITEMS).mock(return_value=httpx.Response(401))
    with pytest.raises(TrackerAuthError):
        azure.existing_work_items([1])


# --- Comments --------------------------------------------------------------------------------


@respx.mock
def test_add_comment_posts_markdown(azure: AzureBoardsClient) -> None:
    route = respx.post(COMMENTS).mock(return_value=httpx.Response(200, json={"id": 987}))
    assert azure.add_comment(12, "**hello** tt:abc") == 987
    request = route.calls.last.request
    assert request.url.params["format"] == "markdown"
    assert request.url.params["api-version"] == COMMENTS_API_VERSION == "7.1-preview.4"
    assert json.loads(request.content) == {"text": "**hello** tt:abc"}


@respx.mock
def test_add_comment_to_missing_work_item(azure: AzureBoardsClient) -> None:
    respx.post(COMMENTS).mock(return_value=httpx.Response(404))
    with pytest.raises(TrackerNotFoundError):
        azure.add_comment(12, "x")


@respx.mock
def test_add_comment_refused_for_good(azure: AzureBoardsClient) -> None:
    respx.post(COMMENTS).mock(return_value=httpx.Response(400, json={"message": "too long"}))
    with pytest.raises(TrackerError) as exc:
        azure.add_comment(12, "x")
    assert not isinstance(exc.value, TrackerTransientError)


@respx.mock
def test_list_comments_follows_continuation_tokens(azure: AzureBoardsClient) -> None:
    pages = [
        httpx.Response(200, json={"comments": [{"id": 1, "text": "a"}], "continuationToken": "t1"}),
        httpx.Response(200, json={"comments": [{"id": 2, "text": "tt:abc"}]}),
    ]
    route = respx.get(COMMENTS).mock(side_effect=pages)
    comments = azure.list_comments(12)
    assert [(c.id, c.text) for c in comments] == [(1, "a"), (2, "tt:abc")]
    assert route.calls[1].request.url.params["continuationToken"] == "t1"


# --- Retries and throttling ------------------------------------------------------------------


@respx.mock
def test_429_honours_retry_after(azure: AzureBoardsClient, sleeps: Sleeps) -> None:
    respx.post(COMMENTS).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, json={"id": 1}),
        ]
    )
    assert azure.add_comment(12, "x") == 1
    assert sleeps == [7.0]


@respx.mock
def test_503_backs_off_exponentially_with_jitter(azure: AzureBoardsClient, sleeps: Sleeps) -> None:
    respx.post(COMMENTS).mock(
        side_effect=[httpx.Response(503)] * 4 + [httpx.Response(200, json={"id": 1})]
    )
    assert azure.add_comment(12, "x") == 1
    for wait, base in zip(sleeps, [1, 2, 4, 8], strict=True):
        assert base * 0.8 <= wait <= base * 1.2


@respx.mock
def test_gives_up_after_five_attempts(azure: AzureBoardsClient, sleeps: Sleeps) -> None:
    route = respx.post(COMMENTS).mock(return_value=httpx.Response(429))
    with pytest.raises(TrackerTransientError, match="5 attempts"):
        azure.add_comment(12, "x")
    assert route.call_count == 5
    assert len(sleeps) == 4


@respx.mock
def test_retry_after_is_capped_at_60_seconds(azure: AzureBoardsClient, sleeps: Sleeps) -> None:
    respx.get(ITEMS).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "3600"}),
            httpx.Response(200, json={"value": []}),
        ]
    )
    azure.existing_work_items([1])
    assert sleeps == [60.0]


@respx.mock
def test_timeouts_are_retried(azure: AzureBoardsClient) -> None:
    respx.post(COMMENTS).mock(
        side_effect=[httpx.ReadTimeout("slow"), httpx.Response(200, json={"id": 5})]
    )
    assert azure.add_comment(12, "x") == 5


@respx.mock
def test_rate_limit_delay_slows_the_next_request(azure: AzureBoardsClient, sleeps: Sleeps) -> None:
    respx.get(ITEMS).mock(
        return_value=httpx.Response(200, json={"value": []}, headers={"X-RateLimit-Delay": "2.5"})
    )
    azure.existing_work_items([1])
    assert sleeps == []
    azure.existing_work_items([2])
    assert sleeps == [2.5]


@respx.mock
def test_server_errors_are_transient(azure: AzureBoardsClient) -> None:
    respx.post(COMMENTS).mock(return_value=httpx.Response(502))
    with pytest.raises(TrackerTransientError, match="HTTP 502"):
        azure.add_comment(12, "x")


def test_every_request_takes_a_concurrency_slot(sleeps: Sleeps) -> None:
    taken: list[str] = []

    class CountingLimiter:
        @contextmanager
        def slot(self) -> Iterator[None]:
            taken.append("in")
            yield
            taken.append("out")

    with (
        respx.mock,
        AzureBoardsClient(ORG, "Web App", "pat", sleep=sleeps, limiter=CountingLimiter()) as azure,
    ):
        respx.post(COMMENTS).mock(
            side_effect=[httpx.Response(503), httpx.Response(200, json={"id": 1})]
        )
        azure.add_comment(12, "x")
    assert taken == ["in", "out", "in", "out"]  # released while waiting to retry
