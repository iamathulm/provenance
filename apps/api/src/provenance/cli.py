"""`provenance` command line: operational tasks run outside the web process."""

import argparse
import asyncio
import signal
import sys
import time
from collections.abc import Coroutine, Sequence
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from qdrant_client import AsyncQdrantClient

from provenance.core.config import REPO_ROOT, get_settings
from provenance.db.engine import create_engine_from_settings, session_factory
from provenance.demo import company_corpus, research_corpus
from provenance.ingest.runtime import build_worker
from provenance.seed import seed_demo, upload_corpus

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
COMPANY_SOURCE = REPO_ROOT / "data" / "company" / "source"
COMPANY_FILES = REPO_ROOT / "data" / "company" / "files"
RESEARCH_MANIFEST = REPO_ROOT / "data" / "research" / "manifest.yaml"
RESEARCH_FILES = REPO_ROOT / "data" / "research" / "files"


def _run(coroutine: Coroutine[Any, Any, None]) -> None:
    # psycopg's async driver needs a selector event loop (Windows defaults to Proactor).
    asyncio.run(coroutine, loop_factory=asyncio.SelectorEventLoop)


def _say(message: str) -> None:
    print(message, file=sys.stderr)


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


async def _seed_demo(*, with_corpora: bool) -> None:
    settings = get_settings()
    engine = create_engine_from_settings(settings)
    factory = session_factory(engine)
    try:
        await seed_demo(factory)
        if not with_corpora:
            return
        research = research_corpus.fetch(RESEARCH_MANIFEST, RESEARCH_FILES)
        company = sorted(COMPANY_FILES.iterdir())
        queued = await upload_corpus(factory, settings, "Company KB", company)
        queued += await upload_corpus(factory, settings, "Research Papers", research)
        _say(f"queued {queued} documents; indexing...")
        started = time.perf_counter()
        qdrant = AsyncQdrantClient(url=settings.qdrant_url)
        try:
            worker = await build_worker(settings, factory, qdrant)
            processed = await worker.run_until_idle()
        finally:
            await qdrant.close()
        _say(f"indexed {processed} jobs in {time.perf_counter() - started:.1f}s")
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="provenance", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="apply database migrations up to head")
    seed = commands.add_parser("seed-demo", help="create demo users and workspaces (idempotent)")
    seed.add_argument(
        "--with-corpora",
        action="store_true",
        help="also upload and index the company and research demo corpora",
    )
    worker = commands.add_parser("worker", help="process ingestion jobs until stopped")
    worker.add_argument(
        "--until-idle", action="store_true", help="exit once no job is ready (seeding, CI)"
    )
    commands.add_parser(
        "build-company-corpus", help="render data/company/source/*.yaml into office files"
    )
    research = commands.add_parser(
        "fetch-research", help="download the pinned CC BY research papers and verify checksums"
    )
    research.add_argument(
        "--refresh", action="store_true", help="re-resolve versions and licenses from arXiv"
    )
    args = parser.parse_args(argv)

    match args.command:
        case "migrate":
            _migrate()
        case "worker":
            _run(_worker(until_idle=args.until_idle))
        case "build-company-corpus":
            for path in company_corpus.build(COMPANY_SOURCE, COMPANY_FILES):
                _say(f"wrote {path.relative_to(REPO_ROOT)}")
        case "fetch-research":
            if args.refresh:
                for line in research_corpus.refresh(RESEARCH_MANIFEST, RESEARCH_FILES):
                    _say(line)
            else:
                research_corpus.fetch(RESEARCH_MANIFEST, RESEARCH_FILES)
        case _:
            _run(_seed_demo(with_corpora=args.with_corpora))
    _say(f"{args.command}: done")
    return 0
