from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.sync.parser import DEFAULT_TICKET_PATTERN
from app.sync.template import DEFAULT_COMMENT_TEMPLATE
from tests.integration.helpers import (
    assert_validation_error,
    azure_payload,
    create,
    create_project,
    git_payload,
    signed_in,
)

pytestmark = pytest.mark.integration

URL = "/api/v1/projects"


@pytest.fixture
def headers(client: TestClient) -> dict[str, str]:
    return signed_in(client, "alice@example.com")


@pytest.fixture
def connections(client: TestClient, headers: dict[str, str]) -> dict[str, str]:
    return {
        "git_connection_id": create(client, "git-connections", headers, git_payload())["id"],
        "azure_connection_id": create(client, "azure-connections", headers, azure_payload())["id"],
    }


def _post(
    client: TestClient, headers: dict[str, str], connections: dict[str, str], **body: Any
) -> Any:
    return client.post(URL, headers=headers, json={"name": "P", **connections, **body})


def test_create_with_defaults(
    client: TestClient, headers: dict[str, str], connections: dict[str, str]
) -> None:
    response = _post(client, headers, connections)
    assert response.status_code == 201
    project = response.json()
    assert project["branches"] == []
    assert project["ticket_pattern"] == DEFAULT_TICKET_PATTERN
    assert project["comment_template"] == DEFAULT_COMMENT_TEMPLATE
    assert project["start_from"] is None
    assert project["include_merge_commits"] is False
    assert project["schedule_cron"] is None
    assert project["schedule_enabled"] is False
    assert project["dry_run_default"] is False


def test_create_with_every_field(
    client: TestClient, headers: dict[str, str], connections: dict[str, str]
) -> None:
    project = _post(
        client,
        headers,
        connections,
        branches=["main", "release/1.0", "main"],
        ticket_pattern=r"PROJ-(\d+)",
        comment_template="{short_sha}: {subject} tt:{sha}",
        start_from="2026-01-31",
        include_merge_commits=True,
        schedule_cron="0 8 * * 1-5",
        schedule_enabled=True,
        dry_run_default=True,
    ).json()
    assert project["branches"] == ["main", "release/1.0"]  # de-duplicated
    assert project["start_from"] == "2026-01-31"
    assert project["schedule_cron"] == "0 8 * * 1-5"
    assert project["schedule_enabled"] is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ticket_pattern", r"AB#\d+"),
        ("ticket_pattern", r"AB#(\w+)"),
        ("ticket_pattern", r"(AB)#(\d+)"),
        ("ticket_pattern", r"AB#(\d+"),
        ("comment_template", "{unknown}"),
        ("comment_template", "{sha"),
        ("start_from", "yesterday"),
        ("start_from", "2026-02-30"),
        ("start_from", "xyz1234"),
        ("branches", ["bad branch"]),
        ("branches", ["-main"]),
        ("branches", ["a..b"]),
        ("schedule_cron", "every day"),
        ("schedule_cron", "0 8 * *"),
    ],
)
def test_validation(
    client: TestClient,
    headers: dict[str, str],
    connections: dict[str, str],
    field: str,
    value: Any,
) -> None:
    assert_validation_error(_post(client, headers, connections, **{field: value}), field)


def test_start_from_accepts_a_sha(
    client: TestClient, headers: dict[str, str], connections: dict[str, str]
) -> None:
    project = _post(client, headers, connections, start_from="ABCDEF1").json()
    assert project["start_from"] == "abcdef1"


def test_schedule_respects_minimum_interval(
    client: TestClient, headers: dict[str, str], connections: dict[str, str]
) -> None:
    response = _post(client, headers, connections, schedule_cron="*/2 * * * *")
    assert_validation_error(response, "schedule_cron")
    assert "every 5 minutes" in str(response.json())
    assert _post(client, headers, connections, schedule_cron="*/5 * * * *").status_code == 201


def test_minimum_interval_comes_from_settings(app_factory: Any) -> None:
    with TestClient(app_factory(min_schedule_minutes=60)) as client:
        headers = signed_in(client, "a@example.com")
        response = create_project_response(client, headers, schedule_cron="*/30 * * * *")
        assert response.status_code == 422


def create_project_response(client: TestClient, headers: dict[str, str], **body: Any) -> Any:
    git = create(client, "git-connections", headers, git_payload())["id"]
    azure = create(client, "azure-connections", headers, azure_payload())["id"]
    return client.post(
        URL,
        headers=headers,
        json={"name": "P", "git_connection_id": git, "azure_connection_id": azure, **body},
    )


def test_enabled_schedule_needs_cron(
    client: TestClient, headers: dict[str, str], connections: dict[str, str]
) -> None:
    response = _post(client, headers, connections, schedule_enabled=True)
    assert response.status_code == 422


def test_unknown_connection_is_rejected(
    client: TestClient, headers: dict[str, str], connections: dict[str, str]
) -> None:
    response = _post(
        client,
        headers,
        {**connections, "git_connection_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert_validation_error(response, "git_connection_id")


def test_names_are_unique_per_user(
    client: TestClient, headers: dict[str, str], connections: dict[str, str]
) -> None:
    assert _post(client, headers, connections).status_code == 201
    response = _post(client, headers, connections)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "name_taken"


def test_update_is_partial(client: TestClient, headers: dict[str, str]) -> None:
    project = create_project(client, headers, start_from="2026-01-01", branches=["main"])
    response = client.patch(
        f"{URL}/{project['id']}", headers=headers, json={"ticket_pattern": r"#(\d+)"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ticket_pattern"] == r"#(\d+)"
    assert body["start_from"] == "2026-01-01"
    assert body["branches"] == ["main"]


def test_update_can_clear_optional_fields(client: TestClient, headers: dict[str, str]) -> None:
    project = create_project(client, headers, start_from="2026-01-01", schedule_cron="0 * * * *")
    body = client.patch(
        f"{URL}/{project['id']}",
        headers=headers,
        json={"start_from": None, "schedule_cron": None, "branches": []},
    ).json()
    assert body["start_from"] is None
    assert body["schedule_cron"] is None
    assert body["branches"] == []


def test_update_null_for_required_field_is_ignored(
    client: TestClient, headers: dict[str, str]
) -> None:
    project = create_project(client, headers)
    body = client.patch(f"{URL}/{project['id']}", headers=headers, json={"name": None}).json()
    assert body["name"] == project["name"]


def test_update_rechecks_schedule(client: TestClient, headers: dict[str, str]) -> None:
    project = create_project(client, headers)
    response = client.patch(
        f"{URL}/{project['id']}", headers=headers, json={"schedule_enabled": True}
    )
    assert response.status_code == 422
    response = client.patch(
        f"{URL}/{project['id']}",
        headers=headers,
        json={"schedule_enabled": True, "schedule_cron": "* * * * *"},
    )
    assert_validation_error(response, "schedule_cron")


def test_update_can_switch_connections(client: TestClient, headers: dict[str, str]) -> None:
    project = create_project(client, headers)
    other_git = create(client, "git-connections", headers, git_payload(name="Other"))["id"]
    body = client.patch(
        f"{URL}/{project['id']}", headers=headers, json={"git_connection_id": other_git}
    ).json()
    assert body["git_connection_id"] == other_git


def test_list_get_delete(client: TestClient, headers: dict[str, str]) -> None:
    project = create_project(client, headers)
    assert client.get(URL, headers=headers).json()["total"] == 1
    assert client.get(f"{URL}/{project['id']}", headers=headers).json()["id"] == project["id"]
    assert client.delete(f"{URL}/{project['id']}", headers=headers).status_code == 204
    assert client.get(f"{URL}/{project['id']}", headers=headers).status_code == 404
    # its connections are free again
    git_id = project["git_connection_id"]
    assert client.delete(f"/api/v1/git-connections/{git_id}", headers=headers).status_code == 204


# --- Pattern tester --------------------------------------------------------------------------


def test_pattern_tester_before_saving(client: TestClient, headers: dict[str, str]) -> None:
    response = client.post(
        f"{URL}/test-pattern",
        headers=headers,
        json={
            "pattern": r"(?:fixes|refs)\s+#(\d+)",
            "samples": ["Fixes #12 and refs #13", "chore: nothing here", "fixes #12 again #12"],
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "pattern": r"(?:fixes|refs)\s+#(\d+)",
        "results": [
            {"ids": [12, 13], "error": None},
            {"ids": [], "error": None},
            {"ids": [12], "error": None},
        ],
    }


def test_pattern_tester_rejects_invalid_patterns(
    client: TestClient, headers: dict[str, str]
) -> None:
    response = client.post(
        f"{URL}/test-pattern", headers=headers, json={"pattern": r"AB#\d+", "samples": ["x"]}
    )
    assert_validation_error(response, "pattern")
    assert "capture group" in str(response.json())
    missing = client.post(f"{URL}/test-pattern", headers=headers, json={"samples": ["x"]})
    assert_validation_error(missing, "pattern")


def test_pattern_tester_reports_timeouts_per_sample(
    client: TestClient, headers: dict[str, str]
) -> None:
    body = client.post(
        f"{URL}/test-pattern",
        headers=headers,
        json={"pattern": r"(?:a|a)+#(\d+)", "samples": ["a" * 40 + "!", "a#5"]},
    ).json()
    assert body["results"][0]["ids"] == []
    assert "too long" in body["results"][0]["error"]
    assert body["results"][1] == {"ids": [5], "error": None}


def test_pattern_tester_limits_samples(client: TestClient, headers: dict[str, str]) -> None:
    response = client.post(
        f"{URL}/test-pattern",
        headers=headers,
        json={"pattern": DEFAULT_TICKET_PATTERN, "samples": ["x"] * 51},
    )
    assert response.status_code == 422


def test_project_pattern_tester_uses_saved_pattern(
    client: TestClient, headers: dict[str, str]
) -> None:
    project = create_project(client, headers, ticket_pattern=r"PROJ-(\d+)")
    body = client.post(
        f"{URL}/{project['id']}/test-pattern",
        headers=headers,
        json={"samples": ["PROJ-4 AB#5"]},
    ).json()
    assert body["pattern"] == r"PROJ-(\d+)"
    assert body["results"] == [{"ids": [4], "error": None}]

    override = client.post(
        f"{URL}/{project['id']}/test-pattern",
        headers=headers,
        json={"pattern": DEFAULT_TICKET_PATTERN, "samples": ["PROJ-4 AB#5"]},
    ).json()
    assert override["results"] == [{"ids": [5], "error": None}]


def test_pattern_tester_requires_authentication(app: FastAPI) -> None:
    client = TestClient(app)
    response = client.post(f"{URL}/test-pattern", json={"pattern": "#(\\d+)", "samples": []})
    assert response.status_code == 401
