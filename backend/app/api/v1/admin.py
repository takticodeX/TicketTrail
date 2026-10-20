"""Administration (admins only): users, accounts on or off, and ownership transfers.

An administrator doesn't read other users' projects: they see who owns what, and can
give a user's projects to someone else (for example when a colleague leaves).
Every transfer is recorded.
"""

import logging
import uuid
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import AdminUser, DbSession, PageDep
from app.api.v1.schemas import (
    AdminProjectResponse,
    AdminUserResponse,
    AdminUserSummary,
    AdminUserUpdate,
    Page,
    RunResponse,
    TransferRequest,
    TransferResponse,
    UserResponse,
    UserSummary,
)
from app.core.errors import AppError, field_error, not_found
from app.db.models import OwnershipTransfer, Project, ProjectShare, User
from app.db.repositories import RefreshTokenRepository, project_summaries
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
) -> Page[AdminProjectResponse]:
    """Every project and its owner: no settings, no secrets, no run details."""
    query = select(Project, User).join(User, User.id == Project.owner_id)
    if owner_id is not None:
        query = query.where(Project.owner_id == owner_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(
        query.order_by(User.email, Project.name, Project.id)
        .offset(page.offset)
        .limit(page.page_size)
    ).all()
    ids = [project.id for project, _ in rows]
    summaries = project_summaries(db, ids)
    share_rows = db.execute(
        select(ProjectShare.project_id, func.count())
        .where(ProjectShare.project_id.in_(ids))
        .group_by(ProjectShare.project_id)
    ).all()
    shares = {project_id: count for project_id, count in share_rows}
    items = []
    for project, owner in rows:
        last_run, _ = summaries.get(project.id, (None, 0))
        items.append(
            AdminProjectResponse(
                id=project.id,
                name=project.name,
                owner=_admin_summary(owner),
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
    """Give a project and its connections to another user (copied if still in use)."""
    project = db.get(Project, project_id)
    if project is None:
        raise not_found("Project")
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
