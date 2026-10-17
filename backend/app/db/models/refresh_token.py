import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TimestampedModel


class RefreshToken(TimestampedModel):
    """A refresh token, stored only as a SHA-256 hash so sessions can be revoked."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime]
    revoked: Mapped[bool] = mapped_column(default=False, server_default=false())
