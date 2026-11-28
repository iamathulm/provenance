"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version

import httpx
import structlog
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from qdrant_client import AsyncQdrantClient

from provenance.api.v1 import router as v1_router
from provenance.auth.rate_limit import LoginRateLimiter
from provenance.conversations.limits import QuestionRateLimiter
from provenance.core.config import Settings, get_settings
from provenance.core.errors import register_error_handlers
from provenance.db.engine import create_engine_from_settings, session_factory
from provenance.generation.prompts import load_prompt
from provenance.generation.runtime import build_llm_client
from provenance.observability.logging import configure_logging
from provenance.observability.metrics import REGISTRY
from provenance.observability.middleware import CorrelationIdMiddleware
from provenance.observability.origin import OriginCheckMiddleware
from provenance.observability.telemetry import TelemetryRecorder
from provenance.observability.tracing import configure_tracing
from provenance.profiles.loader import load_profiles
from provenance.retrieval.embeddings import FastEmbedder
from provenance.retrieval.index import ChunkIndex
from provenance.retrieval.rerank import FlashRanker

APP_VERSION = version("provenance-api")
log = structlog.get_logger()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API application. Pass `settings` to override environment config (tests)."""
    resolved = settings or get_settings()
    configure_logging(resolved)
    configure_tracing(resolved)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine_from_settings(resolved)
        app.state.session_factory = session_factory(engine)
        app.state.telemetry = TelemetryRecorder(app.state.session_factory)
        qdrant = AsyncQdrantClient(url=resolved.qdrant_url)
        app.state.chunk_index = ChunkIndex(
            qdrant, resolved.qdrant_collection, resolved.embedding_dimension
        )
        llm_http = httpx.AsyncClient(base_url=resolved.groq_base_url)
        app.state.llm = build_llm_client(resolved, llm_http, app.state.telemetry)
        try:
            await app.state.chunk_index.ensure_collection()
        except Exception as error:
            log.warning("vector_store_unavailable", error_class=type(error).__name__)
        yield
        await llm_http.aclose()
        await qdrant.close()
        await engine.dispose()

    app = FastAPI(title="Provenance API", version=APP_VERSION, lifespan=lifespan)
    app.state.settings = resolved
    app.state.login_limiter = LoginRateLimiter()
    app.state.question_limiter = QuestionRateLimiter(
        resolved.questions_per_minute, resolved.questions_per_hour
    )
    app.state.profiles = load_profiles(resolved.profiles_dir)
    app.state.embedder = FastEmbedder(resolved)  # models load lazily on first search
    app.state.reranker = FlashRanker(resolved)
    app.state.prompts = {name: load_prompt(name) for name in ("answer", "sql")}
    register_error_handlers(app)
    # Last added runs first: correlation IDs wrap everything, including origin rejections.
    app.add_middleware(OriginCheckMiddleware, allowed_origins=resolved.allowed_origins)
    app.add_middleware(CorrelationIdMiddleware)
    app.include_router(v1_router)

    @app.get("/metrics", tags=["ops"], response_class=PlainTextResponse)
    def prometheus_metrics() -> PlainTextResponse:
        return PlainTextResponse(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": APP_VERSION}

    return app
