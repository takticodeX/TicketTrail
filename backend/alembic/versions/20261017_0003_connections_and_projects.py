"""git_connections, azure_connections and projects

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _owned_columns(table: str) -> list[sa.Column[object]]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _owned_constraints(table: str) -> list[sa.Constraint]:
    return [
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f(f"fk_{table}_owner_id_users"), ondelete="CASCADE"
        ),
        sa.UniqueConstraint("owner_id", "name", name=f"uq_{table}_owner_name"),
    ]


def upgrade() -> None:
    op.create_table(
        "git_connections",
        *_owned_columns("git_connections"),
        sa.Column("repo_url", sa.String(2048), nullable=False),
        sa.Column("auth_type", sa.String(16), nullable=False),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column("secret_enc", sa.Text(), nullable=True),
        sa.Column("commit_url_template", sa.String(2048), nullable=True),
        sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_ok", sa.Boolean(), nullable=True),
        *_owned_constraints("git_connections"),
        sa.CheckConstraint(
            "auth_type IN ('token', 'basic', 'none')",
            name=op.f("ck_git_connections_auth_type_valid"),
        ),
    )
    op.create_index(op.f("ix_git_connections_owner_id"), "git_connections", ["owner_id"])

    op.create_table(
        "azure_connections",
        *_owned_columns("azure_connections"),
        sa.Column("organization_url", sa.String(2048), nullable=False),
        sa.Column("azure_project", sa.String(255), nullable=False),
        sa.Column("pat_enc", sa.Text(), nullable=False),
        sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_ok", sa.Boolean(), nullable=True),
        *_owned_constraints("azure_connections"),
    )
    op.create_index(op.f("ix_azure_connections_owner_id"), "azure_connections", ["owner_id"])

    op.create_table(
        "projects",
        *_owned_columns("projects"),
        sa.Column("git_connection_id", sa.Uuid(), nullable=False),
        sa.Column("azure_connection_id", sa.Uuid(), nullable=False),
        sa.Column(
            "branches",
            postgresql.ARRAY(sa.String(255)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("ticket_pattern", sa.String(500), nullable=False),
        sa.Column("comment_template", sa.Text(), nullable=False),
        sa.Column("start_from", sa.String(64), nullable=True),
        sa.Column("include_merge_commits", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("schedule_cron", sa.String(100), nullable=True),
        sa.Column("schedule_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("dry_run_default", sa.Boolean(), server_default=sa.false(), nullable=False),
        *_owned_constraints("projects"),
        sa.ForeignKeyConstraint(
            ["git_connection_id"],
            ["git_connections.id"],
            name=op.f("fk_projects_git_connection_id_git_connections"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["azure_connection_id"],
            ["azure_connections.id"],
            name=op.f("fk_projects_azure_connection_id_azure_connections"),
            ondelete="RESTRICT",
        ),
    )
    op.create_index(op.f("ix_projects_owner_id"), "projects", ["owner_id"])
    op.create_index(op.f("ix_projects_git_connection_id"), "projects", ["git_connection_id"])
    op.create_index(op.f("ix_projects_azure_connection_id"), "projects", ["azure_connection_id"])


def downgrade() -> None:
    op.drop_table("projects")
    op.drop_table("azure_connections")
    op.drop_table("git_connections")
