import pytest

from provenance.core.config import Settings
from provenance.retrieval.rerank import FlashRanker


@pytest.mark.slow
def test_flashrank_prefers_the_relevant_passage(settings: Settings) -> None:
    ranker = FlashRanker(settings)

    scores = ranker.score(
        "How long may a drone hover after a battery fault?",
        [
            "Expense reports are due within 30 days of travel.",
            "After a battery fault, land within 90 seconds and swap the pack.",
        ],
    )

    assert scores[1] > scores[0]
    assert ranker.score("anything", []) == []
