"""board connections: Azure connections generalised for other boards; text work item IDs

`azure_connections` becomes `board_connections` with a `kind` and generic columns
(`url`, `scope`, `secret_enc`). Work item IDs become text, so IDs that are not
small integers (Planka's) fit, and the API can return them without losing digits.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD, _NEW = "azure_connections", "board_connections"
# Constraints and indexes named after the table (see NAMING_CONVENTION).
_CONSTRAINTS = (
    "pk_{}",
    "ck_{}_one_owner",
    "uq_{}_owner_name",
    "uq_{}_organization_name",
    "fk_{}_owner_id_users",
    "fk_{}_organization_id_organizations",
)
_INDEXES = ("ix_{}_owner_id", "ix_{}_organization_id")
_COLUMNS = (("organization_url", "url"), ("azure_project", "scope"), ("pat_enc", "secret_enc"))
# Tables whose work_item_id becomes text, and whether it is nullable.
_WORK_ITEM_TABLES = (
    ("sync_run_items", True),
    ("posted_comments", False),
    ("commit_links", False),
    ("commit_exclusions", False),
)


def _rename_table(old: str, new: str) -> None:
    op.rename_table(old, new)
    for name in _CONSTRAINTS:
        op.execute(f"ALTER TABLE {new} RENAME CONSTRAINT {name.format(old)} TO {name.format(new)}")
    for name in _INDEXES:
        op.execute(f"ALTER INDEX {name.format(old)} RENAME TO {name.format(new)}")


def _rename_project_column(old: str, new: str) -> None:
    op.alter_column("projects", f"{old}_connection_id", new_column_name=f"{new}_connection_id")
    op.execute(
        f"ALTER TABLE projects RENAME CONSTRAINT "
        f"fk_projects_{old}_connection_id_{old}_connections "
        f"TO fk_projects_{new}_connection_id_{new}_connections"
    )
    op.execute(
        f"ALTER INDEX ix_projects_{old}_connection_id RENAME TO ix_projects_{new}_connection_id"
    )


def upgrade() -> None:
    _rename_table(_OLD, _NEW)
    for old, new in _COLUMNS:
        op.alter_column(_NEW, old, new_column_name=new)
    op.add_column(_NEW, sa.Column("kind", sa.String(16), server_default="azure", nullable=False))
    op.create_check_constraint(op.f(f"ck_{_NEW}_kind_valid"), _NEW, "kind IN ('azure', 'planka')")
    _rename_project_column("azure", "board")

    for table, nullable in _WORK_ITEM_TABLES:
        op.alter_column(
            table,
            "work_item_id",
            type_=sa.String(64),
            existing_type=sa.Integer(),
            existing_nullable=nullable,
            postgresql_using="work_item_id::text",
        )
    op.alter_column(
        "posted_comments",
        "azure_comment_id",
        new_column_name="comment_id",
        type_=sa.String(64),
        existing_type=sa.Integer(),
        existing_nullable=True,
        postgresql_using="azure_comment_id::text",
    )
    op.execute(
        "UPDATE audit_events SET resource_type = 'board_connection' "
        "WHERE resource_type = 'azure_connection'"
    )


def downgrade() -> None:
    # Only Azure data goes back: Planka connections, their projects and their rows can't.
    op.execute(
        "DELETE FROM projects WHERE board_connection_id IN "
        "(SELECT id FROM board_connections WHERE kind <> 'azure')"
    )
    op.execute("DELETE FROM board_connections WHERE kind <> 'azure'")
    op.execute(
        "UPDATE audit_events SET resource_type = 'azure_connection' "
        "WHERE resource_type = 'board_connection'"
    )
    op.alter_column(
        "posted_comments",
        "comment_id",
        new_column_name="azure_comment_id",
        type_=sa.Integer(),
        existing_type=sa.String(64),
        existing_nullable=True,
        postgresql_using="comment_id::integer",
    )
    for table, nullable in _WORK_ITEM_TABLES:
        op.alter_column(
            table,
            "work_item_id",
            type_=sa.Integer(),
            existing_type=sa.String(64),
            existing_nullable=nullable,
            postgresql_using="work_item_id::integer",
        )

    _rename_project_column("board", "azure")
    op.drop_constraint(op.f(f"ck_{_NEW}_kind_valid"), _NEW, type_="check")
    op.drop_column(_NEW, "kind")
    for old, new in _COLUMNS:
        op.alter_column(_NEW, new, new_column_name=old)
    _rename_table(_NEW, _OLD)
