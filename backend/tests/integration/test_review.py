"""Reviewing a dry run: the work item picker, manual links, exclusions, Post selected."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.fixtures.azure import FakeAzure
from tests.fixtures.repos import FixtureRepo
from tests.integration.helpers import bearer, create_project, login, register

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("no_dns")]

API = "/api/v1"


@pytest.fixture(autouse=True)
def board(azure: FakeAzure) -> FakeAzure:
    azure.work_items.update({1, 2, 3, 4, 5})
    azure.details.update(
        {
            3: ("Login page crashes", "Bug", "Active"),
            4: ("Old checkout", "User Story", "Closed"),
            5: ("Checkout redesign", "User Story", "New"),
        }
    )
    return azure


@pytest.fixture
def headers(client: TestClient) -> dict[str, str]:
    register(client, "olivia@example.com")
    return bearer(login(client, "olivia@example.com"))


@pytest.fixture
def project(
    client: TestClient, headers: dict[str, str], db_engine: Engine, tmp_path: Path
) -> dict[str, Any]:
    origin = FixtureRepo(tmp_path / "origin")
    origin.commit("Fix login AB#1")
    origin.commit("Refactor the cart")  # no reference
    origin.commit("Tidy up AB#99")  # no such work item
    origin.commit("Feature AB#2")
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


def dry_run(client: TestClient, headers: dict[str, str], project: dict[str, Any]) -> str:
    response = client.post(
        f"{API}/projects/{project['id']}/sync", headers=headers, json={"dry_run": True}
    )
    assert response.status_code == 202, response.text
    run_id: str = response.json()["run_id"]
    return run_id


def items(client: TestClient, headers: dict[str, str], run_id: str) -> dict[str, dict[str, Any]]:
    """The run's rows by commit subject (and work item, when a commit has several)."""
    page = client.get(f"{API}/runs/{run_id}/items?page_size=100", headers=headers).json()
    return {i["commit_subject"]: i for i in page["items"]}


def test_search_lists_open_work_items_first(
    client: TestClient, headers: dict[str, str], project: dict[str, Any]
) -> None:
    url = f"{API}/projects/{project['id']}/work-items"
    found = client.get(f"{url}?q=checkout", headers=headers).json()
    assert found["ok"] is True
    assert [(w["id"], w["closed"]) for w in found["items"]] == [(5, False), (4, True)]
    assert found["items"][0] == {
        "id": 5,
        "title": "Checkout redesign",
        "type": "User Story",
        "state": "New",
        "closed": False,
    }
    by_id = client.get(f"{url}?q=%233", headers=headers).json()
    assert [w["id"] for w in by_id["items"]] == [3]
    everything = client.get(url, headers=headers).json()
    assert [w["id"] for w in everything["items"]] == [5, 3, 2, 1, 4]  # closed last


def test_review_links_deselects_and_posts_exactly_the_selection(
    client: TestClient,
    headers: dict[str, str],
    project: dict[str, Any],
    azure: FakeAzure,
) -> None:
    run_id = dry_run(client, headers, project)
    rows = items(client, headers, run_id)
    assert {s: r["action"] for s, r in rows.items()} == {
        "Fix login AB#1": "would_post",
        "Refactor the cart": "no_reference",
        "Tidy up AB#99": "skipped_not_found",
        "Feature AB#2": "would_post",
    }

    def put(subject: str, work_item_id: int) -> Any:
        return client.put(
            f"{API}/runs/{run_id}/items/{rows[subject]['id']}/work-item",
            headers=headers,
            json={"work_item_id": work_item_id},
        )

    linked = put("Refactor the cart", 5)
    assert linked.status_code == 200, linked.text
    assert (linked.json()["action"], linked.json()["work_item_id"], linked.json()["manual"]) == (
        "would_post",
        5,
        True,
    )
    fixed = put("Tidy up AB#99", 3).json()
    assert (fixed["action"], fixed["work_item_id"]) == ("would_post", 3)
    excluded = client.post(
        f"{API}/runs/{run_id}/items/{rows['Feature AB#2']['id']}/exclude", headers=headers
    )
    assert excluded.json()["action"] == "excluded"
    detail = client.get(f"{API}/runs/{run_id}", headers=headers).json()
    assert detail["counts_by_action"] == {"would_post": 3, "excluded": 1}

    started = client.post(f"{API}/runs/{run_id}/post", headers=headers)
    assert started.status_code == 202, started.text
    posted_run = client.get(f"{API}/runs/{started.json()['run_id']}", headers=headers).json()
    assert (posted_run["status"], posted_run["dry_run"], posted_run["source_run_id"]) == (
        "success",
        False,
        run_id,
    )
    assert posted_run["comments_posted"] == 3
    assert {wi: azure.count(wi) for wi in (1, 2, 3, 5)} == {1: 1, 2: 0, 3: 1, 5: 1}
    posted = items(client, headers, posted_run["id"])
    assert posted["Refactor the cart"]["manual"] is True
    assert posted["Fix login AB#1"]["manual"] is False


def test_links_and_exclusions_apply_to_every_later_run(
    client: TestClient,
    headers: dict[str, str],
    project: dict[str, Any],
    azure: FakeAzure,
) -> None:
    run_id = dry_run(client, headers, project)
    rows = items(client, headers, run_id)
    client.put(
        f"{API}/runs/{run_id}/items/{rows['Refactor the cart']['id']}/work-item",
        headers=headers,
        json={"work_item_id": 5},
    )
    client.post(f"{API}/runs/{run_id}/items/{rows['Feature AB#2']['id']}/exclude", headers=headers)

    # A later dry run shows them; Sync now posts the link and never the excluded pair.
    again = items(client, headers, dry_run(client, headers, project))
    assert (again["Refactor the cart"]["action"], again["Refactor the cart"]["manual"]) == (
        "would_post",
        True,
    )
    assert again["Feature AB#2"]["action"] == "excluded"
    sync = client.post(
        f"{API}/projects/{project['id']}/sync", headers=headers, json={"dry_run": False}
    )
    real = items(client, headers, sync.json()["run_id"])
    assert real["Refactor the cart"]["action"] == "posted"
    assert real["Feature AB#2"]["action"] == "excluded"
    assert (azure.count(5), azure.count(2)) == (1, 0)


def test_a_deselected_row_can_be_selected_again(
    client: TestClient, headers: dict[str, str], project: dict[str, Any]
) -> None:
    run_id = dry_run(client, headers, project)
    row = items(client, headers, run_id)["Feature AB#2"]
    url = f"{API}/runs/{run_id}/items/{row['id']}/exclude"
    client.post(url, headers=headers)
    back = client.delete(url, headers=headers)
    assert back.json()["action"] == "would_post"
    again = items(client, headers, dry_run(client, headers, project))
    assert again["Feature AB#2"]["action"] == "would_post"


def test_changing_a_linked_row_replaces_the_link(
    client: TestClient, headers: dict[str, str], project: dict[str, Any], db_engine: Engine
) -> None:
    run_id = dry_run(client, headers, project)
    row = items(client, headers, run_id)["Refactor the cart"]
    url = f"{API}/runs/{run_id}/items/{row['id']}/work-item"
    client.put(url, headers=headers, json={"work_item_id": 5})
    client.put(url, headers=headers, json={"work_item_id": 3})
    with db_engine.connect() as conn:
        links = conn.execute(text("SELECT work_item_id FROM commit_links")).scalars().all()
        exclusions = conn.execute(text("SELECT count(*) FROM commit_exclusions")).scalar()
    assert (links, exclusions) == ([3], 0)


def test_review_errors(
    client: TestClient, headers: dict[str, str], project: dict[str, Any]
) -> None:
    run_id = dry_run(client, headers, project)
    rows = items(client, headers, run_id)
    base = f"{API}/runs/{run_id}/items"

    def code(response: Any) -> str:
        value: str = response.json()["error"]["code"]
        return value

    assert code(
        client.post(f"{base}/{rows['Refactor the cart']['id']}/exclude", headers=headers)
    ) == ("not_selectable")
    taken = client.put(
        f"{base}/{rows['Fix login AB#1']['id']}/work-item",
        headers=headers,
        json={"work_item_id": 1},
    )
    assert taken.status_code == 200  # the same work item: nothing to change
    other = dry_run(client, headers, project)
    foreign = items(client, headers, other)["Fix login AB#1"]["id"]
    assert client.post(f"{base}/{foreign}/exclude", headers=headers).status_code == 404

    sync = client.post(
        f"{API}/projects/{project['id']}/sync", headers=headers, json={"dry_run": False}
    ).json()["run_id"]
    real_row = items(client, headers, sync)["Fix login AB#1"]["id"]
    not_dry = client.post(f"{API}/runs/{sync}/items/{real_row}/exclude", headers=headers)
    assert code(not_dry) == "not_reviewable"

    for row in ("Fix login AB#1", "Feature AB#2"):
        client.post(f"{base}/{rows[row]['id']}/exclude", headers=headers)
    assert code(client.post(f"{API}/runs/{run_id}/post", headers=headers)) == "nothing_selected"


def test_only_editors_review(
    client: TestClient, headers: dict[str, str], project: dict[str, Any]
) -> None:
    register(client, "victor@example.com")
    viewer = bearer(login(client, "victor@example.com"))
    register(client, "sam@example.com")
    stranger = bearer(login(client, "sam@example.com"))
    client.post(
        f"{API}/projects/{project['id']}/shares",
        headers=headers,
        json={"email": "victor@example.com", "role": "viewer"},
    )
    run_id = dry_run(client, headers, project)
    row = items(client, headers, run_id)["Feature AB#2"]["id"]
    calls = [
        ("GET", f"/projects/{project['id']}/work-items", None),
        ("PUT", f"/runs/{run_id}/items/{row}/work-item", {"work_item_id": 3}),
        ("POST", f"/runs/{run_id}/items/{row}/exclude", None),
        ("DELETE", f"/runs/{run_id}/items/{row}/exclude", None),
        ("POST", f"/runs/{run_id}/post", None),
    ]
    for method, path, body in calls:
        as_viewer = client.request(method, API + path, headers=viewer, json=body)
        assert as_viewer.status_code == 403, (method, path)
        as_stranger = client.request(method, API + path, headers=stranger, json=body)
        assert as_stranger.status_code == 404, (method, path)
