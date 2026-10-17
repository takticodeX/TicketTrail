import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.worker import connection_checks
from tests.integration.helpers import (
    AZURE_PAT,
    assert_validation_error,
    azure_payload,
    create,
    create_project,
    signed_in,
)

pytestmark = pytest.mark.integration

URL = "/api/v1/azure-connections"
AZURE_PROJECT_API = "https://dev.azure.com/acme/_apis/projects/proj"


@pytest.fixture
def headers(client: TestClient) -> dict[str, str]:
    return signed_in(client, "alice@example.com")


@pytest.fixture
def no_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(connection_checks, "check_public_host", lambda *_, **__: None)


def test_create_never_returns_the_pat(client: TestClient, headers: dict[str, str]) -> None:
    body = create(client, "azure-connections", headers, azure_payload())
    assert body["organization_url"] == "https://dev.azure.com/acme"
    assert body["azure_project"] == "proj"
    assert body["has_secret"] is True
    assert "pat" not in body and "pat_enc" not in body
    assert AZURE_PAT not in str(body)


def test_pat_is_stored_encrypted(
    app: FastAPI, client: TestClient, headers: dict[str, str], db_engine: Engine
) -> None:
    create(client, "azure-connections", headers, azure_payload())
    with db_engine.connect() as conn:
        stored = conn.execute(text("SELECT pat_enc FROM azure_connections")).scalar_one()
    assert AZURE_PAT not in stored
    assert app.state.secret_box.decrypt(stored) == AZURE_PAT


def test_trailing_slash_is_removed(client: TestClient, headers: dict[str, str]) -> None:
    body = create(
        client,
        "azure-connections",
        headers,
        azure_payload(organization_url="https://dev.azure.com/acme/"),
    )
    assert body["organization_url"] == "https://dev.azure.com/acme"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("organization_url", "http://dev.azure.com/acme"),
        ("organization_url", "https://user:pw@dev.azure.com/acme"),
        ("azure_project", ""),
        ("pat", ""),
        ("name", "  "),
    ],
)
def test_validation(client: TestClient, headers: dict[str, str], field: str, value: str) -> None:
    response = client.post(URL, headers=headers, json=azure_payload(**{field: value}))
    assert_validation_error(response, field)


def test_update_keeps_pat_when_empty(
    app: FastAPI, client: TestClient, headers: dict[str, str], db_engine: Engine
) -> None:
    connection = create(client, "azure-connections", headers, azure_payload())
    body = client.patch(
        f"{URL}/{connection['id']}", headers=headers, json={"azure_project": "other", "pat": ""}
    ).json()
    assert body["azure_project"] == "other"
    with db_engine.connect() as conn:
        stored = conn.execute(text("SELECT pat_enc FROM azure_connections")).scalar_one()
    assert app.state.secret_box.decrypt(stored) == AZURE_PAT


def test_update_replaces_pat(
    app: FastAPI, client: TestClient, headers: dict[str, str], db_engine: Engine
) -> None:
    connection = create(client, "azure-connections", headers, azure_payload())
    client.patch(f"{URL}/{connection['id']}", headers=headers, json={"pat": "new-pat"})
    with db_engine.connect() as conn:
        stored = conn.execute(text("SELECT pat_enc FROM azure_connections")).scalar_one()
    assert app.state.secret_box.decrypt(stored) == "new-pat"


def test_list_and_delete(client: TestClient, headers: dict[str, str]) -> None:
    connection = create(client, "azure-connections", headers, azure_payload())
    assert client.get(URL, headers=headers).json()["total"] == 1
    assert client.delete(f"{URL}/{connection['id']}", headers=headers).status_code == 204
    assert client.get(URL, headers=headers).json()["total"] == 0


def test_delete_is_refused_while_a_project_uses_it(
    client: TestClient, headers: dict[str, str]
) -> None:
    project = create_project(client, headers)
    response = client.delete(f"{URL}/{project['azure_connection_id']}", headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "connection_in_use"


@respx.mock
def test_test_connection_finds_the_project(
    client: TestClient, headers: dict[str, str], no_dns: None
) -> None:
    route = respx.get(AZURE_PROJECT_API).mock(
        return_value=httpx.Response(200, json={"id": "1", "name": "proj"})
    )
    connection = create(client, "azure-connections", headers, azure_payload())

    response = client.post(f"{URL}/{connection['id']}/test", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"ok": True, "project_name": "proj", "error": None}
    assert route.called
    saved = client.get(f"{URL}/{connection['id']}", headers=headers).json()
    assert saved["last_test_ok"] is True


@respx.mock
def test_test_connection_with_bad_pat(
    client: TestClient, headers: dict[str, str], no_dns: None
) -> None:
    respx.get(AZURE_PROJECT_API).mock(return_value=httpx.Response(401))
    connection = create(client, "azure-connections", headers, azure_payload())

    body = client.post(f"{URL}/{connection['id']}/test", headers=headers).json()
    assert body["ok"] is False
    assert "PAT invalid, expired or missing scope" in body["error"]
    assert AZURE_PAT not in body["error"]
    assert client.get(f"{URL}/{connection['id']}", headers=headers).json()["last_test_ok"] is False


def test_test_refuses_private_hosts(client: TestClient, headers: dict[str, str]) -> None:
    connection = create(
        client,
        "azure-connections",
        headers,
        azure_payload(organization_url="https://192.168.1.20/tfs/DefaultCollection"),
    )
    body = client.post(f"{URL}/{connection['id']}/test", headers=headers).json()
    assert body["ok"] is False
    assert "private address" in body["error"]
