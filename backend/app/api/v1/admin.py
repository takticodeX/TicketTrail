"""Administration (admins only): users, accounts on or off, and ownership transfers.

An administrator doesn't read other users' projects: they see who owns what, and can
give a user's projects to someone else (for example when a colleague leaves).
Every transfer is recorded.
"""

import logging
import uuid
from collections.abc import Sequence
from typing import Annotated, Any

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import AdminUser, DbSession, PageDep
from app.api.v1.azure_connections import to_response as azure_response
from app.api.v1.git_connections import to_response as git_response
from app.api.v1.schemas import (
    AdminAzureConnectionResponse,
    AdminGitConnectionResponse,
    AdminOrganizationResponse,
    AdminProjectResponse,
    AdminUserResponse,
    AdminUserSummary,
    AdminUserUpdate,
    MemberResponse,
    OrganizationSummary,
    Page,
    PromoteAdmin,
    RunResponse,
    TransferRequest,
    TransferResponse,
    UserResponse,
    UserSummary,
)
from app.core.errors import AppError, field_error, not_found
from app.db.models import (
    AzureConnection,
    GitConnection,
    Organization,
    OrganizationMember,
    OrganizationRole,
    OwnershipTransfer,
    Project,
    ProjectShare,
    User,
)
from app.db.repositories import (
    MemberRepository,
    RefreshTokenRepository,
    owned_counts,
    project_summaries,
)
from app.db.repositories.transfers import owns_anything, transfer_everything, transfer_project

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


def _project_counts(db: DbSession, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    rows = db.execute(
        select(Project.owner_id, func.count())
        .where(Project.owner_id.in_(user_ids))
        .group_by(Project.owner_id)
    ).all()
    return {owner: count for owner, count in rows}


def _response(user: User, projects: int) -> AdminUserResponse:
    return AdminUserResponse(**UserResponse.model_validate(user).model_dump(), projects=projects)


@router.get("/users")
def list_users(admin: AdminUser, db: DbSession, page: PageDep) -> Page[AdminUserResponse]:
    total = db.scalar(select(func.count()).select_from(User)) or 0
    users = db.scalars(
        select(User).order_by(User.created_at, User.id).offset(page.offset).limit(page.page_size)
    ).all()
    counts = _project_counts(db, [u.id for u in users])
    return Page(
        items=[_response(u, counts.get(u.id, 0)) for u in users],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.patch("/users/{user_id}")
def update_user(
    user_id: uuid.UUID, body: AdminUserUpdate, admin: AdminUser, db: DbSession
) -> AdminUserResponse:
    """Turning an account off signs it out everywhere and stops its scheduled syncs."""
    user = db.get(User, user_id)
    if user is None:
        raise not_found("User")
    if user.id == admin.id and not body.is_active:
        raise AppError(409, "cannot_disable_self", "You can't turn off your own account.")
    user.is_active = body.is_active
    if not body.is_active:
        RefreshTokenRepository(db).revoke_all_for_user(user.id)
    db.commit()
    db.refresh(user)
    return _response(user, _project_counts(db, [user.id]).get(user.id, 0))


def _admin_summary(user: User) -> AdminUserSummary:
    return AdminUserSummary(
        id=user.id, display_name=user.display_name, email=user.email, is_active=user.is_active
    )


@router.get("/projects")
def list_all_projects(
    admin: AdminUser,
    db: DbSession,
    page: PageDep,
    owner_id: Annotated[uuid.UUID | None, Query(description="Only this user's projects")] = None,
    organization_id: Annotated[
        uuid.UUID | None, Query(description="Only this organization's projects")
    ] = None,
) -> Page[AdminProjectResponse]:
    """Every project and its owner (a user or an organization): no settings or secrets."""
    query = (
        select(Project, User, Organization)
        .outerjoin(User, User.id == Project.owner_id)
        .outerjoin(Organization, Organization.id == Project.organization_id)
    )
    if owner_id is not None:
        query = query.where(Project.owner_id == owner_id)
    if organization_id is not None:
        query = query.where(Project.organization_id == organization_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(
        query.order_by(
            Project.organization_id.is_not(None), Organization.name, User.email, Project.name
        )
        .offset(page.offset)
        .limit(page.page_size)
    ).all()
    ids = [project.id for project, _, _ in rows]
    summaries = project_summaries(db, ids)
    share_rows = db.execute(
        select(ProjectShare.project_id, func.count())
        .where(ProjectShare.project_id.in_(ids))
        .group_by(ProjectShare.project_id)
    ).all()
    shares = {project_id: count for project_id, count in share_rows}
    items = []
    for project, owner, organization in rows:
        last_run, _ = summaries.get(project.id, (None, 0))
        items.append(
            AdminProjectResponse(
                id=project.id,
                name=project.name,
                owner=_admin_summary(owner) if owner else None,
                organization=(
                    OrganizationSummary.model_validate(organization) if organization else None
                ),
                shares=shares.get(project.id, 0),
                created_at=project.created_at,
                last_run=RunResponse.model_validate(last_run) if last_run else None,
            )
        )
    return Page(items=items, total=total, page=page.page, page_size=page.page_size)


def _recipient(db: DbSession, body: TransferRequest, previous: User) -> User:
    to = db.get(User, body.to_user_id)
    if to is None:
        raise field_error("to_user_id", "User not found")
    if not to.is_active:
        raise field_error("to_user_id", "This account is turned off")
    if to.id == previous.id:
        raise field_error("to_user_id", "This user is already the owner")
    return to


def _transfer_responses(
    db: DbSession, transfers: Sequence[OwnershipTransfer]
) -> list[TransferResponse]:
    ids = {u for t in transfers for u in (t.admin_id, t.from_user_id, t.to_user_id) if u}
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(ids)))}

    def summary(user_id: uuid.UUID | None) -> UserSummary | None:
        user = users.get(user_id) if user_id else None
        return UserSummary.model_validate(user) if user else None

    return [
        TransferResponse(
            id=t.id,
            created_at=t.created_at,
            admin=summary(t.admin_id),
            from_user=summary(t.from_user_id),
            to_user=summary(t.to_user_id),
            project_id=t.project_id,
            projects_moved=t.projects_moved,
            connections_moved=t.connections_moved,
            connections_copied=t.connections_copied,
            summary=t.summary,
        )
        for t in transfers
    ]


def _done(db: DbSession, transfer: OwnershipTransfer) -> TransferResponse:
    db.commit()
    db.refresh(transfer)
    logger.info(
        "Admin %s transferred %s project(s) from user %s to user %s",
        transfer.admin_id,
        transfer.projects_moved,
        transfer.from_user_id,
        transfer.to_user_id,
    )
    return _transfer_responses(db, [transfer])[0]


@router.post("/projects/{project_id}/transfer")
def transfer_one_project(
    project_id: uuid.UUID, body: TransferRequest, admin: AdminUser, db: DbSession
) -> TransferResponse:
    """Give a personal project and its connections to another user (copied if still in use).

    An organization's project is not the administrator's to move: its admins move it.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise not_found("Project")
    if project.owner_id is None:
        raise AppError(
            409,
            "organization_project",
            "This project belongs to an organization. Its admins can move it to a member.",
        )
    previous = db.get(User, project.owner_id)
    assert previous is not None  # noqa: S101  (the owner's foreign key)
    to = _recipient(db, body, previous)
    return _done(db, transfer_project(db, admin=admin, project=project, previous=previous, to=to))


@router.post("/users/{user_id}/transfer")
def transfer_all(
    user_id: uuid.UUID, body: TransferRequest, admin: AdminUser, db: DbSession
) -> TransferResponse:
    """Give everything a user owns (for example someone who left) to another user."""
    previous = db.get(User, user_id)
    if previous is None:
        raise not_found("User")
    to = _recipient(db, body, previous)
    if not owns_anything(db, previous.id):
        raise AppError(409, "nothing_to_transfer", "This user owns no projects or connections.")
    return _done(db, transfer_everything(db, admin=admin, previous=previous, to=to))


@router.get("/transfers")
def list_transfers(admin: AdminUser, db: DbSession, page: PageDep) -> Page[TransferResponse]:
    """Newest first."""
    total = db.scalar(select(func.count()).select_from(OwnershipTransfer)) or 0
    transfers = db.scalars(
        select(OwnershipTransfer)
        .order_by(OwnershipTransfer.created_at.desc(), OwnershipTransfer.id)
        .offset(page.offset)
        .limit(page.page_size)
    ).all()
    return Page(
        items=_transfer_responses(db, transfers),
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


def _organization_responses(
    db: DbSession, organizations: Sequence[Organization]
) -> list[AdminOrganizationResponse]:
    ids = [org.id for org in organizations]
    rows = db.execute(
        select(OrganizationMember, User)
        .join(User, User.id == OrganizationMember.user_id)
        .where(OrganizationMember.organization_id.in_(ids))
        .order_by(User.display_name)
    ).all()
    people: dict[uuid.UUID, list[MemberResponse]] = {}
    for member, user in rows:
        people.setdefault(member.organization_id, []).append(
            MemberResponse(
                user=UserSummary.model_validate(user),
                role=OrganizationRole(member.role).value,
                created_at=member.created_at,
            )
        )
    responses = []
    for org in organizations:
        projects, connections = owned_counts(db, org.id)
        responses.append(
            AdminOrganizationResponse(
                id=org.id,
                name=org.name,
                timezone=org.timezone,
                members=len(people.get(org.id, [])),
                admins=[p.user for p in people.get(org.id, []) if p.role == "admin"],
                people=people.get(org.id, []),
                projects=projects,
                connections=connections,
                created_at=org.created_at,
            )
        )
    return responses


@router.get("/organizations")
def list_organizations(
    admin: AdminUser, db: DbSession, page: PageDep
) -> Page[AdminOrganizationResponse]:
    """Every organization with its admins, for when one is left without an admin."""
    total = db.scalar(select(func.count()).select_from(Organization)) or 0
    organizations = db.scalars(
        select(Organization)
        .order_by(Organization.name, Organization.id)
        .offset(page.offset)
        .limit(page.page_size)
    ).all()
    return Page(
        items=_organization_responses(db, organizations),
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.post("/organizations/{organization_id}/admins")
def promote_admin(
    organization_id: uuid.UUID, body: PromoteAdmin, admin: AdminUser, db: DbSession
) -> AdminOrganizationResponse:
    """Make a member an admin of the organization (it may have lost its last admin)."""
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise not_found("Organization")
    member = MemberRepository(db, organization_id).get(body.user_id)
    if member is None:
        raise field_error("user_id", "Not a member of the organization")
    member.role = OrganizationRole.ADMIN
    db.commit()
    logger.info(
        "Admin %s made user %s an admin of organization %s",
        admin.id,
        body.user_id,
        organization_id,
    )
    return _organization_responses(db, [organization])[0]


def _connection_owners(
    db: DbSession, connections: Sequence[GitConnection] | Sequence[AzureConnection], column: Any
) -> tuple[dict[uuid.UUID, User], dict[uuid.UUID, Organization], dict[uuid.UUID, int]]:
    user_ids = {c.owner_id for c in connections if c.owner_id}
    org_ids = {c.organization_id for c in connections if c.organization_id}
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(user_ids)))}
    orgs = {o.id: o for o in db.scalars(select(Organization).where(Organization.id.in_(org_ids)))}
    usage = db.execute(
        select(column, func.count()).where(column.in_([c.id for c in connections])).group_by(column)
    ).all()
    return users, orgs, {connection_id: count for connection_id, count in usage}


def _owner_fields(
    connection: GitConnection | AzureConnection,
    users: dict[uuid.UUID, User],
    orgs: dict[uuid.UUID, Organization],
    usage: dict[uuid.UUID, int],
) -> dict[str, Any]:
    owner = users.get(connection.owner_id) if connection.owner_id else None
    org = orgs.get(connection.organization_id) if connection.organization_id else None
    return {
        "owner": _admin_summary(owner) if owner else None,
        "organization": OrganizationSummary.model_validate(org) if org else None,
        "projects": usage.get(connection.id, 0),
    }


def _all(db: DbSession, model: type[Any], page: PageDep) -> tuple[Sequence[Any], int]:
    total = db.scalar(select(func.count()).select_from(model)) or 0
    items = db.scalars(
        select(model)
        .order_by(model.name, model.created_at, model.id)
        .offset(page.offset)
        .limit(page.page_size)
    ).all()
    return items, total


@router.get("/git-connections")
def list_all_git_connections(
    admin: AdminUser, db: DbSession, page: PageDep
) -> Page[AdminGitConnectionResponse]:
    """Every Git connection with its owner. Secrets stay write-only, also for admins."""
    items, total = _all(db, GitConnection, page)
    users, orgs, usage = _connection_owners(db, items, Project.git_connection_id)
    return Page(
        items=[
            AdminGitConnectionResponse(
                **git_response(c).model_dump(), **_owner_fields(c, users, orgs, usage)
            )
            for c in items
        ],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get("/azure-connections")
def list_all_azure_connections(
    admin: AdminUser, db: DbSession, page: PageDep
) -> Page[AdminAzureConnectionResponse]:
    """Every Azure connection with its owner. PATs stay write-only, also for admins."""
    items, total = _all(db, AzureConnection, page)
    users, orgs, usage = _connection_owners(db, items, Project.azure_connection_id)
    return Page(
        items=[
            AdminAzureConnectionResponse(
                **azure_response(c).model_dump(), **_owner_fields(c, users, orgs, usage)
            )
            for c in items
        ],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )
