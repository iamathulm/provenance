"""Reciprocal rank fusion: combine ranked lists without comparing their incompatible scores.

score(d) = sum over lists of 1 / (k + rank(d)), rank 1-based. k = 60 (Cormack et al., 2009) damps
the advantage of a single top rank so agreement between the dense and sparse branches wins.
"""

import uuid
from collections.abc import Sequence

RRF_K = 60


def rrf(rankings: Sequence[Sequence[uuid.UUID]], k: int = RRF_K) -> list[tuple[uuid.UUID, float]]:
    """Fused (id, score) pairs, best first; ties keep the order of first appearance."""
    scores: dict[uuid.UUID, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    order = {item: position for position, item in enumerate(scores)}
    return sorted(scores.items(), key=lambda pair: (-pair[1], order[pair[0]]))
