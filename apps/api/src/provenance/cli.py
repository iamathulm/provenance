"""`provenance` command line: operational tasks run outside the web process."""

import argparse
import asyncio
import signal
import sys
from collections.abc import Coroutine, Sequence
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from qdrant_client import AsyncQdrantClient

from provenance.core.config import get_settings
from provenance.db.engine import create_engine_from_settings, session_factory
from provenance.ingest.runtime import build_worker
from provenance.seed import seed_demo

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def _run(coroutine: Coroutine[Any, Any, None]) -> None:
    # psycopg's async driver needs a selector event loop (Windows defaults to Proactor).
    asyncio.run(coroutine, loop_factory=asyncio.SelectorEventLoop)


def _migrate() -> None:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", get_settings().database_url)
    command.upgrade(config, "head")


async def _worker(*, until_idle: bool) -> None:
    settings = get_settings()
    engine = create_engine_from_settings(settings)
    qdrant = AsyncQdrantClient(url=settings.qdrant_url)
    try:
        worker = await build_worker(settings, session_factory(engine), qdrant)
        if until_idle:
            await worker.run_until_idle()
            return
        stop = asyncio.Event()
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, lambda *_: stop.set())
        await worker.run(stop)
    finally:
        await qdrant.close()
        await engine.dispose()


async def _seed_demo() -> None:
    engine = create_engine_from_settings(get_settings())
    try:
        await seed_demo(session_factory(engine))
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="provenance", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="apply database migrations up to head")
    commands.add_parser("seed-demo", help="create demo users and workspaces (idempotent)")
    worker = commands.add_parser("worker", help="process ingestion jobs until stopped")
    worker.add_argument(
        "--until-idle", action="store_true", help="exit once no job is ready (seeding, CI)"
    )
    args = parser.parse_args(argv)

    if args.command == "migrate":
        _migrate()
    elif args.command == "worker":
        _run(_worker(until_idle=args.until_idle))
    else:
        _run(_seed_demo())
    print(f"{args.command}: done", file=sys.stderr)
    return 0
