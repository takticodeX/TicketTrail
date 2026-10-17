"""Tenant isolation (spec sections 10 and 13): user B gets 404 on everything user A owns."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.integration.helpers import (
    AZURE_PAT,
    GIT_TOKEN,
    azure_payload,
    create_project,
    git_payload,
    signed_in,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def alice_resources(client: TestClient) -> dict[str, Any]:
    alice = signed_in(client, "alice@example.com")
    project = create_project(client, alice, name="Alice project")
    return {"headers": alice, "project": project}


def _endpoints(project: dict[str, Any]) -> list[tuple[str, str, dict[str, Any] | None]]:
    git = f"/api/v1/git-connections/{project['git_connection_id']}"
    azure = f"/api/v1/azure-connections/{project['azure_connection_id']}"
    proj = f"/api/v1/projects/{project['id']}"
    return [
        ("GET", git, None),
        ("PATCH", git, {"name": "stolen"}),
        ("DELETE", git, None),
        ("POST", f"{git}/test", None),
        ("GET", azure, None),
        ("PATCH", azure, {"name": "stolen"}),
        ("DELETE", azure, None),
        ("POST", f"{azure}/test", None),
        ("GET", proj, None),
        ("PATCH", proj, {"name": "stolen"}),
        ("DELETE", proj, None),
        ("POST", f"{proj}/test-pattern", {"samples": ["AB#1"]}),
    ]


def test_other_users_resources_are_not_found(
    client: TestClient, alice_resources: dict[str, Any]
) -> None:
    bob = signed_in(client, "bob@example.com")
    for method, path, body in _endpoints(alice_resources["project"]):
        response = client.request(method, path, headers=bob, json=body)
        assert response.status_code == 404, f"{method} {path} -> {response.status_code}"
        assert response.json()["error"]["code"] == "not_found"


def test_alices_resources_are_untouched(
    client: TestClient, alice_resources: dict[str, Any]
) -> None:
    bob = signed_in(client, "bob@example.com")
    for method, path, body in _endpoints(alice_resources["project"]):
        client.request(method, path, headers=bob, json=body)

    alice = alice_resources["headers"]
    project = alice_resources["project"]
    assert client.get(f"/api/v1/projects/{project['id']}", headers=alice).json()["name"] == (
        "Alice project"
    )
    git = client.get(f"/api/v1/git-connections/{project['git_connection_id']}", headers=alice)
    assert git.json()["name"] == "App repo"
    assert git.json()["last_test_ok"] is None  # Bob's test never ran


def test_lists_only_show_own_resources(client: TestClient, alice_resources: dict[str, Any]) -> None:
    bob = signed_in(client, "bob@example.com")
    for path in ("git-connections", "azure-connections", "projects"):
        page = client.get(f"/api/v1/{path}", headers=bob).json()
        assert page == {"items": [], "total": 0, "page": 1, "page_size": 25}


def test_cannot_build_a_project_on_someone_elses_connections(
    client: TestClient, alice_resources: dict[str, Any]
) -> None:
    bob = signed_in(client, "bob@example.com")
    project = alice_resources["project"]
    own_git = client.post("/api/v1/git-connections", headers=bob, json=git_payload()).json()
    own_azure = client.post("/api/v1/azure-connections", headers=bob, json=azure_payload()).json()

    for git_id, azure_id, field in [
        (project["git_connection_id"], own_azure["id"], "git_connection_id"),
        (own_git["id"], project["azure_connection_id"], "azure_connection_id"),
    ]:
        response = client.post(
            "/api/v1/projects",
            headers=bob,
            json={"name": "Sneaky", "git_connection_id": git_id, "azure_connection_id": azure_id},
        )
        assert response.status_code == 422
        assert response.json()["error"]["details"]["errors"][0]["loc"] == ["body", field]

    bob_project = client.post(
        "/api/v1/projects",
        headers=bob,
        json={
            "name": "Mine",
            "git_connection_id": own_git["id"],
            "azure_connection_id": own_azure["id"],
        },
    ).json()
    response = client.patch(
        f"/api/v1/projects/{bob_project['id']}",
        headers=bob,
        json={"git_connection_id": project["git_connection_id"]},
    )
    assert response.status_code == 422


def test_no_response_ever_contains_a_secret(
    client: TestClient, alice_resources: dict[str, Any]
) -> None:
    alice = alice_resources["headers"]
    project = alice_resources["project"]
    paths = [
        "/api/v1/git-connections",
        "/api/v1/azure-connections",
        "/api/v1/projects",
        f"/api/v1/git-connections/{project['git_connection_id']}",
        f"/api/v1/azure-connections/{project['azure_connection_id']}",
        f"/api/v1/projects/{project['id']}",
    ]
    for path in paths:
        text = client.get(path, headers=alice).text
        assert GIT_TOKEN not in text
        assert AZURE_PAT not in text
