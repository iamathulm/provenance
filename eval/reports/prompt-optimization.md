# Prompt optimization

Run 2026-11-28T07:09:36+00:00 at `1538050af52d`. Objective = mean of faithfulness, citation precision and abstention accuracy per domain, averaged over domains. Top 2 on dev plus the baseline are re-scored on the held-out test split; the winner replaces the baseline only if it leads by ≥ 0.02.

| Prompt | Dev objective | Dev tokens | Test objective |
|---|---|---|---|
| answer.strict_citation | 0.958 | 1225 | 0.969 |
| answer.abstention_first | 0.946 | 1214 | 0.921 |
| answer | 0.938 | 1193 | 0.908 |
| answer.concise | 0.915 | 1169 | – |

Winner on test: `answer.strict_citation` (+0.061 vs baseline); pinned as the new baseline.
