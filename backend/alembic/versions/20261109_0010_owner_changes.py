"""owner changes: one history for users and organizations

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

T = "ownership_transfers"


def upgrade() -> None:
    op.drop_constraint(op.f("fk_ownership_transfers_admin_id_users"), T, type_="foreignkey")
    op.alter_column(T, "admin_id", new_column_name="actor_id")
    op.create_foreign_key(
        op.f("fk_ownership_transfers_actor_id_users"),
        T,
        "users",
        ["actor_id"],
        ["id"],
        ondelete="SET NULL",
    )
    for column in ("from_organization_id", "to_organization_id"):
        op.add_column(T, sa.Column(column, sa.Uuid(), nullable=True))
        op.create_foreign_key(
            op.f(f"fk_ownership_transfers_{column}_organizations"),
            T,
            "organizations",
            [column],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    for column in ("to_organization_id", "from_organization_id"):
        op.drop_constraint(
            op.f(f"fk_ownership_transfers_{column}_organizations"), T, type_="foreignkey"
        )
        op.drop_column(T, column)
    op.drop_constraint(op.f("fk_ownership_transfers_actor_id_users"), T, type_="foreignkey")
    op.alter_column(T, "actor_id", new_column_name="admin_id")
    op.create_foreign_key(
        op.f("fk_ownership_transfers_admin_id_users"),
        T,
        "users",
        ["admin_id"],
        ["id"],
        ondelete="SET NULL",
    )
