from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

PASSWORD = "correct-horse-battery"


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
    other = TestClient(app)
    return other.post("/api/v1/auth/refresh", headers={"Cookie": f"tt_refresh={refresh_token}"})


def new_client(app: FastAPI) -> TestClient:
    """A second browser/device for the same app (see refresh_with about `with`)."""
    return TestClient(app)
