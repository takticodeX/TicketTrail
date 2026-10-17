"""Builds the Celery app. The API uses it only to send tasks and read their results."""

from celery import Celery
from celery.schedules import crontab

from app.config import Settings
from app.worker import task_names


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
        # The scheduler service (Celery Beat) only ticks the dispatcher; the
        # schedules themselves are read from the database each minute.
        beat_schedule={
            "dispatch-due-schedules": {
                "task": task_names.DISPATCH_SCHEDULES,
                "schedule": crontab(),  # every minute
                "options": {"expires": 55},  # a late tick is dropped; the next one catches up
            }
        },
    )
    return app
