# P3 Retrieval + Structured Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A signed-in user can search a workspace with hybrid retrieval (dense + BM25, fused with RRF, reranked by FlashRank with a labelled fallback) and see every rank and score; table questions can be answered by guarded, read-only DuckDB SQL over the workspace's own spreadsheets; a rule-based router picks docs / table / both; a deterministic evaluation over golden sets for both domains measures retrieval quality per ablation and gates CI.

**Architecture:** `retrieval/` gains query embeddings, Qdrant branch searches, `fusion.py` (RRF), `rerank.py` (FlashRank behind a `Reranker` protocol), `search.py` (the search pipeline as `Pipeline` stages) and `router.py`. `structured/` owns the table catalog, the sqlglot SQL guard and the DuckDB engine. `search/router.py` and `structured/router.py` expose HTTP. `provenance/evaluation/` owns golden-set loading, metrics, bootstrap CIs, reports and the threshold gate; `provenance eval` runs it.

**Tech Stack:** FlashRank 0.2 (`ms-marco-MiniLM-L-12-v2`, ONNX), DuckDB 2.0, sqlglot 30, qdrant-client 1.20, FastEmbed 0.9.

**Spec:** `docs/superpowers/specs/2026-11-26-provenance-design.md` (P3 row, Orchestration/query pipeline, RAG core, Guardrails/SQL, Automated evaluation, FR-05/08/09, NFR-01/05).

## Global Constraints

- All P0–P2 constraints hold. New workspace routes depend on `OwnedWorkspace`; no new path parameters, so the isolation suite covers them automatically.
- **Search is authorized twice:** Qdrant filters both branches on `workspace_id` and `active=true` (pre-filter only); Postgres then keeps a chunk only if its document belongs to the workspace, is not deleted, and `documents.active_version_id == chunk.version_id`. Postgres wins on any disagreement.
- **Modes:** `dense`, `sparse`, `hybrid` (RRF), `hybrid_rerank` (default). RRF `k = 60`, each branch fetches 40 candidates, the reranker sees the top 30 fused authorized candidates, results return `top_k` (1–20, default 8).
- **Rerank fallback:** reranker error or 3 s timeout → RRF order, `rerank_mode = "rrf_fallback"`, stage recorded as `fallback`, `degraded` contains `rerank`. Other modes report `rerank_mode = "off"`.
- **Diagnostics per hit:** `dense_rank/dense_score`, `sparse_rank/sparse_score` (null when the branch missed it), `fused_score`, `rerank_score` (null without rerank), final `rank`, plus stage timings in ms. No query text in logs or telemetry.
- **Tables:** every CSV/XLSX table Parquet carries a `_row` column (the spreadsheet row number the user sees). SQL names are `t_<slug>` unique per workspace (document filename stem + sheet). Only the active, non-deleted version's tables are registered, in a fresh in-memory DuckDB connection with `enable_external_access=false` and locked configuration.
- **SQL guard (sqlglot, DuckDB dialect):** exactly one statement; a query (`SELECT`/`UNION`/CTE) at the root; no DDL/DML/`PRAGMA`/`SET`/`ATTACH`/`COPY`/`INSTALL`/`LOAD`/commands; every table reference is a registered table or a CTE; no table-valued or file functions (`read_*`, `*_scan`, `glob`, `query`, …); outer `LIMIT` forced to ≤ 200; 5 s execution timeout (interrupt). Rejections are `sql_rejected` 422 with the reason.
- **Router (rules, no LLM):** `table` when the question has aggregate intent and a table chunk ranks in the top 5; `both` when only one of those holds and the workspace has tables; otherwise `docs`. Returns reasons.
- **Golden sets:** `eval/golden/{company,research}/{dev,test}.yaml`, ≥ 50 items per domain: ≥ 30 answerable (factual, multi-hop, table), ≥ 10 unanswerable, ≥ 5 adversarial. Each answerable item lists gold `{file, anchor}`; anchors are matched by page/slide number, section-path prefix, or row-range overlap.
- **Metrics:** anchor-level recall@5, MRR@10, nDCG@10 (binary relevance), document-level recall@5, router accuracy; answerable items only for ranking metrics. 95% CIs by seeded bootstrap (1000 resamples, stdlib `random`). Proposed targets recall@5 ≥ 0.80, MRR@10 ≥ 0.65 (gated on the `test` split, default mode).
- **Reproducibility:** each report records git SHA, golden-set SHA-256, profile SHA-256, model ids, mode, split and timestamp.

## Review Focus

- **Stale vector payload:** a point still marked `active` in Qdrant whose version is no longer active in Postgres is never returned — `test_postgres_overrides_stale_vector_payload` (Task 3).
- **Reranker down:** search still answers in RRF order and says so — `test_rerank_failure_falls_back_to_rrf` (Task 3).
- **Cross-tenant search:** tenant B never sees tenant A's chunks or tables, via search or SQL — `test_search_never_crosses_workspaces`, `test_sql_sees_only_own_tables` (Tasks 4, 6).
- **Hostile SQL:** `read_csv('/etc/passwd')`, `ATTACH`, `COPY … TO`, two statements, DML, CTE-shadowing tricks — all rejected before execution — `test_sql_guard_rejects` (Task 5).
- **Deleted spreadsheet:** its table disappears from the catalog at once — `test_deleted_document_tables_unavailable` (Task 6).
- **Gate:** a deliberately weak mode (`sparse`) or raised threshold fails `provenance eval --check` with exit 1 — `test_gate_trips_on_regression` (Task 9).

---

### Task 1: Query embeddings and branch searches

**Files:** modify `retrieval/embeddings.py` (protocol + FastEmbedder: `embed_query_dense(text) -> list[float]`, `embed_query_sparse(text) -> SparseEmbedding` using FastEmbed `query_embed`), `retrieval/index.py` (`search_dense`, `search_sparse`), `tests/retrieval/fakes.py`; tests `tests/retrieval/test_index.py`.

**Interfaces — Produces:**
- `ScoredPoint(chunk_id: UUID, score: float)`.
- `ChunkIndex.search_dense(workspace_id, vector, limit, document_ids=None) -> list[ScoredPoint]`, `ChunkIndex.search_sparse(workspace_id, sparse, limit, document_ids=None)`; both filter `workspace_id` + `active=true` (+ `document_id` any-of).
- [ ] Tests: other-workspace and inactive points never returned; `document_ids` narrows; sparse branch finds exact keyword.
- [ ] Commit `feat(retrieval): query embeddings and filtered branch searches`.

### Task 2: RRF and reranker

**Files:** create `retrieval/fusion.py`, `retrieval/rerank.py`; modify `core/config.py` (`reranker_model`, `flashrank_cache_dir`, `rerank_candidates=30`, `rerank_timeout_s=3.0`); tests `tests/retrieval/test_fusion.py`, `test_rerank.py`; fakes `FakeReranker`, `FailingReranker`.

**Interfaces — Produces:**
- `rrf(rankings: Sequence[Sequence[UUID]], k: int = 60) -> list[tuple[UUID, float]]` (sorted desc, ties by first appearance).
- `Reranker` protocol: `score(query: str, passages: list[str]) -> list[float]`; `FlashRanker(settings)` lazy-loads the model.
- [ ] Tests: RRF formula on a hand example, item in both lists outranks single-list items, stable ties; FlashRanker ranks a relevant passage above an irrelevant one (marked `slow`, uses cached model).
- [ ] Commit `feat(retrieval): reciprocal rank fusion and FlashRank reranker`.

### Task 3: Search pipeline with authorization

**Files:** create `retrieval/search.py`; tests `tests/retrieval/test_search.py`.

**Interfaces — Produces:**
- `SearchMode = Literal["dense", "sparse", "hybrid", "hybrid_rerank"]`; `SearchRequest(query, mode, top_k, document_ids)`.
- `Hit(chunk: Chunk, document: Document, rank, dense_rank, dense_score, sparse_rank, sparse_score, fused_score, rerank_score)`; `SearchResult(hits, mode, rerank_mode, timings_ms)`.
- `Searcher(embedder, index, reranker, recorder, settings).search(db, ctx, workspace_id, request) -> SearchResult` running stages `embed_query → retrieve → authorize → rerank` through `Pipeline` (rerank stage has the RRF fallback).
- [ ] Tests: hybrid finds keyword-only and meaning-only matches; deleted and superseded versions excluded even when Qdrant says active; rerank failure/timeout → `rrf_fallback` + degraded; modes produce their own orders; spans recorded.
- [ ] Commit `feat(retrieval): authorized hybrid search pipeline with rerank fallback`.

### Task 4: Search Explorer API

**Files:** create `search/{__init__,router}.py`; modify `api/v1.py`, `api/app.py` (embedder + reranker + searcher on `app.state`), `tests/conftest.py` (harness swaps in fakes); tests `tests/search/test_search_api.py`.

**Interfaces — Produces:** `POST /v1/workspaces/{workspace_id}/search` body `{query: 1–500 chars, mode?, top_k?, document_ids?}` → `{mode, rerank_mode, degraded, route: {kind, reasons}, timings_ms, hits: [{rank, chunk_id, document_id, version_id, document_title, filename, anchor, text, scores: {...}}]}`.
- [ ] Tests: indexed upload is found with anchor; other tenant gets 404 on the route and never sees chunks in its own search; empty workspace → empty hits; validation errors use the standard error shape.
- [ ] Commit `feat(search): Search Explorer API with rank diagnostics`.

### Task 5: SQL guard

**Files:** create `structured/{__init__,sql_guard}.py`; tests `tests/structured/test_sql_guard.py`.

**Interfaces — Produces:** `guard_sql(sql: str, allowed_tables: set[str], max_rows: int) -> str` (returns normalized SQL with enforced LIMIT) raising `SqlRejectedError(reason)`.
- [ ] Tests: allowed SELECT/CTE/UNION/aggregates/joins pass with LIMIT enforced (added, lowered, kept); rejects multiple statements, DML/DDL, PRAGMA/SET/ATTACH/COPY/INSTALL/LOAD, unknown tables, file/table functions, CTE named like a file function, unparseable SQL.
- [ ] Commit `feat(structured): sqlglot SQL guard`.

### Task 6: Table catalog, DuckDB engine and tables API

**Files:** modify `ingest/parsers/tables.py` (`_row` column); create `structured/catalog.py`, `structured/engine.py`, `structured/router.py`; modify `api/v1.py`, `core/config.py` (`sql_max_rows=200`, `sql_timeout_s=5.0`); tests `tests/structured/test_engine.py`, `test_tables_api.py`.

**Interfaces — Produces:**
- `TableEntry(sql_name, table_id, document_id, version_id, document_title, sheet, columns, row_count)`; `load_catalog(db, workspace_id) -> list[TableEntry]`.
- `run_query(db, workspace_id, sql, settings) -> QueryResult(sql, columns, rows, row_refs, truncated)`; `row_refs` = `{sql_name, row}` when `_row` is selected or derivable (single-table, non-aggregate queries add `_row` automatically).
- `GET /v1/workspaces/{id}/tables`; `POST /v1/workspaces/{id}/tables/query` `{sql}`.
- [ ] Tests: aggregate over sales sheet is exact; `_row` refs match spreadsheet rows; other tenant's tables unknown; deleted document's table gone; replaced document exposes only the new version; timeout interrupts; external access disabled even if the guard were bypassed.
- [ ] Commit `feat(structured): workspace-scoped DuckDB tables with row references`.

### Task 7: Router

**Files:** create `retrieval/router.py`; wire into search response; tests `tests/retrieval/test_router.py`.

**Interfaces — Produces:** `Route(kind: Literal["docs","table","both"], reasons: list[str])`; `route_query(question, hits, workspace_has_tables) -> Route`.
- [ ] Tests: aggregate + table hit → table; table hit only → both; aggregate only with tables → both; no tables → docs; plain question → docs.
- [ ] Commit `feat(retrieval): rule-based docs/table router`.

### Task 8: Golden sets

**Files:** create `eval/golden/company/{dev,test}.yaml`, `eval/golden/research/{dev,test}.yaml`, `provenance/evaluation/{__init__,golden}.py`; tests `tests/evaluation/test_golden.py`.

**Interfaces — Produces:** `GoldenItem(id, question, category, route, gold: list[GoldAnchor], reference)`; `GoldAnchor(file, page?, slide?, section?, rows?)`; `load_golden(domain, split) -> GoldenSet(items, sha256)`.
- [ ] Questions written from the corpus source (company YAML, research PDF text); every gold file exists in the corpus; ids unique across splits; split sizes and category minimums asserted by test.
- [ ] Commit `feat(eval): golden sets for company and research domains`.

### Task 9: Retrieval evaluation, ablations and CI gate

**Files:** create `provenance/evaluation/{metrics,retrieval,report}.py`, `eval/thresholds.yaml`, `eval/reports/` (committed reports); modify `cli.py` (`eval` command), `.github/workflows/ci.yml` (`eval` job: services, model + research-file caches, seed + index corpora, `provenance eval --split test --check`); tests `tests/evaluation/test_metrics.py`, `test_gate.py`.

**Interfaces — Produces:** `recall_at_k`, `mrr_at_k`, `ndcg_at_k`, `bootstrap_ci`; `evaluate(domain, split, mode) -> RetrievalReport`; `check_thresholds(reports, thresholds) -> list[str]` (failures); CLI `provenance eval --domain {company,research,all} --split {dev,test} [--ablation] [--check eval/thresholds.yaml] [--out eval/reports]`.
- [ ] Tests: metric values on hand examples; bootstrap CI deterministic for a seed and contains the mean; gate returns failures for a raised threshold; CLI exits 1 on failure.
- [ ] Run full ablation on both domains locally, commit JSON + markdown reports, tune only via profile/settings if targets are missed (misses reported, not hidden).
- [ ] Commit `feat(eval): deterministic retrieval evaluation with ablations and CI gate`.

### Task 10: Docs, review, PR

- [ ] ADRs `0004-hybrid-retrieval-client-rrf.md`, `0005-flashrank-reranker.md` (PRD deviation from Voyage), `0006-duckdb-sql-guard.md`; update `docs/progress.md`.
- [ ] Full suite + ruff/mypy/vulture green; code review; PR `feat/p3-retrieval` → report to user.
