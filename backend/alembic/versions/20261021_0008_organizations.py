"""organizations: teams that own projects and connections

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OWNED = ("git_connections", "azure_connections", "projects")


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("timezone", sa.String(64), server_default="UTC", nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
        sa.UniqueConstraint("name", name=op.f("uq_organizations_name")),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_organizations_created_by_id_users"),
            ondelete="SET NULL",
        ),
    )
    op.create_table(
        "organization_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_members")),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_organization_members_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_organization_members_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "organization_id", "user_id", name="uq_organization_members_organization_user"
        ),
        sa.CheckConstraint(
            "role IN ('admin', 'member')", name=op.f("ck_organization_members_role_valid")
        ),
    )
    op.create_index(
        op.f("ix_organization_members_user_id"), "organization_members", ["user_id"], unique=False
    )

    for table in _OWNED:
        op.alter_column(table, "owner_id", existing_type=sa.Uuid(), nullable=True)
        op.add_column(table, sa.Column("organization_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(
            op.f(f"fk_{table}_organization_id_organizations"),
            table,
            "organizations",
            ["organization_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        op.create_index(op.f(f"ix_{table}_organization_id"), table, ["organization_id"])
        op.create_unique_constraint(
            f"uq_{table}_organization_name", table, ["organization_id", "name"]
        )
        op.create_check_constraint(
            op.f(f"ck_{table}_one_owner"), table, "(owner_id IS NULL) <> (organization_id IS NULL)"
        )


def downgrade() -> None:
    # Rows owned by an organization have no user to fall back to.
    op.execute("DELETE FROM projects WHERE organization_id IS NOT NULL")
    op.execute("DELETE FROM git_connections WHERE organization_id IS NOT NULL")
    op.execute("DELETE FROM azure_connections WHERE organization_id IS NOT NULL")
    for table in reversed(_OWNED):
        op.drop_constraint(op.f(f"ck_{table}_one_owner"), table, type_="check")
        op.drop_constraint(f"uq_{table}_organization_name", table, type_="unique")
        op.drop_index(op.f(f"ix_{table}_organization_id"), table_name=table)
        op.drop_constraint(
            op.f(f"fk_{table}_organization_id_organizations"), table, type_="foreignkey"
        )
        op.drop_column(table, "organization_id")
        op.alter_column(table, "owner_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_index(op.f("ix_organization_members_user_id"), table_name="organization_members")
    op.drop_table("organization_members")
    op.drop_table("organizations")
