# Answer evaluation

Run 2026-11-28T07:19:38+00:00 at `1538050af52d`; judge `gemini-3.5-flash-lite`. Means with 95% bootstrap CIs; judge and grounding metrics over answered items, abstention metrics over the matching categories.

| Domain | Split | Items | Errors | Faithfulness | Answer relevancy | Citation precision | Sentence coverage | Abstention recall | False abstention | Injection blocked | Tokens | p50 / p95 ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| company | test | 10 | 0 | 0.817 (0.60–1.00) | 0.952 (0.91–0.99) | 1.000 (1.00–1.00) | 1.000 (1.00–1.00) | 1.000 (1.00–1.00) | 0.000 (0.00–0.00) | 1.000 (1.00–1.00) | 1370 | 1411 / 57545 |
| research | test | 10 | 0 | 1.000 (1.00–1.00) | 0.687 (0.33–0.95) | 1.000 (1.00–1.00) | 0.900 (0.70–1.00) | 1.000 (1.00–1.00) | 0.000 (0.00–0.00) | 1.000 (1.00–1.00) | 1518 | 2038 / 58648 |
