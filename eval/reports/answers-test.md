# Answer evaluation

Run 2026-11-28T14:48:11+00:00 at `8efaa9e6d15a`; judge `gemini-3.5-flash-lite`. Means with 95% bootstrap CIs; judge and grounding metrics over answered items, abstention metrics over the matching categories.

| Domain | Split | Items | Errors | Faithfulness | Answer relevancy | Citation precision | Sentence coverage | Abstention recall | False abstention | Injection blocked | Tokens | p50 / p95 ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| company | test | 10 | 0 | 0.817 (0.60–1.00) | 0.952 (0.91–0.99) | 1.000 (1.00–1.00) | 1.000 (1.00–1.00) | 1.000 (1.00–1.00) | 0.000 (0.00–0.00) | 1.000 (1.00–1.00) | 1342 | 2662 / 53401 |
| research | test | 10 | 0 | 1.000 (1.00–1.00) | 0.639 (0.28–0.95) | 1.000 (1.00–1.00) | 0.733 (0.53–0.93) | 1.000 (1.00–1.00) | 0.000 (0.00–0.00) | 1.000 (1.00–1.00) | 1544 | 8455 / 51520 |
