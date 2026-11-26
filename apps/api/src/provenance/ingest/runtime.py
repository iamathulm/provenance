"""Assembles the production indexing dependencies (real embeddings, Qdrant, telemetry)."""

from collections.abc import Callable

from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.core.config import Settings
from provenance.ingest.handlers import build_handlers
from provenance.ingest.indexing import IndexingDeps
from provenance.ingest.worker import Worker
from provenance.observability.telemetry import TelemetryRecorder
from provenance.profiles.loader import load_profiles
from provenance.retrieval.embeddings import FastEmbedder
from provenance.retrieval.index import ChunkIndex


async def build_worker(
    settings: Settings, session_factory: Callable[[], AsyncSession], qdrant: AsyncQdrantClient
) -> Worker:
    index = ChunkIndex(qdrant, settings.qdrant_collection, settings.embedding_dimension)
    await index.ensure_collection()
    deps = IndexingDeps(
        settings=settings,
        profiles=load_profiles(settings.profiles_dir),
        embedder=FastEmbedder(settings),
        index=index,
        recorder=TelemetryRecorder(session_factory),
    )
    return Worker(session_factory, build_handlers(session_factory, deps))
