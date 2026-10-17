"""Registration, login and refresh-token rotation."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Cookie, Depends, Header, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import DbSession, LoginLimiterDep, SettingsDep
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
    REFRESH_REUSE_GRACE,
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "tt_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"
CSRF_HEADER_VALUE = "TicketTrail"


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


def require_csrf_header(x_requested_with: str | None = Header(default=None)) -> None:
    """CSRF protection for the cookie-authenticated endpoints (spec section 10).

    Another site can make a browser send the refresh cookie, but it cannot add a
    custom header without a CORS preflight, which this API never grants.
    SameSite=Strict on the cookie is the first line; this is the second.
    """
    if x_requested_with != CSRF_HEADER_VALUE:
        raise AppError(
            403, "csrf_failed", f"Missing the X-Requested-With: {CSRF_HEADER_VALUE} header."
        )


@router.post(
    "/login",
    responses={429: {"model": ErrorResponse, "description": "Too many login attempts"}},
)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
    settings: SettingsDep,
    limiter: LoginLimiterDep,
) -> TokenResponse:
    """Returns an access token and sets the refresh token as an httpOnly cookie.

    At most 5 attempts a minute per IP address and per email.
    """
    client_ip = request.client.host if request.client else "unknown"
    retry_after = limiter.hit(client_ip, body.email)
    if retry_after is not None:
        raise AppError(
            429,
            "too_many_attempts",
            "Too many login attempts. Wait a minute and try again.",
            headers={"Retry-After": str(retry_after)},
        )
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
    dependencies=[Depends(require_csrf_header)],
)
def refresh(
    response: Response,
    db: DbSession,
    settings: SettingsDep,
    tt_refresh: str | None = Cookie(default=None, include_in_schema=False),
) -> TokenResponse | JSONResponse:
    """Rotates the refresh cookie: the old token stops working, a new one is set.

    Presenting a token that was revoked more than REFRESH_REUSE_GRACE ago means it
    was copied, so every session of that user is revoked. Inside the grace window
    it is the normal race of two tabs refreshing at once: the request is refused
    without touching the cookie, which the other tab has already replaced.
    """

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

    tokens_repo = RefreshTokenRepository(db)
    stored = tokens_repo.get_by_hash_for_update(hash_token(tt_refresh))
    now = datetime.now(UTC)
    if stored is None or stored.expires_at <= now:
        return reject()
    if stored.revoked:
        if stored.revoked_at is not None and now - stored.revoked_at <= REFRESH_REUSE_GRACE:
            return error_response(
                401,
                "refresh_token_superseded",
                "This session was just refreshed by another request. Retry the refresh.",
            )
        logger.warning(
            "Refresh token reuse detected; revoking all sessions",
            extra={"user_id": str(stored.user_id)},
        )
        tokens_repo.revoke_all_for_user(stored.user_id)
        db.commit()
        return reject()
    user = UserRepository(db).get(stored.user_id)
    if user is None or not user.is_active:
        return reject()

    tokens_repo.revoke(stored)
    tokens = _start_session(db, user, response, settings)
    db.commit()
    return tokens


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf_header)],
)
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
