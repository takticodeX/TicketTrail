from typing import Any

from fastapi import APIRouter

from app.api.v1 import auth, health, me
from app.core.errors import ErrorResponse

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Not authenticated"},
    422: {"model": ErrorResponse, "description": "Validation error"},
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
