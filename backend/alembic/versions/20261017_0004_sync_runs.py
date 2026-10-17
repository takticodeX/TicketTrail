"""sync_runs, sync_run_items and project_cursors

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.schema import SchemaItem

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base(table: str) -> list[SchemaItem]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
    ]


def upgrade() -> None:
    op.create_table(
        "sync_runs",
        *_base("sync_runs"),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("trigger", sa.String(16), nullable=False),
        sa.Column("dry_run", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("commits_scanned", sa.Integer(), server_default="0", nullable=False),
        sa.Column("comments_posted", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skipped", sa.Integer(), server_default="0", nullable=False),
        sa.Column("errors", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_sync_runs_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "trigger IN ('manual', 'scheduled')", name=op.f("ck_sync_runs_trigger_valid")
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'success', 'partial', 'failed', 'skipped')",
            name=op.f("ck_sync_runs_status_valid"),
        ),
    )
    op.create_index("ix_sync_runs_project_id_created_at", "sync_runs", ["project_id", "created_at"])

    op.create_table(
        "sync_run_items",
        *_base("sync_run_items"),
        sa.Column("sync_run_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("commit_sha", sa.String(40), nullable=False),
        sa.Column("work_item_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("commit_subject", sa.String(500), server_default="", nullable=False),
        sa.Column("branch", sa.String(255), server_default="", nullable=False),
        sa.ForeignKeyConstraint(
            ["sync_run_id"],
            ["sync_runs.id"],
            name=op.f("fk_sync_run_items_sync_run_id_sync_runs"),
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "action IN ('posted', 'would_post', 'skipped_duplicate', 'skipped_not_found', "
            "'no_reference', 'error')",
            name=op.f("ck_sync_run_items_action_valid"),
        ),
    )
    op.create_index(
        "ix_sync_run_items_sync_run_id_action", "sync_run_items", ["sync_run_id", "action"]
    )
    op.create_index(
        "ix_sync_run_items_sync_run_id_position", "sync_run_items", ["sync_run_id", "position"]
    )

    op.create_table(
        "project_cursors",
        *_base("project_cursors"),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("branch", sa.String(255), nullable=False),
        sa.Column("last_sha", sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_project_cursors_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("project_id", "branch", name="uq_project_cursors_project_branch"),
    )


def downgrade() -> None:
    op.drop_table("project_cursors")
    op.drop_table("sync_run_items")
    op.drop_table("sync_runs")
