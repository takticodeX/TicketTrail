"""FastAPI dependencies: settings, database session and the authenticated user."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated, cast

from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session, sessionmaker

from app.api.v1.schemas.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.config import Settings
from app.core.crypto import SecretBox
from app.core.errors import AppError
from app.core.security import TokenError, TokenExpiredError, decode_token
from app.db.models import User
from app.db.repositories import UserRepository
from app.worker.runner import TaskRunner


def get_app_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_db(request: Request) -> Iterator[Session]:
    factory = cast(sessionmaker[Session], request.app.state.session_factory)
    with factory() as session:
        yield session


def get_secret_box(request: Request) -> SecretBox:
    return cast(SecretBox, request.app.state.secret_box)


def get_task_runner(request: Request) -> TaskRunner:
    return cast(TaskRunner, request.app.state.task_runner)


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
DbSession = Annotated[Session, Depends(get_db)]
SecretBoxDep = Annotated[SecretBox, Depends(get_secret_box)]
TaskRunnerDep = Annotated[TaskRunner, Depends(get_task_runner)]


@dataclass(frozen=True)
class PageParams:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def get_page_params(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> PageParams:
    return PageParams(page=page, page_size=page_size)


PageDep = Annotated[PageParams, Depends(get_page_params)]

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
