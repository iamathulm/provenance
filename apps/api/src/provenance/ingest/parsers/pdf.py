"""PDF: one anchor per page; pages without extractable text are reported, never guessed."""

import pymupdf

from provenance.ingest.parsers.base import Anchor, Block, ParsedDocument, ParseWarning
from provenance.ingest.parsers.text import split_paragraphs

MIN_PAGE_CHARS = 20


def parse_pdf(content: bytes, fallback_title: str) -> ParsedDocument:
    with pymupdf.open(stream=content, filetype="pdf") as document:
        title = (document.metadata or {}).get("title") or fallback_title
        parsed = ParsedDocument(title=title, unit_count=document.page_count)
        low_text_pages = 0
        for number, page in enumerate(document, start=1):
            anchor = Anchor.for_page(number)
            text = page.get_text("text")
            if len(text.strip()) < MIN_PAGE_CHARS:
                low_text_pages += 1
                parsed.warnings.append(
                    ParseWarning("low_text_page", f"Page {number} has no extractable text.", anchor)
                )
            parsed.blocks.extend(Block(p, anchor) for p in split_paragraphs(text))
    if low_text_pages * 2 > parsed.unit_count:
        parsed.warnings.insert(
            0,
            ParseWarning(
                "low_text_extraction",
                "Most pages have no extractable text; this looks scanned. OCR is not supported.",
            ),
        )
    return parsed
