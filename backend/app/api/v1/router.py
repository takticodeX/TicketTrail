from typing import Any

from fastapi import APIRouter

from app.api.v1 import auth, azure_connections, git_connections, health, me, projects
from app.core.errors import ErrorResponse

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Not authenticated"},
    422: {"model": ErrorResponse, "description": "Validation error"},
}
_RESOURCE_ERRORS: dict[int | str, dict[str, Any]] = {
    **_ERRORS,
    404: {"model": ErrorResponse, "description": "Not found, or owned by another user"},
    409: {"model": ErrorResponse, "description": "Name taken, or still in use"},
}

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(
    auth.router,
    responses={
        **_ERRORS,
        403: {"model": ErrorResponse, "description": "Forbidden"},
        409: {"model": ErrorResponse, "description": "Conflict"},
    },
)
api_router.include_router(
    me.router,
    responses={**_ERRORS, 400: {"model": ErrorResponse, "description": "Bad request"}},
)
_CONNECTION_ERRORS = {
    **_RESOURCE_ERRORS,
    503: {"model": ErrorResponse, "description": "The worker did not answer a test"},
}
api_router.include_router(git_connections.router, responses=_CONNECTION_ERRORS)
api_router.include_router(azure_connections.router, responses=_CONNECTION_ERRORS)
api_router.include_router(projects.router, responses=_RESOURCE_ERRORS)
