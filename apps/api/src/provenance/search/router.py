"""Search Explorer: hybrid search with every rank, score, stage timing and the routing decision."""

import uuid

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from provenance.api.dependencies import AppSettings
from provenance.auth.dependencies import CurrentUser
from provenance.core.context import RequestContext, correlation_id_var
from provenance.db.engine import DbSession
from provenance.documents.router import AnchorOut, anchor_out
from provenance.retrieval.router import RouteKind, route_query
from provenance.retrieval.search import RerankMode, Searcher, SearchMode, SearchRequest
from provenance.structured.catalog import load_catalog
from provenance.workspaces.dependencies import OwnedWorkspace

router = APIRouter(prefix="/workspaces/{workspace_id}/search", tags=["search"])


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    mode: SearchMode = "hybrid_rerank"
    top_k: int = Field(default=8, ge=1, le=20)
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class ScoresOut(BaseModel):
    dense_rank: int | None
    dense_score: float | None
    sparse_rank: int | None
    sparse_score: float | None
    fused_score: float
    rerank_score: float | None


class HitOut(BaseModel):
    rank: int
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    version_id: uuid.UUID
    document_title: str
    filename: str
    anchor: AnchorOut
    text: str
    scores: ScoresOut


class RouteOut(BaseModel):
    kind: RouteKind
    reasons: list[str]


class SearchOut(BaseModel):
    mode: SearchMode
    rerank_mode: RerankMode
    degraded: list[str]
    route: RouteOut
    timings_ms: dict[str, float]
    hits: list[HitOut]


@router.post("")
async def search(
    body: SearchIn,
    request: Request,
    workspace: OwnedWorkspace,
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
) -> SearchOut:
    state = request.app.state
    searcher = Searcher(
        state.embedder, state.chunk_index, state.reranker, state.telemetry, settings
    )
    ctx = RequestContext(correlation_id_var.get(), user_id=user.id, workspace_id=workspace.id)
    result = await searcher.search(
        db,
        ctx,
        workspace.id,
        SearchRequest(body.query, body.mode, body.top_k, tuple(body.document_ids)),
    )
    has_tables = bool(await load_catalog(db, workspace.id))
    route = route_query(body.query, result.ranked_chunks, has_tables)
    return SearchOut(
        mode=result.mode,
        rerank_mode=result.rerank_mode,
        degraded=sorted(ctx.degraded),
        route=RouteOut(kind=route.kind, reasons=route.reasons),
        timings_ms=result.timings_ms,
        hits=[
            HitOut(
                rank=hit.rank,
                chunk_id=hit.chunk.id,
                document_id=hit.document.id,
                version_id=hit.chunk.version_id,
                document_title=hit.document.title,
                filename=hit.document.filename,
                anchor=anchor_out(hit.chunk),
                text=hit.chunk.text,
                scores=ScoresOut(
                    dense_rank=hit.candidate.dense_rank,
                    dense_score=hit.candidate.dense_score,
                    sparse_rank=hit.candidate.sparse_rank,
                    sparse_score=hit.candidate.sparse_score,
                    fused_score=hit.candidate.fused_score,
                    rerank_score=hit.rerank_score,
                ),
            )
            for hit in result.hits
        ],
    )
