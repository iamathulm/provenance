# ADR-0009: Evaluation design on free tiers

- **Status:** Accepted
- **Date:** 2026-11-28

## Context

Automated evaluation is non-negotiable. Retrieval, answers, guardrails and prompt changes must each be measured on both domains, with uncertainty shown and on a held-out split. Every model involved is on a free tier: Groq allows about 200K tokens per day per model, and Gemini's limits are per project. A full RAGAS run over all golden items with every metric would cost several times the daily quota.

## Decision

**Four evaluation suites:**

| Suite | What it measures | Model calls |
|---|---|---|
| `retrieval` (P3) | recall, MRR and nDCG | none (deterministic) |
| `answers` | the real answer pipeline on a category-stratified sample (`--limit`) | Groq answers |
| `guardrails` | local injection rules against Groq-hosted Prompt Guard | Prompt Guard |
| `optimize` | prompt variants scored on dev and decided on test | Groq answers, judge |

All of them report per domain with seeded bootstrap 95% CIs and record reproducibility metadata.

**Answer metrics:**
- **Our own, no model needed:** citation precision, sentence coverage, abstention recall, false-abstention rate, injection block rate, tokens and latency.
- **RAGAS:** faithfulness and answer relevancy (`strictness=1`).
- **Not run:** RAGAS context precision and recall, which would mean one judge call per retrieved chunk. Context quality is measured instead by the deterministic retrieval suite against the gold evidence.

**Judge:**
- `gemini-3.5-flash-lite` when `GEMINI_API_KEY` is set. It uses a separate quota from the answers, and a different model family avoids self-preference.
- Otherwise `openai/gpt-oss-20b` on Groq.
- Judge contexts are the cited sources. For SQL rows, the query is included, because rows alone (`num_tickets 3`) don't show what was counted.
- Gemini is evaluation-only. Its free tier may use inputs to improve Google's products, so only the synthetic and CC-BY evaluation corpora are ever sent to it.

**Cost control:**
- Every answer and Prompt Guard call is recorded as a cassette and committed, and judge replies are cached on disk. An identical rerun costs no quota.
- A run interrupted by a 429 marks the affected items `error` and resumes on the next run.
- RAGAS analytics are switched off before RAGAS is imported, and RAGAS lives in a separate `eval` dependency group that is never in the runtime image.

**CI:**
- Per pull request, only the deterministic retrieval gate runs.
- `eval.yml` runs answers and guardrails manually or weekly, using repository secrets.

## Alternatives considered

- **Full RAGAS on every item and every PR:** would exceed the free quota in one run and make CI depend on a third-party model.
- **The answer model as its own judge:** cheaper, but known to inflate scores (self-preference).
- **An LLM-generated synthetic test set (RAGAS testset):** it would be labeled by the same kind of model it evaluates. The handwritten golden sets with evidence phrases are smaller but trustworthy.

## Consequences

- Samples are small (10 items per domain and split), so CIs are wide. The reports show them rather than claiming precision.
- The local injection rules score perfectly on attacks written alongside them (in-sample). Prompt Guard is the out-of-sample comparison, and new attack phrasings should be added to `eval/golden/injections.yaml` as they are found.
- Changing a prompt, the model options or the retrieval output invalidates the cassettes for the affected requests. The next live run records new ones.
