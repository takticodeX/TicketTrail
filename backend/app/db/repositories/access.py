"""Who may see a project, and with which role (spec section 4, *Access rules*).

Every project-level query for a signed-in user goes through here, so the rules live
in one place:

- the owner of a personal project, and the admins of an organization's project,
  have the owner role;
- the members of an organization are viewers of its projects;
- a share (viewer or editor) gives that role, or raises a member's.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import Select, and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    Organization,
    OrganizationMember,
    OrganizationRole,
    Project,
    ProjectRole,
    ProjectShare,
    User,
)


class ProjectScope(StrEnum):
    ALL = "all"
    OWNED = "owned"
    ORGANIZATIONS = "organizations"
    SHARED = "shared"


@dataclass(frozen=True)
class SeenProject:
    """A project as one user sees it, with its owner: a user or an organization."""

    project: Project
    role: ProjectRole
    owner: User | None
    organization: Organization | None

    @property
    def timezone(self) -> str:
        """The schedule's time zone: the organization's, or the owning user's."""
        if self.organization is not None:
            return self.organization.timezone
        return self.owner.timezone if self.owner is not None else "UTC"


def member_organization_ids(user_id: uuid.UUID) -> Select[tuple[uuid.UUID]]:
    return select(OrganizationMember.organization_id).where(OrganizationMember.user_id == user_id)


def accessible_project_ids(user_id: uuid.UUID) -> Select[tuple[uuid.UUID]]:
    """IDs of the projects a user owns, sees through an organization, or that are shared."""
    return select(Project.id).where(
        or_(
            Project.owner_id == user_id,
            Project.organization_id.in_(member_organization_ids(user_id)),
            Project.id.in_(select(ProjectShare.project_id).where(ProjectShare.user_id == user_id)),
        )
    )


class ProjectAccessRepository:
    """Projects as seen by one user, each with that user's role on it."""

    def __init__(self, session: Session, user_id: uuid.UUID) -> None:
        self.session = session
        self.user_id = user_id

    def _query(self, scope: ProjectScope = ProjectScope.ALL) -> Any:
        member = OrganizationMember
        role = case(
            (Project.owner_id == self.user_id, ProjectRole.OWNER.value),
            (member.role == OrganizationRole.ADMIN.value, ProjectRole.OWNER.value),
            (ProjectShare.role == ProjectRole.EDITOR.value, ProjectRole.EDITOR.value),
            else_=ProjectRole.VIEWER.value,
        )
        query = (
            select(Project, role, User, Organization)
            .outerjoin(User, User.id == Project.owner_id)
            .outerjoin(Organization, Organization.id == Project.organization_id)
            .outerjoin(
                ProjectShare,
                and_(ProjectShare.project_id == Project.id, ProjectShare.user_id == self.user_id),
            )
            .outerjoin(
                member,
                and_(
                    member.organization_id == Project.organization_id,
                    member.user_id == self.user_id,
                ),
            )
        )
        if scope is ProjectScope.OWNED:
            return query.where(Project.owner_id == self.user_id)
        if scope is ProjectScope.ORGANIZATIONS:
            return query.where(member.id.is_not(None))
        if scope is ProjectScope.SHARED:
            return query.where(
                ProjectShare.id.is_not(None),
                Project.owner_id.is_distinct_from(self.user_id),
                member.id.is_(None),
            )
        return query.where(
            or_(
                Project.owner_id == self.user_id,
                member.id.is_not(None),
                ProjectShare.id.is_not(None),
            )
        )

    @staticmethod
    def _seen(row: Any) -> SeenProject:
        project, role, owner, organization = row
        return SeenProject(project, ProjectRole(role), owner, organization)

    def get(self, project_id: uuid.UUID) -> SeenProject | None:
        """None both when the project doesn't exist and when the user has no access to it."""
        row = self.session.execute(self._query().where(Project.id == project_id)).first()
        return None if row is None else self._seen(row)

    def list(
        self, *, scope: ProjectScope, offset: int, limit: int
    ) -> tuple[list[SeenProject], int]:
        query = self._query(scope)
        total = self.session.scalar(select(func.count()).select_from(query.subquery()))
        rows = self.session.execute(
            query.order_by(Project.name, Project.id).offset(offset).limit(limit)
        ).all()
        return [self._seen(row) for row in rows], total or 0


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
