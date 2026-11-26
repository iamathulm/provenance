"""FastAPI application factory."""

from importlib.metadata import version

from fastapi import FastAPI

from provenance.core.config import Settings, get_settings

APP_VERSION = version("provenance-api")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API application. Pass `settings` to override environment config (tests)."""
    app = FastAPI(title="Provenance API", version=APP_VERSION)
    app.state.settings = settings or get_settings()

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": APP_VERSION}

    return app
