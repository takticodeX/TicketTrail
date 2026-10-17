import uuid
from typing import Any

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


@celery_app.task(name=task_names.TEST_AZURE_CONNECTION)
def check_azure_connection(connection_id: str, owner_id: str) -> dict[str, Any]:
    return run_azure_connection_check(
        get_worker_context(), uuid.UUID(connection_id), uuid.UUID(owner_id)
    )
