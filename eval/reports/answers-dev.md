# Answer evaluation

Run 2026-11-28T07:15:10+00:00 at `1538050af52d`; judge `gemini-3.5-flash-lite`. Means with 95% bootstrap CIs; judge and grounding metrics over answered items, abstention metrics over the matching categories.

| Domain | Split | Items | Errors | Faithfulness | Answer relevancy | Citation precision | Sentence coverage | Abstention recall | False abstention | Injection blocked | Tokens | p50 / p95 ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| company | dev | 10 | 0 | 0.833 (0.50–1.00) | 0.935 (0.85–0.99) | 1.000 (1.00–1.00) | 0.917 (0.75–1.00) | 1.000 (1.00–1.00) | 0.000 (0.00–0.00) | 1.000 (1.00–1.00) | 865 | 1468 / 53517 |
| research | dev | 10 | 0 | 0.883 (0.75–1.00) | 0.879 (0.82–0.94) | 1.000 (1.00–1.00) | 1.000 (1.00–1.00) | 1.000 (1.00–1.00) | 0.000 (0.00–0.00) | 1.000 (1.00–1.00) | 1474 | 1562 / 56436 |
