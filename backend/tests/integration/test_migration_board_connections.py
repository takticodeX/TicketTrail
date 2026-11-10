"""Migration 0012 keeps existing Azure data: connections, projects, comments, reviews."""

import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

from tests.integration.conftest import alembic_config

pytestmark = pytest.mark.integration

SHA = "a" * 40


@pytest.fixture
def scratch_database(database_url: str) -> Iterator[tuple[str, Engine]]:
    """A database of its own, so it can be taken to an older revision."""
    name = f"tt_migration_{uuid.uuid4().hex[:8]}"
    admin = create_engine(database_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = make_url(database_url).set(database=name).render_as_string(hide_password=False)
    engine = create_engine(url)
    try:
        yield url, engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


def _seed(engine: Engine) -> dict[str, uuid.UUID]:
    ids = {key: uuid.uuid4() for key in ("user", "git", "azure", "project", "run")}
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email, password_hash, display_name) "
                "VALUES (:user, 'ada@example.com', 'x', 'Ada')"
            ),
            ids,
        )
        conn.execute(
            text(
                "INSERT INTO git_connections (id, owner_id, name, repo_url, auth_type) "
                "VALUES (:git, :user, 'Repo', 'https://example.com/r.git', 'none')"
            ),
            ids,
        )
        conn.execute(
            text(
                "INSERT INTO azure_connections (id, owner_id, name, organization_url, "
                "azure_project, pat_enc) VALUES (:azure, :user, 'Board', "
                "'https://dev.azure.com/acme', 'Web', 'ciphertext')"
            ),
            ids,
        )
        conn.execute(
            text(
                "INSERT INTO projects (id, owner_id, name, git_connection_id, "
                "azure_connection_id, ticket_pattern, comment_template) "
                "VALUES (:project, :user, 'App', :git, :azure, 'AB#(\\d+)', '{message}')"
            ),
            ids,
        )
        conn.execute(
            text(
                "INSERT INTO sync_runs (id, project_id, trigger, status) "
                "VALUES (:run, :project, 'manual', 'success')"
            ),
            ids,
        )
        conn.execute(
            text(
                "INSERT INTO sync_run_items (id, sync_run_id, position, commit_sha, "
                "work_item_id, action) VALUES (:id, :run, 0, :sha, 42, 'posted')"
            ),
            {"id": uuid.uuid4(), "sha": SHA, **ids},
        )
        conn.execute(
            text(
                "INSERT INTO posted_comments (id, project_id, commit_sha, work_item_id, "
                "azure_comment_id, status) VALUES (:id, :project, :sha, 42, 7, 'posted')"
            ),
            {"id": uuid.uuid4(), "sha": SHA, **ids},
        )
        for table in ("commit_links", "commit_exclusions"):
            conn.execute(
                text(
                    f"INSERT INTO {table} (id, project_id, commit_sha, work_item_id) "  # noqa: S608
                    "VALUES (:id, :project, :sha, 43)"
                ),
                {"id": uuid.uuid4(), "sha": SHA, **ids},
            )
        conn.execute(
            text(
                "INSERT INTO audit_events (id, actor_email, action, resource_type, "
                "resource_id, resource_name, owner_label) VALUES (:id, 'root@example.com', "
                "'update', 'azure_connection', :azure, 'Board', 'ada@example.com')"
            ),
            {"id": uuid.uuid4(), **ids},
        )
    return ids


def test_azure_data_becomes_board_data_and_back(
    scratch_database: tuple[str, Engine],
) -> None:
    url, engine = scratch_database
    config = alembic_config(url)
    command.upgrade(config, "0011")
    ids = _seed(engine)

    command.upgrade(config, "0012")
    with engine.connect() as conn:
        board = conn.execute(
            text("SELECT kind, url, scope, secret_enc FROM board_connections WHERE id = :azure"),
            ids,
        ).one()
        assert tuple(board) == ("azure", "https://dev.azure.com/acme", "Web", "ciphertext")
        assert (
            conn.execute(
                text("SELECT board_connection_id FROM projects WHERE id = :project"), ids
            ).scalar_one()
            == ids["azure"]
        )
        assert tuple(
            conn.execute(text("SELECT work_item_id, comment_id FROM posted_comments")).one()
        ) == ("42", "7")
        assert conn.execute(text("SELECT work_item_id FROM sync_run_items")).scalar_one() == "42"
        for table in ("commit_links", "commit_exclusions"):
            assert (
                conn.execute(text(f"SELECT work_item_id FROM {table}")).scalar_one()  # noqa: S608
                == "43"
            )
        assert (
            conn.execute(text("SELECT resource_type FROM audit_events")).scalar_one()
            == "board_connection"
        )
        # The same commit and work item still collide: de-duplication is unchanged.
        with pytest.raises(Exception, match="uq_posted_comments_pair"):
            conn.execute(
                text(
                    "INSERT INTO posted_comments (id, project_id, commit_sha, work_item_id, "
                    "status) VALUES (:id, :project, :sha, '42', 'pending')"
                ),
                {"id": uuid.uuid4(), "sha": SHA, **ids},
            )
        conn.rollback()

    command.downgrade(config, "0011")
    with engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT azure_project FROM azure_connections WHERE id = :azure"), ids
            ).scalar_one()
            == "Web"
        )
        assert conn.execute(text("SELECT azure_comment_id FROM posted_comments")).scalar_one() == 7
        assert (
            conn.execute(text("SELECT resource_type FROM audit_events")).scalar_one()
            == "azure_connection"
        )
