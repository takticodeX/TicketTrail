"""refresh_tokens.revoked_at for reuse detection

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "refresh_tokens", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True)
    )
    # Tokens revoked before this column existed count as revoked long ago.
    op.execute("UPDATE refresh_tokens SET revoked_at = updated_at WHERE revoked")


def downgrade() -> None:
    op.drop_column("refresh_tokens", "revoked_at")
