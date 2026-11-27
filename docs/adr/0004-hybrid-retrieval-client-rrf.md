# ADR-0004: Hybrid retrieval with client-side RRF and a Postgres authorization re-check

- **Status:** Accepted
- **Date:** 2026-11-27

## Context

FR-05 asks for hybrid retrieval: dense and sparse, filtered to the caller's workspace and the
active version, fused, then reranked, with a labelled fallback. FR-08 (Search Explorer) asks to
show each branch's rank and score. FR-01 forbids any cross-tenant read.

## Decision

- Query Qdrant twice, once per named vector (`dense`, `bm25`), each pre-filtered on
  `workspace_id` and `active=true`, 40 candidates each.
- Fuse in the application with reciprocal rank fusion (k = 60), keeping each branch's rank and
  score on the candidate.
- Re-check every candidate in Postgres (`documents.workspace_id`, `deleted_at IS NULL`,
  `active_version_id = chunk.version_id`) before reranking. Postgres wins over the Qdrant payload.
- Expose `dense`, `sparse`, `hybrid` and `hybrid_rerank` modes for ablations.

## Alternatives considered

- **Qdrant's server-side fusion (`prefetch` + `FusionQuery.RRF`):** one round trip, but it returns
  only the fused score, so the Search Explorer could not show per-branch ranks.
- **Trusting the Qdrant `active` payload alone:** payload updates happen after the database
  commit during version activation; a crash between the two would leave a stale point searchable.
- **Weighted score sum:** dense cosine and BM25 scores are on unrelated scales; RRF needs no
  calibration.

## Consequences

- Two Qdrant queries per search (run concurrently) and one indexed Postgres lookup.
- A stale or inconsistent payload can only hide results, never leak them.
- The ablation report compares all four modes on the same golden sets.
