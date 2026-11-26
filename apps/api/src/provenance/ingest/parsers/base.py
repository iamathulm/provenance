"""Parser output model: text blocks carrying the provenance anchor a citation will show."""

from dataclasses import dataclass, field
from typing import Literal

import pyarrow as pa

AnchorKind = Literal["page", "slide", "section", "rows", "none"]


@dataclass(frozen=True)
class Anchor:
    kind: AnchorKind
    label: str
    page: int | None = None
    slide: int | None = None
    section_path: str | None = None
    sheet: str | None = None
    row_start: int | None = None
    row_end: int | None = None

    @classmethod
    def for_page(cls, number: int) -> "Anchor":
        return cls("page", f"p. {number}", page=number)

    @classmethod
    def for_slide(cls, number: int, title: str) -> "Anchor":
        label = f"slide {number}" + (f" · {title}" if title else "")
        return cls("slide", label[:255], slide=number)

    @classmethod
    def for_section(cls, path: list[str]) -> "Anchor":
        if not path:
            return cls("none", "no section heading")
        joined = " > ".join(path)
        return cls("section", joined[:255], section_path=joined[:500])

    @classmethod
    def for_lines(cls, first: int, last: int) -> "Anchor":
        return cls("section", f"lines {first}–{last}")

    @classmethod
    def for_rows(cls, sheet: str, first: int, last: int) -> "Anchor":
        return cls(
            "rows",
            f"{sheet} · rows {first}–{last}"[:255],
            sheet=sheet,
            row_start=first,
            row_end=last,
        )


@dataclass(frozen=True)
class Block:
    text: str
    anchor: Anchor
    is_table: bool = False


@dataclass(frozen=True)
class ParseWarning:
    code: str
    message: str
    anchor: Anchor | None = None


@dataclass(frozen=True)
class ParsedTable:
    name: str
    columns: list[str]
    rows: pa.Table


@dataclass
class ParsedDocument:
    title: str
    unit_count: int  # pages, slides, lines or table rows
    blocks: list[Block] = field(default_factory=list)
    tables: list[ParsedTable] = field(default_factory=list)
    warnings: list[ParseWarning] = field(default_factory=list)


class ParseFailedError(Exception):
    """The file passed validation but its content could not be extracted (permanent failure)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
