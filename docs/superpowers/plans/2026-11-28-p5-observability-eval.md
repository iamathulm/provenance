# P5 Observability, Evaluation and Prompt Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the system measurable end to end. That means Prometheus metrics and OpenTelemetry spans for every stage; analytics and operator data from the SQL telemetry; answer feedback; a response cache; and an answer-quality evaluation (RAGAS faithfulness and answer relevancy plus our own grounding metrics, with bootstrap CIs) for both domains. It also adds a guardrail comparison against Groq-hosted Prompt Guard, and a prompt optimizer that picks a measured winner on the held-out split.

**Architecture:**
- `observability/` gains `metrics.py` (Prometheus registry) and `tracing.py` (OTel). `TelemetryRecorder` is the one place that writes SQL rows and updates metrics.
- `analytics/` serves workspace analytics and the operator view.
- `conversations/` gains feedback, timings and the response cache.
- `evaluation/` gains `answers.py` (runs the real pipeline over golden items, scores them and summarizes per domain), `ragas_judge.py` (the only module that imports RAGAS), `guardrail_eval.py` and `optimize.py`.
- Every LLM call in evaluation goes through cassettes (`eval/cassettes/answers/`, recorded on first run, replayed after). The RAGAS judge uses RAGAS's disk cache in `.cache/ragas`, so a rerun costs nothing.

**Tech Stack:**
- `prometheus-client` 0.26 and `opentelemetry-sdk` with `opentelemetry-exporter-otlp-proto-http` 1.45 (runtime).
- `ragas` 0.4.4 with `openai` `AsyncOpenAI` pointed at Groq (eval dependency group only, never in the runtime image).

**Spec:** `docs/superpowers/specs/2026-11-26-provenance-design.md`. Relevant sections: the P5 row, non-negotiables 3 (observability), 4 (automated evaluation) and 5 (prompt optimization), FR-09, NFR-01, NFR-07, NFR-08 and NFR-10. Read `docs/progress.md` (P3/P4 gotchas) first.

## Global Constraints

- All P0–P4 constraints hold. Telemetry, metrics labels and span attributes carry IDs, names, timings, outcomes and counts, never question, answer or document text.
- **Metrics:** `GET /metrics` is public, contains no workspace or user IDs, and is listed in the isolation suite's `PUBLIC_OPERATIONS`.
- **Tracing:** spans are created always, but nothing is exported unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set. The service name is `provenance-api`.
- **Operator view:** only for emails in `OPERATOR_EMAILS`, default `["demo@provenance.local"]`. Others get 403 `forbidden`. It shows service-wide aggregates only.
- **Cache key:** the response cache keys on SHA-256 of (normalized question, history digest, answer prompt version, answer model list, corpus version). The corpus version is the SHA-256 of the workspace's sorted `(document_id, active_version_id)` pairs. TTL is `ANSWER_CACHE_TTL_S = 86400`. Only `answered` and `abstained` answers are cached, and only when nothing was degraded. A hit adds the notice `Served from cache (same question and documents).`
- **Feedback:** `rating ∈ {up, down}` with an optional comment of ≤ 500 characters, PII-redacted. There is one feedback per (message, user), and it upserts. Only assistant messages accept feedback.
- **Groq free-tier budget (ADR-0007):** at most about 200K tokens per day per model.
  - Answers run on `qwen/qwen3.8-27b` and fall back to `openai/gpt-oss-120b`.
  - The RAGAS judge is `openai/gpt-oss-20b` with JSON mode, which keeps it out of the answer models' pools.
  - Answer relevancy uses `strictness=1`.
  - Context precision and recall are not run with RAGAS. Our deterministic retrieval metrics (P3) measure context quality; ADR-0009 records this deviation.
  - Evaluation commands take `--limit` (items per domain and split, stratified by category) and are resumable through cassettes and the judge cache.
- **RAGAS telemetry:** importing RAGAS must happen with `RAGAS_DO_NOT_TRACK=true` already set, in `evaluation/ragas_judge.py` before the import. Nothing in the runtime package imports RAGAS.
- **Own answer metrics** (per domain, with 95% bootstrap CI):

| Metric | Definition |
|---|---|
| `citation_precision` | Share of citations whose document filename is a gold file. Answered answerable items only. |
| `sentence_coverage` | Kept sentences ÷ drafted sentences. Answered items only. |
| `abstention_recall` | Unanswerable items whose status is `abstained` or `blocked`. |
| `false_abstention_rate` | Answerable items whose status is `abstained`. |
| `injection_block_rate` | Injection-type adversarial items that end `blocked`. |
| `latency_ms` | p50 and p95. |
| `tokens_mean` | Mean tokens per answer. |

- **Optimizer:**
  - Variants live in `prompts/variants/answer.<name>.yaml`: `strict_citation`, `concise`, `abstention_first`.
  - The objective is the mean of `faithfulness`, `citation_precision` and `abstention_accuracy`, where `abstention_accuracy` is 1 − (wrong abstentions + missed abstentions) ÷ items. Ties are broken by fewer tokens.
  - The top 2 on dev are re-scored on test, and the winner is decided on test. The baseline stays pinned unless the winner beats it by ≥ 0.02.

## Review Focus

- **Cached answer citing a deleted or replaced document:** a new version changes the corpus version, so the cache misses — `test_cache_invalidates_when_documents_change` (Task 3).
- **Feedback on someone else's message or a user message:** 404, or 422 `feedback_not_allowed` — `test_feedback_rules` plus the isolation suite picking up `message_id` (Task 2).
- **Non-operator calling the operator endpoint:** 403 with no aggregates leaked — `test_operator_requires_operator_email` (Task 4).
- **Question text or PII in `/metrics` or span attributes:** never present — `test_metrics_and_spans_carry_no_text` (Task 1).
- **Quota exhausted mid-evaluation:** the item is recorded as `error` with its code, the run continues, the report counts errors, and a rerun resumes from cassettes — `test_evaluation_survives_provider_errors` (Task 5).

---

### Task 1: Prometheus metrics and OTel spans

**Files:**
- Create: `observability/metrics.py`, `observability/tracing.py`.
- Modify: `observability/telemetry.py` (update metrics in `record`, `record_provider_call`, `record_guardrails`; new `record_answer(ctx, status, latency_ms)`).
- Modify: `core/pipeline.py` (`run_stage` opens a span); `answers/pipeline.py` (`_span` opens a span); `api/app.py` (configure tracing, mount `/metrics`); `core/config.py` (`otel_exporter_otlp_endpoint: str | None = None`).
- Modify: `pyproject.toml` (runtime deps); isolation suite `PUBLIC_OPERATIONS`.
- Tests: `tests/observability/test_metrics.py`, `test_tracing.py`.

**Interfaces — Produces:**

Metrics in `metrics.py`, all on module-level `REGISTRY = CollectorRegistry()`:

| Name | Type | Labels |
|---|---|---|
| `provenance_stage_duration_seconds` | Histogram | `stage`, `outcome` |
| `provenance_llm_calls_total` | Counter | `model`, `purpose`, `status` |
| `provenance_llm_tokens_total` | Counter | `model`, `direction` (`prompt`/`completion`) |
| `provenance_guardrail_actions_total` | Counter | `name`, `action` |
| `provenance_answers_total` | Counter | `status` |
| `provenance_answer_latency_seconds` | Histogram | — |

Tracing in `tracing.py`:
- `configure_tracing(settings) -> None`, idempotent.
- `stage_span(name: str, ctx: RequestContext) -> ContextManager[None]`, with attributes `provenance.correlation_id`, `provenance.workspace_id` and `provenance.stage`. Records exceptions and marks status error.

- [ ] Test `test_metrics_endpoint_counts_stages_and_calls`: run one search and one scripted answer through the API, then `GET /metrics`. Expect 200, `text/plain`, a `provenance_stage_duration_seconds_count{stage="retrieve",outcome="ok"}` line, and a `provenance_llm_calls_total{…status="ok"}` line.
- [ ] Test `test_metrics_and_spans_carry_no_text`: the `/metrics` body and every recorded span attribute (`InMemorySpanExporter`) contain neither the question words nor the email used in the question.
- [ ] Test `test_spans_per_stage_without_exporter`: with no endpoint configured, the stages `embed_query`, `retrieve`, `authorize`, `rerank`, `answer_generate` and `answer_verify` produce spans (in-memory processor in the test), and nothing is exported over the network.
- [ ] Implement, run `uv run pytest apps/api/tests/observability -q` (pass), then commit `feat(observability): Prometheus metrics and OpenTelemetry stage spans`.

### Task 2: Answer timings and feedback

**Files:**
- Modify: `conversations/models.py`. Add `Message.latency_ms: float | None` and `Message.ttft_ms: float | None`, and a new `Feedback(id, message_id FK cascade, user_id FK cascade, rating String(4), comment Text | None, created_at)` with unique `(message_id, user_id)`.
- Create: migration `0007_feedback_timings`.
- Modify: `conversations/router.py` (measure first-token and total time, store them, call `telemetry.record_answer`).
- Create: `conversations/feedback.py` (service) and the route `PUT /v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages/{message_id}/feedback`.
- Modify: `MessageOut` (+ `latency_ms`, `ttft_ms`, `feedback: Literal["up","down"] | None` for the current user).
- Modify: isolation suite (`message_id` in `KNOWN_PARAMETERS`; tenant A gets an assistant message).
- Tests: `tests/conversations/test_feedback.py`.

**Interfaces — Produces:**
- `FeedbackIn(rating: Literal["up","down"], comment: str | None ≤ 500)` → `FeedbackOut(message_id, rating, comment)`.
- Errors: `FeedbackNotAllowedError` (422 `feedback_not_allowed`).

- [ ] Test `test_feedback_rules`:
  - a thumbs-up then a thumbs-down on the same message leaves one row, rating `down`;
  - a comment `"mail me at jane@example.com"` is stored redacted;
  - feedback on the user's own question message → 422;
  - an unknown message id → 404.
- [ ] Test `test_answers_store_latency_and_ttft`: after an SSE answer, the stored message has `0 < ttft_ms <= latency_ms`.
- [ ] Implement, run the conversations and isolation tests (pass), then commit `feat(conversations): answer timings and per-user feedback`.

### Task 3: Response cache

**Files:**
- Create: `conversations/cache.py`; model `AnswerCache(id, workspace_id FK cascade, key String(64) unique, payload JSONB, created_at)` in `conversations/models.py`, in the same migration as Task 2 if that is not merged yet, otherwise `0008`.
- Modify: `conversations/router.py` (look up before running the pipeline; store after a cacheable final).
- Modify: `core/config.py` (`answer_cache_ttl_s: int = 86_400`).
- Tests: `tests/conversations/test_cache.py`.

**Interfaces — Produces:**
- `corpus_version(db, workspace_id) -> str`
- `cache_key(question: str, history: Sequence[Exchange], prompt_version: str, models: Sequence[str], corpus: str) -> str`. It normalizes the question by redacting PII, lower-casing, and collapsing whitespace and trailing punctuation.
- `get_cached(db, workspace_id, key, ttl_s) -> dict | None`
- `put_cached(db, workspace_id, key, payload: dict) -> None`. The payload is `MessageOut`'s fields minus `id` and `created_at`.

- [ ] Test `test_repeat_question_is_served_from_cache`: asking the same question twice in new conversations makes one provider call. The second final has the same content and citations plus the cache notice, and its own message id.
- [ ] Test `test_cache_invalidates_when_documents_change`: upload a new version of the cited document, then ask again. It misses the cache and makes a provider call.
- [ ] Test `test_uncacheable_results`: `blocked`, `error` and degraded answers are never stored, and an expired entry (TTL 0) misses.
- [ ] Implement, test, then commit `feat(conversations): response cache keyed by question, prompt and corpus version`.

### Task 4: Workspace analytics and operator view

**Files:**
- Create: `analytics/{__init__,service,router}.py`.
- Modify: `api/v1.py`; `core/config.py` (`operator_emails: list[str] = ["demo@provenance.local"]`); `core/errors.py` (`ForbiddenError` 403 `forbidden`).
- Tests: `tests/analytics/test_analytics_api.py`.

**Interfaces — Produces:**
- `GET /v1/workspaces/{workspace_id}/analytics?days=7` (1–90) returns `WorkspaceAnalytics`:
  - `questions_by_day: [{date, count}]`
  - `statuses: {answered, abstained, blocked, error}`
  - `latency_ms: {p50, p95}` and `ttft_ms: {p50, p95}`
  - `feedback: {up, down}`
  - `guardrails: [{name, action, count}]`
  - `top_documents: [{document_id, title, citations}]` (max 5)
  - `documents: {queued, processing, ready, partial, failed}`
  - `degraded_answers: int`
- `GET /v1/operator/overview` returns `OperatorOverview`:
  - `services: {database: {ok, latency_ms}, vector_store: {ok, points}, worker: {active_leases, last_job_at}, llm: {key_configured, cassettes}}`
  - `queue: {queued, running, failed}`
  - `models: [{model, purpose, calls_24h, errors_24h, rate_limited_24h, tokens_today, tokens_per_day_limit: 200000}]`
  - `answers_24h: {status: count}`
  - `latest_eval: {created_at, git_sha, domains: {domain: {metric: value}}} | None`, read from `eval/reports/answers-test.json` and `retrieval-test.json` when present.
- Percentiles are computed with Postgres `percentile_cont`.

- [ ] Test `test_analytics_counts_a_workspace_only`: two workspaces with scripted answers, feedback and a blocked question. Each workspace's analytics reflect only its own rows: status counts, feedback counts, `top_documents[0]` and the guardrail counts.
- [ ] Test `test_operator_requires_operator_email`: the secondary demo user gets 403 `forbidden` with no counts in the body; the primary gets 200 with `services.database.ok == true` and `queue` counts that match the seeded jobs.
- [ ] Implement, test, then commit `feat(analytics): workspace analytics and operator overview from SQL telemetry`.

### Task 5: Answer evaluation with own metrics and RAGAS

**Files:**
- Create: `evaluation/answers.py` (runs and scores), `evaluation/ragas_judge.py` (the RAGAS adapter: env guard, `AsyncOpenAI` to Groq, `llm_factory(settings.judge_model, client=…, cache=DiskCacheBackend(".cache/ragas"))`, a `FastEmbedRagasEmbedding(BaseRagasEmbedding)` wrapping `FastEmbedder.embed_query_dense`, and `Faithfulness` plus `AnswerRelevancy(strictness=1)`).
- Modify: `answers/pipeline.py` (`Answer.sentences_removed: int`); `core/config.py` (`judge_model: str = "openai/gpt-oss-20b"`); `cli.py` (`eval --suite {retrieval,answers}`, `--limit`, `--judge/--no-judge`).
- Modify: `evaluation/report.py` (answer report JSON/MD); `docs/budget.md`.
- Tests: `tests/evaluation/test_answers_eval.py` (scripted provider and a fake judge, no RAGAS import).

**Interfaces — Produces:**
- `select_items(golden, limit) -> list[GoldenItem]`: stratified round-robin over categories in id order; deterministic.
- `AnswerJudge` protocol: `async score(question, answer, contexts) -> JudgeScores(faithfulness: float | None, answer_relevancy: float | None)`.
- `evaluate_answers(session_factory, answerer, golden, limit, judge: AnswerJudge | None) -> AnswerReport`, holding per-item records `{id, category, status, error_code, citations_gold: [bool], sentences_kept, sentences_removed, latency_ms, tokens, faithfulness, answer_relevancy}` and per-metric `Estimate`s.
- CLI: `provenance eval --suite answers --domain all --split dev --limit 10 [--no-judge] --out eval/reports`. It uses `CassetteProvider(eval/cassettes/answers, "record", groq)` when a key is set, and `"replay"` otherwise.

- [ ] Test `test_answer_metrics_on_scripted_answers`: four items (answered with a gold citation; answered with a non-gold citation; unanswerable that abstained; answerable that abstained). Expect `citation_precision == 0.5`, `abstention_recall == 1.0`, `false_abstention_rate == 0.5`, and judge scores averaged over answered items only.
- [ ] Test `test_evaluation_survives_provider_errors`: the second item raises `LLMRateLimitedError`. It records `status="error"` and `error_code="llm_rate_limited"`, the third item still runs, and the report shows `errors == 1`.
- [ ] Test `test_select_items_is_stratified_and_stable`: limit 5 over the company dev set includes every category present, and two calls return the same order.
- [ ] Test `test_ragas_judge_disables_tracking` (marked `slow`): importing `provenance.evaluation.ragas_judge` sets `os.environ["RAGAS_DO_NOT_TRACK"] == "true"` before `ragas` is in `sys.modules`.
- [ ] Implement, test, then commit `feat(eval): answer evaluation with grounding metrics and a RAGAS judge`.

### Task 6: Guardrail evaluation against Prompt Guard

**Files:**
- Create: `eval/golden/injections.yaml` (the 22 known attack strings; the guardrail tests now load them from here), `evaluation/guardrail_eval.py`.
- Modify: `cli.py` (`eval --suite guardrails`); `tests/guardrails/test_guards.py`.

**Interfaces — Produces:**
- `evaluate_guardrails(questions: list[LabeledQuestion], classifiers: Mapping[str, Classifier]) -> GuardrailReport` with precision, recall and false-positive rate per classifier.
- Classifiers:
  - `local`: `detect_injection`.
  - `prompt_guard`: a Groq chat completion to `meta-llama/llama-prompt-guard-2-86m`, cassette-cached. It counts as malicious when the returned score or label marks the input as an attack. Check the response shape on the first live call and record the parsing rule in the module docstring.
- Labels: positives are the attack strings plus the golden injection items; negatives are every other golden question.

- [ ] Test `test_local_classifier_scores` (offline, `local` only): recall 1.0 and FPR 0.0 on the shipped data.
- [ ] Implement, record the Prompt Guard cassettes once with a key (about 140 tiny calls), then commit `feat(eval): guardrail evaluation against Groq Prompt Guard`.

### Task 7: Prompt optimizer

**Files:**
- Create: `prompts/variants/answer.strict_citation.yaml`, `answer.concise.yaml`, `answer.abstention_first.yaml`; `evaluation/optimize.py`.
- Modify: `generation/prompts.py` (`load_prompt(prompt_id, directory)` already takes a directory; add `variant_ids() -> list[str]`); `cli.py` (`optimize`).
- Tests: `tests/evaluation/test_optimize.py` (scripted provider and fake judge).

**Interfaces — Produces:**
- `objective(report) -> float`.
- `optimize(session_factory, answerer_for: Callable[[Prompt], Answerer], judge, dev_limit, test_limit) -> OptimizationReport` with dev scores for all variants, test scores for the top 2 and the baseline, the winner, and whether to pin.
- CLI: `provenance optimize --dev-limit 8 --test-limit 8 [--pin]`. It writes `eval/reports/prompt-optimization.json` and `docs/prompt-optimization.md`. `--pin` copies the winner's `system` into `prompts/answer.yaml`, keeping `id: answer`.

- [ ] Test `test_optimizer_picks_the_test_winner_not_the_dev_winner`: a fake judge where variant A wins dev but B wins test. The winner is B and the report lists both splits.
- [ ] Test `test_baseline_kept_without_margin`: the winner is 0.01 better than the baseline, so `pin is False`.
- [ ] Implement, test, then commit `feat(optimize): prompt variant search scored on dev, decided on test`.

### Task 8: Live runs, eval workflow, reports, docs

- [ ] **Answer eval:** with the key, run `provenance eval --suite answers --split dev --limit 10 --out eval/reports` and `--split test --limit 10`, for both domains. Expect about 40 answers (~130K tokens) and about 80 judge calls (~120K tokens on `gpt-oss-20b`), which may span two days of quota; the cassettes and the judge cache resume the run. Commit the cassettes and the reports.
- [ ] **Guardrail eval and optimizer:** run `provenance eval --suite guardrails`, and run `provenance optimize --dev-limit 8 --test-limit 8` (about 100 answers). Pin only if the margin rule says so (re-record the P4 e2e cassettes if pinned). Commit the reports and `docs/prompt-optimization.md`.
- [ ] **Workflow:** `.github/workflows/eval.yml` runs on `workflow_dispatch` and a weekly cron. It uses `secrets.GROQ_API_KEY`, indexes the corpora, runs the answers and guardrails suites with record cassettes, and uploads `eval-report/` as an artifact. The user adds the secret.
- [ ] **Docs:**
  - `docs/eval-report.md`: retrieval, answers and guardrails tables with CIs and the optimizer result, with misses stated.
  - ADR-0009: evaluation design and the RAGAS budget deviation.
  - Update `docs/budget.md` and `docs/progress.md`.
- [ ] Full suite plus ruff, mypy and vulture; code review; PR. After the merge the user tags `v0.5.0`.
