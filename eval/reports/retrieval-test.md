# Retrieval evaluation

Run 2026-11-27T05:15:49+00:00 at `3236d0d0b191`; models: dense `BAAI/bge-small-en-v1.5`, sparse `Qdrant/bm25`, reranker `ms-marco-MiniLM-L-12-v2`. Means with 95% bootstrap CIs; ranking metrics over answerable items only.

| Domain | Split | Mode | Recall@5 | MRR@10 | nDCG@10 | Doc recall@5 | Route acc. | p50 / p95 ms | Rerank fallbacks |
|---|---|---|---|---|---|---|---|---|---|
| company | test | dense | 0.920 (0.80–1.00) | 0.851 (0.73–0.95) | 0.869 (0.78–0.95) | 0.960 (0.88–1.00) | 0.697 (0.55–0.85) | 54 / 65 | – |
| company | test | sparse | 0.960 (0.88–1.00) | 0.893 (0.79–0.98) | 0.893 (0.79–0.97) | 1.000 (1.00–1.00) | 0.636 (0.48–0.82) | 37 / 69 | – |
| company | test | hybrid | 0.960 (0.88–1.00) | 0.899 (0.80–0.98) | 0.909 (0.83–0.97) | 1.000 (1.00–1.00) | 0.636 (0.48–0.82) | 66 / 78 | – |
| company | test | hybrid_rerank | 0.960 (0.88–1.00) | 0.848 (0.73–0.95) | 0.871 (0.78–0.95) | 1.000 (1.00–1.00) | 0.667 (0.52–0.82) | 1226 / 1555 | 0/33 |
| research | test | dense | 0.667 (0.44–0.89) | 0.325 (0.17–0.48) | 0.409 (0.24–0.56) | 0.944 (0.86–1.00) | 1.000 (1.00–1.00) | 57 / 63 | – |
| research | test | sparse | 0.750 (0.56–0.94) | 0.541 (0.36–0.72) | 0.617 (0.45–0.78) | 1.000 (1.00–1.00) | 1.000 (1.00–1.00) | 38 / 40 | – |
| research | test | hybrid | 0.667 (0.44–0.89) | 0.401 (0.23–0.57) | 0.473 (0.29–0.64) | 0.972 (0.92–1.00) | 1.000 (1.00–1.00) | 68 / 83 | – |
| research | test | hybrid_rerank | 0.750 (0.56–0.92) | 0.566 (0.39–0.73) | 0.632 (0.48–0.78) | 0.972 (0.92–1.00) | 1.000 (1.00–1.00) | 1075 / 1113 | 0/26 |

## company / test (hybrid_rerank)

| Category | n | Recall@5 | MRR@10 |
|---|---|---|---|
| factual | 18 | 0.944 | 0.844 |
| multi_hop | 2 | 1.000 | 1.000 |
| table | 5 | 1.000 | 0.800 |

Missed at 5 (1):
- `company-test-05` top files: talon-x2-product-specification.docx, flight-operations-safety-manual.pdf, talon-x2-product-specification.docx

## research / test (hybrid_rerank)

| Category | n | Recall@5 | MRR@10 |
|---|---|---|---|
| factual | 16 | 0.812 | 0.606 |
| multi_hop | 2 | 0.250 | 0.250 |

Missed at 5 (5):
- `research-test-01` top files: 2212.03533v2.pdf, 2212.03533v2.pdf, 2212.03533v2.pdf
- `research-test-06` top files: 2309.15217v2.pdf, 2309.15217v2.pdf, 2309.15217v2.pdf
- `research-test-07` top files: 2401.05856v1.pdf, 2401.05856v1.pdf, 2401.05856v1.pdf
- `research-test-17` top files: 2311.09476v2.pdf, 2311.09476v2.pdf, 2311.09476v2.pdf
- `research-test-18` top files: 2403.14403v2.pdf, 2310.07554v3.pdf, 2310.07554v3.pdf
