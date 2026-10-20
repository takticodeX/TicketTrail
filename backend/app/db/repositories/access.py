"""Who may see a project: its owner and the users it is shared with.

Every project-level query for a signed-in user goes through here, so the rule
"owner, or shared with you" lives in one place.
"""

import uuid
from collections.abc import Sequence
from enum import StrEnum
from typing import Any

from sqlalchemy import Select, and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import Project, ProjectRole, ProjectShare, User


class ProjectScope(StrEnum):
    ALL = "all"
    OWNED = "owned"
    SHARED = "shared"


def accessible_project_ids(user_id: uuid.UUID) -> Select[tuple[uuid.UUID]]:
    """IDs of the projects a user owns or that are shared with them."""
    return select(Project.id).where(
        or_(
            Project.owner_id == user_id,
            Project.id.in_(select(ProjectShare.project_id).where(ProjectShare.user_id == user_id)),
        )
    )


class ProjectAccessRepository:
    """Projects as seen by one user, each with that user's role on it."""

    def __init__(self, session: Session, user_id: uuid.UUID) -> None:
        self.session = session
        self.user_id = user_id

    def _query(self, scope: ProjectScope = ProjectScope.ALL) -> Any:
        role = case(
            (Project.owner_id == self.user_id, ProjectRole.OWNER.value), else_=ProjectShare.role
        )
        query = (
            select(Project, role, User)
            .join(User, User.id == Project.owner_id)
            .outerjoin(
                ProjectShare,
                and_(ProjectShare.project_id == Project.id, ProjectShare.user_id == self.user_id),
            )
        )
        if scope is ProjectScope.OWNED:
            return query.where(Project.owner_id == self.user_id)
        if scope is ProjectScope.SHARED:
            return query.where(ProjectShare.id.is_not(None), Project.owner_id != self.user_id)
        return query.where(or_(Project.owner_id == self.user_id, ProjectShare.id.is_not(None)))

    def get(self, project_id: uuid.UUID) -> tuple[Project, ProjectRole, User] | None:
        """None both when the project doesn't exist and when the user has no access to it."""
        row = self.session.execute(self._query().where(Project.id == project_id)).first()
        if row is None:
            return None
        project, role, owner = row
        return project, ProjectRole(role), owner

    def list(
        self, *, scope: ProjectScope, offset: int, limit: int
    ) -> tuple[list[tuple[Project, ProjectRole, User]], int]:
        query = self._query(scope)
        total = self.session.scalar(select(func.count()).select_from(query.subquery()))
        rows = self.session.execute(
            query.order_by(Project.name, Project.id).offset(offset).limit(limit)
        ).all()
        return [(p, ProjectRole(r), owner) for p, r, owner in rows], total or 0


class ProjectShareRepository:
    """The shares of one project. The caller has already checked it may manage them."""

    def __init__(self, session: Session, project_id: uuid.UUID) -> None:
        self.session = session
        self.project_id = project_id

    def list(self) -> Sequence[tuple[ProjectShare, User]]:
        rows = self.session.execute(
            select(ProjectShare, User)
            .join(User, User.id == ProjectShare.user_id)
            .where(ProjectShare.project_id == self.project_id)
            .order_by(User.display_name, User.email)
        ).all()
        return [(share, user) for share, user in rows]

    def get(self, user_id: uuid.UUID) -> ProjectShare | None:
        return self.session.scalar(
            select(ProjectShare).where(
                ProjectShare.project_id == self.project_id, ProjectShare.user_id == user_id
            )
        )

    def add(self, user_id: uuid.UUID, role: ProjectRole) -> ProjectShare:
        share = ProjectShare(project_id=self.project_id, user_id=user_id, role=role.value)
        self.session.add(share)
        self.session.flush()
        return share

    def delete(self, share: ProjectShare) -> None:
        self.session.delete(share)
        self.session.flush()

    def count(self) -> int:
        return (
            self.session.scalar(
                select(func.count())
                .select_from(ProjectShare)
                .where(ProjectShare.project_id == self.project_id)
            )
            or 0
        )
