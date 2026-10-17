"""Administration: list users and turn accounts on or off (admins only)."""

import uuid

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import AdminUser, DbSession, PageDep
from app.api.v1.schemas import AdminUserResponse, AdminUserUpdate, Page, UserResponse
from app.core.errors import AppError, not_found
from app.db.models import Project, User
from app.db.repositories import RefreshTokenRepository

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
