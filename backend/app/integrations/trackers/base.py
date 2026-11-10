"""The interface every work-item tracker implements: Azure Boards and Planka.

Work item and comment IDs are strings: Azure's are small integers, Planka's are
too large for a JavaScript number.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol


class TrackerError(Exception):
    """A tracker call failed for good (retrying won't help). Safe to show and store."""


class TrackerAuthError(TrackerError):
    """Credentials are invalid, expired or lack a scope. Stops the whole run."""


class TrackerNotFoundError(TrackerError):
    pass


class TrackerTransientError(TrackerError):
    """Throttling, timeouts or server errors that outlasted the retries. May go away."""


@dataclass(frozen=True)
class TrackerComment:
    id: str
    text: str


@dataclass(frozen=True)
class TrackerWorkItem:
    id: str
    title: str
    type: str
    state: str
    closed: bool


class WorkItemTracker(Protocol):
    def __enter__(self) -> "WorkItemTracker": ...

    def __exit__(self, *_: object) -> None: ...

    def test_connection(self) -> str:
        """Check credentials and access; return the project's or board's display name."""
        ...

    def existing_work_items(self, ids: Iterable[str]) -> set[str]:
        """The subset of `ids` that exist."""
        ...

    def add_comment(self, work_item_id: str, text: str) -> str:
        """Post a Markdown comment; return its ID."""
        ...

    def list_comments(self, work_item_id: str) -> list[TrackerComment]: ...

    def search_work_items(self, text: str, *, limit: int) -> list[TrackerWorkItem]:
        """Work items whose title contains `text` (or with that ID), open ones first."""
        ...
