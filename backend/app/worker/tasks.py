import uuid
from typing import Any

from app.sync.engine import run_sync
from app.worker import task_names
from app.worker.celery_app import celery_app
from app.worker.connection_checks import run_azure_connection_check, run_git_connection_check
from app.worker.context import get_worker_context


@celery_app.task(name=task_names.PING)
def ping() -> str:
    """Smoke-test task: proves the worker consumes from the broker."""
    return "pong"


@celery_app.task(name=task_names.TEST_GIT_CONNECTION)
def check_git_connection(connection_id: str, owner_id: str) -> dict[str, Any]:
    return run_git_connection_check(
        get_worker_context(), uuid.UUID(connection_id), uuid.UUID(owner_id)
    )


@celery_app.task(name=task_names.SYNC_PROJECT)
def sync_project(project_id: str, trigger: str, dry_run: bool, run_id: str | None = None) -> None:
    """Spec signature sync_project(project_id, trigger, dry_run).

    Manual runs pass the run_id of the row the API already created. Scheduled
    runs (Milestone 6) will let the task create its own row.
    """
    if run_id is None:
        raise NotImplementedError("scheduled runs arrive in Milestone 6")
    run_sync(get_worker_context(), uuid.UUID(run_id))


@celery_app.task(name=task_names.TEST_AZURE_CONNECTION)
def check_azure_connection(connection_id: str, owner_id: str) -> dict[str, Any]:
    return run_azure_connection_check(
        get_worker_context(), uuid.UUID(connection_id), uuid.UUID(owner_id)
    )
