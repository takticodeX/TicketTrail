"""Sync runs and their items. Runs are owned through their project's owner_id."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Project, ProjectCursor, SyncRun, SyncRunItem


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
