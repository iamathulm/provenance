"""Dispatch a validated upload to its format parser.

A file can pass validation (right container, right main part) and still be malformed inside.
Library errors from such files become a permanent `corrupt_file` failure with a user-facing
message, rather than a transient error that would be retried pointlessly.
"""

from pathlib import PurePath

import structlog

from provenance.ingest.parsers.base import ParsedDocument, ParseFailedError
from provenance.ingest.parsers.docx import parse_docx
from provenance.ingest.parsers.pdf import parse_pdf
from provenance.ingest.parsers.pptx import parse_pptx
from provenance.ingest.parsers.tables import parse_csv, parse_xlsx
from provenance.ingest.parsers.text import parse_text
from provenance.ingest.validation import ValidatedFile
from provenance.profiles.loader import DomainProfile

log = structlog.get_logger()


def _dispatch(validated: ValidatedFile, profile: DomainProfile, max_rows: int) -> ParsedDocument:
    title = PurePath(validated.filename).stem
    rows_per_chunk = profile.chunking.table_rows_per_chunk
    content = validated.content
    match validated.kind:
        case "pdf":
            return parse_pdf(content, title)
        case "docx":
            return parse_docx(content, title)
        case "pptx":
            return parse_pptx(content, title)
        case "txt":
            return parse_text(content, title)
        case "csv":
            return parse_csv(content, title, rows_per_chunk, max_rows)
        case "xlsx":
            return parse_xlsx(content, title, rows_per_chunk, max_rows)


def parse(
    validated: ValidatedFile, profile: DomainProfile, *, max_table_rows: int
) -> ParsedDocument:
    try:
        parsed = _dispatch(validated, profile, max_table_rows)
    except ParseFailedError:
        raise
    except Exception as error:
        log.warning("parse_failed", kind=validated.kind, error_class=type(error).__name__)
        raise ParseFailedError(
            "corrupt_file", "The file could not be read. It may be damaged; re-export and retry."
        ) from error
    if not parsed.blocks:
        raise ParseFailedError(
            "no_text_extracted",
            "No text could be extracted from this file. Scanned documents are not supported.",
        )
    return parsed
