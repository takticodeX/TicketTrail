"""FastAPI dependencies: settings, database session and the authenticated user."""

from collections.abc import Iterator
from typing import Annotated, cast

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.core.errors import AppError
from app.core.security import TokenError, TokenExpiredError, decode_token
from app.db.models import User
from app.db.repositories import UserRepository


def get_app_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_db(request: Request) -> Iterator[Session]:
    factory = cast(sessionmaker[Session], request.app.state.session_factory)
    with factory() as session:
        yield session


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
DbSession = Annotated[Session, Depends(get_db)]

_bearer = HTTPBearer(auto_error=False, description="Access token from /auth/login")

_AUTH_HEADERS = {"WWW-Authenticate": "Bearer"}


def get_current_user(
    db: DbSession,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise AppError(401, "not_authenticated", "Authentication required.", headers=_AUTH_HEADERS)
    try:
        user_id = decode_token(
            credentials.credentials, settings.jwt_secret.get_secret_value(), "access"
        )
    except TokenExpiredError as exc:
        raise AppError(
            401, "token_expired", "The access token has expired.", headers=_AUTH_HEADERS
        ) from exc
    except TokenError as exc:
        raise AppError(
            401, "invalid_token", "The access token is invalid.", headers=_AUTH_HEADERS
        ) from exc

    user = UserRepository(db).get(user_id)
    if user is None or not user.is_active:
        raise AppError(401, "invalid_token", "The access token is invalid.", headers=_AUTH_HEADERS)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
