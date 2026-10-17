"""How the API hands work to the worker and waits for short answers (connection tests)."""

import logging
from typing import Any, Protocol

from celery import Celery
from celery.exceptions import TimeoutError as CeleryTimeoutError

logger = logging.getLogger(__name__)


class WorkerUnavailableError(Exception):
    """The task couldn't be queued, or no worker answered in time."""


class TaskRunner(Protocol):
    def run(self, name: str, args: list[str], *, timeout: float) -> Any:
        """Run a task on the worker and return its result."""
        ...


class CeleryTaskRunner:
    def __init__(self, celery: Celery) -> None:
        self._celery = celery

    def run(self, name: str, args: list[str], *, timeout: float) -> Any:
        try:
            result = self._celery.send_task(name, args=args, retry=False)
        except Exception as exc:  # broker down: kombu raises several error types
            logger.warning("Could not queue task %s", name, exc_info=True)
            raise WorkerUnavailableError("the task queue is unavailable") from exc
        try:
            return result.get(timeout=timeout)
        except CeleryTimeoutError as exc:
            result.forget()
            raise WorkerUnavailableError("no worker answered in time") from exc
