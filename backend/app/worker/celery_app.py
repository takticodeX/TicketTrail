"""Celery app for the worker and the scheduler (Celery Beat) processes."""

from typing import Any

from celery.signals import setup_logging

from app.config import get_settings
from app.core.logging import configure_logging
from app.worker.celery_factory import create_celery_app

celery_app = create_celery_app(get_settings())


@setup_logging.connect
def _json_logging(**_: Any) -> None:
    """Use TicketTrail's JSON, secret-scrubbing logging instead of Celery's own."""
    configure_logging(get_settings().log_level)
