"""The work item search behind the review's picker, run by the worker.

The API never talks to a board itself; it asks the worker and waits, as for the
connection tests.
"""

import uuid
from typing import Any

from app.api.v1.schemas.review import WorkItemOption, WorkItemSearchResult
from app.db.models import BoardConnection, Project
from app.integrations.trackers.base import TrackerError
from app.worker.boards import BoardUnavailableError, open_board
from app.worker.connection_checks import TEST_TIMEOUT_SECONDS
from app.worker.context import WorkerContext

SEARCH_LIMIT = 50


def _search(context: WorkerContext, connection: BoardConnection, text: str) -> WorkItemSearchResult:
    try:
        with open_board(context, connection, timeout=TEST_TIMEOUT_SECONDS) as client:
            found = client.search_work_items(text, limit=SEARCH_LIMIT)
    except BoardUnavailableError as exc:
        return WorkItemSearchResult(ok=False, error=str(exc))
    except TrackerError as exc:
        return WorkItemSearchResult(ok=False, error=str(exc))
    return WorkItemSearchResult(
        ok=True,
        items=[
            WorkItemOption(id=w.id, title=w.title, type=w.type, state=w.state, closed=w.closed)
            for w in found
        ],
    )


def run_work_item_search(
    context: WorkerContext, project_id: uuid.UUID, text: str
) -> dict[str, Any]:
    """The API has already checked that the caller may review this project."""
    with context.session_factory() as db:
        project = db.get(Project, project_id)
        connection = db.get(BoardConnection, project.board_connection_id) if project else None
        if connection is None:
            return WorkItemSearchResult(ok=False, error="Project not found.").model_dump(
                mode="json"
            )
        return _search(context, connection, text).model_dump(mode="json")
