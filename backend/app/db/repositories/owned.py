"""Owner-scoped data access: every query filters on owner_id (spec section 10)."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import OwnedModel
from app.db.models import AzureConnection, GitConnection, Project


class OwnedRepository[M: OwnedModel]:
    model: type[M]

    def __init__(self, session: Session, owner_id: uuid.UUID) -> None:
        self.session = session
        self.owner_id = owner_id

    def _scoped(self) -> Any:
        return select(self.model).where(self.model.owner_id == self.owner_id)

    def get(self, item_id: uuid.UUID) -> M | None:
        """None both when the row doesn't exist and when another user owns it."""
        result: M | None = self.session.scalar(self._scoped().where(self.model.id == item_id))
        return result

    def list(self, *, offset: int, limit: int) -> tuple[Sequence[M], int]:
        total = self.session.scalar(
            select(func.count()).select_from(self.model).where(self.model.owner_id == self.owner_id)
        )
        items = self.session.scalars(
            self._scoped().order_by(self.model.name, self.model.id).offset(offset).limit(limit)
        ).all()
        return items, total or 0

    def name_taken(self, name: str, *, exclude_id: uuid.UUID | None = None) -> bool:
        query = (
            select(func.count())
            .select_from(self.model)
            .where(self.model.owner_id == self.owner_id, self.model.name == name)
        )
        if exclude_id is not None:
            query = query.where(self.model.id != exclude_id)
        return bool(self.session.scalar(query))

    def add(self, item: M) -> M:
        item.owner_id = self.owner_id
        self.session.add(item)
        self.session.flush()
        return item

    def delete(self, item: M) -> None:
        self.session.delete(item)
        self.session.flush()


class GitConnectionRepository(OwnedRepository[GitConnection]):
    model = GitConnection


class AzureConnectionRepository(OwnedRepository[AzureConnection]):
    model = AzureConnection


class ProjectRepository(OwnedRepository[Project]):
    model = Project

    def names_using(
        self,
        *,
        git_connection_id: uuid.UUID | None = None,
        azure_connection_id: uuid.UUID | None = None,
    ) -> list[str]:
        query = select(Project.name).where(Project.owner_id == self.owner_id)
        if git_connection_id is not None:
            query = query.where(Project.git_connection_id == git_connection_id)
        if azure_connection_id is not None:
            query = query.where(Project.azure_connection_id == azure_connection_id)
        return list(self.session.scalars(query.order_by(Project.name)))
