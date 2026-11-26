# Provenance — Design & Build Plan (v4: speed + simplification pass)

## Context

Joining/capstone project proving readiness for an AI engineering role. Brief: *enterprise GenAI knowledge assistant — ingest structured + unstructured docs, embedding-based knowledge repository, RAG pipeline, API + lightweight app, with citation grounding, prompt optimization, automated evaluation, guardrails, observability.* Authoritative inputs in `references/`:
- `PRD.MD` — FR-01..FR-10, NFR-01..NFR-10, Definition of Done (two domains, isolation, failure-injection, load, a11y, CI/CD, README runbook, quota/cost accounting).
- `DESIGN_BRIEF.MD` — screens, flows, states, component mapping, responsive + WCAG 2.2 AA rules.
- `GETDESIGN.MD` — base design system (editorial: cream canvas, one orange stamp per viewport, pill controls, dark code wells, three-family type).

Deliverables: public GitHub repo (real CI/CD, phase-wise PRs) + professional demo video. Reviewer = industry specialist; runs locally **or** opens cloud URL. Folder is greenfield (only `references/`).

### Decisions (with user)
- **LLM:** free cloud API — Groq only (Gemini failover cut in v4).
- **Reranker:** FlashRank (local ONNX). PRD's Voyage mention is an accidental carryover → removed; ADR records deviation.
- **Structured data:** DuckDB query engine (text-to-SQL, guarded).
- **Evaluation:** RAGAS + own retrieval/citation/abstention/SQL/guardrail metrics.
- **Frontend:** Next.js + shadcn/ui, built with `design-taste-frontend` skill + React Bits via shadcn MCP; GETDESIGN/DESIGN_BRIEF govern look.
- **Python env:** `uv` everywhere (workspace, lockfile, dependency groups, `uv run`, Docker builds).
- **Approach A:** own typed pipeline + orchestrator, targeted libs only. No LangChain/LangGraph in runtime.
- **Demo data:** two domains — synthetic company KB + open-licensed research papers.
- **Section 8 targets:** missing from PRD → proposed below.
- **Cloud (no card):** Vercel (web) · Hugging Face Spaces Docker (API + worker) · Neon Postgres (metadata, telemetry, **and file storage**) · Qdrant Cloud free.
- **Local:** Docker Compose (no Kubernetes).
- **Timeline:** ~14 days, 10 phases. Attribution lines kept on commits/PRs. User reviews + merges every PR.

### Claude's calls (correct if wrong)
- **Embeddings local:** FastEmbed `bge-small-en-v1.5` dense + `Qdrant/bm25` sparse, baked into image — no quota, ingestion never blocked.
- **File storage:** Postgres `files` table everywhere (local + Neon) — one code path. Holds originals + DuckDB Parquet tables. Access via short-lived HMAC-signed links + session + workspace check. 10 MB/file cap.
- **Auth:** own email + password (argon2id), opaque server sessions in Postgres, httpOnly SameSite cookies; web proxies `/api/*` to backend so cookies stay first-party on Vercel. GitHub OAuth = stretch.
- **Job queue:** Postgres (`SELECT … FOR UPDATE SKIP LOCKED`, leases + heartbeat) — no Redis, survives restarts.
- **React Bits vs brief:** brief wins ("zero ambient animation, no glowing AI motifs"). React Bits only for landing hero entrance, metric count-ups, drawer/disclosure transitions — all `prefers-reduced-motion` safe.
- **No-key mode:** app boots, ingests, Search Explorer works; chat shows "Add GROQ_API_KEY" notice — never crashes.
- **No dead code:** ruff + `vulture` (Python) and `knip` (TS) gate CI; mypy/tsc strict.

### Speed + reviewer-experience rules (v4)
- **LLM call budget:** ≤ 1 Groq call per doc answer, ≤ 2 for table answers (SQL + answer). Guardrails, router, citation checks run locally (ms). Query rewrite off by default; enabled per profile only if eval shows gain.
- **Answer model chosen for rate-limit headroom** (tokens/min, requests/day) on P4 day, not just quality; token budget per answer capped (~2.5k context). Target TTFT ≈ 1–2 s warm, no 429s in normal reviewer use.
- **Demo snapshot:** both demo workspaces ship as pre-built index snapshot (Qdrant snapshot + Postgres seed dump, versioned with corpus hash). First boot restores in seconds — no CPU re-embedding. App usable ≈ 30 s after containers start. Rebuild via `uv run provenance seed --rebuild`.
- **One-click demo sign-in:** "Continue as demo user" on sign-in screen when `DEMO_MODE=true` (local + cloud demo); regular sign-in still works.
- **Only port 3000 exposed to host.** Postgres, Qdrant, API on internal compose network → no clashes with reviewer's existing services.
- **Quickstart preflight:** checks Docker running, port 3000 free, Groq key valid; each failure prints exact fix. README states honest timings (image pull 2–4 min on typical connection, ready ≈ 30 s after).

### Constraints
- Zero cost; every service's free allowance, card requirement, region, data policy, limits, expiry documented (NFR-10). Anything needing a card → marked blocked, never silently paid.
- Local footprint ≤ ~5 GB; CI gate.
- Non-negotiables each a dedicated, tested module with CI evidence (sections below).

### Goals / non-goals / anti-goals
- **Goals:** full PRD workflow (auth → workspace → upload/index → search → chat → citations → analytics); two domains via config only; measurable quality + latency; reproducible eval; polished accessible UI per brief.
- **Non-goals (PRD):** shared workspaces, SSO, doc ACLs, connectors, OCR, fine-tuning, HA/SLA, pixel-perfect complex layouts.
- **Anti-goals:** cross-tenant leak via any path; citation to chunk/row not retrieved + authorized; "Indexed" before searchable; >1 orange element per viewport; crash without keys; raw content in logs/telemetry; dead code; one giant commit.

---

## Architecture

```
 Browser ── Next.js web (Vercel | :3000) ── /api/* proxy (same-origin cookies)
                          │
                 FastAPI API (:8000) ─┬─ Postgres: users, sessions, workspaces, documents,
                                      │   versions, jobs, chunks, conversations, files,
                                      │   telemetry tables, eval_runs
                                      ├─ Qdrant: dense + sparse vectors, payload
                                      │   {workspace_id, document_id, version_id, active}
                                      └─ DuckDB (in-process): per-workspace Parquet tables
        Worker (same image, `provenance worker`) ── Postgres job queue
```

### Orchestration (own, typed — no framework)
- **Core abstraction:** `Stage[In, Out]` protocol (`async run(ctx, input) -> output`), each with name, timeout, fallback policy. `Pipeline` executes stages in order, opens an OTel span + SQL `stage_spans` row per stage, enforces per-request budget, records degraded modes. `RequestContext` carries correlation ID, user, workspace, profile, prompt version.
- **Query pipeline:**
  `InputGuard → QueryRewrite → Router → {DocRetrieve → Rerank → Authorize → PackContext} ∥ {SQLGenerate → SQLGuard → SQLExecute} → Generate(stream) → CitationVerify → OutputGuard`
  - **Router:** rules only (table-card hit in retrieval, aggregate keywords, profile hints) → `docs | table | both`. No LLM call.
  - **QueryRewrite:** off by default (profile flag); skipped stage costs nothing.
  - **Fallbacks:** rerank timeout/error → RRF order (labelled `rerank_mode=rrf_fallback`); SQL failure → docs-only with notice; LLM failure/429 → actionable error, never invented answer.
- **Ingestion pipeline (job-driven):** `Validate → Parse → Chunk(profile) → Embed → Index → [TableExtract → Parquet] → Activate`, each a queued stage with bounded retry, idempotency key `(version_id, stage)`, heartbeat lease; worker restart resumes mid-pipeline.

### Stack
- **Backend:** Python 3.12, uv workspace, FastAPI, Pydantic v2 + pydantic-settings, SQLAlchemy 2 + Alembic, psycopg 3, httpx, structlog, prometheus-client, OpenTelemetry SDK.
- **Parsing:** PyMuPDF (PDF pages, encryption detection), python-docx (heading sections), python-pptx (slide anchors), UTF-8 TXT, pandas/openpyxl (CSV/XLSX). Magic-byte + size + page validation.
- **Retrieval:** Qdrant (container / Qdrant Cloud), FastEmbed dense + BM25 sparse, own RRF (dense/sparse/fused ranks exposed), **FlashRank** reranker (`ms-marco-MiniLM-L-12-v2`, ~34 MB, baked in).
- **Structured:** DuckDB + Parquet.
- **LLM:** Groq only. Answer model + SQL/judge utility model picked on P4 day by quality *and* free-tier headroom; IDs in config only.
- **Eval (uv group `eval`, not in runtime image):** RAGAS (judge = Groq via OpenAI-compatible client, embeddings = FastEmbed), numpy/scipy for bootstrap CIs.
- **Frontend:** Next.js 15 App Router (standalone), TS strict, Tailwind v4, shadcn/ui re-themed to tokens, React Bits (`@react-bits` registry via shadcn MCP), TanStack Query, `openapi-typescript`, `next/font` local: Bricolage Grotesque (display), Geist (UI/body), JetBrains Mono (code). Light/Dark/System.
- **Testing:** pytest (+ Postgres/Qdrant service containers), Playwright + `@axe-core/playwright`, Locust, vulture, knip.

### Footprint (local)
api/worker image ≤ 1.2 GB (models baked) · web ≤ 250 MB · postgres ~400 MB · qdrant ~200 MB · data + snapshot < 150 MB → **~2.2 GB**. `scripts/size_budget.py` gates CI at 5 GB.

### Repo layout
```
provenance/
  apps/api/src/provenance/
    core/ (config, errors, ids, pipeline.py, stage.py) · auth/ · workspaces/ · documents/ · storage/
    ingest/ (parsers/, chunking, jobs, worker) · retrieval/ (dense, sparse, rrf, rerank) · structured/ (duckdb, sql_guard)
    generation/ (providers/, prompts registry, citations) · guardrails/ (injection, pii, safety, context)
    observability/ (tracing, telemetry repo, metrics, logging) · analytics/ · eval/ (ragas_runner, metrics, report)
    optimize/ (prompt optimizer) · api/v1/
  apps/api/migrations/  apps/web/
  profiles/ (company.yaml, research.yaml)   prompts/ (versioned YAML)
  data/company/ (synthetic generator + outputs)   data/research/ (manifest: CC-BY arXiv IDs, license, sha256; fetch script)
  eval/ (golden/{company,research}/{dev,test}.yaml, thresholds.yaml, cassettes/, reports/)
  docs/ (architecture, runbook, threat-model, budget, data-handling, known-limits, eval-report,
         prompt-optimization, observability, adr/, requirements/, superpowers/specs/)
  DESIGN.md   scripts/   .github/   docker-compose.yml   Makefile
```

---

## Non-negotiable modules

### 1. Citation grounding
- Context packed as numbered, delimited sources `[S1…]` (doc chunks with page/slide/section/row anchors; SQL rows with table + row ids). Retrieved text wrapped as untrusted data.
- **Citation verifier:** every `[Sn]` exists, was retrieved, is authorized + active; every answer sentence has ≥ 1 citation; sentence↔source support scored by FlashRank cross-encoder; unsupported sentences flagged/removed; nothing supported → abstain: "No supporting passage found in workspace".
- Response `citations[]`: doc/version id, title, anchor, char span, excerpt, support score. UI chip `[report.pdf · p.4]` → source drawer with highlighted span; deleted/revoked → denied.

### 2. Guardrails (`guardrails/`, every one with local fallback)
- **Input:** length + rate limits; prompt-injection detector (local regex/heuristic rules at runtime; Groq-hosted Prompt Guard used only in eval as comparison, never in request path); **regex PII redactor** (email, phone, card w/ Luhn, SSN-like, IBAN, IP, API-key/token patterns) — redacts before logging/telemetry, flags in UI; off-topic via retrieval-score floor.
- **Context:** indirect-injection scan of retrieved chunks → quarantine (company corpus ships a poisoned doc to prove it).
- **SQL:** sqlglot parse → single `SELECT`, no DDL/DML/PRAGMA/ATTACH/file functions, only current workspace's tables registered, `LIMIT` enforced, timeout.
- **Output:** citation verifier; PII leak scan; local rule-based safety check (hosted Llama Guard only in eval, not request path).
- Each decision → response `guardrails[]`, span, telemetry row, metric, UI badge. Red-team items in golden sets.

### 3. Observability (`observability/`)
- **SQL telemetry (Postgres):** `query_traces` (correlation id, workspace, route, rerank mode, status, latency, TTFT, tokens, cost est = 0, prompt version, model ids), `stage_spans` (stage, duration, outcome, error class, retries), `ingest_events` (job/version stage transitions, durations, errors), `provider_calls` (provider, model, latency, tokens, status, 429s), `guardrail_events`, `feedback`. No raw question/document text — redacted hashes + lengths only (NFR-07/08).
- **Tracing:** thin OpenTelemetry spans per stage (OpenInference attributes); OTLP exporter off by default, enable via env to any collector. No Phoenix container (cut in v4).
- **Logs:** structlog JSON, correlation ID from upload → job → query, PII-redacted.
- **Metrics:** Prometheus `/metrics` (stage latency histograms, tokens, cache hits, guardrail triggers, abstain rate, rerank fallbacks, provider errors, queue depth).
- **Dashboards (in app):** Analytics (workspace: volume, job states, latency p50/p95, feedback, success/failure/degraded) and Operator (service health, heartbeats, backlog, provider error rates, quota usage vs free-tier limits) — all from SQL telemetry, charts + accessible tables.

### 4. Automated evaluation (`eval/`)
- **Datasets:** golden sets per domain (≥ 50 items each: ≥ 30 answerable incl. multi-hop + table/SQL, ≥ 10 unanswerable, ≥ 5 adversarial), split **dev / held-out test**; gold doc + anchor ids; versioned by hash.
- **RAGAS metrics:** faithfulness, answer relevancy, context precision, context recall.
- **Own metrics:** recall@5, MRR@10, nDCG@10, citation precision + sentence coverage, abstention recall + false-abstention, SQL result exact-match, guardrail block rate + false-positive rate, latency p50/p95, tokens.
- **Ablations:** dense-only, sparse-only, RRF-only, RRF+FlashRank; prompt versions.
- **Runs:** `uv run provenance eval --domain {company,research,all} [--ablation] [--split test]` → JSON + markdown report with bootstrap 95% CIs, per-category breakdown, failures listed; records git SHA, dataset/profile/prompt hashes, model ids (reproducible); stored in `eval_runs` + `eval/reports/`, shown in Operator view.
- **CI:** deterministic metrics + cassette-replayed generation every PR (gate on `thresholds.yaml`); RAGAS/LLM-judge nightly + manual via `eval.yml` (repo secret, throttled).

**Proposed targets (per domain, NFR-01):** recall@5 ≥ 0.80 · MRR@10 ≥ 0.65 · RAGAS faithfulness ≥ 0.85 · context precision ≥ 0.70 · citation precision ≥ 0.90 · sentence coverage ≥ 0.95 · abstention recall ≥ 0.85 · false-abstention ≤ 0.10 · SQL exact-match ≥ 0.80 · injection resistance 100%. Misses published with CIs, not hidden.

### 5. Prompt optimization (`optimize/` + `prompts/`)
- **Registry:** versioned YAML templates (system, answer, rewrite, router, SQL, judge); content hash stamped on every trace and eval run; profile selects variant.
- **Offline optimizer** (`uv run provenance optimize --domain …`): 4–5 handwritten variants (baseline, strict-citation, concise, few-shot, abstention-first) × few-shot example sets drawn from dev split → each scored on dev with RAGAS faithfulness + citation precision + abstention + tokens → top candidates confirmed on held-out test split (guards overfit) → winner pinned with diff + report `docs/prompt-optimization.md`. Call budget capped; results cached. LLM-generated mutations = stretch.
- **Runtime optimization:** context compression (rerank cutoff, near-duplicate removal, MMR, token budget per profile), response cache keyed by query + prompt version + corpus version, query rewrite as profile flag (off by default; on only if eval shows gain). Token savings measured in report.

### 6. RAG core / knowledge repository
- Structure-aware, profile-driven chunking (headings/pages/slides first, then token windows with overlap; tables never split mid-row).
- Hybrid retrieval: both branches filtered by workspace + active version; client RRF (k=60); FlashRank top-k; Postgres authorization re-check.
- Structured path: CSV/XLSX → Parquet per document version → DuckDB views registered per request for that workspace only; table cards (schema + description + sample rows) indexed in Qdrant so router/retrieval find tables.

---

## Requirement → proof map

| Req | How met | Proof |
|---|---|---|
| FR-01 auth + isolation | sessions; workspace dependency on every route; Qdrant filters + Postgres re-check; DuckDB per-workspace registration | **Isolation suite generated from OpenAPI route table** (every route × foreign IDs, direct + service-mediated) |
| FR-02 manage docs | upload/list/replace/delete, limits, actionable errors | invalid/encrypted/oversized fixtures |
| FR-03 provenance | page/slide/section/row anchors; low/empty → partial/failed | fixture per format |
| FR-04 reliable index | Postgres queue, real states, bounded backoff, idempotent, atomic activation, failed replace keeps prior | worker-kill + duplicate-chunk tests |
| FR-05 hybrid | filtered branches, RRF, FlashRank attempt, labelled fallback | injected rerank timeout/error |
| FR-06 answers | SSE stage + token stream, verified citations, abstain | cassette E2E |
| FR-07 sources | drawer excerpt + anchor; missing anchor labelled; revoked → denied | E2E + isolation |
| FR-08 Search Explorer | filters, ranks, dense/sparse/fused/rerank scores, mode label | API + UI tests |
| FR-09 monitor/eval | Analytics + Operator from SQL telemetry; eval command incl. both domains + RRF-only | reports |
| FR-10 deploy | Compose (web, api, worker, postgres, qdrant); CI builds; CD approved deploy; cloud smoke laptop-off | cd.yml + cron smoke |
| NFR-01 | targets above, CIs | eval report |
| NFR-02 | Locust 100 q / 5 users; p95 retrieval ≤ 3 s, TTFT ≤ 8 s; Groq throttling reported separately | load report |
| NFR-03 | 20 files ≤ 20 pages, ≥ 90% searchable < 2 min | ingest report |
| NFR-04 | TLS (cloud), server-side checks, injection tests, untrusted-context wrapping, no secrets in bundle/logs | threat-model + scans |
| NFR-05 | rerank failure → RRF; Groq/Qdrant/embed failure → actionable error; worker restart resumes | failure-injection suite |
| NFR-06 | 320/768/desktop, keyboard flows, axe no critical | Playwright + axe |
| NFR-07 | revoke immediate; purge job removes original, Parquet, chunks, vectors with retry + audit; no raw content logged | deletion + log-scan tests |
| NFR-08 | SQL telemetry + correlation IDs + dashboard (success/failure/degraded) | telemetry tests |
| NFR-09 | `/v1` API, parser/provider/storage/reranker interfaces, uv.lock + pnpm-lock, Alembic, validated config, reproducible images, profiles w/o code change | CI |
| NFR-10 | `docs/budget.md` per service, usage meter, quota → safe labelled degrade | doc + quota tests |

---

## Frontend (DESIGN_BRIEF + GETDESIGN)

- **Process:** load `design-taste-frontend` before UI work, use as finish gate; components via shadcn MCP (`@shadcn`, `@react-bits`) restyled to tokens; `DESIGN.md` (GETDESIGN + extension tokens) linted with `npx @google/design.md lint DESIGN.md` in CI.
- **Tokens:** CSS variables from brief (canvas `#f9f7f3`, bone, card, dark, deep, hairlines, ink scale, primary `#ea2804`, success/warning/error/highlight extensions, dark canvas). No hex in components.
- **Enforced rules:** one primary orange per viewport (Playwright check), pills for controls / `rounded-md|lg` cards, dark code wells for SQL/IDs/scores/diagnostics, shadows only on drawer/popover/modal, gradient only in landing hero, body weight 400, display line-height 1.0, answer measure ≤ 760px.
- **Screens:** Landing + Sign in, Workspaces, Chat (+ source drawer), Documents (+ upload review), Document detail, Search Explorer, Analytics, Workspace settings (profile + reindex warning), Account (theme), Operator health & evaluation, shared dialogs/toasts/offline banner. Every screen: empty / loading / error-degraded / success / offline.
- **A11y:** skip link, landmarks, focus trap + restore, Enter/Shift+Enter composer, polite aria-live for stage changes, icon + text status, 200% zoom reflow, reduced motion.

---

## Reviewer experience

- **Cloud (zero setup):** README link → "Continue as demo user" → two preloaded workspaces (Company KB, Research Papers). Live status badge from cd.yml cron smoke.
- **Local:**
  ```
  git clone … && cd provenance
  cp .env.example .env     # paste free GROQ_API_KEY
  docker compose up -d     # pulls GHCR images; migrate + snapshot restore automatically
  # http://localhost:3000  (only exposed port)
  ```
  `scripts/quickstart.ps1|.sh`: preflight (Docker running, port 3000 free, key valid) → compose up → health wait → open browser. `make dev` for non-Docker (uv + pnpm). Two demo users so reviewer can try cross-tenant access.
- **Expected timeline:** clone + key ≈ 1 min · image pull 2–4 min (network) · ready ≈ 30 s · first answer streams in ≈ 1–2 s.

---

## GitHub workflow

- Conventional Commits; protected `main` (required checks + review); `feat/pN-<name>` per phase; PR template (what / why / test evidence / eval delta / screenshots); merge commits keep phase history; milestone tags; CHANGELOG; attribution lines.
- pre-commit: ruff, ruff-format, mypy, eslint, prettier, gitleaks.
- **Workflows (4):**
  - `ci.yml` — lint/type, vulture + knip, pip-audit + pnpm audit, unit, integration + isolation, offline eval gate both domains, web build, DESIGN.md lint.
  - `e2e.yml` — build images, size budget, compose up → Playwright + axe at 320/768/1280; on tag also pushes amd64 images to GHCR + GitHub Release.
  - `cd.yml` — main → `production` environment approval → HF Space + Vercel → cloud smoke; plus 6-hourly cron smoke (keeps Space awake, README badge).
  - `eval.yml` — nightly/manual RAGAS + LLM-judge eval, report artifact.
  - CodeQL via GitHub default setup (repo setting, no workflow); Dependabot weekly.
- **ADRs:** own orchestrator vs LangChain/LangGraph · Postgres queue vs Redis · Postgres file storage · hybrid + client RRF · FlashRank over Voyage (PRD deviation) · DuckDB structured path + SQL guard · RAGAS + custom metrics · prompt optimizer design · auth sessions + same-origin proxy · guardrail layering · cloud hosts · domain profiles.

---

## Phases — 10 phases over 14 days

**Rhythm:** fresh session reads this plan + `docs/progress.md` → `superpowers:writing-plans` for the phase → TDD → 6–15 small commits → PR → CI green → user reviews + merges → handoff note. ≤ ~4 h/day inside a 5-hour window. **Must** always ships; **Stretch** cut first.

| Phase | Days | Must | Done when |
|---|---|---|---|
| **P0 Bootstrap** | 1 | git init; user creates repo + protection; uv workspace, FastAPI `/healthz`, validated settings; Next.js + Tailwind v4 + shadcn + `@react-bits` registry + fonts + `tokens.css` + DESIGN.md; dev compose (Postgres, Qdrant); pre-commit; `ci.yml` skeleton green; templates, LICENSE, CODEOWNERS, dependabot; references → `docs/requirements/`; design → `docs/superpowers/specs/2026-11-26-provenance-design.md`; ADR-000/001; `docs/progress.md` | CI green, tag `v0.1.0` |
| **P1 Platform core** | 2–3 | Models + Alembic; auth (argon2id, sessions, rate-limited non-enumerating login); workspaces + membership dependency; Postgres file storage + signed links; demo-mode one-click sign-in; `core/pipeline.py` + `Stage` + `RequestContext`; correlation-ID middleware; structlog + regex PII redactor; telemetry tables + repo; error model; `/v1` skeleton; route-table isolation harness; seed demo users | isolation suite green on all routes; migrations up/down clean |
| **P2 Ingestion + corpora** | 4–5 | Upload validation; parsers PDF/DOCX/PPTX/TXT/CSV/XLSX + anchors + partial/failed; domain profiles; job queue + worker (lease, heartbeat, backoff, idempotent); FastEmbed dense + BM25; Qdrant payload indexes; Parquet + table cards; atomic activation, replace, delete purge + audit, reindex; company corpus generator (incl. poisoned doc); research manifest + fetch | worker-kill resumes w/o duplicates; both corpora indexed via config only |
| **P3 Retrieval + structured** | 6 | Hybrid filtered retrieval; client RRF; FlashRank + labelled fallback; auth re-check; Search Explorer API + diagnostics; DuckDB path + sqlglot SQL guard; router; golden sets (dev/test) both domains; deterministic eval + ablations; thresholds + CI gate | ablation report per domain; gate trips on deliberate regression |
| **P4 Generation + grounding + guardrails** | 7 | Verify Groq free-tier terms + pick models by headroom → budget draft; provider protocol (Groq, Mock) + limiter + backoff; prompt registry; query pipeline end-to-end within LLM call budget; SSE chat + conversations; context packing; citation verifier + abstain; all guardrails; cassettes; quota → safe degrade | cassette E2E green both domains with no key; poisoned doc quarantined; injection suite 100% |
| **P5 Observability + eval + prompt opt** | 8 | Thin OTel spans (exporter off by default); `/metrics`; analytics + operator endpoints from SQL telemetry; feedback; RAGAS runner + own metrics + bootstrap CIs + versioned reports; `eval.yml`; prompt optimizer (handwritten variants) + report; response cache; first full eval committed | report with real numbers both domains; optimizer shows measured winner on held-out test; tag `v0.5.0` |
| **P6 Frontend** | 9–10 | Load taste skill; shell; landing + sign in; workspaces; documents + upload review + detail; chat + drawer + chips + stage indicator + feedback; Search Explorer w/ code-well diagnostics + SQL view; analytics; settings; account theme; operator + eval comparison; all 5 states; typed client | every brief flow works on local stack at 320/768/1280 |
| **P7 Quality gates + packaging** | 11–12 | Playwright E2E + one-orange check; axe + manual keyboard/contrast checklist; failure-injection suite; Locust load report; ingest perf report; threat model + injection/bundle-secret/log scans; vulture/knip zero; Dockerfiles (multi-stage, non-root, models baked, `uv sync --frozen`); full compose (only port 3000 exposed; auto-migrate + demo snapshot restore); demo snapshot build command; `e2e.yml` with size budget + GHCR release on tag; quickstart scripts with preflight; Windows fresh-clone test | clean clone → app usable ≈ 30 s after pull; first answer ≈ 1–2 s; reports in `docs/`; tag `v0.9.0` |
| **P8 Cloud + CD** | 13 | User creates Vercel, HF, Neon, Qdrant Cloud accounts (Claude verifies terms first, gives steps); final `docs/budget.md`; HF Space (API + worker, Postgres storage); Vercel + `/api` proxy (verify SSE); secrets; `cd.yml` with approval + cron smoke; seed demo workspaces (synthetic + CC-BY only) | approved deploy → smoke green with laptop off |
| **P9 Docs + demo** | 14 (+ buffer) | README (architecture, both setups, runbook, known limits, data handling, quota/cost, recovery, FR/NFR gate table w/ evidence links); architecture + observability docs; remaining ADRs; final reports; `docs/demo-script.md` + recording checklist; CHANGELOG; `v1.0.0`; user records video | all Actions green; release out; video recorded |

**Cut in v4 (not built):** Gemini failover, Phoenix container, hosted guard models in request path, LLM router fallback, filesystem storage backend, separate release/docker/security/keepalive workflows.

**Stretch / cut order if slipping:** GitHub OAuth → LLM-generated prompt mutations → arm64 images → dark-theme polish. Never cut non-negotiables or PRD gates (PRD DoD allows explicit "failed" marking over silent omission).

**Demo storyline:** problem → cloud URL + local one-command → sign in, create workspace → upload PDF/PPTX/XLSX, real stages → ask, stream, citation → drawer → table question shows generated SQL + row citations → unanswerable abstains → injection blocked + PII redacted → Search Explorer diagnostics + reranker fallback → Research workspace (same code, different profile) → analytics + operator quota → eval (RAGAS + ablation, prompt optimizer win) → CI/CD → architecture + trade-offs.

---

## Key risks
- **Groq free limits (tokens/min) vs responsiveness + load test:** ≤ 1 LLM call per doc answer, capped context, model picked for headroom, response cache, client limiter queues instead of erroring; throttling reported separately (PRD allows).
- **RAGAS judge calls on free tier:** dev-split sampling, caching, throttle; nightly not per-PR.
- **SSE via Vercel proxy:** verified P8; fallback Next route-handler streaming proxy.
- **HF Space sleep / Neon cold start:** 6-hourly cron smoke in cd.yml; cold starts reported separately.
- **Neon 0.5 GB:** 10 MB/file cap, demo corpus small; usage shown in Operator view.
- **Free-tier terms change:** verified on use day; blocked → marked, not paid.
- **Research licensing:** CC-BY/CC0 only; manifest records license.

## Verification (end-to-end)
1. CI green: pytest (unit, integration, isolation, failure-injection), web tests, Playwright E2E + axe, vulture/knip clean.
2. `uv run provenance eval --domain all --ablation --split test` meets proposed targets (or misses published) with CIs, reproducible from recorded versions.
3. Load + ingest reports meet or honestly report NFR-02/03.
4. Fresh Windows clone: quickstart → full flow; size budget ≤ 5 GB.
5. Cloud: approved deploy, smoke green, works laptop-off.
6. Manual demo-script run; README gate table complete.

## After sign-off
P0 commits this design to `docs/superpowers/specs/`; `superpowers:writing-plans` per phase; execute phase by phase.

## Left to the builder
Chunk sizes/thresholds (tuned via eval), fictional company name, specific CC-BY papers, golden-set wording, optimizer variant count, chart library, minor UI details within brief.
