import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, false, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import OwnedModel, ownership_constraints


class Project(OwnedModel):
    """One Git connection paired with one Azure DevOps board."""

    __tablename__ = "projects"
    __table_args__ = ownership_constraints("projects")

    # RESTRICT: a connection can't be deleted while a project uses it.
    git_connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("git_connections.id", ondelete="RESTRICT"), index=True
    )
    azure_connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("azure_connections.id", ondelete="RESTRICT"), index=True
    )
    # Empty means "the remote's default branch only".
    branches: Mapped[list[str]] = mapped_column(
        ARRAY(String(255)), default=list, server_default=text("'{}'")
    )
    ticket_pattern: Mapped[str] = mapped_column(String(500))
    comment_template: Mapped[str] = mapped_column(Text)
    # An ISO date (YYYY-MM-DD) or a commit SHA; null means the full history.
    start_from: Mapped[str | None] = mapped_column(String(64))
    include_merge_commits: Mapped[bool] = mapped_column(default=False, server_default=false())
    schedule_cron: Mapped[str | None] = mapped_column(String(100))
    schedule_enabled: Mapped[bool] = mapped_column(default=False, server_default=false())
    # The latest schedule slot a run was started for, so each slot fires once,
    # even with several schedulers. Reset to "now" whenever the schedule changes.
    schedule_last_fired_at: Mapped[datetime | None]
    dry_run_default: Mapped[bool] = mapped_column(default=False, server_default=false())
