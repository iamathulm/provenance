# Answer evaluation

Run 2026-11-28T05:50:02+00:00 at `61bdc7b306ee`; judge `gemini-3.5-flash-lite`. Means with 95% bootstrap CIs; judge and grounding metrics over answered items, abstention metrics over the matching categories.

| Domain | Split | Items | Errors | Faithfulness | Answer relevancy | Citation precision | Sentence coverage | Abstention recall | False abstention | Injection blocked | Tokens | p50 / p95 ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| company | test | 10 | 0 | 0.700 (0.30–1.00) | 0.893 (0.83–0.95) | 1.000 (1.00–1.00) | 0.900 (0.70–1.00) | 1.000 (1.00–1.00) | 0.167 (0.00–0.50) | 1.000 (1.00–1.00) | 1332 | 1256 / 58218 |
| research | test | 10 | 0 | 0.875 (0.62–1.00) | 0.798 (0.51–1.00) | 1.000 (1.00–1.00) | 0.750 (0.50–1.00) | 1.000 (1.00–1.00) | 0.200 (0.00–0.60) | 1.000 (1.00–1.00) | 1479 | 6627 / 49863 |
