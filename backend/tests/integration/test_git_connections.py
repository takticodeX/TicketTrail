from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.core.crypto import SecretBox
from app.integrations.git.client import GitAuthError, GitClient, GitError, RemoteInfo
from app.worker import connection_checks
from tests.integration.helpers import (
    GIT_TOKEN,
    assert_validation_error,
    create,
    create_project,
    git_payload,
    signed_in,
)

pytestmark = pytest.mark.integration

URL = "/api/v1/git-connections"


@pytest.fixture
def headers(client: TestClient) -> dict[str, str]:
    return signed_in(client, "alice@example.com")


@pytest.fixture
def no_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Treat every host as public, so tests don't depend on real DNS."""
    monkeypatch.setattr(connection_checks, "check_public_host", lambda *_, **__: None)


def _fake_ls_remote(monkeypatch: pytest.MonkeyPatch, result: RemoteInfo | Exception) -> list[Any]:
    seen: list[Any] = []

    def ls_remote(self: GitClient, url: str) -> RemoteInfo:
        seen.append((self._credentials, url))
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(GitClient, "ls_remote", ls_remote)
    return seen


# --- Create and read -------------------------------------------------------------------------


def test_create_returns_connection_without_secret(
    client: TestClient, headers: dict[str, str]
) -> None:
    body = create(client, "git-connections", headers, git_payload())
    assert body["name"] == "App repo"
    assert body["auth_type"] == "token"
    assert body["username"] == "pat"
    assert body["has_secret"] is True
    assert body["host"] == "azure_repos"
    assert body["commit_url_pattern"] == "https://dev.azure.com/acme/proj/_git/app/commit/{sha}"
    assert body["last_test_ok"] is None
    assert "secret" not in body and "secret_enc" not in body
    assert GIT_TOKEN not in str(body)


def test_secret_is_stored_encrypted(
    app: FastAPI, client: TestClient, headers: dict[str, str], db_engine: Engine
) -> None:
    create(client, "git-connections", headers, git_payload())
    with db_engine.connect() as conn:
        stored = conn.execute(text("SELECT secret_enc FROM git_connections")).scalar_one()
    assert GIT_TOKEN not in stored
    box: SecretBox = app.state.secret_box
    assert box.decrypt(stored) == GIT_TOKEN


def test_get_and_list(client: TestClient, headers: dict[str, str]) -> None:
    first = create(client, "git-connections", headers, git_payload(name="B repo"))
    create(client, "git-connections", headers, git_payload(name="A repo"))

    assert client.get(f"{URL}/{first['id']}", headers=headers).json()["name"] == "B repo"
    page = client.get(URL, headers=headers).json()
    assert page["total"] == 2
    assert page["page"] == 1
    assert page["page_size"] == 25
    assert [c["name"] for c in page["items"]] == ["A repo", "B repo"]


def test_pagination(client: TestClient, headers: dict[str, str]) -> None:
    for index in range(3):
        create(client, "git-connections", headers, git_payload(name=f"repo {index}"))
    page = client.get(URL, headers=headers, params={"page": 2, "page_size": 2}).json()
    assert page["total"] == 3
    assert [c["name"] for c in page["items"]] == ["repo 2"]
    assert client.get(URL, headers=headers, params={"page_size": 101}).status_code == 422
    assert client.get(URL, headers=headers, params={"page": 0}).status_code == 422


def test_url_username_is_dropped(client: TestClient, headers: dict[str, str]) -> None:
    body = create(
        client,
        "git-connections",
        headers,
        git_payload(repo_url="https://acme@dev.azure.com/acme/proj/_git/app"),
    )
    assert body["repo_url"] == "https://dev.azure.com/acme/proj/_git/app"


@pytest.mark.parametrize(
    "repo_url",
    [
        "http://github.com/acme/app.git",
        "git@github.com:acme/app.git",
        "https://user:token@github.com/acme/app.git",
        "not a url",
    ],
)
def test_rejects_unsafe_urls(client: TestClient, headers: dict[str, str], repo_url: str) -> None:
    response = client.post(URL, headers=headers, json=git_payload(repo_url=repo_url))
    assert_validation_error(response, "repo_url")


@pytest.mark.parametrize("missing", ["username", "secret"])
def test_token_auth_needs_username_and_secret(
    client: TestClient, headers: dict[str, str], missing: str
) -> None:
    response = client.post(URL, headers=headers, json=git_payload(**{missing: None}))
    assert response.status_code == 422


def test_public_repo_needs_no_credentials(client: TestClient, headers: dict[str, str]) -> None:
    body = create(
        client,
        "git-connections",
        headers,
        git_payload(
            auth_type="none",
            repo_url="https://github.com/acme/oss.git",
            username="ignored",
            secret="ignored",
        ),
    )
    assert body["username"] is None
    assert body["has_secret"] is False
    assert body["commit_url_pattern"] == "https://github.com/acme/oss/commit/{sha}"


def test_commit_url_template(client: TestClient, headers: dict[str, str]) -> None:
    template = "https://gitea.example.com/acme/app/commit/{sha}"
    body = create(
        client,
        "git-connections",
        headers,
        git_payload(
            repo_url="https://gitea.example.com/acme/app.git", commit_url_template=template
        ),
    )
    assert body["commit_url_pattern"] == template
    for bad in ["https://gitea.example.com/commit/", "http://x/{sha}", "https://x/{sha}/{branch}"]:
        response = client.post(
            URL, headers=headers, json=git_payload(name=bad, commit_url_template=bad)
        )
        assert_validation_error(response, "commit_url_template")


def test_names_are_unique_per_user(client: TestClient, headers: dict[str, str]) -> None:
    create(client, "git-connections", headers, git_payload())
    response = client.post(URL, headers=headers, json=git_payload())
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "name_taken"
    other = signed_in(client, "bob@example.com")
    create(client, "git-connections", other, git_payload())  # same name, other user: fine


def test_requires_authentication(client: TestClient) -> None:
    assert client.get(URL).status_code == 401
    assert client.post(URL, json=git_payload()).status_code == 401


# --- Update ----------------------------------------------------------------------------------


def test_empty_secret_keeps_the_saved_one(
    app: FastAPI, client: TestClient, headers: dict[str, str], db_engine: Engine
) -> None:
    connection = create(client, "git-connections", headers, git_payload())
    response = client.patch(
        f"{URL}/{connection['id']}", headers=headers, json={"name": "Renamed", "secret": ""}
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"
    assert response.json()["has_secret"] is True
    with db_engine.connect() as conn:
        stored = conn.execute(text("SELECT secret_enc FROM git_connections")).scalar_one()
    assert app.state.secret_box.decrypt(stored) == GIT_TOKEN


def test_new_secret_replaces_the_old_one(
    app: FastAPI, client: TestClient, headers: dict[str, str], db_engine: Engine
) -> None:
    connection = create(client, "git-connections", headers, git_payload())
    client.patch(f"{URL}/{connection['id']}", headers=headers, json={"secret": "new-token"})
    with db_engine.connect() as conn:
        stored = conn.execute(text("SELECT secret_enc FROM git_connections")).scalar_one()
    assert app.state.secret_box.decrypt(stored) == "new-token"


def test_switching_to_public_clears_credentials(
    client: TestClient, headers: dict[str, str]
) -> None:
    connection = create(client, "git-connections", headers, git_payload())
    body = client.patch(
        f"{URL}/{connection['id']}", headers=headers, json={"auth_type": "none"}
    ).json()
    assert body["username"] is None
    assert body["has_secret"] is False


def test_switching_to_token_needs_a_secret(client: TestClient, headers: dict[str, str]) -> None:
    connection = create(
        client, "git-connections", headers, git_payload(auth_type="none", secret=None)
    )
    response = client.patch(
        f"{URL}/{connection['id']}",
        headers=headers,
        json={"auth_type": "token", "username": "pat"},
    )
    assert_validation_error(response, "secret")


def test_clearing_username_for_token_auth_is_refused(
    client: TestClient, headers: dict[str, str]
) -> None:
    connection = create(client, "git-connections", headers, git_payload())
    response = client.patch(f"{URL}/{connection['id']}", headers=headers, json={"username": ""})
    assert_validation_error(response, "username")


def test_rename_to_taken_name_is_conflict(client: TestClient, headers: dict[str, str]) -> None:
    create(client, "git-connections", headers, git_payload(name="one"))
    two = create(client, "git-connections", headers, git_payload(name="two"))
    response = client.patch(f"{URL}/{two['id']}", headers=headers, json={"name": "one"})
    assert response.status_code == 409


# --- Delete ----------------------------------------------------------------------------------


def test_delete(client: TestClient, headers: dict[str, str]) -> None:
    connection = create(client, "git-connections", headers, git_payload())
    assert client.delete(f"{URL}/{connection['id']}", headers=headers).status_code == 204
    assert client.get(f"{URL}/{connection['id']}", headers=headers).status_code == 404


def test_delete_is_refused_while_a_project_uses_it(
    client: TestClient, headers: dict[str, str]
) -> None:
    project = create_project(client, headers, name="Uses it")
    response = client.delete(f"{URL}/{project['git_connection_id']}", headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "connection_in_use"
    assert response.json()["error"]["details"]["projects"] == ["Uses it"]


# --- Test connection (runs on the worker) ----------------------------------------------------


def test_test_connection_lists_branches(
    client: TestClient, headers: dict[str, str], monkeypatch: pytest.MonkeyPatch, no_dns: None
) -> None:
    seen = _fake_ls_remote(monkeypatch, RemoteInfo(branches=["dev", "main"], default_branch="main"))
    connection = create(client, "git-connections", headers, git_payload())

    response = client.post(f"{URL}/{connection['id']}/test", headers=headers)
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "branches": ["dev", "main"],
        "default_branch": "main",
        "error": None,
    }
    credentials, url = seen[0]
    assert (credentials.username, credentials.secret) == ("pat", GIT_TOKEN)
    assert url == "https://dev.azure.com/acme/proj/_git/app"

    saved = client.get(f"{URL}/{connection['id']}", headers=headers).json()
    assert saved["last_test_ok"] is True
    assert saved["last_test_at"] is not None


def test_test_connection_reports_auth_failure(
    client: TestClient, headers: dict[str, str], monkeypatch: pytest.MonkeyPatch, no_dns: None
) -> None:
    _fake_ls_remote(monkeypatch, GitAuthError("fatal: Authentication failed"))
    connection = create(client, "git-connections", headers, git_payload())

    body = client.post(f"{URL}/{connection['id']}/test", headers=headers).json()
    assert body["ok"] is False
    assert "Authentication failed" in body["error"]
    assert "Code: Read" in body["error"]
    saved = client.get(f"{URL}/{connection['id']}", headers=headers).json()
    assert saved["last_test_ok"] is False


def test_test_connection_reports_other_git_errors(
    client: TestClient, headers: dict[str, str], monkeypatch: pytest.MonkeyPatch, no_dns: None
) -> None:
    _fake_ls_remote(monkeypatch, GitError("git timed out after 20 s"))
    connection = create(client, "git-connections", headers, git_payload())
    body = client.post(f"{URL}/{connection['id']}/test", headers=headers).json()
    assert body == {
        "ok": False,
        "branches": [],
        "default_branch": None,
        "error": "git timed out after 20 s",
    }


def test_public_repo_test_sends_no_credentials(
    client: TestClient, headers: dict[str, str], monkeypatch: pytest.MonkeyPatch, no_dns: None
) -> None:
    seen = _fake_ls_remote(monkeypatch, RemoteInfo(branches=["main"], default_branch="main"))
    connection = create(
        client,
        "git-connections",
        headers,
        git_payload(auth_type="none", repo_url="https://github.com/acme/oss.git"),
    )
    client.post(f"{URL}/{connection['id']}/test", headers=headers)
    assert seen[0][0] is None


def test_test_refuses_private_hosts(
    client: TestClient, headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _fake_ls_remote(monkeypatch, RemoteInfo())
    connection = create(
        client, "git-connections", headers, git_payload(repo_url="https://10.0.0.5/repo.git")
    )
    body = client.post(f"{URL}/{connection['id']}/test", headers=headers).json()
    assert body["ok"] is False
    assert "private address" in body["error"]
    assert "TT_ALLOW_PRIVATE_HOSTS" in body["error"]
    assert seen == []  # git never ran


def test_private_hosts_can_be_allowed(app_factory: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_ls_remote(monkeypatch, RemoteInfo(branches=["main"], default_branch="main"))
    with TestClient(app_factory(allow_private_hosts=True)) as client:
        headers = signed_in(client, "lan@example.com")
        connection = create(
            client, "git-connections", headers, git_payload(repo_url="https://10.0.0.5/repo.git")
        )
        assert client.post(f"{URL}/{connection['id']}/test", headers=headers).json()["ok"] is True


def test_test_reports_worker_unavailable(
    app: FastAPI, client: TestClient, headers: dict[str, str]
) -> None:
    connection = create(client, "git-connections", headers, git_payload())
    app.state.task_runner.unavailable = True
    response = client.post(f"{URL}/{connection['id']}/test", headers=headers)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "worker_unavailable"


def test_editing_credentials_resets_the_test_result(
    client: TestClient, headers: dict[str, str], monkeypatch: pytest.MonkeyPatch, no_dns: None
) -> None:
    _fake_ls_remote(monkeypatch, RemoteInfo(branches=["main"], default_branch="main"))
    connection = create(client, "git-connections", headers, git_payload())
    client.post(f"{URL}/{connection['id']}/test", headers=headers)

    renamed = client.patch(f"{URL}/{connection['id']}", headers=headers, json={"name": "x"}).json()
    assert renamed["last_test_ok"] is True  # renaming doesn't invalidate the test
    changed = client.patch(
        f"{URL}/{connection['id']}", headers=headers, json={"secret": "other"}
    ).json()
    assert changed["last_test_ok"] is None
