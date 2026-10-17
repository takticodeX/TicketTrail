import uuid

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, false, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import OwnedModel


class Project(OwnedModel):
    """One Git connection paired with one Azure DevOps board."""

    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_projects_owner_name"),)

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
    dry_run_default: Mapped[bool] = mapped_column(default=False, server_default=false())
