import logging
import uuid
from typing import Any

from celery.signals import worker_ready

from app.db.models import SyncRun
from app.db.repositories import close_stale_runs
from app.sync.engine import run_sync, stale_after
from app.worker import task_names
from app.worker.celery_app import celery_app
from app.worker.connection_checks import run_azure_connection_check, run_git_connection_check
from app.worker.context import get_worker_context
from app.worker.runner import CeleryTaskRunner
from app.worker.scheduler import dispatch_due_schedules

logger = logging.getLogger(__name__)


@celery_app.task(name=task_names.PING)
def ping() -> str:
    """Smoke-test task: proves the worker consumes from the broker."""
    return "pong"


@celery_app.task(name=task_names.TEST_GIT_CONNECTION)
def check_git_connection(connection_id: str, owner_id: str | None = None) -> dict[str, Any]:
    """owner_id is ignored: kept so messages queued by an older API still run."""
    return run_git_connection_check(get_worker_context(), uuid.UUID(connection_id))


@celery_app.task(name=task_names.SYNC_PROJECT)
def sync_project(project_id: str, trigger: str, dry_run: bool, run_id: str | None = None) -> None:
    """Spec signature sync_project(project_id, trigger, dry_run).

    The API and the scheduler create the run row first and pass its run_id, so a
    queued run is visible straight away. Without one, the task creates the row.
    """
    context = get_worker_context()
    if run_id is None:
        with context.session_factory() as db:
            run = SyncRun(project_id=uuid.UUID(project_id), trigger=trigger, dry_run=dry_run)
            db.add(run)
            db.commit()
            run_id = str(run.id)
    run_sync(context, uuid.UUID(run_id))


@celery_app.task(name=task_names.DISPATCH_SCHEDULES)
def dispatch_schedules() -> int:
    """Called every minute by Celery Beat (the scheduler service)."""
    return len(dispatch_due_schedules(get_worker_context(), CeleryTaskRunner(celery_app)))


@celery_app.task(name=task_names.TEST_AZURE_CONNECTION)
def check_azure_connection(connection_id: str, owner_id: str | None = None) -> dict[str, Any]:
    """owner_id is ignored: kept so messages queued by an older API still run."""
    return run_azure_connection_check(get_worker_context(), uuid.UUID(connection_id))


@worker_ready.connect
def close_runs_left_by_a_crash(**_: Any) -> None:
    """A run whose heartbeat stopped long ago belonged to a worker that died."""
    context = get_worker_context()
    lock = context.project_lock()
    with context.session_factory() as db:
        closed = close_stale_runs(db, older_than=stale_after(context))
        db.commit()
    for run_id, project_id in closed:  # their locks would otherwise block for 30 minutes
        lock.release(project_id, run_id)
    if closed:
        logger.warning("Closed %d run(s) left behind by a stopped worker", closed)
