"""The administrator's view of all projects, and ownership transfers (a colleague leaves)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.integration.helpers import (
    azure_payload,
    bearer,
    create,
    create_project,
    git_payload,
    login,
    register,
)

pytestmark = pytest.mark.integration

API = "/api/v1"


class Person:
    def __init__(self, client: TestClient, email: str, name: str) -> None:
        self.email = email
        self.id: str = register(client, email, display_name=name)["id"]
        self.headers = bearer(login(client, email))


@pytest.fixture
def admin(client: TestClient) -> Person:
    return Person(client, "admin@example.com", "Admin")  # the first user is the admin


@pytest.fixture
def marco(client: TestClient, admin: Person) -> Person:
    return Person(client, "marco@example.com", "Marco")


@pytest.fixture
def anna(client: TestClient, admin: Person) -> Person:
    return Person(client, "anna@example.com", "Anna")


def transfer_project(client: TestClient, admin: Person, project_id: str, to: Person) -> Any:
    return client.post(
        f"{API}/admin/projects/{project_id}/transfer",
        headers=admin.headers,
        json={"to_user_id": to.id},
    )


def transfer_all(client: TestClient, admin: Person, previous: Person, to: Person) -> Any:
    return client.post(
        f"{API}/admin/users/{previous.id}/transfer",
        headers=admin.headers,
        json={"to_user_id": to.id},
    )


def names(client: TestClient, who: Person, path: str) -> list[str]:
    return [
        item["name"] for item in client.get(f"{API}/{path}", headers=who.headers).json()["items"]
    ]


def test_admin_lists_every_project_with_its_owner(
    client: TestClient, admin: Person, marco: Person, anna: Person
) -> None:
    create_project(client, marco.headers, name="Billing")
    create_project(client, anna.headers, name="Shop")
    page = client.get(f"{API}/admin/projects", headers=admin.headers).json()
    assert [(p["owner"]["email"], p["name"]) for p in page["items"]] == [
        ("anna@example.com", "Shop"),
        ("marco@example.com", "Billing"),
    ]
    first = page["items"][0]
    assert set(first) == {"id", "name", "owner", "organization", "shares", "created_at", "last_run"}
    only_marco = client.get(
        f"{API}/admin/projects?owner_id={marco.id}", headers=admin.headers
    ).json()
    assert [p["name"] for p in only_marco["items"]] == ["Billing"]


def test_admin_does_not_get_into_projects_otherwise(
    client: TestClient, admin: Person, marco: Person
) -> None:
    project = create_project(client, marco.headers)
    assert client.get(f"{API}/projects/{project['id']}", headers=admin.headers).status_code == 404
    assert client.get(f"{API}/projects", headers=admin.headers).json()["total"] == 0


def test_only_admins_can_transfer(
    client: TestClient, admin: Person, marco: Person, anna: Person
) -> None:
    project = create_project(client, marco.headers)
    for method, path in [
        ("GET", "/admin/projects"),
        ("GET", "/admin/transfers"),
        ("POST", f"/admin/projects/{project['id']}/transfer"),
        ("POST", f"/admin/users/{marco.id}/transfer"),
    ]:
        response = client.request(
            method, API + path, headers=marco.headers, json={"to_user_id": anna.id}
        )
        assert response.status_code == 403, path


def test_transfer_everything_when_a_colleague_leaves(
    client: TestClient, admin: Person, marco: Person, anna: Person, db_engine: Engine
) -> None:
    create_project(client, marco.headers, name="Billing")
    create(client, "git-connections", marco.headers, git_payload(name="Spare repo"))
    with db_engine.connect() as conn:
        secrets_before = (
            conn.execute(text("SELECT secret_enc FROM git_connections ORDER BY name"))
            .scalars()
            .all()
        )
    client.patch(f"{API}/admin/users/{marco.id}", headers=admin.headers, json={"is_active": False})

    response = transfer_all(client, admin, marco, anna)
    assert response.status_code == 200, response.text
    transfer = response.json()
    assert (transfer["projects_moved"], transfer["connections_moved"]) == (1, 3)
    assert transfer["connections_copied"] == 0
    assert transfer["from_user"]["email"] == marco.email
    assert transfer["admin"]["email"] == admin.email

    assert names(client, anna, "projects") == ["Billing"]
    assert names(client, anna, "git-connections") == ["App repo", "Spare repo"]
    assert names(client, anna, "azure-connections") == ["Acme board"]
    # Secrets moved as they were: still encrypted, and still there.
    with db_engine.connect() as conn:
        secrets_after = (
            conn.execute(text("SELECT secret_enc FROM git_connections ORDER BY name"))
            .scalars()
            .all()
        )
    assert secrets_after == secrets_before
    connections = client.get(f"{API}/git-connections", headers=anna.headers).json()["items"]
    assert all(c["has_secret"] for c in connections)


def test_names_the_new_owner_already_uses_get_a_suffix(
    client: TestClient, admin: Person, marco: Person, anna: Person
) -> None:
    create_project(client, marco.headers, name="Billing")
    create_project(client, anna.headers, name="Billing")
    transfer = transfer_all(client, admin, marco, anna).json()
    assert names(client, anna, "projects") == ["Billing", "Billing (from Marco)"]
    assert names(client, anna, "git-connections") == ["App repo", "App repo (from Marco)"]
    assert 'Project "Billing" renamed to "Billing (from Marco)"' in transfer["summary"]


def test_transfer_one_project_moves_its_unshared_connections(
    client: TestClient, admin: Person, marco: Person, anna: Person
) -> None:
    project = create_project(client, marco.headers, name="Billing")
    transfer = transfer_project(client, admin, project["id"], anna).json()
    assert (transfer["projects_moved"], transfer["connections_moved"]) == (1, 2)
    assert transfer["project_id"] == project["id"]
    assert names(client, marco, "git-connections") == []
    seen = client.get(f"{API}/projects/{project['id']}", headers=anna.headers).json()
    assert seen["role"] == "owner"
    assert seen["git_connection_id"] == project["git_connection_id"]


def test_connections_still_used_by_the_previous_owner_are_copied(
    client: TestClient, admin: Person, marco: Person, anna: Person
) -> None:
    first = create_project(client, marco.headers, name="Billing")
    create_project(
        client,
        marco.headers,
        name="Billing v2",
        git_connection_id=first["git_connection_id"],
        azure_connection_id=first["azure_connection_id"],
    )
    transfer = transfer_project(client, admin, first["id"], anna).json()
    assert (transfer["connections_moved"], transfer["connections_copied"]) == (0, 2)

    moved = client.get(f"{API}/projects/{first['id']}", headers=anna.headers).json()
    assert moved["git_connection_id"] != first["git_connection_id"]
    annas = client.get(f"{API}/git-connections", headers=anna.headers).json()["items"]
    assert [(c["id"], c["has_secret"]) for c in annas] == [(moved["git_connection_id"], True)]
    # Marco's other project still has its connections.
    assert names(client, marco, "git-connections") == ["App repo"]
    assert names(client, marco, "projects") == ["Billing v2"]


def test_new_owners_share_is_dropped_and_other_shares_stay(
    client: TestClient, admin: Person, marco: Person, anna: Person
) -> None:
    luca = Person(client, "luca@example.com", "Luca")
    project = create_project(client, marco.headers)
    for who in (anna, luca):
        client.post(
            f"{API}/projects/{project['id']}/shares",
            headers=marco.headers,
            json={"email": who.email, "role": "editor"},
        )
    transfer_project(client, admin, project["id"], anna)
    shares = client.get(f"{API}/projects/{project['id']}/shares", headers=anna.headers).json()
    assert [s["user"]["email"] for s in shares] == [luca.email]


def test_transfer_errors(client: TestClient, admin: Person, marco: Person, anna: Person) -> None:
    project = create_project(client, marco.headers)
    unknown = "00000000-0000-0000-0000-000000000000"
    response = client.post(
        f"{API}/admin/projects/{project['id']}/transfer",
        headers=admin.headers,
        json={"to_user_id": unknown},
    )
    assert response.status_code == 422
    assert transfer_project(client, admin, project["id"], marco).status_code == 422
    client.patch(f"{API}/admin/users/{anna.id}", headers=admin.headers, json={"is_active": False})
    assert transfer_project(client, admin, project["id"], anna).status_code == 422
    assert transfer_project(client, admin, unknown, marco).status_code == 404
    nothing = transfer_all(client, admin, admin, marco)
    assert nothing.status_code == 409
    assert nothing.json()["error"]["code"] == "nothing_to_transfer"


def test_transfers_are_recorded(
    client: TestClient, admin: Person, marco: Person, anna: Person
) -> None:
    project = create_project(client, marco.headers, name="Billing")
    create(client, "azure-connections", marco.headers, azure_payload(name="Spare board"))
    transfer_project(client, admin, project["id"], anna)
    transfer_all(client, admin, marco, anna)
    page = client.get(f"{API}/admin/transfers", headers=admin.headers).json()
    assert page["total"] == 2
    newest, oldest = page["items"]
    assert newest["project_id"] is None
    assert newest["summary"].startswith("Everything owned by marco@example.com")
    assert oldest["summary"].startswith('Project "Billing" from marco@example.com')
