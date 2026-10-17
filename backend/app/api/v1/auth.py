"""Registration, login and refresh-token rotation."""

from datetime import UTC, datetime

from fastapi import APIRouter, Cookie, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import DbSession, SettingsDep
from app.api.v1.schemas import (
    AuthConfigResponse,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.config import Settings
from app.core.errors import AppError, ErrorResponse, error_response
from app.core.security import (
    ACCESS_TOKEN_TTL,
    REFRESH_TOKEN_TTL,
    TokenError,
    burn_password_check,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    verify_password,
)
from app.db.models import User
from app.db.repositories import RefreshTokenRepository, UserRepository

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "tt_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"


def _set_refresh_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=int(REFRESH_TOKEN_TTL.total_seconds()),
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="strict",
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        REFRESH_COOKIE,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="strict",
    )


def issue_refresh_cookie(db: Session, user: User, response: Response, settings: Settings) -> None:
    """Store a new refresh token and set it as the cookie. The caller commits."""
    refresh = create_refresh_token(user.id, settings.jwt_secret.get_secret_value())
    RefreshTokenRepository(db).create(
        user_id=user.id, token_hash=hash_token(refresh.token), expires_at=refresh.expires_at
    )
    _set_refresh_cookie(response, refresh.token, settings)


def _start_session(
    db: Session, user: User, response: Response, settings: Settings
) -> TokenResponse:
    """Issue an access token and a stored refresh token. The caller commits."""
    issue_refresh_cookie(db, user, response, settings)
    access = create_access_token(user.id, settings.jwt_secret.get_secret_value())
    return TokenResponse(
        access_token=access.token, expires_in=int(ACCESS_TOKEN_TTL.total_seconds())
    )


@router.get("/config")
def auth_config(settings: SettingsDep) -> AuthConfigResponse:
    """Public settings the login page needs, such as whether sign-up is open."""
    return AuthConfigResponse(allow_registration=settings.allow_registration)


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: DbSession, settings: SettingsDep) -> UserResponse:
    if not settings.allow_registration:
        raise AppError(403, "registration_disabled", "Registration is turned off.")
    users = UserRepository(db)
    if users.get_by_email(body.email) is not None:
        raise AppError(409, "email_taken", "An account with this email already exists.")
    try:
        user = users.create(
            email=body.email,
            password_hash=hash_password(body.password),
            display_name=body.display_name or body.email.split("@", 1)[0],
        )
        db.commit()
    except IntegrityError as exc:  # lost a race with a parallel registration
        db.rollback()
        raise AppError(409, "email_taken", "An account with this email already exists.") from exc
    return UserResponse.model_validate(user)


@router.post("/login")
def login(
    body: LoginRequest, response: Response, db: DbSession, settings: SettingsDep
) -> TokenResponse:
    """Returns an access token and sets the refresh token as an httpOnly cookie."""
    user = UserRepository(db).get_by_email(body.email)
    if user is None:
        burn_password_check(body.password)
        raise AppError(401, "invalid_credentials", "Email or password is incorrect.")
    if not verify_password(user.password_hash, body.password):
        raise AppError(401, "invalid_credentials", "Email or password is incorrect.")
    if not user.is_active:
        raise AppError(403, "account_disabled", "This account has been turned off.")
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)

    tokens = _start_session(db, user, response, settings)
    db.commit()
    return tokens


@router.post(
    "/refresh",
    response_model=TokenResponse,
    responses={401: {"model": ErrorResponse, "description": "Missing or invalid refresh token"}},
)
def refresh(
    response: Response,
    db: DbSession,
    settings: SettingsDep,
    tt_refresh: str | None = Cookie(default=None, include_in_schema=False),
) -> TokenResponse | JSONResponse:
    """Rotates the refresh cookie: the old token stops working, a new one is set."""

    def reject() -> JSONResponse:
        # Returned rather than raised, so the cookie-clearing header is kept.
        rejection = error_response(
            401, "invalid_refresh_token", "The session has expired. Log in again."
        )
        _clear_refresh_cookie(rejection, settings)
        return rejection

    if not tt_refresh:
        return reject()
    try:
        decode_token(tt_refresh, settings.jwt_secret.get_secret_value(), "refresh")
    except TokenError:
        return reject()

    stored = RefreshTokenRepository(db).get_by_hash_for_update(hash_token(tt_refresh))
    if stored is None or stored.revoked or stored.expires_at <= datetime.now(UTC):
        return reject()
    user = UserRepository(db).get(stored.user_id)
    if user is None or not user.is_active:
        return reject()

    stored.revoked = True
    tokens = _start_session(db, user, response, settings)
    db.commit()
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    db: DbSession,
    settings: SettingsDep,
    tt_refresh: str | None = Cookie(default=None, include_in_schema=False),
) -> Response:
    """Revokes the current refresh token and clears the cookie."""
    if tt_refresh:
        RefreshTokenRepository(db).revoke_by_hash(hash_token(tt_refresh))
        db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_refresh_cookie(response, settings)
    return response
