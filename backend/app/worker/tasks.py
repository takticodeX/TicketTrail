import logging
import uuid
from typing import Any

from celery.signals import worker_ready

from app.db.repositories import close_stale_runs
from app.sync.engine import run_sync, stale_after
from app.worker import task_names
from app.worker.celery_app import celery_app
from app.worker.connection_checks import run_azure_connection_check, run_git_connection_check
from app.worker.context import get_worker_context

logger = logging.getLogger(__name__)


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


@worker_ready.connect
def close_runs_left_by_a_crash(**_: Any) -> None:
    """A run whose heartbeat stopped long ago belonged to a worker that died."""
    context = get_worker_context()
    with context.session_factory() as db:
        closed = close_stale_runs(db, older_than=stale_after(context))
        db.commit()
    if closed:
        logger.warning("Closed %d run(s) left behind by a stopped worker", closed)
