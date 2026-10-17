from enum import StrEnum

from sqlalchemy import CheckConstraint, String, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TimestampedModel


class UserRole(StrEnum):
    USER = "user"
    ADMIN = "admin"


class User(TimestampedModel):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('user', 'admin')", name="role_valid"),)

    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(100))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", server_default="UTC")
    role: Mapped[str] = mapped_column(String(16), default=UserRole.USER, server_default="user")
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN
