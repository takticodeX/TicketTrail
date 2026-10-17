"""posted_comments

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "posted_comments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("commit_sha", sa.String(40), nullable=False),
        sa.Column("work_item_id", sa.Integer(), nullable=False),
        sa.Column("azure_comment_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_posted_comments")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_posted_comments_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "project_id", "commit_sha", "work_item_id", name="uq_posted_comments_pair"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'posted')", name=op.f("ck_posted_comments_status_valid")
        ),
    )


def downgrade() -> None:
    op.drop_table("posted_comments")
