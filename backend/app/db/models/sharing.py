import uuid
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TimestampedModel


class ProjectRole(StrEnum):
    """What a user may do on a project, weakest first. The owner is implicit."""

    VIEWER = "viewer"
    EDITOR = "editor"
    OWNER = "owner"

    @property
    def rank(self) -> int:
        return _RANKS[self]

    def at_least(self, other: "ProjectRole") -> bool:
        return self.rank >= other.rank


_RANKS = {ProjectRole.VIEWER: 1, ProjectRole.EDITOR: 2, ProjectRole.OWNER: 3}
SHARE_ROLES = (ProjectRole.VIEWER, ProjectRole.EDITOR)


class ProjectShare(TimestampedModel):
    """A project shared with another user, as viewer or editor."""

    __tablename__ = "project_shares"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_shares_project_user"),
        CheckConstraint("role IN ('viewer', 'editor')", name="role_valid"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))


class OwnershipTransfer(TimestampedModel):
    """Audit trail of what an administrator moved from one user to another."""

    __tablename__ = "ownership_transfers"

    admin_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    from_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    to_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # Null when everything the user owned was moved.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL")
    )
    projects_moved: Mapped[int] = mapped_column(Integer)
    connections_moved: Mapped[int] = mapped_column(Integer)
    connections_copied: Mapped[int] = mapped_column(Integer)
    # Human-readable summary (names, renames), readable even after the users change.
    summary: Mapped[str] = mapped_column(Text)


class AuditEvent(TimestampedModel):
    """What an administrator did to someone else's project, run, connection or organization.

    Names and owners are copied, so an event stays readable after the resource is gone.
    """

    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_created_at", "created_at"),)

    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_email: Mapped[str] = mapped_column(String(320))
    # A verb such as "update", "delete", "sync" or "share".
    action: Mapped[str] = mapped_column(String(64))
    # "project", "run", "git_connection", "azure_connection" or "organization".
    resource_type: Mapped[str] = mapped_column(String(32))
    resource_id: Mapped[uuid.UUID | None]
    resource_name: Mapped[str] = mapped_column(String(200))
    # Whose it is: the owner's email, or the organization's name.
    owner_label: Mapped[str] = mapped_column(String(320))
