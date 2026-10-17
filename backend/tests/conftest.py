import os
from collections.abc import Callable
from typing import Any

import pytest
from cryptography.fernet import Fernet

from app.config import Settings

# Ryuk (the testcontainers reaper) needs the Docker socket mounted into a container,
# which rootless Podman doesn't allow. Containers are stopped by the fixtures instead.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

TEST_JWT_SECRET = "test-jwt-secret-that-is-long-enough-0123456789"


@pytest.fixture
def make_settings() -> Callable[..., Settings]:
    def factory(**overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "database_url": "postgresql+psycopg://unused:unused@127.0.0.1:1/unused",
            "redis_url": "redis://127.0.0.1:1/0",
            "encryption_key": Fernet.generate_key().decode(),
            "jwt_secret": TEST_JWT_SECRET,
            "public_url": "http://localhost:8080",
        }
        values.update(overrides)
        return Settings(**values)

    return factory
