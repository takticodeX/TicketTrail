"""project sharing, run authors and ownership transfers

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _user_fk(table: str, column: str, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], ["users.id"], name=op.f(f"fk_{table}_{column}_users"), ondelete=ondelete
    )


def upgrade() -> None:
    op.create_table(
        "project_shares",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_shares")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_project_shares_project_id_projects"),
            ondelete="CASCADE",
        ),
        _user_fk("project_shares", "user_id", "CASCADE"),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_shares_project_user"),
        sa.CheckConstraint(
            "role IN ('viewer', 'editor')", name=op.f("ck_project_shares_role_valid")
        ),
    )
    op.create_index(op.f("ix_project_shares_user_id"), "project_shares", ["user_id"], unique=False)

    op.add_column("sync_runs", sa.Column("triggered_by_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_sync_runs_triggered_by_id_users"),
        "sync_runs",
        "users",
        ["triggered_by_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "ownership_transfers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("admin_id", sa.Uuid(), nullable=True),
        sa.Column("from_user_id", sa.Uuid(), nullable=True),
        sa.Column("to_user_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("projects_moved", sa.Integer(), nullable=False),
        sa.Column("connections_moved", sa.Integer(), nullable=False),
        sa.Column("connections_copied", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ownership_transfers")),
        _user_fk("ownership_transfers", "admin_id", "SET NULL"),
        _user_fk("ownership_transfers", "from_user_id", "SET NULL"),
        _user_fk("ownership_transfers", "to_user_id", "SET NULL"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_ownership_transfers_project_id_projects"),
            ondelete="SET NULL",
        ),
    )


def downgrade() -> None:
    op.drop_table("ownership_transfers")
    op.drop_constraint(op.f("fk_sync_runs_triggered_by_id_users"), "sync_runs", type_="foreignkey")
    op.drop_column("sync_runs", "triggered_by_id")
    op.drop_index(op.f("ix_project_shares_user_id"), table_name="project_shares")
    op.drop_table("project_shares")
