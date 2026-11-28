# Answer evaluation

Run 2026-11-28T05:45:42+00:00 at `61bdc7b306ee`; judge `gemini-3.5-flash-lite`. Means with 95% bootstrap CIs; judge and grounding metrics over answered items, abstention metrics over the matching categories.

| Domain | Split | Items | Errors | Faithfulness | Answer relevancy | Citation precision | Sentence coverage | Abstention recall | False abstention | Injection blocked | Tokens | p50 / p95 ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| company | dev | 10 | 0 | 1.000 (1.00–1.00) | 0.974 (0.95–1.00) | 1.000 (1.00–1.00) | 1.000 (1.00–1.00) | 1.000 (1.00–1.00) | 0.167 (0.00–0.50) | 1.000 (1.00–1.00) | 826 | 1261 / 54335 |
| research | dev | 10 | 0 | 0.800 (0.67–0.93) | 0.850 (0.81–0.91) | 1.000 (1.00–1.00) | 1.000 (1.00–1.00) | 1.000 (1.00–1.00) | 0.000 (0.00–0.00) | 1.000 (1.00–1.00) | 1451 | 2142 / 55208 |
