"""The dry-run engine against fixture repositories and a real Postgres."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.fixtures.repos import FixtureRepo
from tests.integration.helpers import create_project, signed_in

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("no_dns")]


@pytest.fixture
def origin(tmp_path: Path) -> FixtureRepo:
    return FixtureRepo(tmp_path / "origin")


@pytest.fixture
def headers(client: TestClient) -> dict[str, str]:
    return signed_in(client, "alice@example.com")


ProjectFactory = Callable[..., dict[str, Any]]


@pytest.fixture
def project_for(client: TestClient, headers: dict[str, str], db_engine: Engine) -> ProjectFactory:
    """A project whose Git connection points at a fixture repo.

    Set in the database: the API (rightly) only accepts https:// URLs.
    """

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


def dry_run(client: TestClient, headers: dict[str, str], project: dict[str, Any]) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/projects/{project['id']}/sync", headers=headers, json={"dry_run": True}
    )
    assert response.status_code == 202, response.text
    run: dict[str, Any] = client.get(
        f"/api/v1/runs/{response.json()['run_id']}", headers=headers
    ).json()
    return run


def items(
    client: TestClient, headers: dict[str, str], run: dict[str, Any], **params: Any
) -> list[Any]:
    page = client.get(
        f"/api/v1/runs/{run['id']}/items",
        headers=headers,
        params={"page_size": 100, **params},
    ).json()
    result: list[Any] = page["items"]
    return result


def pairs(run_items: list[Any]) -> list[tuple[str, int | None, str]]:
    return [(i["commit_subject"], i["work_item_id"], i["action"]) for i in run_items]


def test_dry_run_lists_each_commit_with_its_ids(
    client: TestClient, headers: dict[str, str], origin: FixtureRepo, project_for: ProjectFactory
) -> None:
    origin.commit("Fix login AB#12")
    origin.commit("chore: bump deps")
    origin.commit("Refactor billing AB#45\n\nAlso touches ab#46 and AB#45 again.")
    run = dry_run(client, headers, project_for(origin))

    assert run["status"] == "success"
    assert run["dry_run"] is True
    assert run["commits_scanned"] == 3
    assert run["comments_posted"] == 0
    assert run["counts_by_action"] == {"would_post": 3, "no_reference": 1}
    assert pairs(items(client, headers, run)) == [
        ("Fix login AB#12", 12, "would_post"),
        ("chore: bump deps", None, "no_reference"),
        ("Refactor billing AB#45", 45, "would_post"),
        ("Refactor billing AB#45", 46, "would_post"),
    ]
    first = items(client, headers, run)[0]
    assert first["branch"] == "main"
    assert len(first["commit_sha"]) == 40


def test_nothing_is_sent_to_azure(
    client: TestClient, headers: dict[str, str], origin: FixtureRepo, project_for: ProjectFactory
) -> None:
    origin.commit("Fix AB#1")
    project = project_for(origin)
    with respx.mock(assert_all_called=False) as azure:
        route = azure.route(host="dev.azure.com").mock(return_value=httpx.Response(500))
        assert dry_run(client, headers, project)["status"] == "success"
    assert not route.called


def test_merge_commits_are_skipped_by_default(
    client: TestClient, headers: dict[str, str], origin: FixtureRepo, project_for: ProjectFactory
) -> None:
    origin.commit("base")
    origin.checkout("feature", create=True)
    origin.commit("Feature AB#7")
    origin.checkout("main")
    origin.merge("feature", "Merge feature (AB#7)")

    run = dry_run(client, headers, project_for(origin))
    assert pairs(items(client, headers, run)) == [
        ("base", None, "no_reference"),
        ("Feature AB#7", 7, "would_post"),
    ]


def test_merge_commits_can_be_included(
    client: TestClient, headers: dict[str, str], origin: FixtureRepo, project_for: ProjectFactory
) -> None:
    origin.commit("base")
    origin.checkout("feature", create=True)
    origin.commit("Feature AB#7")
    origin.checkout("main")
    origin.merge("feature", "Merge feature (AB#8)")

    run = dry_run(client, headers, project_for(origin, include_merge_commits=True))
    assert ("Merge feature (AB#8)", 8, "would_post") in pairs(items(client, headers, run))


def test_default_branch_is_used_when_none_configured(
    client: TestClient, headers: dict[str, str], origin: FixtureRepo, project_for: ProjectFactory
) -> None:
    origin.commit("on main AB#1")
    origin.checkout("trunk", create=True)  # the origin's HEAD now points at trunk
    origin.commit("on trunk AB#2")

    run = dry_run(client, headers, project_for(origin))
    assert {i["branch"] for i in items(client, headers, run)} == {"trunk"}
    assert [i["work_item_id"] for i in items(client, headers, run)] == [1, 2]


def test_shared_commits_count_once_across_branches(
    client: TestClient, headers: dict[str, str], origin: FixtureRepo, project_for: ProjectFactory
) -> None:
    origin.commit("shared AB#1")
    origin.checkout("release", create=True)
    origin.commit("release only AB#2")
    origin.checkout("main")
    origin.commit("main only AB#3")

    run = dry_run(client, headers, project_for(origin, branches=["main", "release"]))
    assert run["commits_scanned"] == 3
    assert sorted(i["work_item_id"] for i in items(client, headers, run)) == [1, 2, 3]


def test_start_from_a_date(
    client: TestClient, headers: dict[str, str], origin: FixtureRepo, project_for: ProjectFactory
) -> None:
    origin.commit("Jan 1 AB#1")
    origin.commit("Jan 2 AB#2")
    origin.commit("Jan 3 AB#3")
    run = dry_run(client, headers, project_for(origin, start_from="2026-01-02"))
    assert [i["work_item_id"] for i in items(client, headers, run)] == [2, 3]


def test_start_from_a_commit(
    client: TestClient, headers: dict[str, str], origin: FixtureRepo, project_for: ProjectFactory
) -> None:
    origin.commit("one AB#1")
    start = origin.commit("two AB#2")
    origin.commit("three AB#3")
    run = dry_run(client, headers, project_for(origin, start_from=start))
    assert [i["work_item_id"] for i in items(client, headers, run)] == [3]


def test_unknown_start_commit_fails_the_run(
    client: TestClient, headers: dict[str, str], origin: FixtureRepo, project_for: ProjectFactory
) -> None:
    origin.commit("one")
    run = dry_run(client, headers, project_for(origin, start_from="abcdef1"))
    assert run["status"] == "failed"
    assert "start commit abcdef1" in run["error_message"]


def test_missing_branch_makes_a_partial_run(
    client: TestClient, headers: dict[str, str], origin: FixtureRepo, project_for: ProjectFactory
) -> None:
    origin.commit("on main AB#1")
    run = dry_run(client, headers, project_for(origin, branches=["main", "gone"]))
    assert run["status"] == "partial"
    assert run["errors"] == 1
    assert "'gone' does not exist" in run["error_message"]
    assert [i["work_item_id"] for i in items(client, headers, run)] == [1]


def test_dry_runs_do_not_move_cursors(
    client: TestClient,
    headers: dict[str, str],
    origin: FixtureRepo,
    project_for: ProjectFactory,
    db_engine: Engine,
) -> None:
    origin.commit("one AB#1")
    project = project_for(origin)
    dry_run(client, headers, project)
    origin.commit("two AB#2")
    second = dry_run(client, headers, project)  # sees the whole history again

    assert [i["work_item_id"] for i in items(client, headers, second)] == [1, 2]
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM project_cursors")).scalar_one() == 0


def _set_cursor(db_engine: Engine, project: dict[str, Any], sha: str) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO project_cursors (id, project_id, branch, last_sha) "
                "VALUES (gen_random_uuid(), :project, 'main', :sha)"
            ),
            {"project": project["id"], "sha": sha},
        )


def test_cursor_limits_the_scan(
    client: TestClient,
    headers: dict[str, str],
    origin: FixtureRepo,
    project_for: ProjectFactory,
    db_engine: Engine,
) -> None:
    done = origin.commit("already synced AB#1")
    origin.commit("new AB#2")
    project = project_for(origin)
    _set_cursor(db_engine, project, done)  # as a real sync (Milestone 5) would leave it

    run = dry_run(client, headers, project)
    assert [i["work_item_id"] for i in items(client, headers, run)] == [2]


def test_force_push_falls_back_to_a_full_scan(
    client: TestClient,
    headers: dict[str, str],
    origin: FixtureRepo,
    project_for: ProjectFactory,
    db_engine: Engine,
) -> None:
    origin.commit("base AB#1")
    old_tip = origin.commit("old tip AB#2")
    project = project_for(origin)
    dry_run(client, headers, project)  # mirrors the old history
    _set_cursor(db_engine, project, old_tip)
    origin.rewrite_last("rewritten tip AB#3")

    run = dry_run(client, headers, project)
    assert run["status"] == "success"
    assert "history of 'main' was rewritten" in run["error_message"]
    assert [i["work_item_id"] for i in items(client, headers, run)] == [1, 3]


def test_pattern_timeout_is_an_item_error(
    client: TestClient, headers: dict[str, str], origin: FixtureRepo, project_for: ProjectFactory
) -> None:
    origin.commit("a" * 40 + "!")
    origin.commit("a#5")
    run = dry_run(client, headers, project_for(origin, ticket_pattern=r"(?:a|a)+#(\d+)"))
    assert run["status"] == "partial"
    assert run["errors"] == 1
    actions = items(client, headers, run)
    assert actions[0]["action"] == "error"
    assert "took too long" in actions[0]["detail"]
    assert (actions[1]["work_item_id"], actions[1]["action"]) == (5, "would_post")


def test_unreachable_repository_fails_the_run(
    client: TestClient,
    headers: dict[str, str],
    tmp_path: Path,
    project_for: ProjectFactory,
    db_engine: Engine,
) -> None:
    origin = FixtureRepo(tmp_path / "soon-gone")
    origin.commit("x")
    project = project_for(origin)
    with db_engine.begin() as conn:
        conn.execute(
            text("UPDATE git_connections SET repo_url = :url"),
            {"url": (tmp_path / "missing").as_uri()},
        )
    run = dry_run(client, headers, project)
    assert run["status"] == "failed"
    assert "repository was not found" in run["error_message"]
    assert run["finished_at"] is not None


def test_private_hosts_are_refused(
    client: TestClient,
    headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    db_engine: Engine,
) -> None:
    from app.core.urls import check_public_host
    from app.sync import engine

    monkeypatch.setattr(engine, "check_public_host", check_public_host)  # undo no_dns
    project = create_project(client, headers)
    with db_engine.begin() as conn:
        conn.execute(text("UPDATE git_connections SET repo_url = 'https://10.0.0.5/repo.git'"))

    run = dry_run(client, headers, project)
    assert run["status"] == "failed"
    assert "private address" in run["error_message"]
