from pathlib import Path

import pytest

from provenance.evaluation.report import check_thresholds, load_thresholds, to_markdown
from provenance.evaluation.retrieval import Estimate, ItemResult, RetrievalReport
from provenance.retrieval.search import SearchMode

THRESHOLDS = Path(__file__).resolve().parents[4] / "eval" / "thresholds.yaml"


def report(mode: SearchMode, recall: float) -> RetrievalReport:
    item = ItemResult("company-test-01", "factual", "docs", "docs", 12.0, ["a.pdf"], [])
    item.scores = {"recall_at_5": recall, "mrr_at_10": recall}
    return RetrievalReport(
        domain="company",
        split="test",
        mode=mode,
        items=[item],
        metrics={
            name: Estimate(recall, recall, recall)
            for name in (
                "recall_at_5",
                "mrr_at_10",
                "ndcg_at_10",
                "doc_recall_at_5",
                "route_accuracy",
            )
        },
        by_category={"factual": {"recall_at_5": recall, "mrr_at_10": recall, "count": 1.0}},
        rerank_modes={"flashrank": 1},
        latency_ms={"p50": 12.0, "p95": 12.0},
    )


def test_gate_trips_on_regression() -> None:
    thresholds = load_thresholds(THRESHOLDS)

    passing = check_thresholds([report("hybrid_rerank", 0.95)], thresholds)
    failing = check_thresholds([report("hybrid_rerank", 0.40)], thresholds)
    raised = check_thresholds([report("hybrid_rerank", 0.95)], {"company": {"recall_at_5": 0.99}})

    assert passing == []
    assert failing == [
        "company/test recall_at_5 0.400 < 0.90",
        "company/test mrr_at_10 0.400 < 0.80",
    ]
    assert raised == ["company/test recall_at_5 0.950 < 0.99"]


def test_gate_only_judges_the_default_mode() -> None:
    assert check_thresholds([report("sparse", 0.1)], load_thresholds(THRESHOLDS)) == []


@pytest.mark.parametrize("recall", [1.0, 0.0])
def test_markdown_lists_misses(recall: float) -> None:
    metadata = {
        "created_at": "2026-11-27T00:00:00+00:00",
        "git_sha": "abc123",
        "models": {"dense": "d"},
    }

    markdown = to_markdown([report("hybrid_rerank", recall)], metadata)

    assert "| company | test | hybrid_rerank |" in markdown
    assert ("company-test-01" in markdown) is (recall < 1.0)


def test_markdown_explains_route_misses() -> None:
    metadata = {
        "created_at": "2026-11-27T00:00:00+00:00",
        "git_sha": "abc123",
        "models": {"dense": "d"},
    }
    misrouted = report("hybrid_rerank", 1.0)
    misrouted.items[0] = ItemResult(
        "company-test-05", "factual", "docs", "both", 12.0, ["a.pdf"], ["table chunk at rank 2"]
    )

    markdown = to_markdown([misrouted], metadata)

    assert "| `company-test-05` | docs | both | table chunk at rank 2 |" in markdown
