"""Secret-leak test (spec section 12, M7): no plaintext token in logs or in the database."""

import logging
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.core.logging import JsonFormatter, SecretScrubber
from tests.fixtures.azure import FakeAzure
from tests.fixtures.repos import FixtureRepo
from tests.integration.helpers import create

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("no_dns")]

GIT_SECRET = "ghp_LEAKCANARY_git_0123456789"
AZURE_SECRET = "LEAKCANARY_azure_pat_9876543210"
PASSWORD = "LEAKCANARY-password-42"
CANARIES = [GIT_SECRET, AZURE_SECRET, PASSWORD]


class Capture(logging.Handler):
    """Collects every record as the production handler would write it."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.addFilter(SecretScrubber())
        self.setFormatter(JsonFormatter())
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


def every_text_value(db_engine: Engine) -> list[str]:
    with db_engine.connect() as conn:
        columns = conn.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' "
                "AND data_type IN ('text', 'character varying', 'ARRAY')"
            )
        ).all()
        values: list[str] = []
        for table, column in columns:
            # Identifiers come from information_schema, not from input.
            query = text(f'SELECT "{column}" FROM "{table}"')  # noqa: S608
            values.extend(str(v) for v in conn.execute(query).scalars())
    return values


def test_no_plaintext_secret_in_logs_or_database(
    app: FastAPI,
    client: TestClient,
    azure: FakeAzure,
    db_engine: Engine,
    tmp_path: Path,
) -> None:
    capture = Capture()
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(capture)
    root.setLevel(logging.DEBUG)
    try:
        client.post(
            "/api/v1/auth/register", json={"email": "leak@example.com", "password": PASSWORD}
        )
        login = client.post(
            "/api/v1/auth/login", json={"email": "leak@example.com", "password": PASSWORD}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        git = create(
            client,
            "git-connections",
            headers,
            {
                "name": "repo",
                "repo_url": "https://dev.azure.com/acme/proj/_git/app",
                "auth_type": "token",
                "username": "pat",
                "secret": GIT_SECRET,
            },
        )
        board = create(
            client,
            "azure-connections",
            headers,
            {
                "name": "board",
                "organization_url": "https://dev.azure.com/acme",
                "azure_project": "proj",
                "pat": AZURE_SECRET,
            },
        )
        client.post(f"/api/v1/git-connections/{git['id']}/test", headers=headers)
        client.post(f"/api/v1/azure-connections/{board['id']}/test", headers=headers)

        origin = FixtureRepo(tmp_path / "origin")
        origin.commit("Fix AB#1")
        origin.commit("Fix AB#2")
        with db_engine.begin() as conn:  # sync from the fixture repo, keeping the token
            conn.execute(text("UPDATE git_connections SET repo_url = :url"), {"url": origin.url})
        project = create(
            client,
            "projects",
            headers,
            {
                "name": "p",
                "git_connection_id": git["id"],
                "azure_connection_id": board["id"],
            },
        )
        azure.work_items.update({1, 2})
        azure.next_posts.append(httpx.Response(500, text=f"echo {AZURE_SECRET}"))
        for dry in (True, False):
            client.post(
                f"/api/v1/projects/{project['id']}/sync", headers=headers, json={"dry_run": dry}
            )
        client.get(f"/api/v1/projects/{project['id']}/runs", headers=headers)
    finally:
        root.removeHandler(capture)
        root.setLevel(previous_level)

    assert azure.total_comments() == 1  # the flow really ran (one post failed on purpose)
    logs = "\n".join(capture.lines)
    assert len(capture.lines) > 10
    database = every_text_value(db_engine)
    assert any(v.startswith("gAAAAA") for v in database)  # Fernet ciphertexts are there
    for canary in CANARIES:
        assert canary not in logs, f"{canary} leaked into the logs"
        assert not [v for v in database if canary in v], f"{canary} leaked into the database"
