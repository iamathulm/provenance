"""PPTX: one anchor per slide; speaker notes are deliberately not indexed (and the user is told)."""

import io

from pptx import Presentation
from pptx.shapes.base import BaseShape

from provenance.ingest.parsers.base import Anchor, Block, ParsedDocument, ParseWarning


def _shape_texts(shape: BaseShape) -> list[str]:
    if getattr(shape, "has_table", False):
        table = shape.table  # type: ignore[attr-defined]
        return [" | ".join(cell.text.strip() for cell in row.cells) for row in table.rows]
    if getattr(shape, "has_text_frame", False):
        text: str = shape.text_frame.text  # type: ignore[attr-defined]
        return [line.strip() for line in text.splitlines() if line.strip()]
    return []


def parse_pptx(content: bytes, fallback_title: str) -> ParsedDocument:
    deck = Presentation(io.BytesIO(content))
    parsed = ParsedDocument(
        title=deck.core_properties.title or fallback_title, unit_count=len(deck.slides)
    )
    notes_seen = False
    for number, slide in enumerate(deck.slides, start=1):
        title_shape = slide.shapes.title
        title = title_shape.text.strip() if title_shape is not None else ""
        anchor = Anchor.for_slide(number, title)
        lines = [
            line
            for shape in slide.shapes
            if shape is not title_shape
            for line in _shape_texts(shape)
        ]
        text = " ".join([title, *lines]).strip() if title else " ".join(lines).strip()
        if text:
            parsed.blocks.append(Block(text, anchor))
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip():
            notes_seen = True
    if notes_seen:
        parsed.warnings.append(
            ParseWarning("speaker_notes_excluded", "Speaker notes are not indexed or searchable.")
        )
    return parsed
