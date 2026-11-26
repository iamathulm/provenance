"""Plain text: Markdown-style headings become the section path; otherwise line ranges anchor."""

import re

from provenance.ingest.parsers.base import Anchor, Block, ParsedDocument

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_WHITESPACE = re.compile(r"[ \t]+")


def split_paragraphs(text: str) -> list[str]:
    """Blank-line separated paragraphs with inner line breaks and runs of spaces collapsed."""
    paragraphs = []
    for raw in re.split(r"\n\s*\n", text):
        cleaned = _WHITESPACE.sub(" ", " ".join(line.strip() for line in raw.splitlines())).strip()
        if cleaned:
            paragraphs.append(cleaned)
    return paragraphs


def parse_text(content: bytes, fallback_title: str) -> ParsedDocument:
    lines = content.decode("utf-8-sig").splitlines()
    parsed = ParsedDocument(title=fallback_title, unit_count=len(lines))
    has_headings = any(_HEADING.match(line) for line in lines)
    path: list[str] = []
    buffer: list[str] = []
    first_line = 1

    def flush(last_line: int) -> None:
        text = " ".join(_WHITESPACE.sub(" ", line.strip()) for line in buffer).strip()
        if text:
            anchor = (
                Anchor.for_section(path)
                if has_headings
                else Anchor.for_lines(first_line, last_line)
            )
            parsed.blocks.append(Block(text, anchor))
        buffer.clear()

    for number, line in enumerate(lines, start=1):
        heading = _HEADING.match(line)
        if heading:
            flush(number - 1)
            level = len(heading.group(1))
            path[:] = [*path[: level - 1], heading.group(2)]
            if level == 1 and parsed.title == fallback_title:
                parsed.title = heading.group(2)
            first_line = number + 1
        elif not line.strip():
            flush(number - 1)
            first_line = number + 1
        else:
            if not buffer:
                first_line = number
            buffer.append(line)
    flush(len(lines))
    return parsed
