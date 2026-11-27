"""Context packing: turn authorized search hits and SQL rows into numbered, delimited sources.

Sources are untrusted data. Each is wrapped in a `<source>` element whose closing tag cannot be
forged from inside the text, near-duplicate chunks are dropped, and the total stays within a word
budget so one answer fits the free tier's tokens-per-minute.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from provenance.retrieval.search import Hit
from provenance.structured.engine import QueryResult

DUPLICATE_JACCARD = 0.8
_MAX_TABLE_ROWS = 30


@dataclass(frozen=True)
class Source:
    id: str  # "S1", "S2", ...
    kind: Literal["chunk", "rows"]
    title: str
    location: str
    text: str
    document_id: uuid.UUID
    version_id: uuid.UUID | None = None
    chunk_id: uuid.UUID | None = None
    sheet: str | None = None
    rows: tuple[int, ...] = field(default_factory=tuple)

    def render(self) -> str:
        safe = self.text.replace("</source", "&lt;/source")
        title = self.title.replace('"', "'")
        location = self.location.replace('"', "'")
        return f'<source id="{self.id}" title="{title}" location="{location}">\n{safe}\n</source>'


def _words(text: str) -> set[str]:
    return set(text.lower().split())


def _near_duplicate(text: str, kept: list[set[str]]) -> bool:
    words = _words(text)
    for other in kept:
        union = words | other
        if union and len(words & other) / len(union) >= DUPLICATE_JACCARD:
            return True
    return False


def pack_chunks(
    hits: Sequence[Hit], *, max_sources: int, max_words: int, first_number: int = 1
) -> list[Source]:
    sources: list[Source] = []
    kept: list[set[str]] = []
    words_used = 0
    for hit in hits:
        if len(sources) == max_sources:
            break
        text = hit.chunk.text
        size = len(text.split())
        if words_used + size > max_words or _near_duplicate(text, kept):
            continue
        kept.append(_words(text))
        words_used += size
        sources.append(
            Source(
                id=f"S{first_number + len(sources)}",
                kind="chunk",
                title=hit.document.title,
                location=hit.chunk.anchor_label,
                text=text,
                document_id=hit.document.id,
                version_id=hit.chunk.version_id,
                chunk_id=hit.chunk.id,
            )
        )
    return sources


def rows_source(result: QueryResult, number: int) -> Source | None:
    """One source for a SQL result; row-citable when the result carries row references."""
    if not result.rows or not result.tables:
        return None
    lines = [" | ".join(result.columns)]
    lines += [
        " | ".join("" if v is None else str(v) for v in row)
        for row in result.rows[:_MAX_TABLE_ROWS]
    ]
    if len(result.rows) > _MAX_TABLE_ROWS or result.truncated:
        lines.append(f"(first {min(len(result.rows), _MAX_TABLE_ROWS)} rows shown)")
    first = result.tables[0]
    titles = sorted({f"{t.document_title} · {t.sheet}" for t in result.tables})
    return Source(
        id=f"S{number}",
        kind="rows",
        title=", ".join(titles),
        location=f"SQL: {result.sql}",
        text="\n".join(lines),
        document_id=first.document_id,
        version_id=first.version_id,
        sheet=first.sheet,
        rows=tuple(ref.row for ref in result.row_refs),
    )
