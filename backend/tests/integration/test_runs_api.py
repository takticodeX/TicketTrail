"""POST /projects/{id}/sync and the run history endpoints."""

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.fixtures.azure import FakeAzure
from tests.fixtures.repos import FixtureRepo
from tests.integration.helpers import create_project, signed_in

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("no_dns")]


@pytest.fixture(autouse=True)
def board(azure: FakeAzure) -> FakeAzure:
    azure.work_items.update(range(1, 10))
    return azure


@pytest.fixture
def headers(client: TestClient) -> dict[str, str]:
    return signed_in(client, "alice@example.com")


@pytest.fixture
def project(
    client: TestClient, headers: dict[str, str], db_engine: Engine, tmp_path: Path
) -> dict[str, Any]:
    origin = FixtureRepo(tmp_path / "origin")
    for index in range(1, 6):
        origin.commit(f"commit {index} AB#{index}" if index % 2 else f"commit {index}")
    created = create_project(client, headers)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE git_connections SET repo_url = :url, auth_type = 'none', "
                "username = NULL, secret_enc = NULL"
            ),
            {"url": origin.url},
        )
    return created


def start(client: TestClient, headers: dict[str, str], project: dict[str, Any], **body: Any) -> Any:
    return client.post(f"/api/v1/projects/{project['id']}/sync", headers=headers, json=body)


def test_sync_returns_202_with_the_run_id(
    client: TestClient, headers: dict[str, str], project: dict[str, Any]
) -> None:
    response = start(client, headers, project, dry_run=True)
    assert response.status_code == 202
    run = client.get(f"/api/v1/runs/{response.json()['run_id']}", headers=headers).json()
    assert run["project_id"] == project["id"]
    assert run["trigger"] == "manual"
    assert run["status"] == "success"


def test_run_starts_queued(
    app: FastAPI, client: TestClient, headers: dict[str, str], project: dict[str, Any]
) -> None:
    app.state.task_runner.run_queued_tasks = False
    run_id = start(client, headers, project, dry_run=True).json()["run_id"]
    run = client.get(f"/api/v1/runs/{run_id}", headers=headers).json()
    assert run["status"] == "queued"
    assert run["started_at"] is None
    name, args = app.state.task_runner.calls[-1]
    assert name == "tickettrail.sync_project"
    assert args == [project["id"], "manual", True, run_id]


def test_dry_run_default_applies_when_omitted(
    app: FastAPI, client: TestClient, headers: dict[str, str], project: dict[str, Any]
) -> None:
    app.state.task_runner.run_queued_tasks = False
    real = start(client, headers, project).json()["run_id"]  # the default is off
    client.patch(
        f"/api/v1/projects/{project['id']}", headers=headers, json={"dry_run_default": True}
    )
    dry = start(client, headers, project).json()["run_id"]
    assert client.get(f"/api/v1/runs/{real}", headers=headers).json()["dry_run"] is False
    assert client.get(f"/api/v1/runs/{dry}", headers=headers).json()["dry_run"] is True


def test_queue_down_marks_the_run_failed(
    app: FastAPI, client: TestClient, headers: dict[str, str], project: dict[str, Any]
) -> None:
    app.state.task_runner.unavailable = True
    response = start(client, headers, project, dry_run=True)
    assert response.status_code == 503
    runs = client.get(f"/api/v1/projects/{project['id']}/runs", headers=headers).json()
    assert runs["items"][0]["status"] == "failed"
    assert "never started" in runs["items"][0]["error_message"]


def test_run_history_is_newest_first_and_paginated(
    client: TestClient, headers: dict[str, str], project: dict[str, Any]
) -> None:
    ids = [start(client, headers, project, dry_run=True).json()["run_id"] for _ in range(3)]
    page = client.get(
        f"/api/v1/projects/{project['id']}/runs", headers=headers, params={"page_size": 2}
    ).json()
    assert page["total"] == 3
    assert [r["id"] for r in page["items"]] == [ids[2], ids[1]]


def test_items_filter_and_paginate(
    client: TestClient, headers: dict[str, str], project: dict[str, Any]
) -> None:
    run_id = start(client, headers, project, dry_run=True).json()["run_id"]
    url = f"/api/v1/runs/{run_id}/items"

    everything = client.get(url, headers=headers).json()
    assert everything["total"] == 5
    assert [i["commit_subject"] for i in everything["items"]] == [
        "commit 1 AB#1",
        "commit 2",
        "commit 3 AB#3",
        "commit 4",
        "commit 5 AB#5",
    ]
    would_post = client.get(url, headers=headers, params={"action": "would_post"}).json()
    assert [i["work_item_id"] for i in would_post["items"]] == [1, 3, 5]
    second_page = client.get(url, headers=headers, params={"page": 2, "page_size": 2}).json()
    assert [i["commit_subject"] for i in second_page["items"]] == ["commit 3 AB#3", "commit 4"]
    assert client.get(url, headers=headers, params={"action": "bogus"}).status_code == 422

    detail = client.get(f"/api/v1/runs/{run_id}", headers=headers).json()
    assert detail["counts_by_action"] == {"would_post": 3, "no_reference": 2}


def test_runs_are_isolated_between_users(
    client: TestClient, headers: dict[str, str], project: dict[str, Any]
) -> None:
    run_id = start(client, headers, project, dry_run=True).json()["run_id"]
    bob = signed_in(client, "bob@example.com")
    for method, path in [
        ("POST", f"/api/v1/projects/{project['id']}/sync"),
        ("GET", f"/api/v1/projects/{project['id']}/runs"),
        ("GET", f"/api/v1/runs/{run_id}"),
        ("GET", f"/api/v1/runs/{run_id}/items"),
    ]:
        response = client.request(method, path, headers=bob, json={"dry_run": True})
        assert response.status_code == 404, f"{method} {path}"


def test_deleting_a_project_deletes_its_runs(
    client: TestClient, headers: dict[str, str], project: dict[str, Any], db_engine: Engine
) -> None:
    start(client, headers, project, dry_run=True)
    assert client.delete(f"/api/v1/projects/{project['id']}", headers=headers).status_code == 204
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM sync_runs")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM sync_run_items")).scalar_one() == 0
