"""Organizations: anyone can create one; its admins manage members and connections.

Members are viewers of the organization's projects; a project share raises a member
to editor on that project. Admins have the owner role on every project.
"""

import uuid

from fastapi import APIRouter, Response, status
from sqlalchemy import delete, func, select

from app.api.access import not_organization_admin, organization_for
from app.api.deps import CurrentUser, DbSession
from app.api.v1.schemas import (
    MemberCreate,
    MemberResponse,
    MemberUpdate,
    OrganizationCreate,
    OrganizationResponse,
    OrganizationUpdate,
    UserSummary,
)
from app.core.errors import AppError, not_found
from app.db.models import (
    Organization,
    OrganizationMember,
    OrganizationRole,
    Project,
    ProjectShare,
    User,
)
from app.db.repositories import (
    MemberRepository,
    OrganizationRepository,
    UserRepository,
    organization_name_taken,
    owned_counts,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _name_taken() -> AppError:
    return AppError(409, "name_taken", "An organization with this name already exists.")


def _last_admin() -> AppError:
    return AppError(
        409, "last_admin", "An organization needs an admin. Make someone else an admin first."
    )


def _counts(
    db: DbSession, ids: list[uuid.UUID]
) -> tuple[dict[uuid.UUID, int], dict[uuid.UUID, int]]:
    members = db.execute(
        select(OrganizationMember.organization_id, func.count())
        .where(OrganizationMember.organization_id.in_(ids))
        .group_by(OrganizationMember.organization_id)
    ).all()
    projects = db.execute(
        select(Project.organization_id, func.count())
        .where(Project.organization_id.in_(ids))
        .group_by(Project.organization_id)
    ).all()
    return (
        {org_id: n for org_id, n in members if org_id is not None},
        {org_id: n for org_id, n in projects if org_id is not None},
    )


def _responses(
    db: DbSession, rows: list[tuple[Organization, OrganizationRole]]
) -> list[OrganizationResponse]:
    members, projects = _counts(db, [org.id for org, _ in rows])
    return [
        OrganizationResponse(
            id=org.id,
            name=org.name,
            timezone=org.timezone,
            role=role.value,
            members=members.get(org.id, 0),
            projects=projects.get(org.id, 0),
            created_at=org.created_at,
        )
        for org, role in rows
    ]


def _member_response(member: OrganizationMember, user: User) -> MemberResponse:
    return MemberResponse(
        user=UserSummary.model_validate(user),
        role=OrganizationRole(member.role).value,
        created_at=member.created_at,
    )


@router.get("")
def list_organizations(user: CurrentUser, db: DbSession) -> list[OrganizationResponse]:
    """The organizations you belong to."""
    return _responses(db, OrganizationRepository(db, user.id).mine())


@router.post("", status_code=status.HTTP_201_CREATED)
def create_organization(
    body: OrganizationCreate, user: CurrentUser, db: DbSession
) -> OrganizationResponse:
    """Anyone can create an organization and becomes its first admin."""
    if organization_name_taken(db, body.name):
        raise _name_taken()
    org = Organization(
        name=body.name, timezone=body.timezone or user.timezone, created_by_id=user.id
    )
    db.add(org)
    db.flush()
    MemberRepository(db, org.id).add(user.id, OrganizationRole.ADMIN)
    db.commit()
    return _responses(db, [(org, OrganizationRole.ADMIN)])[0]


@router.get("/{organization_id}")
def get_organization(
    organization_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> OrganizationResponse:
    return _responses(db, [organization_for(db, user, organization_id)])[0]


@router.patch("/{organization_id}")
def update_organization(
    organization_id: uuid.UUID, body: OrganizationUpdate, user: CurrentUser, db: DbSession
) -> OrganizationResponse:
    """Admins rename it or change the time zone its schedules run in."""
    org, role = organization_for(db, user, organization_id, admin=True, action="update")
    if body.name is not None and body.name != org.name:
        if organization_name_taken(db, body.name, exclude_id=org.id):
            raise _name_taken()
        org.name = body.name
    if body.timezone is not None:
        org.timezone = body.timezone
    db.commit()
    db.refresh(org)
    return _responses(db, [(org, role)])[0]


@router.delete("/{organization_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_organization(organization_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    """Admins only, and only once it owns no projects and no connections."""
    org, _ = organization_for(db, user, organization_id, admin=True, action="delete")
    projects, connections = owned_counts(db, org.id)
    if projects or connections:
        raise AppError(
            409,
            "organization_not_empty",
            "Move or delete the organization's projects and connections first.",
            {"projects": projects, "connections": connections},
        )
    db.delete(org)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{organization_id}/members")
def list_members(
    organization_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> list[MemberResponse]:
    """Members see each other (name and email), for example to share a project."""
    organization_for(db, user, organization_id)
    return [_member_response(m, u) for m, u in MemberRepository(db, organization_id).list()]


@router.post("/{organization_id}/members", status_code=status.HTTP_201_CREATED)
def add_member(
    organization_id: uuid.UUID, body: MemberCreate, user: CurrentUser, db: DbSession
) -> MemberResponse:
    """Admins add a registered user, found by their exact email."""
    organization_for(db, user, organization_id, admin=True, action="add a member to")
    target = UserRepository(db).get_by_email(body.email)
    if target is None or not target.is_active:
        raise AppError(404, "user_not_found", "No user with this email.")
    repo = MemberRepository(db, organization_id)
    if repo.get(target.id) is not None:
        raise AppError(409, "already_member", "This user is already a member.")
    member = repo.add(target.id, OrganizationRole(body.role))
    db.commit()
    db.refresh(member)
    return _member_response(member, target)


def _member_or_404(
    db: DbSession, organization_id: uuid.UUID, user_id: uuid.UUID
) -> OrganizationMember:
    member = MemberRepository(db, organization_id).get(user_id)
    if member is None:
        raise not_found("Member")
    return member


@router.patch("/{organization_id}/members/{user_id}")
def update_member(
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    body: MemberUpdate,
    user: CurrentUser,
    db: DbSession,
) -> MemberResponse:
    organization_for(db, user, organization_id, admin=True, action="change a member of")
    member = _member_or_404(db, organization_id, user_id)
    repo = MemberRepository(db, organization_id)
    if (
        member.role == OrganizationRole.ADMIN
        and body.role == OrganizationRole.MEMBER.value
        and repo.admins() == 1
    ):
        raise _last_admin()
    member.role = body.role
    db.commit()
    db.refresh(member)
    target = db.get(User, user_id)
    assert target is not None  # noqa: S101  (the member's foreign key)
    return _member_response(member, target)


@router.delete("/{organization_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    organization_id: uuid.UUID, user_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> Response:
    """Admins remove a member; anyone can leave. The last admin can do neither.

    A removed member also loses the shares they had on the organization's projects:
    this is how access ends when someone leaves.
    """
    leaving = user_id == user.id
    _, role = organization_for(
        db, user, organization_id, action=None if leaving else "remove a member from"
    )
    if not leaving and role is not OrganizationRole.ADMIN:
        raise not_organization_admin()
    member = _member_or_404(db, organization_id, user_id)
    repo = MemberRepository(db, organization_id)
    if member.role == OrganizationRole.ADMIN and repo.admins() == 1:
        raise _last_admin()
    db.execute(
        delete(ProjectShare).where(
            ProjectShare.user_id == user_id,
            ProjectShare.project_id.in_(
                select(Project.id).where(Project.organization_id == organization_id)
            ),
        )
    )
    db.delete(member)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
