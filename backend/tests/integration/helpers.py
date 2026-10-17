from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

PASSWORD = "correct-horse-battery"
# What the frontend sends on every request (CSRF protection on refresh and logout).
BROWSER_HEADERS = {"X-Requested-With": "TicketTrail"}


def register(client: TestClient, email: str, password: str = PASSWORD, **extra: Any) -> Any:
    response = client.post(
        "/api/v1/auth/register", json={"email": email, "password": password, **extra}
    )
    assert response.status_code == 201, response.text
    return response.json()


def login(client: TestClient, email: str, password: str = PASSWORD) -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    return token


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def refresh_with(app: FastAPI, refresh_token: str) -> Any:
    """POST /auth/refresh from a fresh client that sends only the given cookie.

    No `with` block: that would run the app's shutdown and dispose the shared engine.
    """
    other = TestClient(app, headers=BROWSER_HEADERS)
    return other.post("/api/v1/auth/refresh", headers={"Cookie": f"tt_refresh={refresh_token}"})


def new_client(app: FastAPI) -> TestClient:
    """A second browser/device for the same app (see refresh_with about `with`)."""
    return TestClient(app, headers=BROWSER_HEADERS)


def signed_in(client: TestClient, email: str) -> dict[str, str]:
    """Register a user and return their Authorization header."""
    register(client, email)
    return bearer(login(client, email))


GIT_TOKEN = "ghp_plaintext-git-token-123"
AZURE_PAT = "plaintext-azure-pat-456"


def git_payload(**overrides: Any) -> dict[str, Any]:
    return {
        "name": "App repo",
        "repo_url": "https://dev.azure.com/acme/proj/_git/app",
        "auth_type": "token",
        "username": "pat",
        "secret": GIT_TOKEN,
        **overrides,
    }


def azure_payload(**overrides: Any) -> dict[str, Any]:
    return {
        "name": "Acme board",
        "organization_url": "https://dev.azure.com/acme",
        "azure_project": "proj",
        "pat": AZURE_PAT,
        **overrides,
    }


def create(client: TestClient, path: str, headers: dict[str, str], body: dict[str, Any]) -> Any:
    response = client.post(f"/api/v1/{path}", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def create_project(client: TestClient, headers: dict[str, str], **overrides: Any) -> dict[str, Any]:
    """A project with fresh Git and Azure connections, unless their IDs are given."""
    body: dict[str, Any] = {"name": "Main project", **overrides}
    if "git_connection_id" not in body:
        body["git_connection_id"] = create(client, "git-connections", headers, git_payload())["id"]
    if "azure_connection_id" not in body:
        body["azure_connection_id"] = create(client, "azure-connections", headers, azure_payload())[
            "id"
        ]
    project: dict[str, Any] = create(client, "projects", headers, body)
    return project


def assert_validation_error(response: Any, field: str) -> None:
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    locations = [e["loc"] for e in error["details"]["errors"]]
    assert any(field in loc for loc in locations), locations
