import pytest

from provenance.documents.models import Chunk
from provenance.retrieval.router import route_query


def chunk(kind: str) -> Chunk:
    return Chunk(anchor_kind=kind, anchor_label="x", text="x", token_count=1, ordinal=0)


TABLE_TOP = [chunk("rows"), chunk("page")]
DOCS_ONLY = [chunk("page"), chunk("section")]


@pytest.mark.parametrize(
    ("question", "chunks", "has_tables", "expected"),
    [
        ("What was total revenue by region in Q3?", TABLE_TOP, True, "table"),
        ("How many tickets were opened in August?", TABLE_TOP, True, "table"),
        ("Which SKU is the Harrier Mini?", TABLE_TOP, True, "both"),
        ("What is the average warranty claim cost?", DOCS_ONLY, True, "both"),
        ("What is the battery fault procedure?", DOCS_ONLY, True, "docs"),
        ("How many seconds before landing after a battery fault?", DOCS_ONLY, False, "docs"),
    ],
)
def test_routes(question: str, chunks: list[Chunk], has_tables: bool, expected: str) -> None:
    route = route_query(question, chunks, has_tables)

    assert route.kind == expected
    assert route.reasons


def test_table_hit_must_be_near_the_top() -> None:
    late = [*DOCS_ONLY * 3, chunk("rows")]

    assert route_query("What is the refund policy?", late, True).kind == "docs"
