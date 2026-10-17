"""Admin users page and deleting run history."""

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.fixtures.azure import FakeAzure
from tests.fixtures.repos import FixtureRepo
from tests.integration.helpers import (
    PASSWORD,
    bearer,
    create_project,
    login,
    new_client,
    refresh_with,
    register,
    signed_in,
)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("no_dns")]


# --- Admin -----------------------------------------------------------------------------------


@pytest.fixture
def admin(client: TestClient) -> dict[str, str]:
    return signed_in(client, "admin@example.com")  # the first user is the admin


def test_admin_lists_users(client: TestClient, admin: dict[str, str]) -> None:
    bob = signed_in(client, "bob@example.com")
    create_project(client, bob)
    page = client.get("/api/v1/admin/users", headers=admin).json()
    assert page["total"] == 2
    assert [(u["email"], u["role"], u["projects"]) for u in page["items"]] == [
        ("admin@example.com", "admin", 0),
        ("bob@example.com", "user", 1),
    ]
    assert "password_hash" not in str(page)


def test_only_admins_can_use_the_admin_api(client: TestClient, admin: dict[str, str]) -> None:
    bob = signed_in(client, "bob@example.com")
    for method, path in [("GET", "/api/v1/admin/users"), ("PATCH", "/api/v1/admin/users/x")]:
        response = client.request(method, path, headers=bob, json={"is_active": False})
        assert response.status_code == 403, path
        assert response.json()["error"]["code"] == "forbidden"
    assert client.get("/api/v1/admin/users").status_code == 401


def test_turning_an_account_off_signs_it_out_at_once(
    app: FastAPI, client: TestClient, admin: dict[str, str]
) -> None:
    bob_id = register(client, "bob@example.com")["id"]
    bob_device = new_client(app)
    bob_token = login(bob_device, "bob@example.com")
    bob_cookie = bob_device.cookies.get("tt_refresh") or ""

    response = client.patch(
        f"/api/v1/admin/users/{bob_id}", headers=admin, json={"is_active": False}
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False

    assert client.get("/api/v1/me", headers=bearer(bob_token)).status_code == 401
    assert refresh_with(app, bob_cookie).status_code == 401
    denied = client.post(
        "/api/v1/auth/login", json={"email": "bob@example.com", "password": PASSWORD}
    )
    assert denied.json()["error"]["code"] == "account_disabled"

    client.patch(f"/api/v1/admin/users/{bob_id}", headers=admin, json={"is_active": True})
    login(client, "bob@example.com")


def test_admins_cannot_turn_themselves_off(client: TestClient, admin: dict[str, str]) -> None:
    me = client.get("/api/v1/me", headers=admin).json()
    response = client.patch(
        f"/api/v1/admin/users/{me['id']}", headers=admin, json={"is_active": False}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "cannot_disable_self"


def test_unknown_user_is_not_found(client: TestClient, admin: dict[str, str]) -> None:
    response = client.patch(
        "/api/v1/admin/users/00000000-0000-0000-0000-000000000000",
        headers=admin,
        json={"is_active": False},
    )
    assert response.status_code == 404


# --- Deleting run history --------------------------------------------------------------------


@pytest.fixture
def board(azure: FakeAzure) -> FakeAzure:
    azure.work_items.update({1, 2})
    return azure


@pytest.fixture
def project(
    client: TestClient, admin: dict[str, str], db_engine: Engine, tmp_path: Path
) -> dict[str, Any]:
    origin = FixtureRepo(tmp_path / "origin")
    origin.commit("AB#1")
    created = create_project(client, admin)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE git_connections SET repo_url = :url, auth_type = 'none', "
                "username = NULL, secret_enc = NULL"
            ),
            {"url": origin.url},
        )
    return created


def run(client: TestClient, headers: dict[str, str], project: dict[str, Any], dry: bool) -> str:
    run_id: str = client.post(
        f"/api/v1/projects/{project['id']}/sync", headers=headers, json={"dry_run": dry}
    ).json()["run_id"]
    return run_id


def test_delete_one_run(
    client: TestClient,
    admin: dict[str, str],
    project: dict[str, Any],
    board: FakeAzure,
    db_engine: Engine,
) -> None:
    run_id = run(client, admin, project, dry=True)
    assert client.delete(f"/api/v1/runs/{run_id}", headers=admin).status_code == 204
    assert client.get(f"/api/v1/runs/{run_id}", headers=admin).status_code == 404
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM sync_run_items")).scalar_one() == 0


def test_deleting_history_never_reposts(
    client: TestClient,
    admin: dict[str, str],
    project: dict[str, Any],
    board: FakeAzure,
    db_engine: Engine,
) -> None:
    real = run(client, admin, project, dry=False)
    assert board.count(1) == 1
    client.delete(f"/api/v1/runs/{real}", headers=admin)
    with db_engine.begin() as conn:
        conn.execute(text("DELETE FROM project_cursors"))  # rescan everything
    again = run(client, admin, project, dry=False)
    assert client.get(f"/api/v1/runs/{again}", headers=admin).json()["comments_posted"] == 0
    assert board.count(1) == 1


def test_clear_all_dry_runs_keeps_real_syncs(
    client: TestClient, admin: dict[str, str], project: dict[str, Any], board: FakeAzure
) -> None:
    dry_ids = [run(client, admin, project, dry=True) for _ in range(3)]
    real_id = run(client, admin, project, dry=False)

    response = client.delete(
        f"/api/v1/projects/{project['id']}/runs", headers=admin, params={"dry_run": "true"}
    )
    assert response.json() == {"deleted": 3}
    remaining = client.get(f"/api/v1/projects/{project['id']}/runs", headers=admin).json()
    assert [r["id"] for r in remaining["items"]] == [real_id]
    assert all(client.get(f"/api/v1/runs/{i}", headers=admin).status_code == 404 for i in dry_ids)


def test_active_runs_cannot_be_deleted(
    app: FastAPI, client: TestClient, admin: dict[str, str], project: dict[str, Any]
) -> None:
    app.state.task_runner.run_queued_tasks = False
    queued = run(client, admin, project, dry=True)
    response = client.delete(f"/api/v1/runs/{queued}", headers=admin)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "run_active"
    cleared = client.delete(f"/api/v1/projects/{project['id']}/runs", headers=admin)
    assert cleared.json() == {"deleted": 0}
    assert client.get(f"/api/v1/runs/{queued}", headers=admin).status_code == 200


def test_other_users_cannot_delete_runs(
    client: TestClient, admin: dict[str, str], project: dict[str, Any], board: FakeAzure
) -> None:
    run_id = run(client, admin, project, dry=True)
    bob = signed_in(client, "bob@example.com")
    assert client.delete(f"/api/v1/runs/{run_id}", headers=bob).status_code == 404
    assert client.delete(f"/api/v1/projects/{project['id']}/runs", headers=bob).status_code == 404
    assert client.get(f"/api/v1/runs/{run_id}", headers=admin).status_code == 200
