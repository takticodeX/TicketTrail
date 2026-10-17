"""Liveness and readiness probes."""

import logging
from typing import cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from redis import Redis
from sqlalchemy import Engine, text

from app.api.v1.schemas import HealthResponse, ReadyResponse
from app.core.errors import ErrorResponse, error_response

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> HealthResponse:
    """The process is up. Does not touch the database or Redis."""
    return HealthResponse(status="ok")


@router.get(
    "/ready",
    response_model=ReadyResponse,
    responses={503: {"model": ErrorResponse, "description": "A dependency is unavailable"}},
)
def ready(request: Request) -> ReadyResponse | JSONResponse:
    """The database and Redis are reachable."""
    checks: dict[str, str] = {}
    try:
        with cast(Engine, request.app.state.engine).connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        logger.warning("Readiness check failed: database", exc_info=True)
        checks["database"] = "unavailable"
    try:
        cast(Redis, request.app.state.redis).ping()
        checks["redis"] = "ok"
    except Exception:
        logger.warning("Readiness check failed: redis", exc_info=True)
        checks["redis"] = "unavailable"

    if any(value != "ok" for value in checks.values()):
        return error_response(503, "not_ready", "A dependency is unavailable.", {"checks": checks})
    return ReadyResponse(status="ready", checks=checks)
