"""The interface every work-item tracker implements. Azure Boards is the only one in v1."""

from typing import Protocol


class TrackerError(Exception):
    """A tracker call failed. The message is safe to show and store."""


class TrackerAuthError(TrackerError):
    """Credentials are invalid, expired or lack a scope. Stops the whole run."""


class TrackerNotFoundError(TrackerError):
    pass


class WorkItemTracker(Protocol):
    def test_connection(self) -> str:
        """Check credentials and project access; return the project's display name."""
        ...
