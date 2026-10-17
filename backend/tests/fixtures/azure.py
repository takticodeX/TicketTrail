"""A fake Azure DevOps Boards, served through respx, for sync tests."""

import json
import re
import threading
from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

import httpx
import respx

ORG = "https://dev.azure.com/acme"
PROJECT = "proj"

_COMMENTS = re.compile(rf"{re.escape(ORG)}/{PROJECT}/_apis/wit/workItems/(\d+)/comments")


@dataclass
class FakeAzure:
    work_items: set[int] = field(default_factory=set)
    # What Azure holds: work item -> comment texts. The tests' source of truth.
    comments: dict[int, list[tuple[int, str]]] = field(default_factory=lambda: defaultdict(list))
    # Responses to return instead of handling the next calls (popped in order);
    # None handles that call normally.
    next_posts: list[httpx.Response | BaseException | None] = field(default_factory=list)
    next_reads: list[httpx.Response] = field(default_factory=list)
    # Called after a comment is stored, before the response returns (to simulate crashes).
    after_post: Callable[[int, str], None] | None = None
    posts: int = 0
    _ids: int = 1000
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def texts(self, work_item_id: int) -> list[str]:
        return [text for _, text in self.comments[work_item_id]]

    def count(self, work_item_id: int) -> int:
        return len(self.comments[work_item_id])

    def total_comments(self) -> int:
        return sum(len(c) for c in self.comments.values())

    # --- handlers ----------------------------------------------------------------------

    def _work_items(self, request: httpx.Request) -> httpx.Response:
        if self.next_reads:
            return self.next_reads.pop(0)
        ids = [int(i) for i in request.url.params["ids"].split(",")]
        value = [{"id": i, "fields": {}} if i in self.work_items else None for i in ids]
        return httpx.Response(200, json={"count": len(value), "value": value})

    def _post_comment(self, request: httpx.Request) -> httpx.Response:
        match = _COMMENTS.match(str(request.url).split("?")[0])
        assert match, request.url
        work_item_id = int(match.group(1))
        with self._lock:
            self.posts += 1
            planned = self.next_posts.pop(0) if self.next_posts else None
            if isinstance(planned, BaseException):
                raise planned
            if planned is not None:
                return planned
            if work_item_id not in self.work_items:
                return httpx.Response(404, json={"message": "not found"})
            self._ids += 1
            comment_id = self._ids
            text = json.loads(request.content)["text"]
            self.comments[work_item_id].append((comment_id, text))
        if self.after_post is not None:
            self.after_post(work_item_id, text)
        return httpx.Response(200, json={"id": comment_id, "text": text})

    def _list_comments(self, request: httpx.Request) -> httpx.Response:
        match = _COMMENTS.match(str(request.url).split("?")[0])
        assert match, request.url
        work_item_id = int(match.group(1))
        if work_item_id not in self.work_items:
            return httpx.Response(404, json={"message": "not found"})
        comments = [{"id": cid, "text": text} for cid, text in self.comments[work_item_id]]
        return httpx.Response(200, json={"totalCount": len(comments), "comments": comments})


@contextmanager
def fake_azure() -> Iterator[FakeAzure]:
    azure = FakeAzure()
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{ORG}/_apis/projects/{PROJECT}").mock(  # Test connection
            return_value=httpx.Response(200, json={"id": "p", "name": PROJECT})
        )
        router.get(f"{ORG}/{PROJECT}/_apis/wit/workitems").mock(side_effect=azure._work_items)
        router.post(url__regex=_COMMENTS.pattern).mock(side_effect=azure._post_comment)
        router.get(url__regex=_COMMENTS.pattern).mock(side_effect=azure._list_comments)
        yield azure
