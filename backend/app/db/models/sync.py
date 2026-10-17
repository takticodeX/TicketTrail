import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import TimestampedModel


class RunTrigger(StrEnum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"  # not in the spec's list; agreed for Milestone 6


ACTIVE_STATUSES = (RunStatus.QUEUED, RunStatus.RUNNING)


class ItemAction(StrEnum):
    POSTED = "posted"
    WOULD_POST = "would_post"
    SKIPPED_DUPLICATE = "skipped_duplicate"
    SKIPPED_NOT_FOUND = "skipped_not_found"
    NO_REFERENCE = "no_reference"
    ERROR = "error"


def _in(column: str, enum: type[StrEnum]) -> str:
    return f"{column} IN ({', '.join(repr(m.value) for m in enum)})"


class SyncRun(TimestampedModel):
    """One sync run of a project. Owned through its project."""

    __tablename__ = "sync_runs"
    __table_args__ = (
        CheckConstraint(_in("trigger", RunTrigger), name="trigger_valid"),
        CheckConstraint(_in("status", RunStatus), name="status_valid"),
        Index("ix_sync_runs_project_id_created_at", "project_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    trigger: Mapped[str] = mapped_column(String(16))
    dry_run: Mapped[bool] = mapped_column(default=False, server_default=false())
    status: Mapped[str] = mapped_column(String(16), default=RunStatus.QUEUED)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    commits_scanned: Mapped[int] = mapped_column(default=0, server_default="0")
    comments_posted: Mapped[int] = mapped_column(default=0, server_default="0")
    skipped: Mapped[int] = mapped_column(default=0, server_default="0")
    errors: Mapped[int] = mapped_column(default=0, server_default="0")
    # Why a run failed, or warnings for a partial run (missing branch, rewritten history).
    error_message: Mapped[str | None] = mapped_column(Text)
    # Set by POST /runs/{id}/cancel; the worker checks it between commits.
    cancel_requested: Mapped[bool] = mapped_column(default=False, server_default=false())


class SyncRunItem(TimestampedModel):
    """The audit trail: what happened to each commit / work item pair in a run."""

    __tablename__ = "sync_run_items"
    __table_args__ = (
        CheckConstraint(_in("action", ItemAction), name="action_valid"),
        Index("ix_sync_run_items_sync_run_id_action", "sync_run_id", "action"),
        Index("ix_sync_run_items_sync_run_id_position", "sync_run_id", "position"),
    )

    sync_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sync_runs.id", ondelete="CASCADE"))
    # Order within the run (oldest commit first). created_at can't order items:
    # a run writes them all in one transaction.
    position: Mapped[int]
    commit_sha: Mapped[str] = mapped_column(String(40))
    work_item_id: Mapped[int | None]
    action: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str | None] = mapped_column(Text)
    # Not in the spec's key columns: shown in the item list without opening Git.
    commit_subject: Mapped[str] = mapped_column(String(500), default="", server_default="")
    branch: Mapped[str] = mapped_column(String(255), default="", server_default="")


class CommentStatus(StrEnum):
    PENDING = "pending"
    POSTED = "posted"


class PostedComment(TimestampedModel):
    """The source of truth for de-duplication: one row per commit / work item pair.

    The unique constraint is what guarantees a commit is never posted twice to the
    same work item. A row is inserted as `pending` (and committed) before the
    comment is sent, then marked `posted`; a `pending` row left by a crash is
    resolved by looking for the tt:{sha} marker in the work item's comments.
    """

    __tablename__ = "posted_comments"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "commit_sha", "work_item_id", name="uq_posted_comments_pair"
        ),
        CheckConstraint(_in("status", CommentStatus), name="status_valid"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    commit_sha: Mapped[str] = mapped_column(String(40))
    work_item_id: Mapped[int]
    azure_comment_id: Mapped[int | None]
    status: Mapped[str] = mapped_column(String(16), default=CommentStatus.PENDING)
    posted_at: Mapped[datetime | None]


class ProjectCursor(TimestampedModel):
    """Where the last successful (non-dry) sync stopped on a branch. Only an optimisation."""

    __tablename__ = "project_cursors"
    __table_args__ = (
        UniqueConstraint("project_id", "branch", name="uq_project_cursors_project_branch"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    branch: Mapped[str] = mapped_column(String(255))
    last_sha: Mapped[str] = mapped_column(String(40))
