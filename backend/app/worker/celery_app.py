"""Celery app shared by the worker and the scheduler (Celery Beat).

Milestone 2 stub: sync tasks arrive in Milestone 4, the database-backed
schedule in Milestone 6.
"""

from celery import Celery

from app.config import get_settings


def create_celery_app() -> Celery:
    settings = get_settings()
    app = Celery("tickettrail", broker=settings.redis_url, include=["app.worker.tasks"])
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        timezone="UTC",
        enable_utc=True,
        broker_connection_retry_on_startup=True,
    )
    return app


celery_app = create_celery_app()
