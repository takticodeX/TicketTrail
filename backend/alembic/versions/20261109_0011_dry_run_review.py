"""dry-run review: manual links, exclusions, posting a reviewed selection

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_ACTIONS = (
    "'posted', 'would_post', 'skipped_duplicate', 'skipped_not_found', 'no_reference', 'error'"
)


def _pairs(table: str) -> None:
    op.create_table(
        table,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("commit_sha", sa.String(40), nullable=False),
        sa.Column("work_item_id", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f(f"fk_{table}_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f(f"fk_{table}_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("project_id", "commit_sha", "work_item_id", name=f"uq_{table}_pair"),
    )


def upgrade() -> None:
    _pairs("commit_links")
    _pairs("commit_exclusions")
    op.add_column(
        "sync_run_items",
        sa.Column("manual", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.drop_constraint(op.f("ck_sync_run_items_action_valid"), "sync_run_items", type_="check")
    op.create_check_constraint(
        op.f("ck_sync_run_items_action_valid"),
        "sync_run_items",
        f"action IN ({_OLD_ACTIONS}, 'excluded')",
    )
    op.add_column("sync_runs", sa.Column("source_run_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_sync_runs_source_run_id_sync_runs"),
        "sync_runs",
        "sync_runs",
        ["source_run_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_sync_runs_source_run_id_sync_runs"), "sync_runs", type_="foreignkey"
    )
    op.drop_column("sync_runs", "source_run_id")
    op.execute("DELETE FROM sync_run_items WHERE action = 'excluded'")
    op.drop_constraint(op.f("ck_sync_run_items_action_valid"), "sync_run_items", type_="check")
    op.create_check_constraint(
        op.f("ck_sync_run_items_action_valid"), "sync_run_items", f"action IN ({_OLD_ACTIONS})"
    )
    op.drop_column("sync_run_items", "manual")
    op.drop_table("commit_exclusions")
    op.drop_table("commit_links")
