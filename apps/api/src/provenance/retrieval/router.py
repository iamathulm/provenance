"""Rule-based query routing: answer from documents, from tables (SQL), or both. No LLM call.

Two signals: the question's wording asks for a computation over rows, and retrieval already
surfaced a table chunk near the top. Wording comes in two strengths. Strong wording (totals,
counts, averages, per-group breakdowns) is a computation on its own. Weak wording (superlatives
such as "maximum" or "most") is just as often a spec value in prose ("the maximum payload"), so it
counts only when a table chunk is also near the top. Both signals → `table`; one, in a workspace
that has tables → `both`; otherwise → `docs`. Reasons are returned so the choice is explainable.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from provenance.documents.models import Chunk

RouteKind = Literal["docs", "table", "both"]
TABLE_HIT_WINDOW = 3

STRONG_AGGREGATE = re.compile(
    r"\b(how many|how much|total|sum|average|avg|mean|median|count|number of|"
    r"top \d+|bottom \d+|"
    r"per (?:region|team|month|quarter|product|customer|category)|"
    r"by (?:region|team|month|quarter|product|customer|category)|percent(?:age)?|share of|"
    r"greater than|less than|more than|fewer than|over \$?\d|under \$?\d|between \$?\d)\b",
    re.IGNORECASE,
)
WEAK_AGGREGATE = re.compile(
    r"\b(highest|lowest|largest|smallest|most|least|maximum|minimum|max|min|rank|ranking)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Route:
    kind: RouteKind
    reasons: list[str]


def route_query(question: str, chunks: Sequence[Chunk], workspace_has_tables: bool) -> Route:
    if not workspace_has_tables:
        return Route("docs", ["workspace has no tables"])
    strong = STRONG_AGGREGATE.search(question)
    weak = WEAK_AGGREGATE.search(question)
    table_rank = next(
        (rank for rank, c in enumerate(chunks[:TABLE_HIT_WINDOW], 1) if c.anchor_kind == "rows"),
        None,
    )
    reasons = []
    if strong:
        reasons.append(f"strong aggregate '{strong.group(0).lower()}'")
    if weak:
        reasons.append(f"weak aggregate '{weak.group(0).lower()}'")
    if table_rank is not None:
        reasons.append(f"table chunk at rank {table_rank}")
    if table_rank is not None and (strong or weak):
        return Route("table", reasons)
    if strong or table_rank is not None:
        return Route("both", reasons)
    if weak:
        return Route("docs", [*reasons, "weak wording without a table chunk near the top"])
    return Route("docs", ["no aggregate wording and no table chunk near the top"])
