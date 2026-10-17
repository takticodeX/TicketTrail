"""Health probes, error shape, OpenAPI and migrations."""

from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine

import app.db.models  # noqa: F401
from app.db.base import Base

pytestmark = pytest.mark.integration


def test_health_is_ok(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_reports_unavailable_redis(client: TestClient) -> None:
    # The test settings point Redis at a closed port.
    response = client.get("/api/v1/ready")
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "not_ready"
    assert error["details"]["checks"] == {"database": "ok", "redis": "unavailable"}


def test_ready_when_all_dependencies_are_up(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app.state.redis, "ping", lambda: True)
    response = client.get("/api/v1/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok", "redis": "ok"}}


def test_unknown_route_uses_error_shape(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Not Found", "details": {}}
    }


def test_wrong_method_uses_error_shape(client: TestClient) -> None:
    response = client.get("/api/v1/auth/login")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


def test_openapi_documents_v1_endpoints(client: TestClient) -> None:
    assert client.get("/api/docs").status_code == 200
    spec: dict[str, Any] = client.get("/api/openapi.json").json()
    expected = {
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
        "/api/v1/auth/config",
        "/api/v1/me",
        "/api/v1/health",
        "/api/v1/ready",
    }
    assert expected <= set(spec["paths"])
    assert "ErrorResponse" in spec["components"]["schemas"]
    login_responses = spec["paths"]["/api/v1/auth/login"]["post"]["responses"]
    assert login_responses["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/TokenResponse"
    }


def test_migrations_match_models(db_engine: Engine) -> None:
    with db_engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []
