"""DOCX: paragraphs and tables in document order; headings define the section path."""

import io

from docx import Document as WordDocument
from docx.table import Table
from docx.text.paragraph import Paragraph

from provenance.ingest.parsers.base import Anchor, Block, ParsedDocument


def _heading_level(paragraph: Paragraph) -> int | None:
    style = paragraph.style.name if paragraph.style is not None else ""
    if style == "Title":
        return 1
    if style.startswith("Heading "):
        suffix = style.removeprefix("Heading ")
        return int(suffix) if suffix.isdigit() else None
    return None


def _table_text(table: Table) -> str:
    rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
    if not rows:
        return ""
    header, *body = rows
    lines = [" | ".join(header)]
    lines.extend(
        "; ".join(f"{col}: {value}" for col, value in zip(header, row, strict=False) if value)
        for row in body
    )
    return "\n".join(line for line in lines if line.strip())


def parse_docx(content: bytes, fallback_title: str) -> ParsedDocument:
    document = WordDocument(io.BytesIO(content))
    title = document.core_properties.title or fallback_title
    parsed = ParsedDocument(title=title, unit_count=0)
    path: list[str] = []
    for item in document.iter_inner_content():
        if isinstance(item, Table):
            text = _table_text(item)
            if text:
                parsed.blocks.append(Block(text, Anchor.for_section(path), is_table=True))
            continue
        text = item.text.strip()
        if not text:
            continue
        level = _heading_level(item)
        if level is not None:
            path[:] = [*path[: level - 1], text]
            continue
        parsed.blocks.append(Block(text, Anchor.for_section(path)))
    parsed.unit_count = len(parsed.blocks)
    return parsed
