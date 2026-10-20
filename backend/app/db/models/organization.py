import uuid
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TimestampedModel


class OrganizationRole(StrEnum):
    ADMIN = "admin"
    MEMBER = "member"


class Organization(TimestampedModel):
    """A team that owns projects and connections instead of a single user."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(100), unique=True)
    # Scheduled syncs of the organization's projects run in this time zone.
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", server_default="UTC")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class OrganizationMember(TimestampedModel):
    """Admins manage the organization and own its projects; members see its projects."""

    __tablename__ = "organization_members"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "user_id", name="uq_organization_members_organization_user"
        ),
        CheckConstraint("role IN ('admin', 'member')", name="role_valid"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
