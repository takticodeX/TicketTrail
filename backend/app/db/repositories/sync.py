"""Sync runs and their items. Runs are owned through their project's owner_id."""

import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import (
    CommentStatus,
    PostedComment,
    Project,
    ProjectCursor,
    RunStatus,
    SyncRun,
    SyncRunItem,
)


class SyncRunRepository:
    def __init__(self, session: Session, owner_id: uuid.UUID) -> None:
        self.session = session
        self.owner_id = owner_id

    def _owned(self) -> Any:
        return (
            select(SyncRun)
            .join(Project, Project.id == SyncRun.project_id)
            .where(Project.owner_id == self.owner_id)
        )

    def get(self, run_id: uuid.UUID) -> SyncRun | None:
        """None both when the run doesn't exist and when another user owns it."""
        result: SyncRun | None = self.session.scalar(self._owned().where(SyncRun.id == run_id))
        return result

    def list_for_project(
        self, project_id: uuid.UUID, *, offset: int, limit: int
    ) -> tuple[Sequence[SyncRun], int]:
        query = self._owned().where(SyncRun.project_id == project_id)
        total = self.session.scalar(select(func.count()).select_from(query.subquery()))
        runs = self.session.scalars(
            query.order_by(SyncRun.created_at.desc(), SyncRun.id).offset(offset).limit(limit)
        ).all()
        return runs, total or 0

    def items(
        self, run_id: uuid.UUID, *, action: str | None, offset: int, limit: int
    ) -> tuple[Sequence[SyncRunItem], int]:
        """Items of a run the caller has already loaded through get()."""
        query = select(SyncRunItem).where(SyncRunItem.sync_run_id == run_id)
        if action is not None:
            query = query.where(SyncRunItem.action == action)
        total = self.session.scalar(select(func.count()).select_from(query.subquery()))
        items = self.session.scalars(
            query.order_by(SyncRunItem.position).offset(offset).limit(limit)
        ).all()
        return items, total or 0

    def counts_by_action(self, run_id: uuid.UUID) -> dict[str, int]:
        rows = self.session.execute(
            select(SyncRunItem.action, func.count())
            .where(SyncRunItem.sync_run_id == run_id)
            .group_by(SyncRunItem.action)
        ).all()
        return {action: count for action, count in rows}


class CursorRepository:
    """Internal to the worker: the caller has already resolved the project."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def for_project(self, project_id: uuid.UUID) -> dict[str, str]:
        rows = self.session.execute(
            select(ProjectCursor.branch, ProjectCursor.last_sha).where(
                ProjectCursor.project_id == project_id
            )
        ).all()
        return {branch: sha for branch, sha in rows}

    def move(self, project_id: uuid.UUID, branch: str, sha: str) -> None:
        statement = insert(ProjectCursor).values(
            id=uuid.uuid4(), project_id=project_id, branch=branch, last_sha=sha
        )
        self.session.execute(
            statement.on_conflict_do_update(
                constraint="uq_project_cursors_project_branch",
                set_={"last_sha": sha, "updated_at": func.now()},
            )
        )


class PostedCommentRepository:
    """Internal to the worker: the caller has already resolved the project."""

    def __init__(self, session: Session, project_id: uuid.UUID) -> None:
        self.session = session
        self.project_id = project_id

    def for_commits(self, shas: Iterable[str]) -> dict[tuple[str, int], PostedComment]:
        rows = self.session.scalars(
            select(PostedComment).where(
                PostedComment.project_id == self.project_id,
                PostedComment.commit_sha.in_(list(set(shas))),
            )
        ).all()
        return {(row.commit_sha, row.work_item_id): row for row in rows}

    def pending(self) -> Sequence[PostedComment]:
        return self.session.scalars(
            select(PostedComment).where(
                PostedComment.project_id == self.project_id,
                PostedComment.status == CommentStatus.PENDING,
            )
        ).all()


STALE_RUN_MESSAGE = (
    "The run stopped making progress (the worker was probably restarted). "
    "Start it again: nothing will be posted twice."
)


def close_stale_runs(
    session: Session,
    *,
    older_than: timedelta,
    project_id: uuid.UUID | None = None,
    exclude: uuid.UUID | None = None,
) -> int:
    """Fail queued or running runs whose heartbeat stopped. Returns how many."""
    statement = (
        update(SyncRun)
        .where(
            SyncRun.status.in_([RunStatus.QUEUED, RunStatus.RUNNING]),
            SyncRun.updated_at < datetime.now(UTC) - older_than,
        )
        .values(
            status=RunStatus.FAILED,
            finished_at=func.now(),
            error_message=STALE_RUN_MESSAGE,
        )
    )
    if project_id is not None:
        statement = statement.where(SyncRun.project_id == project_id)
    if exclude is not None:
        statement = statement.where(SyncRun.id != exclude)
    result = session.execute(statement)
    return int(getattr(result, "rowcount", 0) or 0)


def other_run_active(session: Session, project_id: uuid.UUID, run_id: uuid.UUID) -> bool:
    return bool(
        session.scalar(
            select(func.count())
            .select_from(SyncRun)
            .where(
                SyncRun.project_id == project_id,
                SyncRun.id != run_id,
                SyncRun.status == RunStatus.RUNNING,
            )
        )
    )
