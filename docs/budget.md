# Free-tier budget (NFR-10)

Every external service is used within a free allowance that needs no payment card. This draft
covers the services in use as of P4; P8 completes it with the cloud hosts.

## Groq (LLM)

- **Verified:** 2026-11-27, from console.groq.com/docs/rate-limits and /docs/your-data.
- **Plan:** free, with no card required. The key comes from console.groq.com/keys and goes in `.env` as `GROQ_API_KEY`.

**Models used:**

| Model | Role | RPM | RPD | TPM | TPD |
|---|---|---|---|---|---|
| `qwen/qwen3.8-27b` | answers (no reasoning tokens) | 30 | 1K | 8K | 200K |
| `openai/gpt-oss-120b` | answer fallback | 30 | 1K | 8K | 200K |
| `openai/gpt-oss-20b` | text-to-SQL | 30 | 1K | 8K | 200K |

**Per-answer cost:**
- At most about 3.2K tokens: ≤ 2.4K context, ~350 prompt and ≤ 450 output.
- A table answer adds one SQL call of about 0.8K tokens.

**Throughput ceilings:**
- About 2 answers per minute per model, or about 4 per minute with the fallback.
- About 60 answers per day per model is the daily token ceiling (200K TPD ÷ 3.2K).

**When the quota runs out:**
- The client-side limiter queues a call for up to 8 s, then returns `llm_rate_limited` ("wait about a minute").
- A server 429 moves the call to the next model.
- Nothing is invented.

**Data:**
- Inference inputs and outputs are not retained by default.
- They may be logged for up to 30 days for reliability or abuse investigation. You can opt out of this in Data Controls.
- Questions are PII-redacted before they are sent.

**Without a key:** search, tables and documents work. Chat explains how to add a key.

## Local components (no quota)

These run on the CPU and are cached in `.cache/`. P7 bakes them into the Docker image.

| Component | Size | Purpose |
|---|---|---|
| FastEmbed `BAAI/bge-small-en-v1.5` | ~65 MB | dense embeddings |
| FastEmbed `Qdrant/bm25` | small | sparse BM25 |
| FlashRank `ms-marco-MiniLM-L-12-v2` | ~33 MB | reranking, citation support |

## Gemini (evaluation judge only)

- **Verified:** 2026-11-28 (ai.google.dev pricing and rate-limit pages).
- **Plan:** free tier, no card. The key comes from aistudio.google.com/apikey and goes in `.env` as `GEMINI_API_KEY`.
- **Model:** `gemini-3.5-flash-lite`, called through the OpenAI-compatible endpoint `https://generativelanguage.googleapis.com/v1beta/openai/`.
- **Use:** RAGAS faithfulness and answer relevancy in `provenance eval --suite answers`. **The app never calls Gemini.**
- **Limits:** per project, shown in AI Studio. Judge calls are cached in `.cache/ragas`, so reruns cost nothing.
- **Data:** the free tier lists inputs as *used to improve Google's products*. The judge only sees the synthetic Kestrel Ridge corpus, the CC-BY/CC0 papers and the golden questions, never user data.
- **Without a key:** the judge falls back to `openai/gpt-oss-20b` on Groq (its own 8K TPM / 200K TPD pool). `--no-judge` skips judging entirely.
