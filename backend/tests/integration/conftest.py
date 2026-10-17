"""Integration fixtures: a real Postgres 16 (testcontainers), migrated with Alembic.

Set TT_TEST_DATABASE_URL to use an existing database instead of starting a container.
"""

import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import Engine, create_engine, text
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from app.config import Settings
from app.core.ratelimit import LoginRateLimiter
from app.main import create_app
from app.worker.context import WorkerContext
from tests.fixtures.azure import FakeAzure, fake_azure
from tests.integration.fakes import InProcessTaskRunner
from tests.integration.helpers import BROWSER_HEADERS

BACKEND_ROOT = Path(__file__).resolve().parents[2]
POSTGRES_IMAGE = "docker.io/library/postgres:16-alpine"
REDIS_IMAGE = "docker.io/library/redis:7-alpine"

pytestmark = pytest.mark.integration


def alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    existing = os.environ.get("TT_TEST_DATABASE_URL")
    if existing:
        yield existing
        return
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer(POSTGRES_IMAGE, driver="psycopg") as postgres:
        # Podman on Windows forwards ports on IPv4 only; "localhost" tries ::1 first
        # and every connection then waits for that attempt to time out.
        yield postgres.get_connection_url().replace("@localhost:", "@127.0.0.1:")


@pytest.fixture(scope="session")
def migrated_database_url(database_url: str) -> str:
    command.upgrade(alembic_config(database_url), "head")
    return database_url


@pytest.fixture(scope="session")
def db_engine(migrated_database_url: str) -> Iterator[Engine]:
    engine = create_engine(migrated_database_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def redis() -> Iterator[Redis]:
    """A real Redis 7, for the project lock and the Azure concurrency limit."""
    container = (
        DockerContainer(REDIS_IMAGE)
        .with_exposed_ports(6379)
        .waiting_for(LogMessageWaitStrategy("Ready to accept connections"))
    )
    with container:
        # 127.0.0.1, not localhost: Podman on Windows forwards ports on IPv4 only.
        client = Redis(host="127.0.0.1", port=int(container.get_exposed_port(6379)))
        yield client
        client.close()


@pytest.fixture(autouse=True)
def _clean_tables(request: pytest.FixtureRequest) -> Iterator[None]:
    yield
    if "db_engine" in request.fixturenames:
        engine: Engine = request.getfixturevalue("db_engine")
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE users, refresh_tokens, posted_comments CASCADE"))
    if "redis" in request.fixturenames:
        request.getfixturevalue("redis").flushdb()


@pytest.fixture
def no_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Treat every host as public, so tests don't depend on real DNS (or have file:// hosts)."""
    from app.sync import engine
    from app.worker import connection_checks

    monkeypatch.setattr(connection_checks, "check_public_host", lambda *_, **__: None)
    monkeypatch.setattr(engine, "check_public_host", lambda *_, **__: None)


@pytest.fixture
def azure() -> Iterator[FakeAzure]:
    """A fake Azure DevOps board at https://dev.azure.com/acme, project "proj"."""
    with fake_azure() as board:
        yield board


@pytest.fixture
def app_factory(
    migrated_database_url: str,
    make_settings: Callable[..., Settings],
    db_engine: Engine,
    tmp_path: Path,
    redis: Redis,
) -> Iterator[Callable[..., FastAPI]]:
    created: list[FastAPI] = []

    def factory(**overrides: Any) -> FastAPI:
        app = create_app(make_settings(database_url=migrated_database_url, **overrides))
        sleeps: list[float] = []
        # Run worker tasks in-process against the test database instead of via the
        # Celery queue, syncing from file:// fixture repositories into a temp directory.
        # The project lock and Azure limit use the real test Redis.
        app.state.task_runner = InProcessTaskRunner(
            WorkerContext(
                settings=app.state.settings,
                session_factory=app.state.session_factory,
                secret_box=app.state.secret_box,
                repos_dir=tmp_path / "repos",
                git_protocols="file",
                redis=redis,
                sleep=sleeps.append,  # retries wait instantly; tests can read the waits
            )
        )
        app.state.sleeps = sleeps
        # The API's own Redis points at a closed port (to test /ready); the login limit
        # uses the real one.
        app.state.login_limiter = LoginRateLimiter(redis)
        created.append(app)
        return app

    yield factory
    for app in created:
        app.state.engine.dispose()


@pytest.fixture
def app(app_factory: Callable[..., FastAPI]) -> FastAPI:
    return app_factory()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    # The browser app sends this header on every call; refresh and logout require it.
    with TestClient(app, headers=BROWSER_HEADERS) as test_client:
        yield test_client
