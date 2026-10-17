"""scheduling and cancellation

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_STATUSES = "'queued', 'running', 'success', 'partial', 'failed', 'skipped'"


def upgrade() -> None:
    op.add_column(
        "sync_runs",
        sa.Column("cancel_requested", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.drop_constraint(op.f("ck_sync_runs_status_valid"), "sync_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_sync_runs_status_valid"), "sync_runs", f"status IN ({_OLD_STATUSES}, 'cancelled')"
    )
    op.add_column(
        "projects",
        sa.Column("schedule_last_fired_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Existing schedules count from now: none fires for a slot that has already passed.
    op.execute("UPDATE projects SET schedule_last_fired_at = now() WHERE schedule_cron IS NOT NULL")


def downgrade() -> None:
    op.drop_column("projects", "schedule_last_fired_at")
    op.execute("UPDATE sync_runs SET status = 'failed' WHERE status = 'cancelled'")
    op.drop_constraint(op.f("ck_sync_runs_status_valid"), "sync_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_sync_runs_status_valid"), "sync_runs", f"status IN ({_OLD_STATUSES})"
    )
    op.drop_column("sync_runs", "cancel_requested")
