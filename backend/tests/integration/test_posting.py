"""Real syncs against a fake Azure: posting, idempotency, crash recovery and error handling.

The idempotency suite (spec section 13): run twice, crash after the POST and before
the database update, two workers at once, a force-pushed branch. Each case asserts
exactly one comment per commit / work item pair in Azure.
"""

import threading
import uuid
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.db.repositories import close_stale_runs
from app.sync.engine import run_sync
from tests.fixtures.azure import FakeAzure
from tests.fixtures.repos import FixtureRepo
from tests.integration.helpers import create_project, signed_in

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("no_dns")]


class WorkerKilled(BaseException):
    """Escapes the engine's error handling, the way a killed process would."""


@pytest.fixture
def board(azure: FakeAzure) -> FakeAzure:
    azure.work_items.update({1, 2, 3, 12, 45, 46})
    return azure


@pytest.fixture
def headers(client: TestClient) -> dict[str, str]:
    return signed_in(client, "alice@example.com")


@pytest.fixture
def origin(tmp_path: Path) -> FixtureRepo:
    return FixtureRepo(tmp_path / "origin")


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


def sync(
    client: TestClient, headers: dict[str, str], project: dict[str, Any], *, dry_run: bool = False
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/projects/{project['id']}/sync", headers=headers, json={"dry_run": dry_run}
    )
    assert response.status_code == 202, response.text
    run: dict[str, Any] = client.get(
        f"/api/v1/runs/{response.json()['run_id']}", headers=headers
    ).json()
    return run


def queue(
    app: FastAPI, client: TestClient, headers: dict[str, str], project: dict[str, Any]
) -> str:
    """Create a queued run without running it, to drive the engine by hand."""
    app.state.task_runner.run_queued_tasks = False
    try:
        run_id: str = client.post(
            f"/api/v1/projects/{project['id']}/sync", headers=headers, json={"dry_run": False}
        ).json()["run_id"]
    finally:
        app.state.task_runner.run_queued_tasks = True
    return run_id


def engine(app: FastAPI, run_id: str) -> None:
    run_sync(app.state.task_runner.context, uuid.UUID(run_id))


def actions(
    client: TestClient, headers: dict[str, str], run: dict[str, Any]
) -> list[tuple[int | None, str]]:
    page = client.get(
        f"/api/v1/runs/{run['id']}/items", headers=headers, params={"page_size": 100}
    ).json()
    return [(i["work_item_id"], i["action"]) for i in page["items"]]


def cursors(db_engine: Engine) -> dict[str, str]:
    with db_engine.connect() as conn:
        rows = conn.execute(text("SELECT branch, last_sha FROM project_cursors")).all()
    return {branch: sha for branch, sha in rows}


def age_runs(db_engine: Engine, minutes: int = 11) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text("UPDATE sync_runs SET updated_at = now() - make_interval(mins => :m)"),
            {"m": minutes},
        )


# --- Posting ---------------------------------------------------------------------------------


def test_posts_one_comment_per_pair_from_the_template(
    client: TestClient,
    headers: dict[str, str],
    origin: FixtureRepo,
    project_for: Any,
    board: FakeAzure,
) -> None:
    first = origin.commit("Fix login AB#12\n\nThe *session* cookie was dropped.")
    origin.commit("chore: bump deps")
    origin.commit("Refactor billing AB#45, AB#46")
    run = sync(client, headers, project_for(origin))

    assert run["status"] == "success"
    assert run["comments_posted"] == 3
    assert actions(client, headers, run) == [
        (12, "posted"),
        (None, "no_reference"),
        (45, "posted"),
        (46, "posted"),
    ]
    assert (board.count(12), board.count(45), board.count(46)) == (1, 1, 1)
    [comment] = board.texts(12)
    assert comment.startswith(f"**Commit** [`{first[:7]}`](")  # the default template
    assert "on `main` by Ada Lovelace, 2026-01-01 12:00 UTC" in comment
    assert "Fix login AB#12\n\nThe \\*session\\* cookie was dropped." in comment
    assert comment.endswith(f"tt:{first}</sub>")


def test_custom_template_always_gets_the_marker(
    client: TestClient,
    headers: dict[str, str],
    origin: FixtureRepo,
    project_for: Any,
    board: FakeAzure,
) -> None:
    sha = origin.commit("Fix AB#1")
    sync(client, headers, project_for(origin, comment_template="{short_sha}: {subject}"))
    assert board.texts(1) == [f"{sha[:7]}: Fix AB#1\n\n<sub>tt:{sha}</sub>"]


def test_cursor_moves_to_the_branch_tip(
    client: TestClient,
    headers: dict[str, str],
    origin: FixtureRepo,
    project_for: Any,
    board: FakeAzure,
    db_engine: Engine,
) -> None:
    origin.commit("AB#1")
    tip = origin.commit("no reference")
    sync(client, headers, project_for(origin))
    assert cursors(db_engine) == {"main": tip}


# --- Idempotency suite ---------------------------------------------------------------------


def test_running_twice_posts_nothing_new(
    client: TestClient,
    headers: dict[str, str],
    origin: FixtureRepo,
    project_for: Any,
    board: FakeAzure,
) -> None:
    origin.commit("AB#1")
    origin.commit("AB#2")
    project = project_for(origin)
    sync(client, headers, project)
    again = sync(client, headers, project)

    assert again["status"] == "success"
    assert again["commits_scanned"] == 0  # the cursor already covers both commits
    assert board.total_comments() == 2


def test_full_rescan_without_cursors_posts_nothing_twice(
    client: TestClient,
    headers: dict[str, str],
    origin: FixtureRepo,
    project_for: Any,
    board: FakeAzure,
    db_engine: Engine,
) -> None:
    origin.commit("AB#1")
    origin.commit("AB#2")
    project = project_for(origin)
    sync(client, headers, project)
    with db_engine.begin() as conn:
        conn.execute(text("DELETE FROM project_cursors"))

    rescan = sync(client, headers, project)
    assert actions(client, headers, rescan) == [(1, "skipped_duplicate"), (2, "skipped_duplicate")]
    assert rescan["skipped"] == 2
    assert board.total_comments() == 2


def test_crash_after_post_before_database_update(
    app: FastAPI,
    client: TestClient,
    headers: dict[str, str],
    origin: FixtureRepo,
    project_for: Any,
    board: FakeAzure,
    db_engine: Engine,
) -> None:
    origin.commit("AB#1")
    origin.commit("AB#2")
    project = project_for(origin)

    def kill(work_item_id: int, _text: str) -> None:
        if work_item_id == 2:
            raise WorkerKilled  # the comment is in Azure; the database never hears of it

    board.after_post = kill
    crashed = queue(app, client, headers, project)
    with pytest.raises(WorkerKilled):
        engine(app, crashed)
    board.after_post = None
    with db_engine.connect() as conn:
        statuses = conn.execute(
            text("SELECT work_item_id, status FROM posted_comments ORDER BY work_item_id")
        ).all()
    assert statuses == [(1, "posted"), (2, "pending")]

    age_runs(db_engine)  # the crashed run's heartbeat has stopped
    recovered = sync(client, headers, project)

    assert recovered["status"] == "success"
    assert (board.count(1), board.count(2)) == (1, 1)  # exactly one comment each
    assert actions(client, headers, recovered) == [
        (1, "skipped_duplicate"),
        (2, "skipped_duplicate"),
    ]
    crashed_run = client.get(f"/api/v1/runs/{crashed}", headers=headers).json()
    assert crashed_run["status"] == "failed"
    assert "stopped making progress" in crashed_run["error_message"]


def test_crash_before_the_post_reaches_azure(
    app: FastAPI,
    client: TestClient,
    headers: dict[str, str],
    origin: FixtureRepo,
    project_for: Any,
    board: FakeAzure,
    db_engine: Engine,
) -> None:
    origin.commit("AB#1")
    project = project_for(origin)
    board.next_posts.append(WorkerKilled())  # dies while sending: nothing reached Azure
    with pytest.raises(WorkerKilled):
        engine(app, queue(app, client, headers, project))
    assert board.total_comments() == 0

    age_runs(db_engine)
    recovered = sync(client, headers, project)
    assert actions(client, headers, recovered) == [(1, "posted")]
    assert board.count(1) == 1


def test_two_workers_on_the_same_project_at_once(
    app: FastAPI,
    client: TestClient,
    headers: dict[str, str],
    origin: FixtureRepo,
    project_for: Any,
    board: FakeAzure,
) -> None:
    for index in range(1, 4):
        origin.commit(f"commit AB#{index}")
    project = project_for(origin)
    runs = [queue(app, client, headers, project) for _ in range(2)]
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def work(run_id: str) -> None:
        try:
            barrier.wait()
            engine(app, run_id)
        except BaseException as exc:  # surface thread failures in the test
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(run_id,)) for run_id in runs]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert [board.count(i) for i in (1, 2, 3)] == [1, 1, 1]
    posted = sum(
        client.get(f"/api/v1/runs/{run_id}", headers=headers).json()["comments_posted"]
        for run_id in runs
    )
    assert posted == 3


def test_force_pushed_branch_posts_only_new_commits(
    client: TestClient,
    headers: dict[str, str],
    origin: FixtureRepo,
    project_for: Any,
    board: FakeAzure,
) -> None:
    origin.commit("base AB#1")
    origin.commit("old tip AB#2")
    project = project_for(origin)
    sync(client, headers, project)
    origin.rewrite_last("rewritten tip AB#3")

    after = sync(client, headers, project)
    assert "rewritten" in after["error_message"]
    assert actions(client, headers, after) == [(1, "skipped_duplicate"), (3, "posted")]
    assert [board.count(i) for i in (1, 2, 3)] == [1, 1, 1]


# --- Errors (spec section 6) ---------------------------------------------------------------


def test_401_stops_the_run_and_marks_the_connection_failing(
    client: TestClient,
    headers: dict[str, str],
    origin: FixtureRepo,
    project_for: Any,
    board: FakeAzure,
    db_engine: Engine,
) -> None:
    origin.commit("AB#1")
    project = project_for(origin)
    board.next_reads.append(httpx.Response(401))

    run = sync(client, headers, project)
    assert run["status"] == "failed"
    assert "PAT invalid, expired or missing scope" in run["error_message"]
    assert board.posts == 0
    assert cursors(db_engine) == {}
    azure = client.get(
        f"/api/v1/azure-connections/{project['azure_connection_id']}", headers=headers
    ).json()
    assert azure["last_test_ok"] is False


def test_401_while_posting_stops_without_a_stray_guard(
    client: TestClient,
    headers: dict[str, str],
    origin: FixtureRepo,
    project_for: Any,
    board: FakeAzure,
    db_engine: Engine,
) -> None:
    origin.commit("AB#1")
    origin.commit("AB#2")
    project = project_for(origin)
    board.next_posts.extend([None, httpx.Response(403)])
    run = sync(client, headers, project)
    assert run["status"] == "failed"
    with db_engine.connect() as conn:
        rows = conn.execute(text("SELECT work_item_id, status FROM posted_comments")).all()
    assert rows == [(1, "posted")]  # the refused pair has no guard: it will be posted later


def test_missing_work_item_is_skipped(
    client: TestClient,
    headers: dict[str, str],
    origin: FixtureRepo,
    project_for: Any,
    board: FakeAzure,
    db_engine: Engine,
) -> None:
    origin.commit("AB#1 and AB#999")
    tip = origin.commit("AB#2")
    run = sync(client, headers, project_for(origin))
    assert run["status"] == "success"
    assert actions(client, headers, run) == [
        (1, "posted"),
        (999, "skipped_not_found"),
        (2, "posted"),
    ]
    assert run["skipped"] == 1
    assert cursors(db_engine) == {"main": tip}  # skipped for good: the cursor moves on


def test_work_item_deleted_between_check_and_post(
    client: TestClient,
    headers: dict[str, str],
    origin: FixtureRepo,
    project_for: Any,
    board: FakeAzure,
) -> None:
    origin.commit("AB#1")
    board.next_posts.append(httpx.Response(404))
    run = sync(client, headers, project_for(origin))
    assert actions(client, headers, run) == [(1, "skipped_not_found")]


def test_429_honours_retry_after_and_then_posts(
    app: FastAPI,
    client: TestClient,
    headers: dict[str, str],
    origin: FixtureRepo,
    project_for: Any,
    board: FakeAzure,
) -> None:
    origin.commit("AB#1")
    board.next_posts.append(httpx.Response(429, headers={"Retry-After": "3"}))
    run = sync(client, headers, project_for(origin))
    assert run["status"] == "success"
    assert board.count(1) == 1
    assert 3.0 in app.state.sleeps


def test_lasting_503_keeps_the_cursor_and_the_next_run_posts_once(
    client: TestClient,
    headers: dict[str, str],
    origin: FixtureRepo,
    project_for: Any,
    board: FakeAzure,
    db_engine: Engine,
) -> None:
    first = origin.commit("AB#1")
    origin.commit("AB#2")
    origin.commit("AB#3")
    project = project_for(origin)
    board.next_posts.extend(
        [None] + [httpx.Response(503)] * 5  # AB#1 goes through, AB#2 gives up
    )

    run = sync(client, headers, project)
    assert run["status"] == "partial"
    assert actions(client, headers, run) == [(1, "posted"), (2, "error"), (3, "posted")]
    assert cursors(db_engine) == {"main": first}  # not past the failed commit

    retry = sync(client, headers, project)
    assert retry["status"] == "success"
    assert actions(client, headers, retry) == [(2, "posted"), (3, "skipped_duplicate")]
    assert [board.count(i) for i in (1, 2, 3)] == [1, 1, 1]


def test_refused_comment_is_an_error_that_does_not_block(
    client: TestClient,
    headers: dict[str, str],
    origin: FixtureRepo,
    project_for: Any,
    board: FakeAzure,
    db_engine: Engine,
) -> None:
    origin.commit("AB#1")
    tip = origin.commit("AB#2")
    board.next_posts.append(httpx.Response(400, json={"message": "bad"}))
    run = sync(client, headers, project_for(origin))
    assert run["status"] == "partial"
    assert actions(client, headers, run) == [(1, "error"), (2, "posted")]
    assert cursors(db_engine) == {"main": tip}


# --- Dry runs and stale runs ---------------------------------------------------------------


def test_dry_run_shows_duplicates_and_missing_items(
    client: TestClient,
    headers: dict[str, str],
    origin: FixtureRepo,
    project_for: Any,
    board: FakeAzure,
    db_engine: Engine,
) -> None:
    origin.commit("AB#1")
    project = project_for(origin)
    sync(client, headers, project)
    origin.commit("AB#2 and AB#999")
    with db_engine.begin() as conn:  # rescan from the start, so AB#1 is seen again
        conn.execute(text("DELETE FROM project_cursors"))

    dry = sync(client, headers, project, dry_run=True)
    assert actions(client, headers, dry) == [
        (1, "skipped_duplicate"),
        (2, "would_post"),
        (999, "skipped_not_found"),
    ]
    assert board.total_comments() == 1
    assert cursors(db_engine) == {}  # dry runs never move cursors


def test_stale_runs_are_closed(
    app: FastAPI,
    client: TestClient,
    headers: dict[str, str],
    origin: FixtureRepo,
    project_for: Any,
    board: FakeAzure,
    db_engine: Engine,
) -> None:
    origin.commit("AB#1")
    project = project_for(origin)
    stuck = queue(app, client, headers, project)
    with db_engine.begin() as conn:
        conn.execute(text("UPDATE sync_runs SET status = 'running'"))
    fresh = queue(app, client, headers, project)

    with app.state.session_factory() as db:  # a recent heartbeat: not stale yet
        assert close_stale_runs(db, older_than=timedelta(minutes=10)) == 0

    age_runs(db_engine)
    with app.state.session_factory() as db:  # what the worker does when it starts
        assert close_stale_runs(db, older_than=timedelta(minutes=10)) == 2
        db.commit()
    for run_id in (stuck, fresh):
        run = client.get(f"/api/v1/runs/{run_id}", headers=headers).json()
        assert run["status"] == "failed"
        assert run["finished_at"] is not None
