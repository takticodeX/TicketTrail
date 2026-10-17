"""Per-process resources for tasks: settings, a database session factory, the secret box."""

from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.core.crypto import SecretBox
from app.db.session import create_db_engine, create_session_factory


@dataclass(frozen=True)
class WorkerContext:
    settings: Settings
    session_factory: sessionmaker[Session]
    secret_box: SecretBox


@lru_cache
def get_worker_context() -> WorkerContext:
    """Created on first use, inside the forked worker process."""
    settings = get_settings()
    return WorkerContext(
        settings=settings,
        session_factory=create_session_factory(create_db_engine(settings.database_url)),
        secret_box=SecretBox.from_settings(settings),
    )
