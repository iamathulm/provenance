import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.core.context import RequestContext
from provenance.documents.models import Document
from provenance.observability.models import StageSpan
from provenance.retrieval.rerank import Reranker
from provenance.retrieval.search import Searcher, SearchMode, SearchRequest, SearchResult
from tests.ingest.harness import Harness
from tests.retrieval.fakes import FailingReranker, FakeReranker

BATTERY = b"# Battery fault\n\nLand within 90 seconds and swap the pack.\n"
LOST_LINK = b"# Lost link\n\nHold position for 30 seconds, then return to home.\n"
TRAVEL = b"# Travel\n\nBook economy fares for flights under six hours.\n"


class SlowReranker:
    def score(self, query: str, passages: list[str]) -> list[float]:  # noqa: ARG002 - protocol
        time.sleep(0.5)
        return [0.0] * len(passages)


def searcher(harness: Harness, reranker: Reranker, **settings: float) -> Searcher:
    deps = harness.deps
    return Searcher(
        deps.embedder,
        deps.index,
        reranker,
        deps.recorder,
        deps.settings.model_copy(update=settings),
    )


async def indexed(harness: Harness) -> None:
    for name, content in [
        ("battery.txt", BATTERY),
        ("lost-link.txt", LOST_LINK),
        ("travel.txt", TRAVEL),
    ]:
        await harness.upload(name, content)
    await harness.worker.run_until_idle()


async def run(
    harness: Harness,
    db: AsyncSession,
    query: str,
    reranker: Reranker | None = None,
    *,
    mode: SearchMode = "hybrid_rerank",
    top_k: int = 8,
    document_ids: tuple[uuid.UUID, ...] = (),
) -> SearchResult:
    ctx = RequestContext(correlation_id="test-search", workspace_id=harness.workspace_id)
    request = SearchRequest(query, mode, top_k, document_ids)
    return await searcher(harness, reranker or FakeReranker()).search(
        db, ctx, harness.workspace_id, request
    )


async def test_hybrid_rerank_finds_and_ranks_keyword_match(
    harness: Harness, db: AsyncSession
) -> None:
    await indexed(harness)

    result = await run(harness, db, "swap the battery pack")

    top = result.hits[0]
    assert result.rerank_mode == "flashrank"
    assert top.document.filename == "battery.txt"
    assert top.chunk.anchor_label == "Battery fault"
    assert top.candidate.sparse_rank == 1
    assert top.rerank_score is not None
    assert set(result.timings_ms) == {"embed_query", "retrieve", "authorize", "rerank"}


async def test_ablation_modes_skip_stages(harness: Harness, db: AsyncSession) -> None:
    await indexed(harness)
    reranker = FakeReranker()

    dense = await run(harness, db, "swap the battery pack", reranker, mode="dense")
    sparse = await run(harness, db, "swap the battery pack", reranker, mode="sparse")
    hybrid = await run(harness, db, "swap the battery pack", reranker, mode="hybrid", top_k=2)

    assert reranker.calls == 0
    assert {dense.rerank_mode, sparse.rerank_mode, hybrid.rerank_mode} == {"off"}
    assert all(h.candidate.sparse_rank is None for h in dense.hits)
    assert all(h.candidate.dense_rank is None for h in sparse.hits)
    assert len(hybrid.hits) == 2
    assert "rerank" not in hybrid.timings_ms


async def test_postgres_overrides_stale_vector_payload(harness: Harness, db: AsyncSession) -> None:
    await indexed(harness)
    battery = await db.scalar(select(Document).where(Document.filename == "battery.txt"))
    travel = await db.scalar(select(Document).where(Document.filename == "travel.txt"))
    assert battery is not None
    assert travel is not None
    battery.active_version_id = None  # Qdrant still says active
    travel.deleted_at = datetime.now(UTC)
    await db.commit()

    result = await run(harness, db, "swap the battery pack economy fares", mode="hybrid")

    assert {hit.document.filename for hit in result.hits} == {"lost-link.txt"}


async def test_rerank_failure_falls_back_to_rrf(harness: Harness, db: AsyncSession) -> None:
    await indexed(harness)
    ctx = RequestContext(correlation_id="rerank-fails", workspace_id=harness.workspace_id)

    fused = await run(harness, db, "swap the battery pack", mode="hybrid")
    failed = await searcher(harness, FailingReranker()).search(
        db, ctx, harness.workspace_id, SearchRequest("swap the battery pack")
    )
    spans = await db.scalar(
        select(func.count())
        .select_from(StageSpan)
        .where(StageSpan.correlation_id == "rerank-fails", StageSpan.outcome == "fallback")
    )

    assert failed.rerank_mode == "rrf_fallback"
    assert ctx.degraded == {"rerank"}
    assert [h.chunk.id for h in failed.hits] == [h.chunk.id for h in fused.hits]
    assert all(h.rerank_score is None for h in failed.hits)
    assert spans == 1


async def test_rerank_timeout_falls_back(harness: Harness, db: AsyncSession) -> None:
    await indexed(harness)
    ctx = RequestContext(correlation_id="rerank-slow", workspace_id=harness.workspace_id)

    result = await searcher(harness, SlowReranker(), rerank_timeout_s=0.05).search(
        db, ctx, harness.workspace_id, SearchRequest("swap the battery pack")
    )

    assert result.rerank_mode == "rrf_fallback"
    assert result.hits


async def test_document_filter_and_empty_workspace(harness: Harness, db: AsyncSession) -> None:
    empty = await run(harness, db, "battery")
    await indexed(harness)
    lost_link = await db.scalar(select(Document.id).where(Document.filename == "lost-link.txt"))
    assert lost_link is not None

    narrowed = await run(harness, db, "swap the battery pack", document_ids=(lost_link,))

    assert empty.hits == []
    assert {hit.document.id for hit in narrowed.hits} == {lost_link}
