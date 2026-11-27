"""Rule-based query routing: answer from documents, from tables (SQL), or both. No LLM call.

Two signals: the question asks for a computation (totals, counts, rankings, comparisons over rows),
and retrieval already surfaced a table chunk near the top. Both → `table`; one, in a workspace that
has tables → `both`; otherwise → `docs`. Reasons are returned so the choice is explainable.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from provenance.documents.models import Chunk

RouteKind = Literal["docs", "table", "both"]
TABLE_HIT_WINDOW = 5

_AGGREGATE = re.compile(
    r"\b(how many|how much|total|sum|average|avg|mean|median|count|number of|"
    r"highest|lowest|largest|smallest|most|least|top \d+|bottom \d+|maximum|minimum|max|min|"
    r"rank|ranking|per (?:region|team|month|quarter|product|customer|category)|"
    r"by (?:region|team|month|quarter|product|customer|category)|percent(?:age)?|share of|"
    r"greater than|less than|more than|fewer than|over \$?\d|under \$?\d|between \$?\d)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Route:
    kind: RouteKind
    reasons: list[str]


def route_query(question: str, chunks: Sequence[Chunk], workspace_has_tables: bool) -> Route:
    if not workspace_has_tables:
        return Route("docs", ["workspace has no tables"])
    aggregate = _AGGREGATE.search(question)
    table_hit = any(chunk.anchor_kind == "rows" for chunk in chunks[:TABLE_HIT_WINDOW])
    reasons = []
    if aggregate:
        reasons.append(f"aggregate wording '{aggregate.group(0).lower()}'")
    if table_hit:
        reasons.append(f"table chunk in top {TABLE_HIT_WINDOW} results")
    if aggregate and table_hit:
        return Route("table", reasons)
    if aggregate or table_hit:
        return Route("both", reasons)
    return Route("docs", ["no aggregate wording and no table chunk near the top"])
