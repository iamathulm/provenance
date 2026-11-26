"""Shared fixtures: a real Postgres test database, migrated once, truncated after each test."""

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from provenance.api.app import create_app
from provenance.core.config import Settings

API_ROOT = Path(__file__).resolve().parents[1]
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://provenance:provenance@127.0.0.1:5432/provenance_test?connect_timeout=5",
)


def pytest_asyncio_loop_factories() -> Mapping[str, Callable[[], asyncio.AbstractEventLoop]] | None:
    """psycopg's async driver cannot run on Windows' default Proactor event loop."""
    if sys.platform == "win32":
        return {"selector": asyncio.SelectorEventLoop}
    return None


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
