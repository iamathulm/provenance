"""Shared fixtures: a real Postgres test database, migrated once, truncated after each test."""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from qdrant_client import AsyncQdrantClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.api.app import create_app
from provenance.core.config import Settings
from provenance.ingest.handlers import build_handlers
from provenance.ingest.indexing import IndexingDeps
from provenance.ingest.worker import Worker
from provenance.retrieval.index import ChunkIndex
from provenance.seed import seed_demo
from provenance.workspaces.models import Workspace
from tests.ingest.harness import Harness
from tests.retrieval.fakes import FakeEmbedder, FakeReranker

API_ROOT = Path(__file__).resolve().parents[1]
TEST_QDRANT_URL = os.environ.get("TEST_QDRANT_URL", "http://127.0.0.1:6333")
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://provenance:provenance@127.0.0.1:5432/provenance_test?connect_timeout=5",
)


def pytest_asyncio_loop_factories() -> Mapping[str, Callable[[], asyncio.AbstractEventLoop]]:
    """Selector loop everywhere: psycopg async cannot run on Windows' default Proactor loop, and
    it is already the default on Linux/macOS."""
    return {"selector": asyncio.SelectorEventLoop}


def alembic_config(database_url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _ensure_database_exists(database_url: str) -> None:
    url = make_url(database_url)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": url.database}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        database_url=TEST_DATABASE_URL,
        qdrant_url=TEST_QDRANT_URL,
        demo_mode=True,
    )


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    _ensure_database_exists(TEST_DATABASE_URL)
    command.upgrade(alembic_config(TEST_DATABASE_URL), "head")


@pytest.fixture(autouse=True)
def _truncate_tables() -> Iterator[None]:
    yield
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as conn:
        tables = conn.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            )
        ).scalars()
        names = ", ".join(f'"{name}"' for name in tables)
        if names:
            conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    engine.dispose()


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


@pytest.fixture
def client_factory(app: FastAPI) -> Callable[[], AsyncClient]:
    """Independent clients (separate cookie jars) for multi-user scenarios."""

    def make() -> AsyncClient:
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    return make


@pytest.fixture
async def db(app: FastAPI) -> AsyncIterator[AsyncSession]:
    async with app.state.session_factory() as session:
        yield session


@pytest.fixture
async def chunk_index(settings: Settings) -> AsyncIterator[ChunkIndex]:
    """A throwaway Qdrant collection per test."""
    client = AsyncQdrantClient(url=settings.qdrant_url)
    index = ChunkIndex(client, f"test_{uuid.uuid4().hex}", settings.embedding_dimension)
    await index.ensure_collection()
    yield index
    await client.delete_collection(index.collection)
    await client.close()


@pytest.fixture
async def harness(app: FastAPI, chunk_index: ChunkIndex, settings: Settings) -> Harness:
    """Seeded demo data, the app wired to a throwaway Qdrant collection, and an inline worker."""
    await seed_demo(app.state.session_factory)
    app.state.chunk_index = chunk_index
    app.state.embedder = FakeEmbedder()
    app.state.reranker = FakeReranker()
    async with app.state.session_factory() as db:
        workspace_id = await db.scalar(select(Workspace.id).where(Workspace.name == "Company KB"))
    assert workspace_id is not None
    deps = IndexingDeps(
        settings, app.state.profiles, app.state.embedder, chunk_index, app.state.telemetry
    )
    worker = Worker(app.state.session_factory, build_handlers(app.state.session_factory, deps))
    return Harness(app.state.session_factory, deps, worker, workspace_id)
