import uuid
from collections.abc import Callable
from typing import Any

from app.sync.engine import run_sync
from app.worker import task_names
from app.worker.connection_checks import run_board_connection_check, run_git_connection_check
from app.worker.context import WorkerContext
from app.worker.runner import WorkerUnavailableError
from app.worker.work_items import run_work_item_search

_TASKS: dict[str, Callable[[WorkerContext, uuid.UUID], dict[str, Any]]] = {
    task_names.TEST_GIT_CONNECTION: run_git_connection_check,
    task_names.TEST_BOARD_CONNECTION: run_board_connection_check,
}


class InProcessTaskRunner:
    """Runs worker tasks synchronously, the way the Celery worker would."""

    def __init__(self, context: WorkerContext) -> None:
        self.context = context
        self.calls: list[tuple[str, list[Any]]] = []
        self.unavailable = False
        # Off: queued runs stay queued, to look at the API before the worker picks them up.
        self.run_queued_tasks = True

    def run(self, name: str, args: list[str], *, timeout: float) -> Any:
        self.calls.append((name, args))
        if self.unavailable:
            raise WorkerUnavailableError("no worker answered in time")
        if name == task_names.SEARCH_WORK_ITEMS:
            project_id, text = args
            return run_work_item_search(self.context, uuid.UUID(project_id), text)
        (connection_id,) = args
        return _TASKS[name](self.context, uuid.UUID(connection_id))

    def enqueue(self, name: str, args: list[Any]) -> None:
        self.calls.append((name, args))
        if self.unavailable:
            raise WorkerUnavailableError("the task queue is unavailable")
        assert name == task_names.SYNC_PROJECT
        _project_id, _trigger, _dry_run, run_id = args
        if self.run_queued_tasks:
            run_sync(self.context, uuid.UUID(run_id))
