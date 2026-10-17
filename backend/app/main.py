"""FastAPI app factory. Run with: uvicorn --factory app.main:create_app"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis import Redis

from app import __version__
from app.api.v1.router import api_router
from app.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.db.session import create_db_engine, create_session_factory


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    engine = create_db_engine(settings.database_url)
    redis = Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        redis.close()
        engine.dispose()

    app = FastAPI(
        title="TicketTrail API",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.state.redis = redis

    register_exception_handlers(app)
    app.include_router(api_router, prefix="/api/v1")
    return app
