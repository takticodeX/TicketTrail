"""Celery app for the worker and the scheduler (Celery Beat) processes.

The database-backed schedule arrives in Milestone 6.
"""

from app.config import get_settings
from app.worker.celery_factory import create_celery_app

celery_app = create_celery_app(get_settings())
