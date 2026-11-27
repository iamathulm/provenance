"""`provenance` command line: operational tasks run outside the web process."""

import argparse
import asyncio
import json
import signal
import sys
import time
from collections.abc import Coroutine, Sequence
from pathlib import Path
from typing import Any, get_args

from alembic import command
from alembic.config import Config
from qdrant_client import AsyncQdrantClient

from provenance.core.config import REPO_ROOT, get_settings
from provenance.db.engine import create_engine_from_settings, session_factory
from provenance.demo import company_corpus, research_corpus
from provenance.evaluation.golden import Domain, Split, load_golden
from provenance.evaluation.report import (
    check_thresholds,
    load_thresholds,
    run_metadata,
    to_json,
    to_markdown,
)
from provenance.evaluation.retrieval import NullRecorder, RetrievalReport, evaluate
from provenance.ingest.runtime import build_worker
from provenance.observability.logging import configure_logging
from provenance.retrieval.embeddings import FastEmbedder
from provenance.retrieval.index import ChunkIndex
from provenance.retrieval.rerank import FlashRanker
from provenance.retrieval.search import SEARCH_MODES, Searcher, SearchMode
from provenance.seed import seed_demo, upload_corpus

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
COMPANY_SOURCE = REPO_ROOT / "data" / "company" / "source"
COMPANY_FILES = REPO_ROOT / "data" / "company" / "files"
RESEARCH_MANIFEST = REPO_ROOT / "data" / "research" / "manifest.yaml"
RESEARCH_FILES = REPO_ROOT / "data" / "research" / "files"


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    # psycopg's async driver needs a selector event loop (Windows defaults to Proactor).
    return asyncio.run(coroutine, loop_factory=asyncio.SelectorEventLoop)


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


async def _eval(
    domains: list[Domain],
    split: Split,
    modes: list[SearchMode],
    out: Path | None,
    check: Path | None,
) -> int:
    settings = get_settings()
    engine = create_engine_from_settings(settings)
    factory = session_factory(engine)
    qdrant = AsyncQdrantClient(url=settings.qdrant_url)
    index = ChunkIndex(qdrant, settings.qdrant_collection, settings.embedding_dimension)
    searcher = Searcher(
        FastEmbedder(settings), index, FlashRanker(settings), NullRecorder(), settings
    )
    golden_sets = [load_golden(domain, split) for domain in domains]
    reports: list[RetrievalReport] = []
    try:
        for golden in golden_sets:
            for mode in modes:
                report = await evaluate(factory, searcher, golden, mode)
                recall = report.metrics["recall_at_5"].mean
                _say(f"{golden.domain}/{split} {mode}: recall@5 {recall:.3f}")
                reports.append(report)
    finally:
        await qdrant.close()
        await engine.dispose()
    metadata = run_metadata(golden_sets, settings)
    markdown = to_markdown(reports, metadata)
    print(markdown)
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        report_json = json.dumps(to_json(reports, metadata), indent=2) + "\n"
        for name, content in (("json", report_json), ("md", markdown)):
            path = out / f"retrieval-{split}.{name}"
            path.write_text(content, encoding="utf-8", newline="\n")  # same bytes on every OS
    if check is None:
        return 0
    failures = check_thresholds(reports, load_thresholds(check))
    for failure in failures:
        _say(f"gate failed: {failure}")
    return 1 if failures else 0


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
    evaluation = commands.add_parser("eval", help="score retrieval against the golden sets")
    evaluation.add_argument(
        "--domain", choices=[*get_args(Domain), "all"], default="all", help="golden set domain"
    )
    evaluation.add_argument("--split", choices=get_args(Split), default="dev")
    evaluation.add_argument(
        "--ablation", action="store_true", help="score every search mode, not only the default"
    )
    evaluation.add_argument("--out", type=Path, help="write retrieval-<split>.json/.md here")
    evaluation.add_argument(
        "--check", type=Path, help="thresholds YAML; exit 1 if the default mode misses one"
    )
    args = parser.parse_args(argv)
    configure_logging(get_settings())

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
        case "eval":
            domains = list(get_args(Domain)) if args.domain == "all" else [args.domain]
            modes: list[SearchMode] = list(SEARCH_MODES) if args.ablation else ["hybrid_rerank"]
            status = _run(_eval(domains, args.split, modes, args.out, args.check))
            _say(f"eval: {'gate failed' if status else 'done'}")
            return status
        case _:
            _run(_seed_demo(with_corpora=args.with_corpora))
    _say(f"{args.command}: done")
    return 0
