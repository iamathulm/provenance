# ADR-0008: Layered local guardrails and verified citations

- **Status:** Accepted
- **Date:** 2026-11-27

## Context

Guardrails and citation grounding are both non-negotiable. They must protect against direct prompt injection, indirect injection from documents (the company corpus ships a poisoned vendor FAQ), personal-data leaks, and ungrounded answers. They also have to work offline and without any extra quota.

## Decision

Every layer runs locally and records its decision as a `GuardrailDecision`. That decision is stored with the message, shown in the UI and counted in `guardrail_events`.

1. **Input guard:**
   - Blocks empty or oversized questions.
   - Phrase-level injection rules block instruction overrides, role impersonation, prompt exfiltration, mode switches and directives aimed at AI assistants.
   - Questions are PII-redacted before they are stored, logged or sent to the model.
2. **Relevance floor:** if the top rerank score is below 0.05, the pipeline abstains without calling the model.
3. **Context guard:** retrieved chunks that carry injection text are quarantined and never reach the model.
4. **Prompt:** sources are numbered, wrapped in `<source>` elements that cannot be closed from inside, and declared untrusted.
5. **Streaming output guard:** the draft is released one sentence at a time, and only after an echo check (8-word overlap with quarantined text or the system prompt) and a PII check. An echo stops the stream and blocks the answer.
6. **Citation verifier:** every sentence must cite a packed source. That source must support it (a FlashRank score of at least 0.5, or exact numbers for SQL rows), and every number in the sentence must appear in the cited sources. Sentences that fail are removed. If none survive, the answer abstains.

Hosted classifiers (Prompt Guard, Llama Guard / gpt-oss-safeguard) are used only in evaluation (P5) as a comparison. They are never in the request path.

## Alternatives considered

- **Hosted Prompt Guard on every request:** it is free (14.4K requests per day), but it adds latency and an outage dependency to every question.
- **LLM-as-judge for citations:** a second model call per answer breaks the call budget (ADR-0007).
- **NLI entailment model for support:** would add a model of several hundred MB for an incremental gain over the reranker plus number checks.

## Consequences

- Precision-first injection rules miss novel phrasings. The rules are tested against 22 known attacks plus every adversarial golden item, with zero false positives on all other golden questions. P5 compares them with Prompt Guard.
- The cross-encoder measures relevance, not entailment, so a fluent but unsupported claim about the right topic can pass. RAGAS faithfulness (P5) measures that remaining risk, and the figure will be reported rather than hidden.
- Streaming sentence by sentence delays the first visible token until the first sentence is complete, which is roughly 0.2–0.5 s at Groq speeds.
