"""Organizations and their members."""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    AzureConnection,
    GitConnection,
    Organization,
    OrganizationMember,
    OrganizationRole,
    Project,
    User,
)


class OrganizationRepository:
    """Organizations as seen by one user: only those they belong to."""

    def __init__(self, session: Session, user_id: uuid.UUID) -> None:
        self.session = session
        self.user_id = user_id

    def mine(self) -> list[tuple[Organization, OrganizationRole]]:
        rows = self.session.execute(
            select(Organization, OrganizationMember.role)
            .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
            .where(OrganizationMember.user_id == self.user_id)
            .order_by(Organization.name)
        ).all()
        return [(org, OrganizationRole(role)) for org, role in rows]

    def get(self, organization_id: uuid.UUID) -> tuple[Organization, OrganizationRole] | None:
        """None both when it doesn't exist and when the user isn't a member."""
        row = self.session.execute(
            select(Organization, OrganizationMember.role)
            .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
            .where(Organization.id == organization_id, OrganizationMember.user_id == self.user_id)
        ).first()
        if row is None:
            return None
        org, role = row
        return org, OrganizationRole(role)


def organization_name_taken(
    session: Session, name: str, *, exclude_id: uuid.UUID | None = None
) -> bool:
    query = (
        select(func.count())
        .select_from(Organization)
        .where(func.lower(Organization.name) == name.lower())
    )
    if exclude_id is not None:
        query = query.where(Organization.id != exclude_id)
    return bool(session.scalar(query))


class MemberRepository:
    """The members of one organization. The caller has already checked access."""

    def __init__(self, session: Session, organization_id: uuid.UUID) -> None:
        self.session = session
        self.organization_id = organization_id

    def list(self) -> Sequence[tuple[OrganizationMember, User]]:
        rows = self.session.execute(
            select(OrganizationMember, User)
            .join(User, User.id == OrganizationMember.user_id)
            .where(OrganizationMember.organization_id == self.organization_id)
            .order_by(User.display_name, User.email)
        ).all()
        return [(member, user) for member, user in rows]

    def get(self, user_id: uuid.UUID) -> OrganizationMember | None:
        return self.session.scalar(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == self.organization_id,
                OrganizationMember.user_id == user_id,
            )
        )

    def add(self, user_id: uuid.UUID, role: OrganizationRole) -> OrganizationMember:
        member = OrganizationMember(
            organization_id=self.organization_id, user_id=user_id, role=role.value
        )
        self.session.add(member)
        self.session.flush()
        return member

    def admins(self) -> int:
        return (
            self.session.scalar(
                select(func.count())
                .select_from(OrganizationMember)
                .where(
                    OrganizationMember.organization_id == self.organization_id,
                    OrganizationMember.role == OrganizationRole.ADMIN,
                )
            )
            or 0
        )

    def count(self) -> int:
        return (
            self.session.scalar(
                select(func.count())
                .select_from(OrganizationMember)
                .where(OrganizationMember.organization_id == self.organization_id)
            )
            or 0
        )


def owned_counts(session: Session, organization_id: uuid.UUID) -> tuple[int, int]:
    """How many projects and connections an organization owns."""
    projects = session.scalar(
        select(func.count()).select_from(Project).where(Project.organization_id == organization_id)
    )
    connections = sum(
        session.scalar(
            select(func.count()).select_from(model).where(model.organization_id == organization_id)
        )
        or 0
        for model in (GitConnection, AzureConnection)
    )
    return projects or 0, connections
