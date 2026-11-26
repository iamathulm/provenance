"""Render the Kestrel Ridge Systems demo corpus from YAML sources into real office files.

Sources live in `data/company/source/*.yaml`; output goes to `data/company/files/`. Output is
byte-for-byte deterministic (fixed metadata timestamps, fixed ZIP entry dates, seeded generators),
so committed files only change when their source changes.
"""

import csv
import io
import random
import re
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pymupdf
import yaml
from docx import Document as WordDocument
from openpyxl import Workbook
from pptx import Presentation

FIXED_TIME = datetime(2026, 10, 1, 9, 0, 0)
AUTHOR = "Kestrel Ridge Systems"
FIXED_ISO = "2026-10-01T09:00:00Z"
# openpyxl stamps the save time into core.xml; pin it so builds are reproducible.
_CORE_TIMESTAMP = re.compile(
    r"(<dcterms:(?:created|modified)[^>]*>)[^<]*(</dcterms:(?:created|modified)>)"
)
_PDF_CSS = """
body { font-family: sans-serif; font-size: 11pt; line-height: 1.45; }
h1 { font-size: 20pt; margin-bottom: 12pt; }
h2 { font-size: 14pt; margin-top: 14pt; }
h3 { font-size: 12pt; margin-top: 10pt; }
"""

Source = dict[str, Any]


def _normalized_zip(data: bytes) -> bytes:
    """Rewrite an OOXML package with fixed entry timestamps so builds are reproducible."""
    output = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(data)) as source,
        zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for item in source.infolist():
            entry = zipfile.ZipInfo(item.filename, date_time=FIXED_TIME.timetuple()[:6])
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            content = source.read(item.filename)
            if item.filename == "docProps/core.xml":
                pinned = _CORE_TIMESTAMP.sub(rf"\g<1>{FIXED_ISO}\g<2>", content.decode())
                content = pinned.encode()
            target.writestr(entry, content)
    return output.getvalue()


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_pdf(source: Source) -> bytes:
    html = "".join(
        f"<h{s['level']}>{_escape(s['heading'])}</h{s['level']}>"
        + "".join(f"<p>{_escape(p)}</p>" for p in s.get("paragraphs", []))
        for s in source["sections"]
    )
    story = pymupdf.Story(html=html, user_css=_PDF_CSS)
    buffer = io.BytesIO()
    writer = pymupdf.DocumentWriter(buffer)
    mediabox = pymupdf.paper_rect("letter")
    margin = 60
    content_area = pymupdf.Rect(
        mediabox.x0 + margin, mediabox.y0 + margin, mediabox.x1 - margin, mediabox.y1 - margin
    )
    more = True
    while more:
        device = writer.begin_page(mediabox)
        more, _ = story.place(content_area)
        story.draw(device)
        writer.end_page()
    writer.close()
    stamp = FIXED_TIME.strftime("D:%Y%m%d%H%M%S")
    with pymupdf.open(stream=buffer.getvalue(), filetype="pdf") as document:
        document.set_metadata(
            {
                "title": source["title"],
                "author": AUTHOR,
                "creator": AUTHOR,
                "producer": AUTHOR,
                "creationDate": stamp,
                "modDate": stamp,
            }
        )
        data: bytes = document.tobytes(garbage=3, deflate=True, no_new_id=True)
    return data


def render_docx(source: Source) -> bytes:
    document = WordDocument()
    properties = document.core_properties
    properties.title, properties.author, properties.last_modified_by = (
        source["title"],
        AUTHOR,
        AUTHOR,
    )
    properties.created = properties.modified = properties.last_printed = FIXED_TIME
    for section in source["sections"]:
        document.add_heading(section["heading"], level=section["level"])
        for paragraph in section.get("paragraphs", []):
            document.add_paragraph(paragraph)
    buffer = io.BytesIO()
    document.save(buffer)
    return _normalized_zip(buffer.getvalue())


def render_pptx(source: Source) -> bytes:
    deck = Presentation()
    properties = deck.core_properties
    properties.title, properties.author, properties.last_modified_by = (
        source["title"],
        AUTHOR,
        AUTHOR,
    )
    properties.created = properties.modified = properties.last_printed = FIXED_TIME
    for spec in source["slides"]:
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = spec["title"]
        body = slide.placeholders[1].text_frame
        body.text = spec["bullets"][0]
        for bullet in spec["bullets"][1:]:
            body.add_paragraph().text = bullet
        if spec.get("notes"):
            slide.notes_slide.notes_text_frame.text = spec["notes"]
    buffer = io.BytesIO()
    deck.save(buffer)
    return _normalized_zip(buffer.getvalue())


def render_xlsx(source: Source) -> bytes:
    workbook = Workbook()
    if workbook.active is not None:
        workbook.remove(workbook.active)
    workbook.properties.title = source["title"]
    workbook.properties.creator = workbook.properties.lastModifiedBy = AUTHOR
    workbook.properties.created = workbook.properties.modified = FIXED_TIME
    for name, sheet_spec in source["sheets"].items():
        sheet = workbook.create_sheet(name)
        sheet.append(sheet_spec["columns"])
        for row in sheet_spec["rows"]:
            sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return _normalized_zip(buffer.getvalue())


def _csv(columns: list[str], rows: list[list[Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _days(spec: Source) -> int:
    return (date.fromisoformat(str(spec["end"])) - date.fromisoformat(str(spec["start"]))).days


def _support_tickets(spec: Source) -> tuple[list[str], list[list[Any]]]:
    rng = random.Random(spec["seed"])  # noqa: S311 - deterministic demo data, not security
    start = date.fromisoformat(str(spec["start"]))
    rows = []
    for number in range(1, spec["rows"] + 1):
        opened = start + timedelta(days=rng.randint(0, _days(spec)))
        severity = rng.choices(spec["severities"], spec["severity_weights"])[0]
        hours = {"S1": (2, 10), "S2": (4, 30), "S3": (8, 48), "S4": (12, 96)}[severity]
        resolved = rng.random() > 0.08
        rows.append(
            [
                f"KR-{number:05d}",
                opened.isoformat(),
                rng.choices(spec["products"], spec["product_weights"])[0],
                rng.choices(spec["categories"], spec["category_weights"])[0],
                severity,
                "resolved" if resolved else "open",
                rng.randint(*hours) if resolved else "",
            ]
        )
    columns = [
        "ticket_id",
        "opened",
        "product",
        "category",
        "severity",
        "status",
        "hours_to_resolve",
    ]
    return columns, rows


def _warranty_claims(spec: Source) -> tuple[list[str], list[list[Any]]]:
    rng = random.Random(spec["seed"])  # noqa: S311 - deterministic demo data, not security
    start = date.fromisoformat(str(spec["start"]))
    costs = {
        "battery swelling": (240, 1150),
        "motor failure": (310, 640),
        "gimbal fault": (420, 1900),
        "compass error": (90, 260),
        "water ingress": (600, 2400),
        "arm crack": (150, 480),
    }
    rows = []
    for number in range(1, spec["rows"] + 1):
        mode = rng.choices(spec["failure_modes"], spec["failure_weights"])[0]
        approved = rng.random() > 0.15
        rows.append(
            [
                f"WC-{number:04d}",
                (start + timedelta(days=rng.randint(0, _days(spec)))).isoformat(),
                rng.choices(spec["products"], spec["product_weights"])[0],
                mode,
                rng.randint(1, 23),
                "yes" if approved else "no",
                rng.randint(*costs[mode]) if approved else 0,
            ]
        )
    columns = [
        "claim_id",
        "filed",
        "product",
        "failure_mode",
        "months_in_service",
        "approved",
        "cost_usd",
    ]
    return columns, rows


_GENERATORS = {"support_tickets": _support_tickets, "warranty_claims": _warranty_claims}


def render(source: Source) -> bytes:
    suffix = Path(source["filename"]).suffix
    if suffix == ".pdf":
        return render_pdf(source)
    if suffix == ".docx":
        return render_docx(source)
    if suffix == ".pptx":
        return render_pptx(source)
    if suffix == ".xlsx":
        return render_xlsx(source)
    if suffix == ".txt":
        return str(source["text"]).encode("utf-8")
    if "generated" in source:
        columns, rows = _GENERATORS[source["generated"]["kind"]](source["generated"])
        return _csv(columns, rows)
    return _csv(source["table"]["columns"], source["table"]["rows"])


def build(source_dir: Path, output_dir: Path) -> list[Path]:
    """Render every source; returns the written paths in a stable order."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for path in sorted(source_dir.glob("*.yaml")):
        source: Source = yaml.safe_load(path.read_text(encoding="utf-8"))
        target = output_dir / source["filename"]
        target.write_bytes(render(source))
        written.append(target)
    return written
