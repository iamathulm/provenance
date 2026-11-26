"""Dispatch a validated upload to its format parser."""

from pathlib import PurePath

from provenance.ingest.parsers.base import ParsedDocument, ParseFailedError
from provenance.ingest.parsers.docx import parse_docx
from provenance.ingest.parsers.pdf import parse_pdf
from provenance.ingest.parsers.pptx import parse_pptx
from provenance.ingest.parsers.tables import parse_csv, parse_xlsx
from provenance.ingest.parsers.text import parse_text
from provenance.ingest.validation import ValidatedFile
from provenance.profiles.loader import DomainProfile


def parse(validated: ValidatedFile, profile: DomainProfile) -> ParsedDocument:
    title = PurePath(validated.filename).stem
    rows_per_chunk = profile.chunking.table_rows_per_chunk
    content = validated.content
    match validated.kind:
        case "pdf":
            parsed = parse_pdf(content, title)
        case "docx":
            parsed = parse_docx(content, title)
        case "pptx":
            parsed = parse_pptx(content, title)
        case "txt":
            parsed = parse_text(content, title)
        case "csv":
            parsed = parse_csv(content, title, rows_per_chunk)
        case "xlsx":
            parsed = parse_xlsx(content, title, rows_per_chunk)
    if not parsed.blocks:
        raise ParseFailedError(
            "no_text_extracted",
            "No text could be extracted from this file. Scanned documents are not supported.",
        )
    return parsed
