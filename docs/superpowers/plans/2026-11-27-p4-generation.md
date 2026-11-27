# P4 Generation, Grounding and Guardrails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A signed-in user asks a question in a workspace conversation and gets a streamed answer grounded only in authorized sources. Every sentence carries a verified `[Sn]` citation to a chunk, or to table rows when the answer comes from SQL. Answers abstain when nothing supports them. Prompt injection, PII and hostile content are caught by guardrails that each run locally. All of this works with one LLM call per document answer, and two per table answer, on Groq's free tier, and degrades safely without a key.

**Architecture:**
- `generation/` holds the provider protocol (Groq over httpx, Mock, Cassette), the token limiter, the prompt registry, context packing and citation verification.
- `guardrails/` gains injection detection and the input, context and output guards, alongside the existing PII redactor.
- `answers/` runs the query pipeline as `Pipeline` stages and owns SQL generation.
- `conversations/` owns persistence and the SSE chat API.
- Prompts live in versioned YAML under `prompts/`.

**Tech Stack:**
- Groq OpenAI-compatible API (`https://api.groq.com/openai/v1`), called with `httpx` streaming. No SDK.
- Existing `Searcher`, `run_query`, FlashRank and the PII redactor.

**Spec:** `docs/superpowers/specs/2026-11-26-provenance-design.md` (P4 row; non-negotiables 1, 2 and 5; FR-06, FR-07; NFR-04, NFR-05, NFR-10).

## Groq free tier, verified 2026-11-27 (console.groq.com/docs/rate-limits, /docs/your-data)

- **Text models on the free plan:**
  - `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `qwen/qwen3.8-27b`. Each has 30 RPM, 1K RPD, 8K TPM and 200K TPD.
  - `meta-llama/llama-prompt-guard-2-86m` has 30 RPM and 14.4K RPD.
  - Limits apply per model and per organization.
- **Rate-limit signals:** a 429 response carries `retry-after`; the `x-ratelimit-*` headers report remaining RPD and TPM.
- **Reasoning tokens:**
  - `qwen/qwen3.8-27b` supports `reasoning_effort: "none"`, so it emits no hidden reasoning tokens.
  - gpt-oss models support `low`.
  - Reasoning tokens count against the TPM limit.
- **Data:** inference inputs and outputs are not retained by default. They may be logged for up to 30 days for reliability or abuse investigation; this can be opted out of in Data Controls.

**Model choice, picked for headroom:**

| Role | Model | Settings |
|---|---|---|
| Answer | `qwen/qwen3.8-27b` | `reasoning_effort: none`, temperature 0.1, max 450 output tokens |
| Answer fallback when the primary has no TPM left | `openai/gpt-oss-120b` | `reasoning_effort: low` |
| SQL | `openai/gpt-oss-20b` | `low`, JSON schema |

- Separate models have separate token buckets.
- One answer is at most ~3.2K tokens (≤ 2.4K context, ~350 prompt, ≤ 450 output). That allows about 2 answers per minute per model, and ~4 per minute with the fallback.
- When both models are throttled, the request waits up to 8 s. After that it returns an actionable `llm_rate_limited` error; it never invents an answer.

## Global Constraints

- All P0–P3 constraints hold.
- **LLM call budget:**
  - Doc route: 1 call (answer).
  - Table route: 2 calls (SQL, then answer).
  - `both` route: 2 calls (SQL, then answer with doc and row sources).
  - Guards, routing and citation checks are local.
- **No-key mode:** without `GROQ_API_KEY`, the app boots, and search and tables work. Chat returns `llm_unavailable` ("Add GROQ_API_KEY to .env…"). Tests and CI use the Mock and Cassette providers.
- **Sources:**
  - Doc sources come only from `Searcher` hits (already authorized). Row sources come only from `run_query` row refs.
  - Each source is numbered `[S1…Sn]` and wrapped as untrusted data: `<source id="S1" title="…" anchor="…">…</source>`.
  - Context budget: 1,800 words, top 6 reranked chunks, near-duplicates (Jaccard ≥ 0.8) dropped.
- **Citation verification:**
  - Every `[Sn]` must exist in the packed sources.
  - Each answer sentence needs at least one citation and a support score of at least `citation_support_min`. The score is the FlashRank cross-encoder (sentence, source) score, with a lexical-overlap fallback when the reranker is unavailable.
  - Unsupported sentences are removed and listed. If no sentence survives, the answer is replaced with the abstention: "I couldn't find support for that in this workspace's documents."
  - Responses carry `citations[]` with: source id, kind (`chunk` | `rows`), document id, version id, title, anchor, excerpt and support score.
- **Guardrails** (each yields `GuardrailDecision(name, stage, action, detail)` with action `pass|flag|redact|block|quarantine`):
  - **Input:**
    - Empty or > 2,000 characters → block.
    - Prompt-injection heuristics (instruction override, role or system impersonation, prompt-exfiltration, developer-mode and jailbreak phrases, encoded payload hints) → block with an explanation.
    - PII is redacted from everything stored or logged and flagged in the UI. The question sent to the LLM keeps the original text minus card, SSN, IBAN and API-key values.
  - **Context:** retrieved chunks matching the injection heuristics are quarantined. They are dropped from the context and listed in `guardrails[]`; `vendor-faq.txt` "Payment instructions" must be quarantined.
  - **Output:**
    - Citation verifier as above.
    - PII in the answer that does not appear in the cited sources → redacted.
    - Any quarantined text or system-prompt fragments echoed back → block and abstain.
  - **Off-topic:** when the top rerank score falls below `relevance_floor` (or the top fused candidate misses, without a reranker), the answer abstains without an LLM call.
- **Telemetry (no raw text):**
  - `provider_calls`: provider, model, purpose, latency, prompt and completion tokens, status and 429 flag.
  - `guardrail_events`: name, stage, action, rule id.
  - Messages store question and answer text because the user owns the conversation; logs never do.
- **Prompts:** `prompts/answer.yaml`, `prompts/sql.yaml` (`id`, `version`, `system`, `template`). The SHA-256 of the rendered template source is stamped on every message as `prompt_version`.

## Review Focus

- **Poisoned vendor FAQ:** the injected account never reaches the LLM or the answer — `test_poisoned_chunk_is_quarantined` (Task 4).
- **Citation to a chunk not in context, or a fabricated `[S9]`:** removed and the answer abstains if nothing is left — `test_citation_verifier` (Task 3).
- **Groq 429 / no key / network down:** actionable error event, no partial invented answer, the conversation stays usable — `test_provider_failures_are_actionable` (Task 6).
- **Cross-tenant:** conversations, messages and sources of another user are 404 (isolation suite picks up `conversation_id`, `chunk_id`).
- **Deleted document cited by an old answer:** the source endpoint returns 410 `source_revoked` — `test_revoked_source` (Task 6).

---

### Task 1: Provider protocol, Groq client, limiter, cassettes
`generation/providers.py`, `generation/limiter.py`, `generation/cassette.py`; settings `groq_base_url`, `answer_models`, `sql_model`, `llm_timeout_s`, `llm_max_wait_s`, `model_tpm`, `model_rpm`; tests with `httpx.MockTransport`.
- `ChatRequest(purpose, messages, max_tokens, temperature, json_schema)`
- `LLMProvider.stream(request, model) -> AsyncIterator[str]`
- `complete(...) -> Completion(text, model, prompt_tokens, completion_tokens)`
- Errors: `LLMUnavailableError`, `LLMRateLimitedError`, `LLMFailedError`.
- `TokenLimiter.acquire(model, tokens)` waits up to `llm_max_wait_s`, else raises; it fails over across `answer_models`.
- Cassette provider keyed by SHA-256 of (model, messages, params); `record` and `replay` modes; files in `eval/cassettes/`.

### Task 2: Prompt registry and context packing
`prompts/*.yaml`, `generation/prompts.py`, `generation/context.py`.

### Task 3: Citation verifier
`generation/citations.py`: sentence split (abbreviation-safe), `[Sn]` parsing, support scoring, abstention.

### Task 4: Guardrails
`guardrails/injection.py`, `guardrails/guards.py`, `GuardrailDecision`; telemetry tables + migration `0006_generation`.

### Task 5: Answer pipeline + SQL generation
`answers/pipeline.py`, `answers/sql.py`: stages `input_guard → search → route → context_guard → [generate_sql → run_sql] → pack → generate → verify → output_guard`. Emits typed events (`stage`, `token`, `final`, `error`).

### Task 6: Conversations, SSE chat, source resolution
`conversations/{models,service,router}.py`:
- `POST/GET /v1/workspaces/{id}/conversations`
- `GET …/conversations/{cid}/messages`
- `POST …/conversations/{cid}/messages` (SSE)
- `GET /v1/workspaces/{id}/sources/{chunk_id}` (200 / 410 revoked / 404).

### Task 7: Cassette E2E, injection suite, docs, PR
- Record cassettes for a dev subset of both domains with the real key (user-provided `.env`), then replay in CI.
- Injection suite: every adversarial golden item plus ≥ 20 known injection strings are blocked or neutralized.
- ADRs 0007 (LLM provider + budget), 0008 (guardrail layering); `docs/budget.md` draft; progress notes; review; PR.
