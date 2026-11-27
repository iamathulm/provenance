# ADR-0007: Groq free tier with a fixed LLM call budget

- **Status:** Accepted
- **Date:** 2026-11-27

## Context

Answers need a capable model at zero cost, with no payment card. On 2026-11-27, Groq's free plan offers three text models: `openai/gpt-oss-120b`, `openai/gpt-oss-20b` and `qwen/qwen3.8-27b`. Each is limited to 30 requests and 8,000 tokens per minute, and to 1,000 requests and 200,000 tokens per day. The limits apply per model and per organization. Reasoning tokens count against these limits too.

## Decision

- **Call over HTTP:** use Groq's OpenAI-compatible API directly with `httpx`. There is no SDK, and errors are typed: unavailable (401 or no key), rate-limited (429 with retry-after), or failed.
- **Call budget:** at most one model call per document answer and two per table answer (one for SQL, one for the answer). Guardrails, routing and citation checks all run locally.
- **Answer model:** `qwen/qwen3.8-27b` with `reasoning_effort: none`, so no hidden tokens are spent. `openai/gpt-oss-120b` with low reasoning is the fallback when the first model has no quota left.
- **SQL model:** `openai/gpt-oss-20b` with JSON-schema output. It is not streamed, because Groq does not stream structured outputs.
- **Size limits:** context is capped at 1,800 words and output at 450 tokens. One answer is at most about 3,200 tokens, which allows roughly two answers per minute per model.
- **Client-side limiter:** a per-model 60-second window queues a call for up to 8 s before it fails with an actionable message. A 429 from the server cools that model down and the call moves to the next model, as long as no text has been streamed yet.
- **No key:** the app still boots, and search and tables still work. Chat explains how to add a key.
- **Tests and CI:** cassettes record real calls once and replay them offline. They are keyed by the full request, so any prompt change invalidates them.

## Alternatives considered

- **Gemini free tier:** cut in v4 to keep a single provider. Its quota and terms change more often, and it would add a second failure mode.
- **Local LLM (Ollama):** free, but several GB of weights and slow CPU inference break the ≈ 5 GB budget and the "quick for the reviewer" goal.
- **LangChain chat models:** unnecessary given ADR-0001; the provider code here is about 150 lines.

## Consequences

- Throughput is roughly 4 answers per minute across both answer models. Load tests report Groq throttling separately (NFR-02 allows this). The response cache planned for P5 reduces repeat calls.
- Free-tier terms can change. The model IDs and limits live in settings, and `docs/budget.md` records when they were last verified.
