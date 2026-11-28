# Evaluation report

This is the current state of Provenance's measured quality. All numbers come from committed reports in `eval/reports/` and can be reproduced from the committed cassettes (answers, Prompt Guard). Judge scores are cached in the gitignored `.cache/ragas`, so reproducing faithfulness and relevancy needs a judge key:
- `provenance eval --suite retrieval|answers|guardrails`
- `provenance optimize`

Means carry 95% bootstrap confidence intervals. The samples are small (10 items per domain and split for answers), so the intervals are wide, and they are shown here rather than hidden. Design and trade-offs: ADR-0004, ADR-0005, ADR-0008, ADR-0009.

## Retrieval (held-out test split, `hybrid_rerank`)

| Domain | Recall@5 | MRR@10 | nDCG@10 |
|---|---|---|---|
| Company | 0.96 (0.88–1.00) | 0.85 (0.73–0.95) | 0.88 (0.79–0.96) |
| Research | 0.75 (0.56–0.92) | 0.57 (0.39–0.73) | 0.63 (0.48–0.78) |

The proposed targets are recall@5 ≥ 0.80 and MRR@10 ≥ 0.65. **Company meets them; research does not.** Most research misses are multi-hop questions that need passages from two papers in the top 5. The full ablation (dense, sparse, hybrid, rerank) is in `eval/reports/retrieval-*.md`.

## Answers (held-out test split, pinned prompt `answer.strict_citation`, judge `gemini-3.5-flash-lite`)

> **Not fully held out.** The prompt optimizer chose `answer.strict_citation` on the test split
> (8 items per domain), and 8 of these 10 test items are the same ones. These answer numbers
> are therefore optimistically biased toward the pinned prompt. Treat them as in-sample for the
> prompt choice until a fresh slice is scored.

| Domain | Faithfulness | Answer relevancy | Citation precision | Sentence coverage | Abstention recall | False abstentions | Injections blocked |
|---|---|---|---|---|---|---|---|
| Company | 0.82 (0.60–1.00) | 0.95 (0.91–0.99) | 1.00 | 1.00 | 1.00 | 0.00 | 1.00 |
| Research | 1.00 (1.00–1.00) | 0.69 (0.33–0.95) | 1.00 | 0.90 (0.70–1.00) | 1.00 | 0.00 | 1.00 |

- **Faithfulness** (RAGAS) is the share of answer statements the cited sources support. The proposed target is ≥ 0.85: research meets it, and company's 0.82 has an interval that spans it.
- **Citation precision** is the share of cited documents that hold the gold evidence.
- **Abstention recall** counts unanswerable questions correctly declined. **False abstentions** count answerable questions wrongly declined.
- **Latency:** p50 is about 1.4–2.0 s. p95 is about 55 s, and that is free-tier queueing: evaluation waits out Groq's 8K tokens-per-minute limit instead of failing over, so the scores never depend on timing.

## Guardrails (all golden questions plus 22 known attacks)

| Classifier | Precision | Recall | False-positive rate |
|---|---|---|---|
| Local rules (request path) | 1.00 | 1.00 | 0.00 |
| Prompt Guard 2 86M (Groq, evaluation only) | 1.00 | 0.67 | 0.00 |

The local rules were written alongside these attacks, so their perfect score is in-sample. Prompt Guard is the out-of-sample comparison; it missed role-prefix and "notice to AI assistants" attacks. New phrasings belong in `eval/golden/injections.yaml`.

## Prompt optimization

Three handwritten variants and the previous prompt were scored on dev, using 8 items per domain. The top two and the baseline were then re-scored on held-out test. The objective is the mean of faithfulness, citation precision and abstention accuracy.

| Prompt | Dev | Test |
|---|---|---|
| `answer.strict_citation` | 0.958 | **0.969** |
| `answer.abstention_first` | 0.946 | 0.921 |
| previous `answer` | 0.938 | 0.908 |
| `answer.concise` | 0.915 | – |

`strict_citation` won on test by +0.061, which clears the 0.02 pin margin, so it is now `prompts/answer.yaml`.

Re-measured on the 10-item test sample (8 of them the items used to choose the winner, so biased in its favour), against the previous prompt:

| Metric | Company | Research |
|---|---|---|
| Faithfulness | 0.70 → 0.82 | 0.88 → 1.00 |
| False abstentions | 0.17 → 0 | 0.20 → 0 |
| Answer relevancy | — | 0.80 → 0.69 |

The research answer-relevancy drop has an interval wide enough (0.33–0.95) that it may be noise. It is the next thing to watch.

## Known limits

- **Prompt selection used the test split:** the optimizer decides on test, so post-pin answer metrics on overlapping test items are not an unbiased estimate. A larger untouched slice is the next evaluation to run.
- **Small samples:** answer evaluation runs on 10 items per domain and split, because of the free-tier budget (ADR-0009). Treat differences smaller than the intervals as noise.
- **Relevance, not entailment:** the request-path citation check scores relevance. RAGAS faithfulness above is the measurement of what that check can miss.
- **Fallback model:** production fails over to `openai/gpt-oss-120b` when the primary model's quota is spent. Its answer quality is not measured here, because evaluation is pinned to the primary model.
