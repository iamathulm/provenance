# Progress Log

Handoff notes per phase: what was done, what is next, gotchas.

## P0 — Bootstrap

**Done:** repo + CI (`api`, `web`, `design`), uv workspace with FastAPI app factory and validated
settings, Next.js 16 web app with design tokens/fonts/shadcn/React Bits registry, DESIGN.md,
Postgres + Qdrant dev containers, pre-commit, templates, ADR-0000/0001.

**Gotchas for later phases:**
- Color naming: `brand` (#EA2804) is the bright accent for the hero band and non-text accents only;
  `primary` (#C01F00) is the WCAG-safe CTA/link fill and what shadcn's `bg-primary` uses.
- shadcn: run `npx shadcn add` from `apps/web` (the shadcn MCP server reads the repo-root
  `components.json`, which does not exist). React Bits items resolve as `@react-bits/<Name>-TS-TW`.
- P6: input borders use `hairline` (rgba .12), which is below 3:1 non-text contrast — use
  `hairline-strong` or another visible boundary for inputs (WCAG 1.4.11).
- Font role variables (`--font-display/sans/mono`) live in `globals.css`; spacing tokens are
  `--spacing-*` (Tailwind v4 namespace).
- Starlette's TestClient warns that `httpx` is deprecated in favor of `httpx2`; the warning is
  filtered in `pyproject.toml` until `httpx2` is verified.
- `@google/design.md lint` waits on stdin when it is not closed — always run with `< /dev/null`.
- Next.js 16 changed APIs: read `apps/web/node_modules/next/dist/docs/` before writing web code.
- Run commands from the repo root (`.env` is resolved relative to the working directory).

## P1 — Platform core

**Done:** async SQLAlchemy + Alembic (4 migrations: auth, workspaces, stored files, telemetry);
accounts with argon2id and server-side sessions (12 h absolute / 2 h idle, hashed tokens),
login throttling, origin checks, demo sign-in; private workspaces behind `require_workspace`
(foreign IDs → 404); Postgres file storage with user-bound signed links; error model with
correlation IDs; structlog JSON logs with regex PII redaction; typed `Stage`/`Pipeline` core;
`request_logs` and `stage_spans` telemetry; OpenAPI-driven tenant isolation suite;
`provenance migrate` / `provenance seed-demo` CLI. CI runs tests on Postgres and checks that
migrations match the models.

**Gotchas for later phases:**
- Every new workspace-scoped route must depend on `OwnedWorkspace`; new path/query parameters
  must be added to `KNOWN_PARAMETERS` in `tests/isolation/test_route_isolation.py`.
- Register each new models module in `provenance/db/models.py` (`MODEL_MODULES`), then
  `uv run alembic -c apps/api/alembic.ini revision --autogenerate -m "<name>" --rev-id 000N`
  and delete Alembic's `# ###` comments.
- Local DB URLs use `127.0.0.1` (on this machine `localhost` resolves to IPv6 and hangs).
- psycopg async needs a selector event loop on Windows: tests use the
  `pytest_asyncio_loop_factories` hook, the CLI passes `loop_factory` to `asyncio.run`.
- Workspace `profile` is validated by a `Literal` today; P2 replaces it with the profiles loaded
  from `profiles/*.yaml` so a new domain needs no code change.
- Telemetry rows must never hold raw text: store IDs, timings, outcomes and error classes only.
- P8: set `TRUSTED_PROXIES` to the web proxy's egress address(es) so login throttling keys on
  the real client IP (otherwise every user shares the proxy's budget). `demo-login` is not
  throttled; revisit if the cloud demo sees abuse.
- Writes use `DbSession` (FastAPI dependency `scope="function"`), which commits before the
  response is sent — keep using it rather than opening ad-hoc sessions in routes.

## P2 — Ingestion + corpora

**Done:** domain profiles as YAML (`profiles/`), content-based upload validation, parsers for
PDF/DOCX/PPTX/TXT/CSV/XLSX with page/slide/section/row anchors, profile-driven chunking, local
FastEmbed dense + BM25 embeddings, Qdrant chunk index, Postgres job queue + worker
(`provenance worker`), document API (upload, list, detail, replace, retry, delete + purge, chunk
preview), profile-change reindexing, Kestrel Ridge company corpus (21 files) and 8 CC BY/CC0
research papers, `provenance seed-demo --with-corpora`.

**Measured (local, Windows laptop CPU, real models):** 29 documents → 311 chunks over 475
pages/slides/sections/rows, indexed in ~63 s end to end (first run includes model loading).
Formal NFR-03 report is P7.

**Gotchas for later phases:**
- Retrieval must trust Postgres (`documents.active_version_id`, `deleted_at`) and use the Qdrant
  `active` payload only as a pre-filter; activation flips Qdrant first, then Postgres.
- Chunk text is cleaned of control characters in `chunking.clean`; any new text path into
  Postgres must do the same.
- Table data for the SQL path is in `version_tables` → Parquet in `stored_files`.
- Speaker notes are never indexed; the Q3 deck notes contain a "Peregrine Aero" line that must
  never appear in answers (useful negative test in P4).
- `vendor-faq.txt` contains the prompt-injection paragraph for P4's context guard.
- FastEmbed models cache in `.cache/fastembed` (~65 MB); CI caches the same directory.
- The research PDFs are fetched (not committed); run `provenance fetch-research` before seeding.
- Indexing, activation, delete and purge serialize on `documents.locking.lock_document`
  (`SELECT … FOR UPDATE`). Anything new that changes which version is live must take it too.
- Table anchors are real sheet rows / CSV file lines (header = row 1), not data-row positions.
- Jobs: an expired lease is reclaimed only while attempts remain; `expire_exhausted` fails the
  rest. Workers act on a job only while `jobs.owns(job, worker_id)`.

## P3 — Retrieval + structured data

**Done:** query embeddings and workspace/active-filtered Qdrant branch searches; client-side RRF
(k = 60); FlashRank reranker with labelled RRF fallback; Postgres authorization re-check before
reranking; `POST /v1/workspaces/{id}/search` (Search Explorer diagnostics + route); `_row` column
in table Parquet; sqlglot SQL guard; workspace-scoped DuckDB engine; `GET/POST
/v1/workspaces/{id}/tables[/query]`; rule-based docs/table/both router; golden sets
(`eval/golden/`, 66 company + 52 research items); `provenance eval` with ablations, bootstrap CIs,
JSON/Markdown reports (`eval/reports/`) and the `eval/thresholds.yaml` gate in the CI `eval` job.

**Measured (held-out test split, `eval/reports/retrieval-test.md`):** company hybrid_rerank
recall@5 0.96, MRR@10 0.85 (meets NFR-01 targets); research recall@5 0.75, MRR@10 0.57 (misses
0.80 / 0.65; misses are mostly multi-hop items needing two papers in the top 5). Reranking
(FlashRank L-12, 20 candidates, 256 tokens) costs ~1.1 s per query on the laptop CPU and helps
MRR on research but not company. Router accuracy on company is ~0.67. Tuning so far: BGE query
instruction, research chunks 450 → 220 words, NFKC text cleaning; done on `dev` only.

**Gotchas for later phases:**
- P4/P5 candidates for research quality: query decomposition for multi-hop questions (counts
  against the LLM call budget) and a better router; re-run `provenance eval --split dev` first.
- `eval/thresholds.yaml` holds regression floors under the committed baseline, not targets.
- Build a `Searcher` per request from `app.state` (`embedder`, `chunk_index`, `reranker`,
  `telemetry`); tests swap those for fakes in the `harness` fixture.
- Search hits are already authorized; P4 citations may only reference chunks from a search result.
- `structured.engine.run_query` is the only way to run SQL. Row citations come back only when
  the query reads one table and selects `_row`; P4's SQL prompt must ask for `_row`.
- The guard rejects functions sqlglot does not know (`exp.Anonymous`); allow-list DuckDB
  functions there if generated SQL needs them.
- Indexes built before P3 lack `_row` and NFKC-cleaned text (and research used 450-word
  chunks); rebuild old local data (truncate + `seed-demo --with-corpora`).
- Gold labels are evidence phrases; `provenance eval` fails fast if any phrase is missing from
  the index (`GoldMissingError`). Tune on `dev`, report and gate on `test`.
- First search after start loads FastEmbed + FlashRank from disk; the embed stage timeout is
  60 s for that reason. P7 should warm both at startup.

## P4 — Generation, grounding, guardrails

**Done:**
- **Models and calls:** Groq over httpx with streaming and typed failures; a free-tier token limiter with per-model failover; cassette record and replay.
- **Grounding:** versioned prompts (`prompts/`); `<source>` packing; a citation verifier (FlashRank support plus numeric fidelity, abstains when nothing is supported).
- **Guardrails:** local input, context and output guards, including the poisoned vendor FAQ quarantine. The answer streams one checked sentence at a time.
- **Answer pipeline:** one model call per document answer, two per table answer; SQL errors degrade to a documents-only answer.
- **Chat API:** conversations with SSE chat, and `GET /sources/{chunk_id}` returning 410 once a source is revoked.
- **Telemetry:** `provider_calls` and `guardrail_events` tables.
- **Docs:** ADR-0007 and ADR-0008, and a draft `docs/budget.md`.

**Measured (live, Groq free tier, laptop):**
- Document and table answers are correct and cited. Time to first visible text is 1.4–3.2 s; the table route makes 2 calls.
- The poisoned FAQ is quarantined, and the speaker-note question (Peregrine Aero) abstains.
- The relevance floor of 0.05 lets half of the unanswerable golden questions skip the model entirely.
- **Known gap:** the verifier scores relevance, not entailment. A fluent wrong gpt-oss answer about how Ragas measures answer relevance passed. P5's RAGAS faithfulness measures this.

**Gotchas for later phases:**
- **Building an `Answerer`:** build it per request from `app.state` (`llm`, `prompts`, `embedder`, `chunk_index`, `reranker`, `telemetry`). Tests swap `app.state.llm` for an `LLMClient` around `tests/generation/fakes.ScriptedProvider`.
- **SSE answers:** they run in their own DB session, because the request session closes before streaming starts. After a rollback, don't touch ORM attributes; use plain ids.
- **Cassettes:**
  - They are keyed by the full request body. Any change to a prompt, the model options or the sources invalidates them.
  - Re-record with `RECORD_CASSETTES=1` and a key in `.env`.
  - Never put the key in `.env.example`; gitleaks blocks the commit.
- **Free tier:** about 2 answers per minute per model, about 4 with the fallback. P7 load tests must report Groq throttling separately.
- **gpt-oss quirks:** it emits ` ` spaces and drops final periods (the verifier NFKC-normalizes). Its reasoning needs 512 tokens of completion headroom.

## P5: Observability, evaluation and prompt optimization

**Done:**
- **Observability:**
  - `GET /metrics` (Prometheus, content-free labels) and OpenTelemetry spans for every stage, exported only when `OTEL_EXPORTER_OTLP_ENDPOINT` is set.
  - Answer timings (time to first visible text, total latency) and per-user feedback.
  - A response cache keyed by question, history, prompt, models and corpus version.
  - Workspace analytics, plus the operator overview for `OPERATOR_EMAILS`.
- **Evaluation:**
  - `provenance eval --suite answers` (our metrics plus RAGAS faithfulness and answer relevancy, with a Gemini judge) and `--suite guardrails` (local rules against Prompt Guard).
  - `provenance optimize` (3 prompt variants, scored on dev, decided on test).
  - `eval.yml` runs manually or weekly; ADR-0009 records the design.

**Measured (10 items per domain and split, Gemini judge, `eval/reports/answers-*.md`):**

| Metric | Result |
|---|---|
| Faithfulness | 0.70–1.00 |
| Answer relevancy | 0.80–0.97 |
| Citation precision | 1.00 |
| Abstention recall | 1.00 |
| Injection block rate | 1.00 |
| False abstentions | 0–0.2 |

- **Guardrails:** the local rules score 27/27 with 0 false positives, but that is in-sample. Prompt Guard scores 18/27 with 0 false positives.

**Gotchas for later phases:**
- **One answer model in evaluation:** `evaluation.runner.eval_settings` pins evaluation to the first answer model. Failover made scores depend on quota timing, and so did the cassette keys, since they include the model.
- **Cassettes:**
  - `eval/cassettes/answers` and `eval/cassettes/prompt_guard` are committed, so reruns are free.
  - Changing a prompt, the model options or the retrieval output re-records.
  - The judge cache in `.cache/ragas` is not committed; `eval.yml` caches it between runs.
- **RAGAS:** lives in the `eval` dependency group (`uv sync --group eval`). CI's default sync and the runtime image don't install it, and mypy ignores its imports when it is absent.
- **Gemini:** evaluation-only (free-tier data terms). Never wire it into the request path.
- **P6 UI wiring:**
  - Show `ttft_ms` and `latency_ms` from messages.
  - The cache notice is `conversations.cache.CACHE_NOTICE`.
  - Analytics and operator payloads are plain dicts, so type them in the client from OpenAPI.
- **P8 `/metrics`:** it's public; decide in P8 whether the cloud deploy exposes it.
