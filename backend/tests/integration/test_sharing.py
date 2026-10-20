"""Sharing projects with other users: the permission check for viewers, editors and owners."""

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
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
    def __init__(self, client: TestClient, email: str) -> None:
        self.email = email
        self.id: str = register(client, email, display_name=email.split("@")[0].title())["id"]
        self.headers = bearer(login(client, email))


@pytest.fixture(autouse=True)
def board(azure: FakeAzure) -> FakeAzure:
    azure.work_items.update(range(1, 10))
    return azure


@pytest.fixture
def owner(client: TestClient) -> Person:
    return Person(client, "olivia@example.com")  # the first user: also the admin


@pytest.fixture
def viewer(client: TestClient, owner: Person) -> Person:
    return Person(client, "victor@example.com")


@pytest.fixture
def editor(client: TestClient, owner: Person) -> Person:
    return Person(client, "edith@example.com")


@pytest.fixture
def stranger(client: TestClient, owner: Person) -> Person:
    return Person(client, "sam@example.com")


@pytest.fixture
def project(
    client: TestClient,
    owner: Person,
    viewer: Person,
    editor: Person,
    db_engine: Engine,
    tmp_path: Path,
) -> dict[str, Any]:
    """Olivia's project, shared with Victor (viewer) and Edith (editor), on a local repo."""
    origin = FixtureRepo(tmp_path / "origin")
    for index in range(1, 4):
        origin.commit(f"commit {index} AB#{index}")
    created = create_project(client, owner.headers)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE git_connections SET repo_url = :url, auth_type = 'none', "
                "username = NULL, secret_enc = NULL"
            ),
            {"url": origin.url},
        )
    share(client, owner, created, viewer.email, "viewer")
    share(client, owner, created, editor.email, "editor")
    return created


def share(client: TestClient, by: Person, project: dict[str, Any], email: str, role: str) -> Any:
    response = client.post(
        f"{API}/projects/{project['id']}/shares",
        headers=by.headers,
        json={"email": email, "role": role},
    )
    assert response.status_code == 201, response.text
    return response.json()


def sync(client: TestClient, who: Person, project: dict[str, Any], *, dry_run: bool) -> Any:
    return client.post(
        f"{API}/projects/{project['id']}/sync", headers=who.headers, json={"dry_run": dry_run}
    )


def error_code(response: Any) -> str:
    code: str = response.json()["error"]["code"]
    return code


# --- What each role sees ---------------------------------------------------------------------


def test_shared_project_shows_in_the_recipients_list(
    client: TestClient, owner: Person, viewer: Person, project: dict[str, Any]
) -> None:
    page = client.get(f"{API}/projects", headers=viewer.headers).json()
    assert page["total"] == 1
    seen = page["items"][0]
    assert seen["id"] == project["id"]
    assert seen["role"] == "viewer"
    assert seen["owner"] == {"id": owner.id, "display_name": "Olivia", "email": owner.email}
    assert seen["git_connection"]["name"] == "App repo"
    assert seen["azure_connection"] == {
        "id": project["azure_connection_id"],
        "name": "Acme board",
        "organization_url": "https://dev.azure.com/acme",
        "azure_project": "proj",
    }
    assert GIT_TOKEN not in str(page) and AZURE_PAT not in str(page)


def test_list_scopes_split_own_and_shared_projects(
    client: TestClient, viewer: Person, project: dict[str, Any]
) -> None:
    create_project(client, viewer.headers, name="Victor's own")

    def names(scope: str) -> list[tuple[str, str]]:
        page = client.get(f"{API}/projects?scope={scope}", headers=viewer.headers).json()
        return [(p["name"], p["role"]) for p in page["items"]]

    assert names("owned") == [("Victor's own", "owner")]
    assert names("shared") == [("Main project", "viewer")]
    assert names("all") == [("Main project", "viewer"), ("Victor's own", "owner")]


def test_owner_sees_how_many_users_a_project_is_shared_with(
    client: TestClient, owner: Person, project: dict[str, Any]
) -> None:
    seen = client.get(f"{API}/projects/{project['id']}", headers=owner.headers).json()
    assert (seen["role"], seen["shares"]) == ("owner", 2)


def test_recipient_does_not_get_the_owners_connections(
    client: TestClient, viewer: Person, editor: Person, project: dict[str, Any]
) -> None:
    for who in (viewer, editor):
        for path in ("git-connections", "azure-connections"):
            assert client.get(f"{API}/{path}", headers=who.headers).json()["total"] == 0
        response = client.get(
            f"{API}/git-connections/{project['git_connection_id']}", headers=who.headers
        )
        assert response.status_code == 404


def test_someone_it_is_not_shared_with_gets_404_everywhere(
    client: TestClient, owner: Person, stranger: Person, project: dict[str, Any]
) -> None:
    run_id = sync(client, owner, project, dry_run=True).json()["run_id"]
    pid = project["id"]
    calls = [
        ("GET", f"/projects/{pid}"),
        ("PATCH", f"/projects/{pid}"),
        ("DELETE", f"/projects/{pid}"),
        ("POST", f"/projects/{pid}/sync"),
        ("GET", f"/projects/{pid}/runs"),
        ("DELETE", f"/projects/{pid}/runs"),
        ("GET", f"/projects/{pid}/shares"),
        ("POST", f"/projects/{pid}/shares"),
        ("POST", f"/projects/{pid}/test-pattern"),
        ("GET", f"/runs/{run_id}"),
        ("GET", f"/runs/{run_id}/items"),
        ("POST", f"/runs/{run_id}/cancel"),
        ("DELETE", f"/runs/{run_id}"),
    ]
    bodies = {
        f"/projects/{pid}/shares": {"email": stranger.email},
        f"/projects/{pid}/test-pattern": {"samples": []},
    }
    for method, path in calls:
        response = client.request(
            method, API + path, headers=stranger.headers, json=bodies.get(path, {})
        )
        assert response.status_code == 404, (method, path, response.text)
    assert client.get(f"{API}/projects", headers=stranger.headers).json()["total"] == 0


# --- Viewer ----------------------------------------------------------------------------------


def test_viewer_reads_the_project_and_its_runs(
    client: TestClient, owner: Person, viewer: Person, project: dict[str, Any]
) -> None:
    run_id = sync(client, owner, project, dry_run=False).json()["run_id"]
    runs = client.get(f"{API}/projects/{project['id']}/runs", headers=viewer.headers).json()
    assert [r["id"] for r in runs["items"]] == [run_id]
    assert runs["items"][0]["triggered_by"]["email"] == owner.email
    items = client.get(f"{API}/runs/{run_id}/items", headers=viewer.headers).json()
    assert items["total"] == 3
    tested = client.post(
        f"{API}/projects/{project['id']}/test-pattern",
        headers=viewer.headers,
        json={"samples": ["fix AB#7"]},
    )
    assert tested.json()["results"][0]["ids"] == [7]


def test_viewer_can_start_a_dry_run_but_not_a_real_sync(
    client: TestClient, viewer: Person, project: dict[str, Any], azure: FakeAzure
) -> None:
    started = sync(client, viewer, project, dry_run=True)
    assert started.status_code == 202
    run = client.get(f"{API}/runs/{started.json()['run_id']}", headers=viewer.headers).json()
    assert run["status"] == "success"
    assert run["triggered_by"]["email"] == viewer.email

    refused = sync(client, viewer, project, dry_run=False)
    assert refused.status_code == 403
    assert error_code(refused) == "insufficient_role"
    assert azure.posts == 0


def test_viewer_whose_default_is_a_real_sync_is_refused(
    client: TestClient, owner: Person, viewer: Person, project: dict[str, Any]
) -> None:
    response = client.post(f"{API}/projects/{project['id']}/sync", headers=viewer.headers, json={})
    assert response.status_code == 403  # dry_run_default is off


def test_viewer_cannot_change_or_delete_anything(
    client: TestClient, owner: Person, viewer: Person, project: dict[str, Any]
) -> None:
    pid = project["id"]
    owners_run = sync(client, owner, project, dry_run=True).json()["run_id"]
    for method, path, body in [
        ("PATCH", f"/projects/{pid}", {"ticket_pattern": r"#(\d+)"}),
        ("DELETE", f"/projects/{pid}", None),
        ("DELETE", f"/projects/{pid}/runs", None),
        ("GET", f"/projects/{pid}/shares", None),
        ("POST", f"/projects/{pid}/shares", {"email": "x@example.com"}),
        ("POST", f"/runs/{owners_run}/cancel", None),
        ("DELETE", f"/runs/{owners_run}", None),
    ]:
        response = client.request(method, API + path, headers=viewer.headers, json=body)
        assert response.status_code == 403, (method, path, response.text)
        assert error_code(response) == "insufficient_role"


def test_viewer_manages_the_dry_runs_they_started(
    app: FastAPI, client: TestClient, viewer: Person, project: dict[str, Any]
) -> None:
    app.state.task_runner.run_queued_tasks = False
    queued = sync(client, viewer, project, dry_run=True).json()["run_id"]
    cancelled = client.post(f"{API}/runs/{queued}/cancel", headers=viewer.headers)
    assert cancelled.status_code == 202
    assert cancelled.json()["status"] == "cancelled"
    assert client.delete(f"{API}/runs/{queued}", headers=viewer.headers).status_code == 204


# --- Editor ----------------------------------------------------------------------------------


def test_editor_changes_settings_and_runs_real_syncs(
    client: TestClient, editor: Person, project: dict[str, Any], azure: FakeAzure
) -> None:
    pid = project["id"]
    changed = client.patch(
        f"{API}/projects/{pid}",
        headers=editor.headers,
        json={"name": "Renamed", "branches": ["main"], "schedule_cron": "0 * * * *"},
    )
    assert changed.status_code == 200, changed.text
    assert (changed.json()["name"], changed.json()["role"]) == ("Renamed", "editor")

    started = sync(client, editor, project, dry_run=False)
    assert started.status_code == 202
    run = client.get(f"{API}/runs/{started.json()['run_id']}", headers=editor.headers).json()
    assert (run["status"], run["comments_posted"]) == ("success", 3)
    assert azure.total_comments() == 3

    cleared = client.delete(f"{API}/projects/{pid}/runs", headers=editor.headers)
    assert cleared.json() == {"deleted": 1}


def test_editor_cannot_change_the_connections(
    client: TestClient, owner: Person, editor: Person, project: dict[str, Any]
) -> None:
    other = create(client, "git-connections", owner.headers, git_payload(name="Other repo"))
    response = client.patch(
        f"{API}/projects/{project['id']}",
        headers=editor.headers,
        json={"git_connection_id": other["id"]},
    )
    assert response.status_code == 403
    assert "owner" in response.json()["error"]["message"]
    # Sending the current connection (as the settings form does) is fine.
    same = client.patch(
        f"{API}/projects/{project['id']}",
        headers=editor.headers,
        json={
            "git_connection_id": project["git_connection_id"],
            "azure_connection_id": project["azure_connection_id"],
            "include_merge_commits": True,
        },
    )
    assert same.status_code == 200, same.text


def test_owner_can_still_change_the_connections(
    client: TestClient, owner: Person, project: dict[str, Any]
) -> None:
    other = create(client, "azure-connections", owner.headers, azure_payload(name="Other board"))
    response = client.patch(
        f"{API}/projects/{project['id']}",
        headers=owner.headers,
        json={"azure_connection_id": other["id"]},
    )
    assert response.status_code == 200
    assert response.json()["azure_connection"]["name"] == "Other board"


def test_editor_rename_is_checked_against_the_owners_names(
    client: TestClient, owner: Person, editor: Person, project: dict[str, Any]
) -> None:
    create_project(
        client,
        owner.headers,
        name="Taken",
        git_connection_id=project["git_connection_id"],
        azure_connection_id=project["azure_connection_id"],
    )
    response = client.patch(
        f"{API}/projects/{project['id']}", headers=editor.headers, json={"name": "Taken"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["message"] == "The owner already has a project with this name."


def test_editor_cannot_delete_the_project_or_manage_shares(
    client: TestClient, editor: Person, viewer: Person, project: dict[str, Any]
) -> None:
    pid = project["id"]
    for method, path, body in [
        ("DELETE", f"/projects/{pid}", None),
        ("GET", f"/projects/{pid}/shares", None),
        ("PATCH", f"/projects/{pid}/shares/{viewer.id}", {"role": "editor"}),
        ("DELETE", f"/projects/{pid}/shares/{viewer.id}", None),
    ]:
        response = client.request(method, API + path, headers=editor.headers, json=body)
        assert response.status_code == 403, (method, path)


def test_next_run_uses_the_owners_time_zone(
    client: TestClient, owner: Person, viewer: Person, project: dict[str, Any]
) -> None:
    client.patch(f"{API}/me", headers=owner.headers, json={"timezone": "Asia/Tokyo"})
    client.patch(
        f"{API}/projects/{project['id']}",
        headers=owner.headers,
        json={"schedule_cron": "0 9 * * *", "schedule_enabled": True},
    )
    seen = client.get(f"{API}/projects/{project['id']}", headers=viewer.headers).json()
    assert seen["next_run_at"][11:16] == "00:00"  # 09:00 in Tokyo
    assert seen["schedule_timezone"] == "Asia/Tokyo"


# --- Managing shares -------------------------------------------------------------------------


def test_owner_lists_changes_and_removes_shares(
    client: TestClient, owner: Person, viewer: Person, editor: Person, project: dict[str, Any]
) -> None:
    base = f"{API}/projects/{project['id']}/shares"
    listed = client.get(base, headers=owner.headers).json()
    assert [(s["user"]["email"], s["role"]) for s in listed] == [
        (editor.email, "editor"),
        (viewer.email, "viewer"),
    ]
    promoted = client.patch(f"{base}/{viewer.id}", headers=owner.headers, json={"role": "editor"})
    assert promoted.json()["role"] == "editor"
    assert client.delete(f"{base}/{editor.id}", headers=owner.headers).status_code == 204
    assert client.get(f"{API}/projects/{project['id']}", headers=editor.headers).status_code == 404
    assert client.delete(f"{base}/{editor.id}", headers=owner.headers).status_code == 404


def test_share_errors(
    app: FastAPI, client: TestClient, owner: Person, viewer: Person, project: dict[str, Any]
) -> None:
    base = f"{API}/projects/{project['id']}/shares"

    def post(email: str, role: str = "viewer") -> Any:
        return client.post(base, headers=owner.headers, json={"email": email, "role": role})

    assert error_code(post("nobody@example.com")) == "user_not_found"
    assert error_code(post(owner.email)) == "is_owner"
    assert error_code(post(viewer.email)) == "already_shared"
    assert post("x@example.com", role="owner").status_code == 422
    # A turned-off account looks like an unknown one.
    off = Person(client, "off@example.com")
    client.patch(f"{API}/admin/users/{off.id}", headers=owner.headers, json={"is_active": False})
    assert error_code(post(off.email)) == "user_not_found"


def test_share_email_is_case_insensitive(
    client: TestClient, owner: Person, stranger: Person, project: dict[str, Any]
) -> None:
    created = share(client, owner, project, "  SAM@Example.com ", "viewer")
    assert created["user"]["id"] == stranger.id


def test_recipient_can_leave_but_not_remove_others(
    client: TestClient, viewer: Person, editor: Person, project: dict[str, Any]
) -> None:
    base = f"{API}/projects/{project['id']}/shares"
    assert client.delete(f"{base}/{editor.id}", headers=viewer.headers).status_code == 403
    assert client.delete(f"{base}/{viewer.id}", headers=viewer.headers).status_code == 204
    assert client.get(f"{API}/projects", headers=viewer.headers).json()["total"] == 0


def test_deleting_the_project_removes_its_shares(
    client: TestClient, owner: Person, viewer: Person, project: dict[str, Any], db_engine: Engine
) -> None:
    assert (
        client.delete(f"{API}/projects/{project['id']}", headers=owner.headers).status_code == 204
    )
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM project_shares")).scalar() == 0


def test_run_author_survives_as_null_when_unknown(
    client: TestClient, owner: Person, project: dict[str, Any], db_engine: Engine
) -> None:
    run_id = sync(client, owner, project, dry_run=True).json()["run_id"]
    with db_engine.begin() as conn:
        conn.execute(text("UPDATE sync_runs SET triggered_by_id = NULL"))
    run = client.get(f"{API}/runs/{run_id}", headers=owner.headers).json()
    assert run["triggered_by"] is None
