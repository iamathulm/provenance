# Retrieval evaluation

Run 2026-11-28T13:50:57+00:00 at `1eb85f63725e`; models: dense `BAAI/bge-small-en-v1.5`, sparse `Qdrant/bm25`, reranker `ms-marco-MiniLM-L-12-v2`. Means with 95% bootstrap CIs; ranking metrics over answerable items only.

| Domain | Split | Mode | Recall@5 | MRR@10 | nDCG@10 | Doc recall@5 | Route acc. | p50 / p95 ms | Rerank fallbacks |
|---|---|---|---|---|---|---|---|---|---|
| company | dev | dense | 0.900 (0.78–1.00) | 0.783 (0.65–0.91) | 0.823 (0.73–0.92) | 0.980 (0.94–1.00) | 0.636 (0.48–0.79) | 25 / 30 | – |
| company | dev | sparse | 0.880 (0.76–1.00) | 0.825 (0.69–0.94) | 0.857 (0.74–0.95) | 1.000 (1.00–1.00) | 0.818 (0.70–0.94) | 13 / 30 | – |
| company | dev | hybrid | 0.960 (0.88–1.00) | 0.842 (0.72–0.95) | 0.880 (0.79–0.96) | 1.000 (1.00–1.00) | 0.788 (0.64–0.94) | 28 / 33 | – |
| company | dev | hybrid_rerank | 0.920 (0.80–1.00) | 0.864 (0.74–0.96) | 0.897 (0.81–0.97) | 1.000 (1.00–1.00) | 0.909 (0.82–1.00) | 1783 / 1968 | 0/33 |
| research | dev | dense | 0.583 (0.36–0.81) | 0.513 (0.33–0.71) | 0.560 (0.40–0.74) | 0.944 (0.86–1.00) | 1.000 (1.00–1.00) | 27 / 31 | – |
| research | dev | sparse | 0.778 (0.56–0.94) | 0.612 (0.42–0.79) | 0.678 (0.52–0.83) | 0.972 (0.92–1.00) | 1.000 (1.00–1.00) | 15 / 16 | – |
| research | dev | hybrid | 0.833 (0.67–1.00) | 0.591 (0.41–0.77) | 0.661 (0.50–0.82) | 0.972 (0.92–1.00) | 1.000 (1.00–1.00) | 31 / 35 | – |
| research | dev | hybrid_rerank | 0.806 (0.61–0.94) | 0.632 (0.45–0.81) | 0.690 (0.53–0.84) | 0.972 (0.92–1.00) | 1.000 (1.00–1.00) | 1782 / 1864 | 0/26 |

## company / dev (hybrid_rerank)

| Category | n | Recall@5 | MRR@10 |
|---|---|---|---|
| factual | 18 | 0.889 | 0.840 |
| multi_hop | 3 | 1.000 | 1.000 |
| table | 4 | 1.000 | 0.875 |

Missed at 5 (2):
- `company-dev-13` top files: q3-2026-business-review.pptx, employee-handbook.pdf, travel-and-expense-policy.pdf
- `company-dev-16` top files: sentinel-dock-launch-plan.pptx, q3-2026-business-review.pptx, sentinel-dock-launch-plan.pptx

Route misses (3):

| Item | Expected | Predicted | Reasons |
|---|---|---|---|
| `company-dev-05` | docs | both | strong aggregate 'how many' |
| `company-dev-09` | docs | table | strong aggregate 'how many'; table chunk at rank 2 |
| `company-dev-23` | docs | both | strong aggregate 'how many' |

## research / dev (hybrid_rerank)

| Category | n | Recall@5 | MRR@10 |
|---|---|---|---|
| factual | 16 | 0.875 | 0.641 |
| multi_hop | 2 | 0.250 | 0.556 |

Missed at 5 (4):
- `research-dev-06` top files: 2311.09476v2.pdf, 2311.09476v2.pdf, 2309.15217v2.pdf
- `research-dev-15` top files: 2403.14403v2.pdf, 2403.14403v2.pdf, 2403.14403v2.pdf
- `research-dev-17` top files: 2311.09476v2.pdf, 2311.09476v2.pdf, 2311.09476v2.pdf
- `research-dev-18` top files: 2212.03533v2.pdf, 2402.03216v5.pdf, 2402.03216v5.pdf
