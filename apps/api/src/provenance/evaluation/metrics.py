"""Ranking metrics over gold anchors, and seeded bootstrap confidence intervals.

`matched[i]` is the set of gold-anchor indexes the hit at rank i+1 satisfies. Relevance is binary
and each gold anchor counts once (a second chunk with the same evidence earns nothing).
"""

import math
import random
from collections.abc import Sequence

Matches = Sequence[frozenset[int]]


def recall_at_k(matched: Matches, gold_count: int, k: int, *, requires_all: bool) -> float:
    found = set().union(*matched[:k]) if matched[:k] else set()
    if requires_all:
        return len(found) / gold_count
    return 1.0 if found else 0.0


def mrr_at_k(matched: Matches, k: int) -> float:
    for rank, hit in enumerate(matched[:k], start=1):
        if hit:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(matched: Matches, gold_count: int, k: int, *, requires_all: bool) -> float:
    """Any-of items have one relevant result (the first alternative found); all-of items need
    every gold anchor, each earning gain once."""
    wanted = gold_count if requires_all else 1
    seen: set[int] = set()
    dcg = 0.0
    for rank, hit in enumerate(matched[:k], start=1):
        new = hit - seen
        if new and len(seen) < wanted:
            dcg += 1.0 / math.log2(rank + 1)
            seen |= new if requires_all else hit
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(wanted, k) + 1))
    return dcg / ideal if ideal else 0.0


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def bootstrap_ci(
    values: Sequence[float], *, resamples: int = 1000, seed: int = 0, level: float = 0.95
) -> tuple[float, float]:
    """Percentile bootstrap CI of the mean; deterministic for a given seed."""
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)  # noqa: S311 - statistics, not security
    n = len(values)
    means = sorted(mean([values[rng.randrange(n)] for _ in range(n)]) for _ in range(resamples))
    tail = (1.0 - level) / 2
    return (means[int(tail * resamples)], means[int((1.0 - tail) * resamples) - 1])
