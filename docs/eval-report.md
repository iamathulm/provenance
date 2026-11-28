# Evaluation report

This is the current state of Provenance's measured quality. All numbers come from committed reports in `eval/reports/` and can be reproduced from the committed cassettes (answers, Prompt Guard). Judge scores are cached in the gitignored `.cache/ragas`, so reproducing faithfulness and relevancy needs a judge key:
- `provenance eval --suite retrieval|answers|sql|guardrails`
- `provenance optimize`

Means carry 95% bootstrap confidence intervals. The samples are small (10 items per domain and split for answers), so the intervals are wide, and they are shown here rather than hidden. Design and trade-offs: ADR-0004, ADR-0005, ADR-0006, ADR-0008, ADR-0009.

## Retrieval (held-out test split, `hybrid_rerank`)

| Domain | Recall@5 | MRR@10 | nDCG@10 |
|---|---|---|---|
| Company | 0.92 (0.80–1.00) | 0.85 (0.72–0.95) | 0.88 (0.79–0.96) |
| Research | 0.81 (0.61–0.94) | 0.58 (0.41–0.74) | 0.65 (0.50–0.80) |

The proposed targets are recall@5 ≥ 0.80 and MRR@10 ≥ 0.65. **Company meets both. Research meets recall but misses MRR.**

- **Where research misses:** 2 of the 4 test misses are single-paper factual questions where the right paper is found but the evidence passage is not in the top 5. The other 2 are multi-hop questions that need two papers.
- **Reranker passage length (P5.1):** the reranker used to truncate passages at 256 tokens while research chunks run to 320, so the end of a chunk was never scored. A dev-only grid picked 384 tokens and 20 candidates:

  | Tokens / candidates | Research R@5 | Research MRR | Company R@5 | Company MRR | p95 ms |
  |---|---|---|---|---|---|
  | 256 / 20 (previous) | 0.750 | 0.579 | 0.920 | 0.864 | 1199 |
  | 256 / 30 | 0.750 | 0.569 | 0.960 | 0.865 | 1681 |
  | **384 / 20 (chosen)** | 0.806 | 0.632 | 0.920 | 0.864 | 2112 |
  | 384 / 30 | 0.806 | 0.662 | 0.920 | 0.864 | 2977 |
  | 512 / 20 | 0.833 | 0.634 | 0.960 | 0.842 | 3196 |
  | 512 / 30 | 0.833 | 0.591 | 0.960 | 0.842 | 3206 |

  512 tokens breaks the 3 s p95 search budget, and 384 / 30 sits right at it. On held-out test, research recall@5 went from 0.75 to 0.81 and MRR@10 from 0.57 to 0.58. Company recall@5 went from 0.96 to 0.92 (one item). Search p95 on the laptop CPU rose from about 1.3 s to about 2.1 s.
- **Ablation:** the full comparison (dense, sparse, hybrid, rerank) is in `eval/reports/retrieval-*.md`. On company, plain hybrid without reranking scores higher on test (0.96 / 0.90) at a fraction of the latency. That is a candidate per-profile setting.

**Query routing** (company only; research has no tables): the rule-based router sends a question to documents, to tables, or to both. Superlatives such as "maximum" or "most" now count only together with a table chunk in the top 3. Route accuracy went from 0.76 to 0.91 on dev and from 0.67 to 0.79 on test. Every table question still reaches the SQL path. The remaining test misses route unanswerable or prose questions to both, because a table chunk ranks near the top. That costs one extra SQL call but doesn't change the answer.

## SQL (company table questions, `openai/gpt-oss-20b`)

| Split | Items | Execution accuracy |
|---|---|---|
| Dev | 4 | 1.00 |
| Test | 5 | 0.80 |

- **Execution accuracy:** the generated query, run through the guarded engine, returns the rows of a hand-written gold query. Row order, column names and extra columns are ignored.
- **Target:** ≥ 0.80. It is met exactly. The one test miss filters `product = 'battery'` where the column is `category`. Reordering the table list in the prompt (P5.1 CI fix) changed which query the model wrote, so with 9 items any single answer moves the score by 0.2.
- **CI:** gates it on test from committed cassettes (floor 0.80).

## Answers (held-out test split, pinned prompt `answer.strict_citation`, judge `gemini-3.5-flash-lite`)

> **Not fully held out.** The prompt optimizer chose `answer.strict_citation` on the test split
> (8 items per domain), and 8 of these 10 test items are the same ones. These answer numbers
> are therefore optimistically biased toward the pinned prompt. Treat them as in-sample for the
> prompt choice until a fresh slice is scored.

| Domain | Faithfulness | Answer relevancy | Citation precision | Sentence coverage | Abstention recall | False abstentions | Injections blocked |
|---|---|---|---|---|---|---|---|
| Company | 0.82 (0.60–1.00) | 0.95 (0.91–0.99) | 1.00 | 1.00 | 1.00 | 0.00 | 1.00 |
| Research | 1.00 (1.00–1.00) | 0.64 (0.28–0.95) | 1.00 | 0.73 (0.53–0.93) | 1.00 | 0.00 | 1.00 |

- **Faithfulness** (RAGAS) is the share of answer statements the cited sources support. The proposed target is ≥ 0.85: research meets it, and company's 0.82 has an interval that spans it.
- **Research sentence coverage fell from 0.90 to 0.73 after the reranker change (P5.1):** the citation verifier scores support with the same cross-encoder, and on 3 multi-hop and factual answers it now drops one sentence that the judge still rates fully faithful. The verifier errs toward removing text, not keeping unsupported text. With 10 items this is within noise, but it is the next thing to watch together with research answer relevancy.
- **Citation precision** is the share of cited documents that hold the gold evidence.
- **Abstention recall** counts unanswerable questions correctly declined. **False abstentions** count answerable questions wrongly declined.
- **Latency:** p50 is about 2.2–4.5 s. p95 is about 55 s, and that is free-tier queueing: evaluation waits out Groq's 8K tokens-per-minute limit instead of failing over, so the scores never depend on timing.

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
