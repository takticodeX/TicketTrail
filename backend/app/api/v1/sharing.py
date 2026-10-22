"""Sharing a project with other users, as viewer or editor. Only the owner manages shares."""

import uuid

from fastapi import APIRouter, Response, status

from app.api.access import project_for
from app.api.deps import CurrentUser, DbSession
from app.api.v1.schemas import ShareCreate, ShareResponse, ShareUpdate, UserSummary
from app.core.errors import AppError, not_found
from app.db.models import ProjectRole, ProjectShare, User
from app.db.repositories import ProjectAccessRepository, ProjectShareRepository, UserRepository

router = APIRouter(prefix="/projects/{project_id}/shares", tags=["sharing"])


def _response(share: ProjectShare, user: User) -> ShareResponse:
    return ShareResponse(
        user=UserSummary.model_validate(user),
        role=ProjectRole(share.role).value,
        created_at=share.created_at,
    )


@router.get("")
def list_shares(project_id: uuid.UUID, user: CurrentUser, db: DbSession) -> list[ShareResponse]:
    project_for(db, user, project_id, ProjectRole.OWNER)
    return [_response(s, u) for s, u in ProjectShareRepository(db, project_id).list()]


@router.post("", status_code=status.HTTP_201_CREATED)
def add_share(
    project_id: uuid.UUID, body: ShareCreate, user: CurrentUser, db: DbSession
) -> ShareResponse:
    """Share with a registered user, found by their exact email."""
    project_for(db, user, project_id, ProjectRole.OWNER)
    target = UserRepository(db).get_by_email(body.email)
    if target is None or not target.is_active:
        # The same answer for unknown and turned-off accounts: no directory of users.
        raise AppError(404, "user_not_found", "No user with this email.")
    if target.id == user.id:
        raise AppError(409, "is_owner", "You own this project already.")
    theirs = ProjectAccessRepository(db, target.id, is_admin=target.is_admin).get(project_id)
    if theirs is not None and theirs.role is ProjectRole.OWNER:
        # For example an admin of the organization that owns the project.
        raise AppError(409, "is_owner", "This user already has owner access to the project.")
    repo = ProjectShareRepository(db, project_id)
    if repo.get(target.id) is not None:
        raise AppError(409, "already_shared", "The project is already shared with this user.")
    share = repo.add(target.id, ProjectRole(body.role))
    db.commit()
    db.refresh(share)
    return _response(share, target)


def _share_or_404(db: DbSession, project_id: uuid.UUID, user_id: uuid.UUID) -> ProjectShare:
    share = ProjectShareRepository(db, project_id).get(user_id)
    if share is None:
        raise not_found("Share")
    return share


@router.patch("/{user_id}")
def update_share(
    project_id: uuid.UUID, user_id: uuid.UUID, body: ShareUpdate, user: CurrentUser, db: DbSession
) -> ShareResponse:
    project_for(db, user, project_id, ProjectRole.OWNER)
    share = _share_or_404(db, project_id, user_id)
    share.role = body.role
    db.commit()
    db.refresh(share)
    target = db.get(User, user_id)
    assert target is not None  # noqa: S101  (the share's foreign key)
    return _response(share, target)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_share(
    project_id: uuid.UUID, user_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> Response:
    """The owner removes anyone; a user can also leave a project shared with them."""
    project_for(
        db, user, project_id, ProjectRole.VIEWER if user_id == user.id else ProjectRole.OWNER
    )
    ProjectShareRepository(db, project_id).delete(_share_or_404(db, project_id, user_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
