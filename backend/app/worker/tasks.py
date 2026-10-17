from app.worker.celery_app import celery_app


@celery_app.task(name="tickettrail.ping")
def ping() -> str:
    """Smoke-test task: proves the worker consumes from the broker."""
    return "pong"
