"""Organizations: members, organization-owned connections and projects, moving projects."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.worker.scheduler import dispatch_due_schedules
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
def root(client: TestClient) -> Person:
    return Person(client, "root@example.com", "Root")  # the instance administrator


@pytest.fixture
def ada(client: TestClient, root: Person) -> Person:
    return Person(client, "ada@example.com", "Ada")  # creates the organization


@pytest.fixture
def ben(client: TestClient, root: Person) -> Person:
    return Person(client, "ben@example.com", "Ben")  # a member


@pytest.fixture
def cy(client: TestClient, root: Person) -> Person:
    return Person(client, "cy@example.com", "Cy")  # another member


@pytest.fixture
def eve(client: TestClient, root: Person) -> Person:
    return Person(client, "eve@example.com", "Eve")  # not a member


@pytest.fixture
def org(client: TestClient, ada: Person, ben: Person, cy: Person) -> dict[str, Any]:
    created = create(
        client, "organizations", ada.headers, {"name": "Acme", "timezone": "Asia/Tokyo"}
    )
    for who in (ben, cy):
        add_member(client, ada, created, who.email)
    return created


def add_member(
    client: TestClient, by: Person, org: dict[str, Any], email: str, role: str = "member"
) -> Any:
    return client.post(
        f"{API}/organizations/{org['id']}/members",
        headers=by.headers,
        json={"email": email, "role": role},
    )


def org_connections(client: TestClient, by: Person, org: dict[str, Any]) -> tuple[str, str]:
    git = create(
        client,
        "git-connections",
        by.headers,
        git_payload(name="Acme repo", organization_id=org["id"]),
    )
    azure = create(
        client,
        "azure-connections",
        by.headers,
        azure_payload(name="Acme board", organization_id=org["id"]),
    )
    return git["id"], azure["id"]


def org_project(
    client: TestClient, by: Person, org: dict[str, Any], connections: tuple[str, str], **extra: Any
) -> dict[str, Any]:
    git_id, azure_id = connections
    return create(
        client,
        "projects",
        by.headers,
        {
            "name": "Shop",
            "organization_id": org["id"],
            "git_connection_id": git_id,
            "azure_connection_id": azure_id,
            **extra,
        },
    )


def role_of(client: TestClient, who: Person, project_id: str) -> Any:
    response = client.get(f"{API}/projects/{project_id}", headers=who.headers)
    return response.json()["role"] if response.status_code == 200 else response.status_code


def code(response: Any) -> str:
    value: str = response.json()["error"]["code"]
    return value


# --- Organizations and members ---------------------------------------------------------------


def test_anyone_creates_an_organization_and_becomes_its_admin(
    client: TestClient, ada: Person
) -> None:
    client.patch(f"{API}/me", headers=ada.headers, json={"timezone": "Europe/Rome"})
    created = create(client, "organizations", ada.headers, {"name": "Acme"})
    assert (created["role"], created["members"], created["timezone"]) == ("admin", 1, "Europe/Rome")
    listed = client.get(f"{API}/organizations", headers=ada.headers).json()
    assert [o["name"] for o in listed] == ["Acme"]
    again = client.post(f"{API}/organizations", headers=ada.headers, json={"name": "acme"})
    assert code(again) == "name_taken"


def test_admins_manage_members(
    client: TestClient, ada: Person, ben: Person, eve: Person, org: dict[str, Any]
) -> None:
    members = client.get(f"{API}/organizations/{org['id']}/members", headers=ben.headers).json()
    assert [(m["user"]["email"], m["role"]) for m in members] == [
        ("ada@example.com", "admin"),
        ("ben@example.com", "member"),
        ("cy@example.com", "member"),
    ]
    assert code(add_member(client, ada, org, "nobody@example.com")) == "user_not_found"
    assert code(add_member(client, ada, org, ben.email)) == "already_member"
    assert add_member(client, ben, org, eve.email).status_code == 403  # members don't add

    promoted = client.patch(
        f"{API}/organizations/{org['id']}/members/{ben.id}",
        headers=ada.headers,
        json={"role": "admin"},
    )
    assert promoted.json()["role"] == "admin"


def test_someone_outside_gets_404(client: TestClient, eve: Person, org: dict[str, Any]) -> None:
    for method, path, body in [
        ("GET", f"/organizations/{org['id']}", None),
        ("PATCH", f"/organizations/{org['id']}", {"name": "Mine now"}),
        ("DELETE", f"/organizations/{org['id']}", None),
        ("GET", f"/organizations/{org['id']}/members", None),
        ("POST", f"/organizations/{org['id']}/members", {"email": eve.email}),
        ("GET", f"/git-connections?organization_id={org['id']}", None),
    ]:
        response = client.request(method, API + path, headers=eve.headers, json=body)
        assert response.status_code == 404, (method, path)
    assert client.get(f"{API}/organizations", headers=eve.headers).json() == []


def test_the_last_admin_cannot_leave_or_step_down(
    client: TestClient, ada: Person, ben: Person, org: dict[str, Any]
) -> None:
    base = f"{API}/organizations/{org['id']}/members"
    assert code(client.delete(f"{base}/{ada.id}", headers=ada.headers)) == "last_admin"
    demote = client.patch(f"{base}/{ada.id}", headers=ada.headers, json={"role": "member"})
    assert code(demote) == "last_admin"
    client.patch(f"{base}/{ben.id}", headers=ada.headers, json={"role": "admin"})
    assert client.delete(f"{base}/{ada.id}", headers=ada.headers).status_code == 204
    assert client.get(f"{API}/organizations/{org['id']}", headers=ada.headers).status_code == 404


def test_a_member_can_leave_but_not_remove_others(
    client: TestClient, ben: Person, cy: Person, org: dict[str, Any]
) -> None:
    base = f"{API}/organizations/{org['id']}/members"
    assert client.delete(f"{base}/{cy.id}", headers=ben.headers).status_code == 403
    assert client.delete(f"{base}/{ben.id}", headers=ben.headers).status_code == 204


def test_admins_rename_and_change_the_time_zone(
    client: TestClient, ada: Person, ben: Person, org: dict[str, Any]
) -> None:
    url = f"{API}/organizations/{org['id']}"
    assert client.patch(url, headers=ben.headers, json={"name": "X"}).status_code == 403
    bad = client.patch(url, headers=ada.headers, json={"timezone": "Mars/Base"})
    assert bad.status_code == 422
    changed = client.patch(url, headers=ada.headers, json={"name": "Acme Inc", "timezone": "UTC"})
    assert (changed.json()["name"], changed.json()["timezone"]) == ("Acme Inc", "UTC")


# --- Organization connections ----------------------------------------------------------------


def test_admins_create_connections_and_members_use_them(
    client: TestClient, ada: Person, ben: Person, eve: Person, org: dict[str, Any]
) -> None:
    git_id, _ = org_connections(client, ada, org)
    refused = client.post(
        f"{API}/git-connections",
        headers=ben.headers,
        json=git_payload(name="Ben's", organization_id=org["id"]),
    )
    assert refused.status_code == 403

    listed = client.get(
        f"{API}/git-connections?organization_id={org['id']}", headers=ben.headers
    ).json()
    assert [(c["name"], c["organization_id"], c["has_secret"]) for c in listed["items"]] == [
        ("Acme repo", org["id"], True)
    ]
    assert GIT_TOKEN not in str(listed)
    # Not in anyone's personal list.
    for who in (ada, ben):
        assert client.get(f"{API}/git-connections", headers=who.headers).json()["total"] == 0

    url = f"{API}/git-connections/{git_id}"
    assert client.get(url, headers=ben.headers).status_code == 200
    assert client.patch(url, headers=ben.headers, json={"name": "X"}).status_code == 403
    assert client.delete(url, headers=ben.headers).status_code == 403
    assert client.get(url, headers=eve.headers).status_code == 404
    assert client.patch(url, headers=ada.headers, json={"name": "Renamed"}).status_code == 200


def test_members_test_the_organizations_connections(
    client: TestClient, ada: Person, ben: Person, org: dict[str, Any]
) -> None:
    _, azure_id = org_connections(client, ada, org)
    result = client.post(f"{API}/azure-connections/{azure_id}/test", headers=ben.headers).json()
    assert result["ok"] is True


def test_connection_names_are_unique_per_organization(
    client: TestClient, ada: Person, org: dict[str, Any]
) -> None:
    org_connections(client, ada, org)
    create(client, "git-connections", ada.headers, git_payload(name="Acme repo"))  # personal: fine
    again = client.post(
        f"{API}/git-connections",
        headers=ada.headers,
        json=git_payload(name="Acme repo", organization_id=org["id"]),
    )
    assert again.json()["error"]["message"] == (
        "The organization already has a Git connection with this name."
    )


# --- Organization projects -------------------------------------------------------------------


def test_member_creates_a_project_and_edits_it_others_view_it(
    client: TestClient, ada: Person, ben: Person, cy: Person, eve: Person, org: dict[str, Any]
) -> None:
    project = org_project(client, ben, org, org_connections(client, ada, org))
    assert project["organization"] == {"id": org["id"], "name": "Acme"}
    assert project["owner"] is None
    assert project["role"] == "editor"  # the member who created it
    assert role_of(client, ada, project["id"]) == "owner"  # admins
    assert role_of(client, cy, project["id"]) == "viewer"  # other members
    assert role_of(client, eve, project["id"]) == 404

    cy_list = client.get(f"{API}/projects?scope=organizations", headers=cy.headers).json()
    assert [p["name"] for p in cy_list["items"]] == ["Shop"]
    assert client.get(f"{API}/projects?scope=shared", headers=cy.headers).json()["total"] == 0


def test_an_organization_project_uses_the_organizations_connections_only(
    client: TestClient, ada: Person, org: dict[str, Any]
) -> None:
    personal_git = create(client, "git-connections", ada.headers, git_payload())["id"]
    _, azure_id = org_connections(client, ada, org)
    response = client.post(
        f"{API}/projects",
        headers=ada.headers,
        json={
            "name": "Shop",
            "organization_id": org["id"],
            "git_connection_id": personal_git,
            "azure_connection_id": azure_id,
        },
    )
    assert response.status_code == 422


def test_a_share_raises_a_member_to_editor(
    client: TestClient, ada: Person, cy: Person, org: dict[str, Any]
) -> None:
    project = org_project(client, ada, org, org_connections(client, ada, org))
    assert role_of(client, cy, project["id"]) == "viewer"
    client.post(
        f"{API}/projects/{project['id']}/shares",
        headers=ada.headers,
        json={"email": cy.email, "role": "editor"},
    )
    assert role_of(client, cy, project["id"]) == "editor"
    assert role_of(client, cy, project["id"]) == "editor"
    as_admin = client.post(
        f"{API}/projects/{project['id']}/shares",
        headers=ada.headers,
        json={"email": ada.email, "role": "viewer"},
    )
    assert code(as_admin) == "is_owner"


def test_members_sync_by_their_role(
    client: TestClient,
    ada: Person,
    ben: Person,
    cy: Person,
    org: dict[str, Any],
    db_engine: Engine,
    tmp_path: Path,
    azure: FakeAzure,
) -> None:
    origin = FixtureRepo(tmp_path / "origin")
    origin.commit("Fix AB#1")
    project = org_project(client, ben, org, org_connections(client, ada, org))
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE git_connections SET repo_url = :url, auth_type = 'none', "
                "username = NULL, secret_enc = NULL"
            ),
            {"url": origin.url},
        )
    url = f"{API}/projects/{project['id']}/sync"
    assert client.post(url, headers=cy.headers, json={"dry_run": False}).status_code == 403
    assert client.post(url, headers=cy.headers, json={"dry_run": True}).status_code == 202
    started = client.post(url, headers=ben.headers, json={"dry_run": False})
    run = client.get(f"{API}/runs/{started.json()['run_id']}", headers=cy.headers).json()
    assert (run["status"], run["comments_posted"]) == ("success", 1)
    assert azure.count(1) == 1


def test_only_admins_change_connections_or_delete_projects(
    client: TestClient, ada: Person, ben: Person, org: dict[str, Any]
) -> None:
    connections = org_connections(client, ada, org)
    project = org_project(client, ben, org, connections)
    other = create(
        client, "git-connections", ada.headers, git_payload(name="Other", organization_id=org["id"])
    )
    url = f"{API}/projects/{project['id']}"
    change = {"git_connection_id": other["id"]}
    assert client.patch(url, headers=ben.headers, json=change).status_code == 403
    assert client.delete(url, headers=ben.headers).status_code == 403
    assert client.patch(url, headers=ada.headers, json=change).status_code == 200
    assert client.delete(url, headers=ada.headers).status_code == 204


def test_project_names_are_unique_per_organization(
    client: TestClient, ada: Person, org: dict[str, Any]
) -> None:
    connections = org_connections(client, ada, org)
    org_project(client, ada, org, connections)
    create_project(client, ada.headers, name="Shop")  # personal: fine
    git_id, azure_id = connections
    again = client.post(
        f"{API}/projects",
        headers=ada.headers,
        json={
            "name": "Shop",
            "organization_id": org["id"],
            "git_connection_id": git_id,
            "azure_connection_id": azure_id,
        },
    )
    assert (
        again.json()["error"]["message"] == "The organization already has a project with this name."
    )


def test_removing_a_member_ends_their_access(
    client: TestClient, ada: Person, cy: Person, org: dict[str, Any]
) -> None:
    project = org_project(client, ada, org, org_connections(client, ada, org))
    client.post(
        f"{API}/projects/{project['id']}/shares",
        headers=ada.headers,
        json={"email": cy.email, "role": "editor"},
    )
    client.delete(f"{API}/organizations/{org['id']}/members/{cy.id}", headers=ada.headers)
    assert role_of(client, cy, project["id"]) == 404


def test_schedules_run_in_the_organizations_time_zone(
    app: FastAPI, client: TestClient, ada: Person, org: dict[str, Any], db_engine: Engine
) -> None:
    project = org_project(
        client,
        ada,
        org,
        org_connections(client, ada, org),
        schedule_cron="0 9 * * *",
        schedule_enabled=True,
    )
    assert project["schedule_timezone"] == "Asia/Tokyo"
    assert project["next_run_at"][11:16] == "00:00"  # 09:00 in Tokyo
    with db_engine.begin() as conn:
        conn.execute(
            text("UPDATE projects SET schedule_last_fired_at = :when"),
            {"when": datetime(2026, 10, 15, 23, 0, tzinfo=UTC)},
        )
        # The creator's account doesn't matter for an organization's project.
        conn.execute(text("UPDATE users SET is_active = false WHERE email = 'ada@example.com'"))
    runner = app.state.task_runner
    runner.run_queued_tasks = False
    assert (
        dispatch_due_schedules(
            runner.context, runner, now=datetime(2026, 10, 15, 23, 59, tzinfo=UTC)
        )
        == []
    )
    started = dispatch_due_schedules(
        runner.context, runner, now=datetime(2026, 10, 16, 0, 0, tzinfo=UTC)
    )
    assert len(started) == 1


# --- Moving projects -------------------------------------------------------------------------


def test_moving_a_personal_project_into_the_organization(
    client: TestClient, ada: Person, ben: Person, cy: Person, org: dict[str, Any]
) -> None:
    project = create_project(client, ben.headers, name="Ben's app")
    moved = client.post(
        f"{API}/projects/{project['id']}/move",
        headers=ben.headers,
        json={"organization_id": org["id"]},
    )
    assert moved.status_code == 200, moved.text
    assert 'to organization "Acme"' in moved.json()["summary"]

    seen = client.get(f"{API}/projects/{project['id']}", headers=ben.headers).json()
    assert (seen["organization"]["name"], seen["role"]) == ("Acme", "editor")
    assert role_of(client, ada, project["id"]) == "owner"
    assert role_of(client, cy, project["id"]) == "viewer"
    # The connections went with it.
    assert client.get(f"{API}/git-connections", headers=ben.headers).json()["total"] == 0
    org_git = client.get(
        f"{API}/git-connections?organization_id={org['id']}", headers=ben.headers
    ).json()
    assert [c["name"] for c in org_git["items"]] == ["App repo"]


def test_connections_still_used_personally_are_copied_into_the_organization(
    client: TestClient, ada: Person, org: dict[str, Any]
) -> None:
    first = create_project(client, ada.headers, name="One")
    create_project(
        client,
        ada.headers,
        name="Two",
        git_connection_id=first["git_connection_id"],
        azure_connection_id=first["azure_connection_id"],
    )
    moved = client.post(
        f"{API}/projects/{first['id']}/move",
        headers=ada.headers,
        json={"organization_id": org["id"]},
    ).json()
    assert "copied" in moved["summary"]
    assert client.get(f"{API}/git-connections", headers=ada.headers).json()["total"] == 1


def test_moving_into_an_organization_you_are_not_in(
    client: TestClient, eve: Person, org: dict[str, Any]
) -> None:
    project = create_project(client, eve.headers)
    response = client.post(
        f"{API}/projects/{project['id']}/move",
        headers=eve.headers,
        json={"organization_id": org["id"]},
    )
    assert response.status_code == 404


def test_admins_move_a_project_out_to_a_member(
    client: TestClient, ada: Person, ben: Person, eve: Person, org: dict[str, Any]
) -> None:
    project = org_project(client, ada, org, org_connections(client, ada, org))
    url = f"{API}/projects/{project['id']}/move"
    assert client.post(url, headers=ben.headers, json={"to_user_id": ben.id}).status_code == 403
    assert client.post(url, headers=ada.headers, json={"to_user_id": eve.id}).status_code == 422
    moved = client.post(url, headers=ada.headers, json={"to_user_id": ben.id})
    assert moved.status_code == 200, moved.text
    assert role_of(client, ben, project["id"]) == "owner"
    assert role_of(client, ada, project["id"]) == 404
    assert [
        c["name"] for c in client.get(f"{API}/git-connections", headers=ben.headers).json()["items"]
    ] == ["Acme repo"]


def test_move_needs_exactly_one_target(
    client: TestClient, ada: Person, org: dict[str, Any]
) -> None:
    project = create_project(client, ada.headers)
    url = f"{API}/projects/{project['id']}/move"
    assert client.post(url, headers=ada.headers, json={}).status_code == 422
    both = {"organization_id": org["id"], "to_user_id": ada.id}
    assert client.post(url, headers=ada.headers, json=both).status_code == 422
    assert code(client.post(url, headers=ada.headers, json={"to_user_id": ada.id})) == (
        "not_in_organization"
    )


# --- Deleting --------------------------------------------------------------------------------


def test_an_organization_is_deleted_only_when_empty(
    client: TestClient, ada: Person, ben: Person, org: dict[str, Any]
) -> None:
    git_id, azure_id = org_connections(client, ada, org)
    url = f"{API}/organizations/{org['id']}"
    assert client.delete(url, headers=ben.headers).status_code == 403
    busy = client.delete(url, headers=ada.headers)
    assert code(busy) == "organization_not_empty"
    assert busy.json()["error"]["details"] == {"projects": 0, "connections": 2}
    client.delete(f"{API}/git-connections/{git_id}", headers=ada.headers)
    client.delete(f"{API}/azure-connections/{azure_id}", headers=ada.headers)
    assert client.delete(url, headers=ada.headers).status_code == 204


# --- The instance administrator --------------------------------------------------------------


def test_admin_sees_organizations_and_names_an_admin(
    client: TestClient,
    root: Person,
    ada: Person,
    ben: Person,
    org: dict[str, Any],
    db_engine: Engine,
) -> None:
    with db_engine.begin() as conn:  # the only admin's account was deleted
        conn.execute(text("DELETE FROM users WHERE email = 'ada@example.com'"))
    listed = client.get(f"{API}/admin/organizations", headers=root.headers).json()
    assert [(o["name"], o["members"], o["admins"]) for o in listed["items"]] == [("Acme", 2, [])]

    assert client.get(f"{API}/admin/organizations", headers=ben.headers).status_code == 403
    not_member = client.post(
        f"{API}/admin/organizations/{org['id']}/admins",
        headers=root.headers,
        json={"user_id": root.id},
    )
    assert not_member.status_code == 422
    promoted = client.post(
        f"{API}/admin/organizations/{org['id']}/admins",
        headers=root.headers,
        json={"user_id": ben.id},
    ).json()
    assert [a["email"] for a in promoted["admins"]] == ["ben@example.com"]


def test_admin_project_list_shows_organizations_and_refuses_their_transfer(
    client: TestClient, root: Person, ada: Person, ben: Person, org: dict[str, Any]
) -> None:
    project = org_project(client, ada, org, org_connections(client, ada, org))
    create_project(client, ben.headers, name="Ben's")
    items = client.get(f"{API}/admin/projects", headers=root.headers).json()["items"]
    assert [
        (
            p["name"],
            p["owner"] and p["owner"]["email"],
            p["organization"] and p["organization"]["name"],
        )
        for p in items
    ] == [
        ("Ben's", "ben@example.com", None),
        ("Shop", None, "Acme"),
    ]
    refused = client.post(
        f"{API}/admin/projects/{project['id']}/transfer",
        headers=root.headers,
        json={"to_user_id": ben.id},
    )
    assert code(refused) == "organization_project"


def test_transfer_everything_leaves_organization_rows_alone(
    client: TestClient, root: Person, ada: Person, ben: Person, org: dict[str, Any]
) -> None:
    org_connections(client, ada, org)
    create_project(client, ada.headers, name="Personal")
    transfer = client.post(
        f"{API}/admin/users/{ada.id}/transfer", headers=root.headers, json={"to_user_id": ben.id}
    ).json()
    assert (transfer["projects_moved"], transfer["connections_moved"]) == (1, 2)
    org_git = client.get(
        f"{API}/git-connections?organization_id={org['id']}", headers=ben.headers
    ).json()
    assert [c["name"] for c in org_git["items"]] == ["Acme repo"]
    assert AZURE_PAT not in str(transfer)
