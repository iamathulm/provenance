# Retrieval evaluation

Run 2026-11-28T13:48:58+00:00 at `1eb85f63725e`; models: dense `BAAI/bge-small-en-v1.5`, sparse `Qdrant/bm25`, reranker `ms-marco-MiniLM-L-12-v2`. Means with 95% bootstrap CIs; ranking metrics over answerable items only.

| Domain | Split | Mode | Recall@5 | MRR@10 | nDCG@10 | Doc recall@5 | Route acc. | p50 / p95 ms | Rerank fallbacks |
|---|---|---|---|---|---|---|---|---|---|
| company | test | dense | 0.920 (0.80–1.00) | 0.851 (0.73–0.95) | 0.888 (0.80–0.96) | 0.960 (0.88–1.00) | 0.818 (0.67–0.94) | 26 / 29 | – |
| company | test | sparse | 0.960 (0.88–1.00) | 0.893 (0.79–0.98) | 0.907 (0.81–0.98) | 1.000 (1.00–1.00) | 0.697 (0.55–0.85) | 13 / 15 | – |
| company | test | hybrid | 0.960 (0.88–1.00) | 0.899 (0.80–0.98) | 0.924 (0.84–0.99) | 1.000 (1.00–1.00) | 0.727 (0.58–0.88) | 28 / 31 | – |
| company | test | hybrid_rerank | 0.920 (0.80–1.00) | 0.847 (0.72–0.95) | 0.884 (0.79–0.96) | 1.000 (1.00–1.00) | 0.788 (0.64–0.91) | 1897 / 2092 | 0/33 |
| research | test | dense | 0.667 (0.44–0.89) | 0.325 (0.17–0.48) | 0.409 (0.24–0.56) | 0.944 (0.86–1.00) | 1.000 (1.00–1.00) | 26 / 28 | – |
| research | test | sparse | 0.750 (0.56–0.94) | 0.541 (0.36–0.72) | 0.617 (0.45–0.78) | 1.000 (1.00–1.00) | 1.000 (1.00–1.00) | 14 / 34 | – |
| research | test | hybrid | 0.667 (0.44–0.89) | 0.401 (0.23–0.57) | 0.473 (0.29–0.64) | 0.972 (0.92–1.00) | 1.000 (1.00–1.00) | 29 / 32 | – |
| research | test | hybrid_rerank | 0.806 (0.61–0.94) | 0.581 (0.41–0.74) | 0.647 (0.50–0.80) | 0.972 (0.92–1.00) | 1.000 (1.00–1.00) | 1858 / 1999 | 0/26 |

## company / test (hybrid_rerank)

| Category | n | Recall@5 | MRR@10 |
|---|---|---|---|
| factual | 18 | 0.889 | 0.843 |
| multi_hop | 2 | 1.000 | 1.000 |
| table | 5 | 1.000 | 0.800 |

Missed at 5 (2):
- `company-test-05` top files: talon-x2-product-specification.docx, flight-operations-safety-manual.pdf, talon-x2-product-specification.docx
- `company-test-16` top files: groundlink-4-2-release-notes.docx, runbook-lost-link.txt, postmortem-2026-08-14-telemetry-outage.txt

Route misses (7):

| Item | Expected | Predicted | Reasons |
|---|---|---|---|
| `company-test-08` | docs | both | table chunk at rank 3 |
| `company-test-12` | docs | both | table chunk at rank 2 |
| `company-test-24` | both | table | strong aggregate 'how many'; table chunk at rank 2 |
| `company-test-27` | docs | both | strong aggregate 'how much' |
| `company-test-28` | docs | both | table chunk at rank 2 |
| `company-test-29` | docs | both | table chunk at rank 3 |
| `company-test-30` | docs | both | strong aggregate 'how many' |

## research / test (hybrid_rerank)

| Category | n | Recall@5 | MRR@10 |
|---|---|---|---|
| factual | 16 | 0.875 | 0.633 |
| multi_hop | 2 | 0.250 | 0.167 |

Missed at 5 (4):
- `research-test-06` top files: 2309.15217v2.pdf, 2309.15217v2.pdf, 2309.15217v2.pdf
- `research-test-07` top files: 2401.05856v1.pdf, 2401.05856v1.pdf, 2401.05856v1.pdf
- `research-test-17` top files: 2311.09476v2.pdf, 2311.09476v2.pdf, 2311.09476v2.pdf
- `research-test-18` top files: 2403.14403v2.pdf, 2310.07554v3.pdf, 2310.07554v3.pdf
