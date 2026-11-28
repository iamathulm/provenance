# Answer evaluation

Run 2026-11-28T14:51:44+00:00 at `8efaa9e6d15a`; judge `gemini-3.5-flash-lite`. Means with 95% bootstrap CIs; judge and grounding metrics over answered items, abstention metrics over the matching categories.

| Domain | Split | Items | Errors | Faithfulness | Answer relevancy | Citation precision | Sentence coverage | Abstention recall | False abstention | Injection blocked | Tokens | p50 / p95 ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| company | dev | 10 | 0 | 0.833 (0.50–1.00) | 0.935 (0.86–0.99) | 1.000 (1.00–1.00) | 0.917 (0.75–1.00) | 1.000 (1.00–1.00) | 0.000 (0.00–0.00) | 1.000 (1.00–1.00) | 879 | 2427 / 45482 |
| research | dev | 10 | 0 | 1.000 (1.00–1.00) | 0.817 (0.74–0.91) | 1.000 (1.00–1.00) | 1.000 (1.00–1.00) | 1.000 (1.00–1.00) | 0.000 (0.00–0.00) | 1.000 (1.00–1.00) | 1488 | 4145 / 50024 |
