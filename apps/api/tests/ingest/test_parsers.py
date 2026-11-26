from pathlib import Path

import pyarrow as pa
import pytest

from provenance.core.config import Settings
from provenance.ingest.parsers import parse
from provenance.ingest.parsers.base import ParsedDocument, ParseFailedError
from provenance.ingest.validation import validate_upload
from provenance.profiles.loader import DomainProfile, load_profiles
from tests.ingest.samples import docx_bytes, pdf_bytes, pptx_bytes, xlsx_bytes


@pytest.fixture(scope="module")
def company() -> DomainProfile:
    return load_profiles(Path(__file__).resolve().parents[4] / "profiles")["company"]


def run(filename: str, content: bytes, profile: DomainProfile) -> ParsedDocument:
    return parse(validate_upload(filename, content, Settings(_env_file=None)), profile)


def test_pdf_page_anchors_and_low_text_warning(company: DomainProfile) -> None:
    parsed = run(
        "handbook.pdf",
        pdf_bytes(["Leave policy applies to all staff.", "", "Expenses are reimbursed monthly."]),
        company,
    )

    assert [(b.anchor.kind, b.anchor.page) for b in parsed.blocks] == [("page", 1), ("page", 3)]
    assert parsed.blocks[0].anchor.label == "p. 1"
    assert [w.code for w in parsed.warnings] == ["low_text_page"]
    assert parsed.warnings[0].anchor is not None
    assert parsed.warnings[0].anchor.page == 2
    assert parsed.unit_count == 3


def test_mostly_blank_pdf_flagged_as_scanned(company: DomainProfile) -> None:
    parsed = run("scan.pdf", pdf_bytes(["", "", "Only this page has text in it."]), company)

    assert parsed.warnings[0].code == "low_text_extraction"


def test_blank_pdf_fails_with_actionable_error(company: DomainProfile) -> None:
    with pytest.raises(ParseFailedError) as raised:
        run("blank.pdf", pdf_bytes(["", ""]), company)

    assert raised.value.code == "no_text_extracted"


def test_docx_heading_path(company: DomainProfile) -> None:
    parsed = run(
        "handbook.docx",
        docx_bytes(
            [
                ("Normal", "Welcome to Kestrel Ridge."),
                ("Heading 1", "Leave policy"),
                ("Heading 2", "Parental leave"),
                ("Normal", "Parents receive 16 weeks of paid leave."),
                ("Heading 1", "Expenses"),
                ("Normal", "Submit receipts within 30 days."),
            ]
        ),
        company,
    )

    assert [(b.anchor.kind, b.anchor.label) for b in parsed.blocks] == [
        ("none", "no section heading"),
        ("section", "Leave policy > Parental leave"),
        ("section", "Expenses"),
    ]


def test_pptx_slide_anchors_exclude_notes(company: DomainProfile) -> None:
    parsed = run(
        "review.pptx",
        pptx_bytes(
            [
                ("Q3 results", "Revenue grew 18 percent.", "Mention the delayed launch."),
                ("Roadmap", "Launch Talon X2 in Q1.", ""),
            ]
        ),
        company,
    )

    assert [b.anchor.label for b in parsed.blocks] == ["slide 1 · Q3 results", "slide 2 · Roadmap"]
    assert "delayed launch" not in " ".join(b.text for b in parsed.blocks)
    assert [w.code for w in parsed.warnings] == ["speaker_notes_excluded"]


def test_text_markdown_headings_and_plain_line_ranges(company: DomainProfile) -> None:
    markdown = run(
        "runbook.txt",
        b"# Drone recovery\n\n## Battery fault\nLand immediately.\nSwap the pack.\n",
        company,
    )
    plain = run("notes.txt", b"First note line.\nStill first.\n\nSecond note.\n", company)

    assert markdown.title == "Drone recovery"
    assert [(b.anchor.label, b.text) for b in markdown.blocks] == [
        ("Drone recovery > Battery fault", "Land immediately. Swap the pack.")
    ]
    assert [b.anchor.label for b in plain.blocks] == ["lines 1–2", "lines 4–4"]


def test_csv_row_anchors_with_repeated_header(company: DomainProfile) -> None:
    rows = "sku,price\n" + "".join(f"S{i},{i * 10}\n" for i in range(1, 46))
    parsed = run("pricing.csv", rows.encode(), company)

    cards = [b for b in parsed.blocks if b.text.startswith("Table pricing:")]
    groups = [b for b in parsed.blocks if b not in cards]
    assert len(cards) == 1
    assert [(g.anchor.row_start, g.anchor.row_end) for g in groups] == [(1, 20), (21, 40), (41, 45)]
    assert all("Columns: sku, price" in g.text for g in groups)
    assert "Row 21: sku: S21; price: 210" in groups[1].text
    table = parsed.tables[0]
    assert table.rows.schema.field("price").type == pa.int64()
    assert table.rows.num_rows == 45


def test_xlsx_values_and_row_anchors(company: DomainProfile) -> None:
    parsed = run(
        "sales.xlsx",
        xlsx_bytes(
            {
                "Q3": [
                    ["region", "revenue", "margin"],
                    ["EMEA", 120000, 0.31],
                    [None, None, None],
                    ["APAC", 98000, 0.27],
                ],
                "Empty": [],
            }
        ),
        company,
    )

    assert [t.name for t in parsed.tables] == ["Q3"]
    table = parsed.tables[0].rows
    assert table.num_rows == 2  # empty row skipped
    assert table.schema.field("revenue").type == pa.int64()
    assert table.schema.field("margin").type == pa.float64()
    group = parsed.blocks[-1]
    assert group.anchor.label == "Q3 · rows 1–2"
    assert "Row 2: region: APAC; revenue: 98000; margin: 0.27" in group.text
