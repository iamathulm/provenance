"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version

from fastapi import FastAPI

from provenance.core.config import Settings, get_settings
from provenance.db.engine import create_engine_from_settings, session_factory

APP_VERSION = version("provenance-api")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API application. Pass `settings` to override environment config (tests)."""
    resolved = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine_from_settings(resolved)
        app.state.session_factory = session_factory(engine)
        yield
        await engine.dispose()

    app = FastAPI(title="Provenance API", version=APP_VERSION, lifespan=lifespan)
    app.state.settings = resolved

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": APP_VERSION}

    return app
