"""Builds the Celery app. The API uses it only to send tasks and read their results."""

from celery import Celery

from app.config import Settings


def create_celery_app(settings: Settings) -> Celery:
    app = Celery(
        "tickettrail",
        broker=settings.redis_url,
        backend=settings.redis_url,
        include=["app.worker.tasks"],
    )
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        result_expires=600,
        timezone="UTC",
        enable_utc=True,
        broker_connection_retry_on_startup=True,
        broker_connection_timeout=5,
    )
    return app
