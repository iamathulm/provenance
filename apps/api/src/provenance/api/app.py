"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version

from fastapi import FastAPI

from provenance.api.v1 import router as v1_router
from provenance.auth.rate_limit import LoginRateLimiter
from provenance.core.config import Settings, get_settings
from provenance.core.errors import register_error_handlers
from provenance.db.engine import create_engine_from_settings, session_factory
from provenance.observability.logging import configure_logging
from provenance.observability.middleware import CorrelationIdMiddleware
from provenance.observability.origin import OriginCheckMiddleware

APP_VERSION = version("provenance-api")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API application. Pass `settings` to override environment config (tests)."""
    resolved = settings or get_settings()
    configure_logging(resolved)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine_from_settings(resolved)
        app.state.session_factory = session_factory(engine)
        yield
        await engine.dispose()

    app = FastAPI(title="Provenance API", version=APP_VERSION, lifespan=lifespan)
    app.state.settings = resolved
    app.state.login_limiter = LoginRateLimiter()
    register_error_handlers(app)
    # Last added runs first: correlation IDs wrap everything, including origin rejections.
    app.add_middleware(OriginCheckMiddleware, allowed_origins=resolved.allowed_origins)
    app.add_middleware(CorrelationIdMiddleware)
    app.include_router(v1_router)

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": APP_VERSION}

    return app
