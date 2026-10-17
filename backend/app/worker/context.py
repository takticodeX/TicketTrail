"""Per-process resources for tasks: settings, a database session factory, the secret box."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from redis import Redis
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.core.crypto import SecretBox
from app.db.session import create_db_engine, create_session_factory
from app.integrations.git.client import DEFAULT_ALLOWED_PROTOCOLS
from app.integrations.trackers.limits import ConcurrencyLimiter, NoLimit, RedisSlotLimiter

REPOS_DIR = Path("/data/repos")


@dataclass(frozen=True)
class WorkerContext:
    settings: Settings
    session_factory: sessionmaker[Session]
    secret_box: SecretBox
    # Mirror clones live in <repos_dir>/<project_id> (the repos_data volume).
    repos_dir: Path = REPOS_DIR
    # Tests use file:// fixture repositories; production only speaks HTTPS.
    git_protocols: str = DEFAULT_ALLOWED_PROTOCOLS
    # Shared by all workers to cap concurrent Azure requests per organization.
    redis: Redis | None = None
    # Waits between Azure retries; tests make it instant.
    sleep: Callable[[float], None] = time.sleep

    def azure_limiter(self, organization_url: str) -> ConcurrencyLimiter:
        if self.redis is None:
            return NoLimit()
        return RedisSlotLimiter.for_organization(
            self.redis, organization_url, self.settings.azure_max_concurrency
        )


@lru_cache
def get_worker_context() -> WorkerContext:
    """Created on first use, inside the forked worker process."""
    settings = get_settings()
    return WorkerContext(
        settings=settings,
        session_factory=create_session_factory(create_db_engine(settings.database_url)),
        secret_box=SecretBox.from_settings(settings),
        redis=Redis.from_url(settings.redis_url, socket_connect_timeout=5, socket_timeout=10),
    )
