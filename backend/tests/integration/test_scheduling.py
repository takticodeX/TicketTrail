"""Milestone 6: scheduled runs, the per-project lock, cancelling, and the dashboard summary."""

import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import Engine, text

from app.sync.engine import run_sync
from app.sync.lock import lock_key
from app.worker.scheduler import dispatch_due_schedules
from tests.fixtures.azure import FakeAzure
from tests.fixtures.repos import FixtureRepo
from tests.integration.helpers import create_project, signed_in

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("no_dns")]


@pytest.fixture(autouse=True)
def board(azure: FakeAzure) -> FakeAzure:
    azure.work_items.update(range(1, 20))
    return azure


@pytest.fixture
def headers(client: TestClient) -> dict[str, str]:
    return signed_in(client, "alice@example.com")


@pytest.fixture
def origin(tmp_path: Path) -> FixtureRepo:
    repo = FixtureRepo(tmp_path / "origin")
    repo.commit("Fix AB#1")
    return repo


@pytest.fixture
def project_for(
    client: TestClient, headers: dict[str, str], db_engine: Engine
) -> Callable[..., dict[str, Any]]:
    def make(repo: FixtureRepo, **overrides: Any) -> dict[str, Any]:
        project = create_project(client, headers, **overrides)
        with db_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE git_connections SET repo_url = :url, auth_type = 'none', "
                    "username = NULL, secret_enc = NULL WHERE id = :id"
                ),
                {"url": repo.url, "id": project["git_connection_id"]},
            )
        return project

    return make


def armed_at(db_engine: Engine, project: dict[str, Any], when: datetime) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text("UPDATE projects SET schedule_last_fired_at = :when WHERE id = :id"),
            {"when": when, "id": project["id"]},
        )


def runs_of(client: TestClient, headers: dict[str, str], project: dict[str, Any]) -> list[Any]:
    page = client.get(f"/api/v1/projects/{project['id']}/runs", headers=headers).json()
    result: list[Any] = page["items"]
    return result


def dispatch(app: FastAPI, now: datetime) -> list[uuid.UUID]:
    runner = app.state.task_runner
    return dispatch_due_schedules(runner.context, runner, now=now)


T0 = datetime(2026, 10, 16, 6, 2, tzinfo=UTC)  # a Friday


# --- Scheduling ------------------------------------------------------------------------------


def test_a_project_scheduled_every_5_minutes_runs_by_itself(
    app: FastAPI,
    client: TestClient,
    headers: dict[str, str],
    origin: FixtureRepo,
    project_for: Any,
    db_engine: Engine,
    board: FakeAzure,
) -> None:
    project = project_for(origin, schedule_cron="*/5 * * * *", schedule_enabled=True)
    armed_at(db_engine, project, T0)

    assert dispatch(app, T0 + timedelta(minutes=2)) == []  # 06:04: nothing due yet
    started = dispatch(app, T0 + timedelta(minutes=3))  # 06:05
    assert len(started) == 1
    assert dispatch(app, T0 + timedelta(minutes=3, seconds=40)) == []  # same slot: once
    assert len(dispatch(app, T0 + timedelta(minutes=8))) == 1  # 06:10

    runs = runs_of(client, headers, project)
    assert [r["trigger"] for r in runs] == ["scheduled", "scheduled"]
    assert {r["status"] for r in runs} == {"success"}
    assert board.count(1) == 1  # the second run found nothing new


def test_scheduled_runs_use_the_dry_run_default(
    app: FastAPI,
    client: TestClient,
    headers: dict[str, str],
    origin: FixtureRepo,
    project_for: Any,
    db_engine: Engine,
    board: FakeAzure,
) -> None:
    project = project_for(
        origin, schedule_cron="*/5 * * * *", schedule_enabled=True, dry_run_default=True
    )
    armed_at(db_engine, project, T0)
    dispatch(app, T0 + timedelta(minutes=3))
    assert runs_of(client, headers, project)[0]["dry_run"] is True
    assert board.posts == 0


def test_schedule_is_evaluated_in_the_users_time_zone(
    app: FastAPI,
    client: TestClient,
    headers: dict[str, str],
    origin: FixtureRepo,
    project_for: Any,
    db_engine: Engine,
) -> None:
    client.patch("/api/v1/me", headers=headers, json={"timezone": "Europe/Rome"})
    project = project_for(origin, schedule_cron="0 8 * * *", schedule_enabled=True)
    armed_at(db_engine, project, datetime(2026, 10, 16, 5, 0, tzinfo=UTC))

    assert dispatch(app, datetime(2026, 10, 16, 5, 59, tzinfo=UTC)) == []  # 07:59 in Rome
    assert len(dispatch(app, datetime(2026, 10, 16, 6, 0, tzinfo=UTC))) == 1  # 08:00 in Rome


def test_turning_the_schedule_off_takes_effect_without_a_restart(
    app: FastAPI,
    client: TestClient,
    headers: dict[str, str],
    origin: FixtureRepo,
    project_for: Any,
    db_engine: Engine,
) -> None:
    project = project_for(origin, schedule_cron="*/5 * * * *", schedule_enabled=True)
    armed_at(db_engine, project, T0)
    client.patch(
        f"/api/v1/projects/{project['id']}", headers=headers, json={"schedule_enabled": False}
    )
    assert dispatch(app, datetime.now(UTC) + timedelta(minutes=10)) == []


def test_changing_the_schedule_takes_effect_and_never_fires_a_past_slot(
    app: FastAPI,
    client: TestClient,
    headers: dict[str, str],
    origin: FixtureRepo,
    project_for: Any,
) -> None:
    project = project_for(origin, schedule_cron="0 3 * * *", schedule_enabled=True)
    response = client.patch(
        f"/api/v1/projects/{project['id']}", headers=headers, json={"schedule_cron": "*/5 * * * *"}
    )
    assert response.status_code == 200
    now = datetime.now(UTC)
    assert dispatch(app, now) == []  # re-armed: the slot that just passed doesn't fire
    assert len(dispatch(app, now + timedelta(minutes=5))) == 1


def test_enabling_a_schedule_does_not_fire_at_once(
    app: FastAPI,
    client: TestClient,
    headers: dict[str, str],
    origin: FixtureRepo,
    project_for: Any,
) -> None:
    project = project_for(origin, schedule_cron="*/5 * * * *")
    client.patch(
        f"/api/v1/projects/{project['id']}", headers=headers, json={"schedule_enabled": True}
    )
    assert dispatch(app, datetime.now(UTC)) == []


def test_two_schedulers_start_each_slot_once(
    app: FastAPI,
    origin: FixtureRepo,
    project_for: Any,
    db_engine: Engine,
) -> None:
    project = project_for(origin, schedule_cron="*/5 * * * *", schedule_enabled=True)
    armed_at(db_engine, project, T0)
    app.state.task_runner.run_queued_tasks = False
    started: list[uuid.UUID] = []
    barrier = threading.Barrier(2)

    def scheduler() -> None:
        barrier.wait()
        started.extend(dispatch(app, T0 + timedelta(minutes=3)))

    threads = [threading.Thread(target=scheduler) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(started) == 1


def test_a_never_armed_schedule_arms_itself_without_firing(
    app: FastAPI, origin: FixtureRepo, project_for: Any, db_engine: Engine
) -> None:
    project = project_for(origin, schedule_cron="*/5 * * * *", schedule_enabled=True)
    with db_engine.begin() as conn:
        conn.execute(text("UPDATE projects SET schedule_last_fired_at = NULL"))
    assert dispatch(app, T0) == []
    assert len(dispatch(app, T0 + timedelta(minutes=5))) == 1
    assert project["id"]


def test_queue_down_marks_the_scheduled_run_failed(
    app: FastAPI,
    client: TestClient,
    headers: dict[str, str],
    origin: FixtureRepo,
    project_for: Any,
    db_engine: Engine,
) -> None:
    project = project_for(origin, schedule_cron="*/5 * * * *", schedule_enabled=True)
    armed_at(db_engine, project, T0)
    app.state.task_runner.unavailable = True
    assert dispatch(app, T0 + timedelta(minutes=3)) == []
    [run] = runs_of(client, headers, project)
    assert run["status"] == "failed"
    assert "never started" in run["error_message"]


def test_disabled_accounts_are_not_scheduled(
    app: FastAPI, origin: FixtureRepo, project_for: Any, db_engine: Engine
) -> None:
    project = project_for(origin, schedule_cron="*/5 * * * *", schedule_enabled=True)
    armed_at(db_engine, project, T0)
    with db_engine.begin() as conn:
        conn.execute(text("UPDATE users SET is_active = false"))
    assert dispatch(app, T0 + timedelta(minutes=3)) == []


# --- One run per project -------------------------------------------------------------------


def test_overlapping_runs_are_skipped(
    client: TestClient,
    headers: dict[str, str],
    origin: FixtureRepo,
    project_for: Any,
    redis: Redis,
    board: FakeAzure,
) -> None:
    project = project_for(origin)
    redis.set(lock_key(uuid.UUID(project["id"])), "another-run")  # a run is in progress

    response = client.post(f"/api/v1/projects/{project['id']}/sync", headers=headers, json={})
    run = client.get(f"/api/v1/runs/{response.json()['run_id']}", headers=headers).json()
    assert run["status"] == "skipped"
    assert "Another run of this project was in progress" in run["error_message"]
    assert board.posts == 0

    redis.delete(lock_key(uuid.UUID(project["id"])))
    again = client.post(f"/api/v1/projects/{project['id']}/sync", headers=headers, json={})
    run_id = again.json()["run_id"]
    assert client.get(f"/api/v1/runs/{run_id}", headers=headers).json()["status"] == "success"
    assert redis.get(lock_key(uuid.UUID(project["id"]))) is None  # released at the end


def test_a_stale_runs_lock_is_released(
    app: FastAPI,
    client: TestClient,
    headers: dict[str, str],
    origin: FixtureRepo,
    project_for: Any,
    redis: Redis,
    db_engine: Engine,
) -> None:
    project = project_for(origin)
    app.state.task_runner.run_queued_tasks = False
    dead = client.post(f"/api/v1/projects/{project['id']}/sync", headers=headers, json={})
    dead_id = dead.json()["run_id"]
    redis.set(lock_key(uuid.UUID(project["id"])), dead_id)  # its worker died holding the lock
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE sync_runs SET status = 'running', "
                "updated_at = now() - interval '11 minutes'"
            )
        )
    app.state.task_runner.run_queued_tasks = True

    fresh = client.post(f"/api/v1/projects/{project['id']}/sync", headers=headers, json={})
    run = client.get(f"/api/v1/runs/{fresh.json()['run_id']}", headers=headers).json()
    assert run["status"] == "success"  # not skipped for 30 minutes
    assert client.get(f"/api/v1/runs/{dead_id}", headers=headers).json()["status"] == "failed"


# --- Cancelling ----------------------------------------------------------------------------


def test_a_queued_run_can_be_cancelled(
    app: FastAPI,
    client: TestClient,
    headers: dict[str, str],
    origin: FixtureRepo,
    project_for: Any,
    board: FakeAzure,
) -> None:
    project = project_for(origin)
    app.state.task_runner.run_queued_tasks = False
    run_id = client.post(f"/api/v1/projects/{project['id']}/sync", headers=headers, json={}).json()[
        "run_id"
    ]

    response = client.post(f"/api/v1/runs/{run_id}/cancel", headers=headers)
    assert response.status_code == 202
    assert response.json()["status"] == "cancelled"

    run_sync(app.state.task_runner.context, uuid.UUID(run_id))  # the worker picks it up late
    assert client.get(f"/api/v1/runs/{run_id}", headers=headers).json()["status"] == "cancelled"
    assert board.posts == 0


def test_a_running_run_stops_between_commits(
    app: FastAPI,
    client: TestClient,
    headers: dict[str, str],
    tmp_path: Path,
    project_for: Any,
    board: FakeAzure,
    db_engine: Engine,
) -> None:
    repo = FixtureRepo(tmp_path / "many")
    first = repo.commit("AB#1")
    for index in range(2, 6):
        repo.commit(f"AB#{index}")
    project = project_for(repo)
    state: dict[str, str] = {}

    def cancel_after_first(work_item_id: int, _text: str) -> None:
        if work_item_id == 1:  # the user presses Cancel while the run is posting
            client.post(f"/api/v1/runs/{state['run_id']}/cancel", headers=headers)

    app.state.task_runner.run_queued_tasks = False
    state["run_id"] = client.post(
        f"/api/v1/projects/{project['id']}/sync", headers=headers, json={}
    ).json()["run_id"]
    board.after_post = cancel_after_first
    run_sync(app.state.task_runner.context, uuid.UUID(state["run_id"]))
    board.after_post = None

    run = client.get(f"/api/v1/runs/{state['run_id']}", headers=headers).json()
    assert run["status"] == "cancelled"
    assert "after 1 of 5 commits" in run["error_message"]
    assert board.total_comments() == 1
    with db_engine.connect() as conn:
        cursor = conn.execute(text("SELECT last_sha FROM project_cursors")).scalar_one()
    assert cursor == first  # done commits stay done

    app.state.task_runner.run_queued_tasks = True
    rest = client.post(f"/api/v1/projects/{project['id']}/sync", headers=headers, json={})
    assert (
        client.get(f"/api/v1/runs/{rest.json()['run_id']}", headers=headers).json()[
            "comments_posted"
        ]
        == 4
    )
    assert [board.count(i) for i in range(1, 6)] == [1, 1, 1, 1, 1]


def test_a_finished_run_cannot_be_cancelled(
    client: TestClient, headers: dict[str, str], origin: FixtureRepo, project_for: Any
) -> None:
    project = project_for(origin)
    run_id = client.post(f"/api/v1/projects/{project['id']}/sync", headers=headers, json={}).json()[
        "run_id"
    ]
    response = client.post(f"/api/v1/runs/{run_id}/cancel", headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "run_finished"


def test_other_users_cannot_cancel(
    app: FastAPI,
    client: TestClient,
    headers: dict[str, str],
    origin: FixtureRepo,
    project_for: Any,
) -> None:
    project = project_for(origin)
    app.state.task_runner.run_queued_tasks = False
    run_id = client.post(f"/api/v1/projects/{project['id']}/sync", headers=headers, json={}).json()[
        "run_id"
    ]
    bob = signed_in(client, "bob@example.com")
    assert client.post(f"/api/v1/runs/{run_id}/cancel", headers=bob).status_code == 404
    assert client.get(f"/api/v1/runs/{run_id}", headers=headers).json()["status"] == "queued"


# --- Dashboard summary ---------------------------------------------------------------------


def test_projects_carry_the_dashboard_summary(
    client: TestClient, headers: dict[str, str], origin: FixtureRepo, project_for: Any
) -> None:
    project = project_for(origin, schedule_cron="0 8 * * *", schedule_enabled=True)
    fresh = client.get("/api/v1/projects", headers=headers).json()["items"][0]
    assert fresh["last_run"] is None
    assert fresh["comments_posted"] == 0
    next_run = datetime.fromisoformat(fresh["next_run_at"])
    assert (next_run.hour, next_run.minute) == (8, 0)  # the user's time zone is UTC

    client.post(f"/api/v1/projects/{project['id']}/sync", headers=headers, json={})
    after = client.get(f"/api/v1/projects/{project['id']}", headers=headers).json()
    assert after["last_run"]["status"] == "success"
    assert after["comments_posted"] == 1

    client.patch(
        f"/api/v1/projects/{project['id']}", headers=headers, json={"schedule_enabled": False}
    )
    assert (
        client.get(f"/api/v1/projects/{project['id']}", headers=headers).json()["next_run_at"]
        is None
    )
