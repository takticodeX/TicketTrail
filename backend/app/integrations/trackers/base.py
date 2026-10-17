"""The interface every work-item tracker implements. Azure Boards is the only one in v1."""

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
    id: int
    text: str


class WorkItemTracker(Protocol):
    def test_connection(self) -> str:
        """Check credentials and project access; return the project's display name."""
        ...

    def existing_work_items(self, ids: Iterable[int]) -> set[int]:
        """The subset of `ids` that exist."""
        ...

    def add_comment(self, work_item_id: int, text: str) -> int:
        """Post a Markdown comment; return its ID."""
        ...

    def list_comments(self, work_item_id: int) -> list[TrackerComment]: ...
