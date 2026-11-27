import uuid

import pytest

from provenance.retrieval.fusion import rrf

A, B, C, D = (uuid.UUID(int=i) for i in range(1, 5))


def test_rrf_matches_the_formula() -> None:
    fused = dict(rrf([[A, B], [B, C]], k=60))

    assert fused[A] == pytest.approx(1 / 61)
    assert fused[B] == pytest.approx(1 / 62 + 1 / 61)
    assert fused[C] == pytest.approx(1 / 62)


def test_agreement_beats_a_single_top_rank() -> None:
    ranked = [item for item, _ in rrf([[A, B, C], [D, B]])]

    assert ranked[0] == B


def test_ties_keep_first_appearance_and_empty_lists_are_fine() -> None:
    assert [item for item, _ in rrf([[A], [], [C]])] == [A, C]
    assert rrf([]) == []
