# ADR-0001: Own typed pipeline core instead of a RAG framework

- **Status:** Accepted
- **Date:** 2026-11-26

## Context

The system needs ingestion, hybrid retrieval, reranking, a structured-data (SQL) path, grounded
generation with citation verification, guardrails, telemetry and evaluation. Each stage must be
observable, independently testable, and degrade predictably (for example, reranker failure falls
back to RRF with a visible label). The runtime image must stay small, and the free-tier LLM
budget means each answer should cost at most one LLM call by default.

## Decision

Build a small, typed orchestration core in Python: a `Stage[In, Out]` protocol and a `Pipeline`
that runs stages in order, opens a trace span and a telemetry row per stage, enforces a request
budget, and applies each stage's fallback policy. Use focused libraries only where they earn
their place: FastEmbed (embeddings), FlashRank (reranking), Qdrant client, DuckDB + sqlglot
(structured path), RAGAS (offline evaluation only).

## Alternatives considered

- **LangChain / LlamaIndex:** fastest to start, but heavy dependency trees, implicit behavior
  that makes citation verification and per-stage fallbacks harder to control and test, and code
  that reviewers tend to read as framework glue.
- **LangGraph-style agent graph:** flexible routing, but multiplies LLM calls per question,
  which conflicts with free-tier rate limits and makes evaluation less stable.

## Consequences

- More code to write, but every stage is visible, unit-tested and explainable.
- Small runtime dependency set and image size.
- Routing is rule-based and deterministic; no hidden LLM calls in the request path.
