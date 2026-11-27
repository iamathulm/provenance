"""Hybrid search: embed query → dense + BM25 branches → RRF → Postgres authorization → rerank.

Qdrant's `active` payload is only a pre-filter. Postgres is the authority: a chunk survives only if
its document is in the caller's workspace, not deleted, and its version is the document's active
version. Authorization runs before reranking so the reranker never sees unauthorized text.

Reranking falls back to fusion order on error or timeout; the result says so (`rrf_fallback`) and
the request is marked degraded. Ablation modes (`dense`, `sparse`, `hybrid`) skip stages.
"""

import asyncio
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Literal, override

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.core.config import Settings
from provenance.core.context import RequestContext
from provenance.core.pipeline import Pipeline, SpanRecorder, Stage
from provenance.documents.models import Chunk, Document
from provenance.retrieval.embeddings import Embedder, SparseEmbedding
from provenance.retrieval.fusion import rrf
from provenance.retrieval.index import ChunkIndex, ScoredPoint
from provenance.retrieval.rerank import Reranker

SearchMode = Literal["dense", "sparse", "hybrid", "hybrid_rerank"]
RerankMode = Literal["flashrank", "rrf_fallback", "off"]
SEARCH_MODES: tuple[SearchMode, ...] = ("dense", "sparse", "hybrid", "hybrid_rerank")


@dataclass(frozen=True)
class SearchRequest:
    query: str
    mode: SearchMode = "hybrid_rerank"
    top_k: int = 8
    document_ids: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True)
class Candidate:
    chunk_id: uuid.UUID
    fused_score: float
    dense_rank: int | None = None
    dense_score: float | None = None
    sparse_rank: int | None = None
    sparse_score: float | None = None


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    document: Document
    rank: int
    candidate: Candidate
    rerank_score: float | None


@dataclass
class SearchResult:
    hits: list[Hit]
    ranked_chunks: list[Chunk]  # every authorized candidate in final order, for routing
    mode: SearchMode
    rerank_mode: RerankMode
    timings_ms: dict[str, float]


@dataclass
class _Work:
    db: AsyncSession
    workspace_id: uuid.UUID
    request: SearchRequest
    dense: list[float] | None = None
    sparse: SparseEmbedding | None = None
    candidates: list[Candidate] = field(default_factory=list)
    authorized: list[tuple[Candidate, Chunk, Document]] = field(default_factory=list)
    reranked: list[tuple[Candidate, Chunk, Document, float | None]] = field(default_factory=list)
    rerank_mode: RerankMode = "off"


def _uses_dense(mode: SearchMode) -> bool:
    return mode != "sparse"


def _uses_sparse(mode: SearchMode) -> bool:
    return mode != "dense"


class EmbedQueryStage(Stage[_Work, _Work]):
    name = "embed_query"
    timeout_s = 60.0  # the first call loads the models from disk

    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder

    @override
    async def run(self, ctx: RequestContext, data: _Work) -> _Work:
        mode, query = data.request.mode, data.request.query
        if _uses_dense(mode):
            data.dense = await asyncio.to_thread(self._embedder.embed_query_dense, query)
        if _uses_sparse(mode):
            data.sparse = await asyncio.to_thread(self._embedder.embed_query_sparse, query)
        return data


class RetrieveStage(Stage[_Work, _Work]):
    name = "retrieve"
    timeout_s = 10.0

    def __init__(self, index: ChunkIndex, limit: int) -> None:
        self._index = index
        self._limit = limit

    @override
    async def run(self, ctx: RequestContext, data: _Work) -> _Work:
        documents = data.request.document_ids or None
        dense_hits, sparse_hits = await asyncio.gather(
            self._index.search_dense(data.workspace_id, data.dense, self._limit, documents)
            if data.dense is not None
            else _no_hits(),
            self._index.search_sparse(data.workspace_id, data.sparse, self._limit, documents)
            if data.sparse is not None
            else _no_hits(),
        )
        data.candidates = _fuse(dense_hits, sparse_hits)
        return data


async def _no_hits() -> list[ScoredPoint]:
    return []


def _fuse(dense: list[ScoredPoint], sparse: list[ScoredPoint]) -> list[Candidate]:
    dense_at = {hit.chunk_id: (rank, hit.score) for rank, hit in enumerate(dense, start=1)}
    sparse_at = {hit.chunk_id: (rank, hit.score) for rank, hit in enumerate(sparse, start=1)}
    rankings = [[hit.chunk_id for hit in branch] for branch in (dense, sparse) if branch]
    candidates = []
    for chunk_id, fused in rrf(rankings):
        dense_rank, dense_score = dense_at.get(chunk_id, (None, None))
        sparse_rank, sparse_score = sparse_at.get(chunk_id, (None, None))
        candidates.append(
            Candidate(chunk_id, fused, dense_rank, dense_score, sparse_rank, sparse_score)
        )
    return candidates


class AuthorizeStage(Stage[_Work, _Work]):
    name = "authorize"
    timeout_s = 10.0

    @override
    async def run(self, ctx: RequestContext, data: _Work) -> _Work:
        if not data.candidates:
            return data
        rows = await data.db.execute(
            select(Chunk, Document)
            .join(Document, Document.id == Chunk.document_id)
            .where(
                Chunk.id.in_([c.chunk_id for c in data.candidates]),
                Chunk.workspace_id == data.workspace_id,
                Document.workspace_id == data.workspace_id,
                Document.deleted_at.is_(None),
                Document.active_version_id == Chunk.version_id,
            )
        )
        allowed = {chunk.id: (chunk, document) for chunk, document in rows}
        data.authorized = [
            (candidate, *allowed[candidate.chunk_id])
            for candidate in data.candidates
            if candidate.chunk_id in allowed
        ]
        return data


class RerankStage(Stage[_Work, _Work]):
    """Cross-encoder rerank of the top fused candidates; falls back to fusion order."""

    name = "rerank"
    # One shared CPU worker: a timed-out rerank keeps running in its thread, so it must not hold
    # the default pool that embedding and SQL use. Calls still waiting are cancelled on timeout.
    _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rerank")

    def __init__(self, reranker: Reranker, candidates: int, timeout_s: float) -> None:
        self._reranker = reranker
        self._candidates = candidates
        self.timeout_s = timeout_s

    @override
    async def run(self, ctx: RequestContext, data: _Work) -> _Work:
        pool = data.authorized[: self._candidates]
        scores = await asyncio.get_running_loop().run_in_executor(
            self._executor,
            self._reranker.score,
            data.request.query,
            [chunk.text for _, chunk, _ in pool],
        )
        ranked = sorted(zip(pool, scores, strict=True), key=lambda pair: -pair[1])
        data.reranked = [(c, chunk, doc, score) for (c, chunk, doc), score in ranked]
        data.rerank_mode = "flashrank"
        return data

    @override
    async def fallback(self, ctx: RequestContext, data: _Work, error: Exception) -> _Work:
        data.reranked = [(c, chunk, doc, None) for c, chunk, doc in data.authorized]
        data.rerank_mode = "rrf_fallback"
        return data


class Searcher:
    def __init__(
        self,
        embedder: Embedder,
        index: ChunkIndex,
        reranker: Reranker,
        recorder: SpanRecorder,
        settings: Settings,
    ) -> None:
        self._embed = EmbedQueryStage(embedder)
        self._retrieve = RetrieveStage(index, settings.search_candidates)
        self._authorize = AuthorizeStage()
        self._rerank = RerankStage(reranker, settings.rerank_candidates, settings.rerank_timeout_s)
        self._pipeline = Pipeline(recorder)

    async def search(
        self,
        db: AsyncSession,
        ctx: RequestContext,
        workspace_id: uuid.UUID,
        request: SearchRequest,
    ) -> SearchResult:
        work = _Work(db, workspace_id, request)
        timings: dict[str, float] = {}
        stages: list[Stage[_Work, _Work]] = [self._embed, self._retrieve, self._authorize]
        if request.mode == "hybrid_rerank":
            stages.append(self._rerank)
        for stage in stages:
            started = time.perf_counter()
            work = await self._pipeline.run_stage(ctx, stage, work)
            timings[stage.name] = round((time.perf_counter() - started) * 1000, 1)
        ordered = work.reranked or [(c, chunk, doc, None) for c, chunk, doc in work.authorized]
        hits = [
            Hit(chunk, document, rank, candidate, score)
            for rank, (candidate, chunk, document, score) in enumerate(
                ordered[: request.top_k], start=1
            )
        ]
        ranked = [chunk for _, chunk, _, _ in ordered]
        return SearchResult(hits, ranked, request.mode, work.rerank_mode, timings)
