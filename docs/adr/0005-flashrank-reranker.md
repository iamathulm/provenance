# ADR-0005: FlashRank cross-encoder instead of a hosted reranker

- **Status:** Accepted
- **Date:** 2026-11-27
- **Deviation from PRD:** the PRD names Voyage for reranking; that was a carry-over from an earlier
  project and conflicts with the zero-cost constraint.

## Context

Reranking needs to run on every search, offline in CI, and without an API key or quota. It must
fail safely (FR-05, NFR-05).

## Decision

Use FlashRank with `ms-marco-MiniLM-L-12-v2` (ONNX, ~33 MB, CPU) behind a `Reranker` protocol.
The top 20 authorized fused candidates are reranked with a 3 s timeout; on any error or timeout
the pipeline keeps the RRF order, reports `rerank_mode = "rrf_fallback"` and marks the request
degraded.

## Alternatives considered

- **Voyage / Cohere rerank APIs:** strong, but need keys, have quotas, and add a network failure
  mode to every query.
- **`ms-marco-TinyBERT-L-2-v2`:** about 20 times faster on a laptop CPU (≈ 3 ms vs 65 ms per
  passage) but weaker; kept as a configuration option (`RERANKER_MODEL`) if latency matters more.
- **`bge-reranker-base`:** better quality, but ~1 GB and seconds per query on CPU.

## Consequences

- Reranking 20 passages costs about 1.3 s on the development laptop; the evaluation report records
  p50/p95 search latency per mode so the trade-off is measured, not assumed.
- Models download on first use and are cached; the Docker image bakes them in (P7).
