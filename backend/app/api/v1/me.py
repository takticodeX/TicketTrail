"""The signed-in user's own profile."""

from fastapi import APIRouter, Response

from app.api.deps import CurrentUser, DbSession, SettingsDep
from app.api.v1.auth import issue_refresh_cookie
from app.api.v1.schemas import UserResponse, UserUpdateRequest
from app.core.errors import AppError
from app.core.security import hash_password, verify_password
from app.db.repositories import RefreshTokenRepository

router = APIRouter(prefix="/me", tags=["me"])


@router.get("")
def get_me(user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(user)


@router.patch("")
def update_me(
    body: UserUpdateRequest,
    user: CurrentUser,
    db: DbSession,
    settings: SettingsDep,
    response: Response,
) -> UserResponse:
    """Update the display name or time zone, or change the password.

    A password change revokes every session and sets a fresh refresh cookie,
    so the caller stays signed in while all other devices are signed out.
    """
    if body.display_name is not None:
        user.display_name = body.display_name
    if body.timezone is not None:
        user.timezone = body.timezone
    if body.new_password is not None:
        if not verify_password(user.password_hash, body.current_password or ""):
            raise AppError(400, "invalid_current_password", "The current password is incorrect.")
        user.password_hash = hash_password(body.new_password)
        RefreshTokenRepository(db).revoke_all_for_user(user.id)
        issue_refresh_cookie(db, user, response, settings)
    db.commit()
    db.refresh(user)
    return UserResponse.model_validate(user)
