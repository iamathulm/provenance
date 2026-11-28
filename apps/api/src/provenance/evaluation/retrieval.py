"""Deterministic retrieval evaluation: run every golden question through search, score the ranks.

No LLM is involved, so results are reproducible for a given corpus, models and settings. Before
scoring, every gold anchor is checked against the indexed corpus: a label that no chunk satisfies
is a broken golden set (or a broken index) and fails the run instead of silently scoring zero.
"""

import time
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.auth.demo import DEMO_ACCOUNTS
from provenance.auth.models import User
from provenance.core.context import RequestContext
from provenance.documents.models import Chunk, Document
from provenance.evaluation.golden import Domain, GoldenItem, GoldenSet
from provenance.evaluation.metrics import bootstrap_ci, mean, mrr_at_k, ndcg_at_k, recall_at_k
from provenance.retrieval.router import route_query
from provenance.retrieval.search import Searcher, SearchMode, SearchRequest
from provenance.structured.catalog import load_catalog
from provenance.workspaces.models import Workspace

DEMO_WORKSPACE: dict[Domain, str] = {"company": "Company KB", "research": "Research Papers"}
RECALL_K, RANK_K = 5, 10
RANKING_METRICS = ("recall_at_5", "mrr_at_10", "ndcg_at_10", "doc_recall_at_5")


class NullRecorder:
    """Evaluation traffic is synthetic: keep it out of the telemetry that analytics reads."""

    async def record(self, *_: object) -> None:
        return None

    async def record_provider_call(self, *_: object) -> None:
        return None


class GoldMissingError(Exception):
    """Gold anchors that no indexed chunk satisfies."""


@dataclass(frozen=True)
class Estimate:
    mean: float
    ci_low: float
    ci_high: float


@dataclass
class ItemResult:
    id: str
    category: str
    route_expected: str
    route_predicted: str
    latency_ms: float
    top_files: list[str]
    route_reasons: list[str]
    scores: dict[str, float] = field(default_factory=dict)


@dataclass
class RetrievalReport:
    domain: Domain
    split: str
    mode: SearchMode
    items: list[ItemResult]
    metrics: dict[str, Estimate]
    by_category: dict[str, dict[str, float]]
    rerank_modes: dict[str, int]
    latency_ms: dict[str, float]


async def workspace_for(db: AsyncSession, domain: Domain) -> uuid.UUID:
    workspace_id = await db.scalar(
        select(Workspace.id)
        .join(User, User.id == Workspace.owner_id)
        .where(Workspace.name == DEMO_WORKSPACE[domain], User.email == DEMO_ACCOUNTS["primary"][0])
    )
    if workspace_id is None:
        name = DEMO_WORKSPACE[domain]
        msg = f"workspace '{name}' not found; run `provenance seed-demo --with-corpora`"
        raise LookupError(msg)
    return workspace_id


async def check_gold(db: AsyncSession, workspace_id: uuid.UUID, golden: GoldenSet) -> None:
    rows = await db.execute(
        select(Document.filename, Chunk.text)
        .join(Chunk, Chunk.version_id == Document.active_version_id)
        .where(Document.workspace_id == workspace_id, Document.deleted_at.is_(None))
    )
    corpus = [(filename, text) for filename, text in rows]
    missing = [
        f"{item.id}: {anchor.file} / {anchor.evidence!r}"
        for item in golden.items
        for anchor in item.gold
        if not any(anchor.matches(filename, text) for filename, text in corpus)
    ]
    if missing:
        raise GoldMissingError("gold anchors not found in the index:\n  " + "\n  ".join(missing))


def _matches(item: GoldenItem, hits: list[tuple[str, str]]) -> list[frozenset[int]]:
    return [
        frozenset(i for i, anchor in enumerate(item.gold) if anchor.matches(filename, text))
        for filename, text in hits
    ]


def _doc_recall(item: GoldenItem, files: list[str]) -> float:
    gold_files = {anchor.file for anchor in item.gold}
    found = gold_files & set(files[:RECALL_K])
    if item.requires == "all":
        return len(found) / len(gold_files)
    return 1.0 if found else 0.0


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))] if ordered else 0.0


async def evaluate(
    session_factory: Callable[[], AsyncSession],
    searcher: Searcher,
    golden: GoldenSet,
    mode: SearchMode,
) -> RetrievalReport:
    async with session_factory() as db:
        workspace_id = await workspace_for(db, golden.domain)
        await check_gold(db, workspace_id, golden)
        has_tables = bool(await load_catalog(db, workspace_id))
    results: list[ItemResult] = []
    rerank_modes: Counter[str] = Counter()
    for item in golden.items:
        ctx = RequestContext(correlation_id=f"eval-{item.id}", workspace_id=workspace_id)
        started = time.perf_counter()
        async with session_factory() as db:
            result = await searcher.search(
                db, ctx, workspace_id, SearchRequest(item.question, mode, RANK_K)
            )
        latency = (time.perf_counter() - started) * 1000
        rerank_modes[result.rerank_mode] += 1
        hits = [(hit.document.filename, hit.chunk.text) for hit in result.hits]
        route = route_query(item.question, result.ranked_chunks, has_tables)
        scored = ItemResult(
            item.id,
            item.category,
            item.route,
            route.kind,
            latency,
            [f for f, _ in hits[:3]],
            route.reasons,
        )
        if item.answerable:
            matched = _matches(item, hits)
            requires_all = item.requires == "all"
            scored.scores = {
                "recall_at_5": recall_at_k(
                    matched, len(item.gold), RECALL_K, requires_all=requires_all
                ),
                "mrr_at_10": mrr_at_k(matched, RANK_K),
                "ndcg_at_10": ndcg_at_k(matched, len(item.gold), RANK_K, requires_all=requires_all),
                "doc_recall_at_5": _doc_recall(item, [f for f, _ in hits]),
            }
        results.append(scored)
    return _summarize(golden, mode, results, rerank_modes)


def _summarize(
    golden: GoldenSet, mode: SearchMode, results: list[ItemResult], rerank_modes: Counter[str]
) -> RetrievalReport:
    scored = [r for r in results if r.scores]
    metrics: dict[str, Estimate] = {}
    for name in RANKING_METRICS:
        values = [r.scores[name] for r in scored]
        metrics[name] = Estimate(mean(values), *bootstrap_ci(values))
    routes = [1.0 if r.route_predicted == r.route_expected else 0.0 for r in results]
    metrics["route_accuracy"] = Estimate(mean(routes), *bootstrap_ci(routes))
    grouped: dict[str, list[ItemResult]] = defaultdict(list)
    for r in scored:
        grouped[r.category].append(r)
    by_category = {
        category: {name: mean([r.scores[name] for r in group]) for name in RANKING_METRICS}
        | {"count": float(len(group))}
        for category, group in sorted(grouped.items())
    }
    latencies = [r.latency_ms for r in results]
    return RetrievalReport(
        domain=golden.domain,
        split=golden.split,
        mode=mode,
        items=results,
        metrics=metrics,
        by_category=by_category,
        rerank_modes=dict(rerank_modes),
        latency_ms={"p50": _percentile(latencies, 0.5), "p95": _percentile(latencies, 0.95)},
    )
