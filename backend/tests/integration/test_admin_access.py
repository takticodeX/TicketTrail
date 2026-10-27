"""Administrators of the instance see and may do everything; secrets stay write-only."""

import logging
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.fixtures.azure import FakeAzure
from tests.fixtures.repos import FixtureRepo
from tests.integration.helpers import (
    AZURE_PAT,
    GIT_TOKEN,
    azure_payload,
    bearer,
    create,
    create_project,
    git_payload,
    login,
    register,
)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("no_dns")]

API = "/api/v1"


class Person:
    def __init__(self, client: TestClient, email: str, name: str) -> None:
        self.email = email
        self.id: str = register(client, email, display_name=name)["id"]
        self.headers = bearer(login(client, email))


@pytest.fixture(autouse=True)
def board(azure: FakeAzure) -> FakeAzure:
    azure.work_items.update(range(1, 10))
    return azure


@pytest.fixture
def admin(client: TestClient) -> Person:
    return Person(client, "root@example.com", "Root")  # the first user is the admin


@pytest.fixture
def bob(client: TestClient, admin: Person) -> Person:
    return Person(client, "bob@example.com", "Bob")


@pytest.fixture
def project(client: TestClient, bob: Person, db_engine: Engine, tmp_path: Path) -> dict[str, Any]:
    """Bob's personal project, on a local repository."""
    origin = FixtureRepo(tmp_path / "origin")
    origin.commit("Fix AB#1")
    created = create_project(client, bob.headers)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE git_connections SET repo_url = :url, auth_type = 'none', "
                "username = NULL, secret_enc = NULL"
            ),
            {"url": origin.url},
        )
    return created


def bob_headers(client: TestClient) -> dict[str, str]:
    return bearer(login(client, "bob@example.com"))


def activity(client: TestClient, admin: Person) -> list[dict[str, Any]]:
    page = client.get(f"{API}/admin/activity", headers=admin.headers).json()
    items: list[dict[str, Any]] = page["items"]
    return items


def audit_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "app.audit"]


def test_admin_opens_any_project_as_owner(
    client: TestClient, admin: Person, project: dict[str, Any]
) -> None:
    seen = client.get(f"{API}/projects/{project['id']}", headers=admin.headers).json()
    assert (seen["role"], seen["owner"]["email"]) == ("owner", "bob@example.com")
    assert seen["admin_access"] is True
    own = client.get(f"{API}/projects/{project['id']}", headers=bob_headers(client)).json()
    assert own["admin_access"] is False


def test_admins_dashboard_lists_only_their_own_projects(
    client: TestClient, admin: Person, project: dict[str, Any]
) -> None:
    assert client.get(f"{API}/projects", headers=admin.headers).json()["total"] == 0


def test_admin_changes_syncs_and_deletes_someone_elses_project(
    client: TestClient,
    admin: Person,
    bob: Person,
    project: dict[str, Any],
    azure: FakeAzure,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="app.audit")
    url = f"{API}/projects/{project['id']}"
    assert client.get(url, headers=admin.headers).status_code == 200
    assert audit_lines(caplog) == []  # reading isn't recorded

    other = create(client, "git-connections", bob.headers, git_payload(name="Other repo"))
    changed = client.patch(
        url, headers=admin.headers, json={"name": "Renamed", "git_connection_id": other["id"]}
    )
    assert changed.status_code == 200, changed.text
    client.patch(
        url, headers=admin.headers, json={"git_connection_id": project["git_connection_id"]}
    )

    started = client.post(f"{url}/sync", headers=admin.headers, json={"dry_run": False})
    run_id = started.json()["run_id"]
    run = client.get(f"{API}/runs/{run_id}", headers=admin.headers).json()
    assert (run["status"], run["triggered_by"]["email"]) == ("success", "root@example.com")
    assert azure.count(1) == 1
    assert client.get(f"{API}/runs/{run_id}/items", headers=admin.headers).json()["total"] == 1
    assert client.delete(f"{API}/runs/{run_id}", headers=admin.headers).status_code == 204

    shared = client.post(
        f"{url}/shares", headers=admin.headers, json={"email": "nobody@example.com"}
    )
    assert shared.json()["error"]["code"] == "user_not_found"  # the owner check passed
    assert client.delete(url, headers=admin.headers).status_code == 204

    lines = audit_lines(caplog)
    assert len(lines) == len(activity(client, admin))
    assert all("root@example.com" in line for line in lines)
    # Newest first; the refused share left nothing.
    assert [
        (e["action"], e["resource_type"], e["resource_name"]) for e in activity(client, admin)
    ] == [
        ("delete", "project", "Renamed"),
        ("delete", "run", "run of Renamed"),
        ("sync", "project", "Renamed"),
        ("update", "project", "Renamed"),
        ("update", "project", "Main project"),
    ]
    assert {e["owner_label"] for e in activity(client, admin)} == {"bob@example.com"}


def test_admin_manages_someone_elses_connections_without_seeing_secrets(
    client: TestClient, admin: Person, bob: Person, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="app.audit")
    git = create(client, "git-connections", bob.headers, git_payload())
    azure = create(client, "azure-connections", bob.headers, azure_payload())
    url = f"{API}/git-connections/{git['id']}"
    read = client.get(url, headers=admin.headers)
    assert read.status_code == 200
    assert read.json()["has_secret"] is True
    assert GIT_TOKEN not in read.text

    listed = client.get(f"{API}/git-connections?owner_id={bob.id}", headers=admin.headers)
    assert [c["name"] for c in listed.json()["items"]] == ["App repo"]
    assert client.patch(url, headers=admin.headers, json={"name": "Renamed"}).status_code == 200
    tested = client.post(f"{API}/azure-connections/{azure['id']}/test", headers=admin.headers)
    assert tested.json()["ok"] is True
    assert client.delete(url, headers=admin.headers).status_code == 204
    assert [
        (e["action"], e["resource_type"], e["resource_name"]) for e in activity(client, admin)
    ] == [
        ("delete", "git_connection", "Renamed"),
        ("update", "git_connection", "App repo"),
    ]
    assert len(audit_lines(caplog)) == 2


def test_only_admins_list_another_users_connections(
    client: TestClient, admin: Person, bob: Person
) -> None:
    create(client, "git-connections", admin.headers, git_payload())
    response = client.get(f"{API}/git-connections?owner_id={admin.id}", headers=bob.headers)
    assert response.status_code == 404


def test_admin_lists_every_connection_with_its_owner(
    client: TestClient, admin: Person, bob: Person, project: dict[str, Any]
) -> None:
    org = create(client, "organizations", bob.headers, {"name": "Acme"})
    create(
        client,
        "azure-connections",
        bob.headers,
        azure_payload(name="Acme board", organization_id=org["id"]),
    )
    gits = client.get(f"{API}/admin/git-connections", headers=admin.headers).json()
    assert [(c["name"], c["owner"]["email"], c["projects"]) for c in gits["items"]] == [
        ("App repo", "bob@example.com", 1)
    ]
    azures = client.get(f"{API}/admin/azure-connections", headers=admin.headers).json()
    assert [
        (
            c["name"],
            c["owner"] and c["owner"]["email"],
            c["organization"] and c["organization"]["name"],
        )
        for c in azures["items"]
    ] == [("Acme board", "bob@example.com", None), ("Acme board", None, "Acme")]
    assert AZURE_PAT not in str(azures)
    assert client.get(f"{API}/admin/git-connections", headers=bob.headers).status_code == 403


def test_admin_acts_as_admin_of_every_organization(
    client: TestClient, admin: Person, bob: Person
) -> None:
    org = create(client, "organizations", bob.headers, {"name": "Acme"})
    url = f"{API}/organizations/{org['id']}"
    assert client.get(url, headers=admin.headers).json()["role"] == "admin"
    assert client.get(f"{url}/members", headers=admin.headers).status_code == 200
    renamed = client.patch(url, headers=admin.headers, json={"name": "Acme Inc"})
    assert renamed.json()["name"] == "Acme Inc"
    created = client.post(
        f"{API}/git-connections",
        headers=admin.headers,
        json=git_payload(name="Acme repo", organization_id=org["id"]),
    )
    assert created.status_code == 201
    # It isn't one of the admin's own organizations.
    assert client.get(f"{API}/organizations", headers=admin.headers).json() == []


def test_sharing_with_an_admin_is_pointless(
    client: TestClient, admin: Person, bob: Person, project: dict[str, Any]
) -> None:
    response = client.post(
        f"{API}/projects/{project['id']}/shares",
        headers=bob.headers,
        json={"email": admin.email, "role": "viewer"},
    )
    assert response.json()["error"]["code"] == "is_owner"


def test_a_regular_user_still_gets_404(client: TestClient, bob: Person, admin: Person) -> None:
    mine = create_project(client, admin.headers)
    assert client.get(f"{API}/projects/{mine['id']}", headers=bob.headers).status_code == 404


def test_organization_actions_are_recorded(
    client: TestClient, admin: Person, bob: Person, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="app.audit")
    org = create(client, "organizations", bob.headers, {"name": "Acme"})
    url = f"{API}/organizations/{org['id']}"
    client.get(url, headers=admin.headers)  # reading: not recorded
    client.patch(url, headers=admin.headers, json={"timezone": "UTC"})
    client.post(
        f"{API}/git-connections",
        headers=admin.headers,
        json=git_payload(name="Acme repo", organization_id=org["id"]),
    )
    events = activity(client, admin)
    assert [(e["action"], e["resource_type"], e["owner_label"]) for e in events] == [
        ("add a connection to", "organization", "organization Acme"),
        ("update", "organization", "organization Acme"),
    ]
    assert len(audit_lines(caplog)) == 2


def test_nothing_is_recorded_for_regular_users_or_own_data(
    client: TestClient, admin: Person, bob: Person, project: dict[str, Any]
) -> None:
    client.patch(f"{API}/projects/{project['id']}", headers=bob.headers, json={"name": "Mine"})
    mine = create_project(client, admin.headers, name="Admin's own")
    client.patch(f"{API}/projects/{mine['id']}", headers=admin.headers, json={"name": "Still mine"})
    assert activity(client, admin) == []


def test_only_admins_read_the_activity(client: TestClient, admin: Person, bob: Person) -> None:
    assert client.get(f"{API}/admin/activity", headers=bob.headers).status_code == 403


def test_activity_filters_by_administrator(
    client: TestClient, admin: Person, bob: Person, project: dict[str, Any]
) -> None:
    client.patch(f"{API}/projects/{project['id']}", headers=admin.headers, json={"name": "X"})
    mine = client.get(f"{API}/admin/activity?actor_id={admin.id}", headers=admin.headers).json()
    theirs = client.get(f"{API}/admin/activity?actor_id={bob.id}", headers=admin.headers).json()
    assert (mine["total"], theirs["total"]) == (1, 0)
