import pytest

from provenance.evaluation.metrics import bootstrap_ci, mrr_at_k, ndcg_at_k, recall_at_k

NONE: frozenset[int] = frozenset()
G0, G1 = frozenset({0}), frozenset({1})


def test_recall_any_and_all() -> None:
    ranked = [NONE, G0, NONE, NONE, NONE, G1]

    assert recall_at_k(ranked, 2, 5, requires_all=False) == 1.0
    assert recall_at_k(ranked, 2, 5, requires_all=True) == 0.5
    assert recall_at_k(ranked, 2, 6, requires_all=True) == 1.0
    assert recall_at_k([], 1, 5, requires_all=False) == 0.0


def test_mrr_uses_first_relevant_rank() -> None:
    assert mrr_at_k([NONE, NONE, G0, G1], 10) == pytest.approx(1 / 3)
    assert mrr_at_k([NONE, G0], 1) == 0.0


def test_ndcg_counts_each_gold_once() -> None:
    perfect = ndcg_at_k([G0, G1], 2, 10)
    duplicate = ndcg_at_k([G0, G0, G1], 2, 10)

    assert perfect == pytest.approx(1.0)
    assert duplicate < perfect
    assert ndcg_at_k([NONE], 1, 10) == 0.0


def test_bootstrap_is_deterministic_and_brackets_the_mean() -> None:
    values = [1.0] * 30 + [0.0] * 10

    low, high = bootstrap_ci(values, seed=7)

    assert (low, high) == bootstrap_ci(values, seed=7)
    assert low <= 0.75 <= high
    assert bootstrap_ci([]) == (0.0, 0.0)
    assert bootstrap_ci([1.0, 1.0]) == (1.0, 1.0)


def test_ndcg_any_of_item_is_perfect_with_one_alternative() -> None:
    assert ndcg_at_k([G0], 1, 10) == pytest.approx(1.0)
