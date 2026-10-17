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

    def enqueue(self, name: str, args: list[Any]) -> None:
        """Queue a task without waiting for it."""
        ...


class CeleryTaskRunner:
    def __init__(self, celery: Celery) -> None:
        self._celery = celery

    def _send(self, name: str, args: list[Any]) -> Any:
        try:
            return self._celery.send_task(name, args=args, retry=False)
        except Exception as exc:  # broker down: kombu raises several error types
            logger.warning("Could not queue task %s", name, exc_info=True)
            raise WorkerUnavailableError("the task queue is unavailable") from exc

    def enqueue(self, name: str, args: list[Any]) -> None:
        self._send(name, args)

    def run(self, name: str, args: list[str], *, timeout: float) -> Any:
        result = self._send(name, args)
        try:
            return result.get(timeout=timeout)
        except CeleryTimeoutError as exc:
            result.forget()
            raise WorkerUnavailableError("no worker answered in time") from exc
