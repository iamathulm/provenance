import io
import zipfile

import pytest

from provenance.core.config import Settings
from provenance.core.errors import PayloadTooLargeError
from provenance.ingest.validation import UploadRejectedError, validate_upload
from tests.ingest.samples import docx_bytes, pdf_bytes, pptx_bytes, xlsx_bytes


@pytest.mark.parametrize(
    ("filename", "content", "kind", "media_type"),
    [
        ("report.pdf", pdf_bytes(["Quarterly report"]), "pdf", "application/pdf"),
        (
            "spec.docx",
            docx_bytes([("Normal", "Spec")]),
            "docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (
            "deck.PPTX",
            pptx_bytes([("Title", "Body", "")]),
            "pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
        ("notes.txt", b"Runbook\nStep one", "txt", "text/plain"),
        ("pricing.csv", b"sku,price\nA1,10\n", "csv", "text/csv"),
        (
            "sales.xlsx",
            xlsx_bytes({"Q3": [["region", "revenue"], ["EMEA", 10]]}),
            "xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
    ],
)
def test_accepts_each_supported_kind(
    filename: str, content: bytes, kind: str, media_type: str, settings: Settings
) -> None:
    validated = validate_upload(filename, content, settings)

    assert (validated.kind, validated.media_type) == (kind, media_type)


def _rejection(filename: str, content: bytes, settings: Settings) -> str:
    with pytest.raises(UploadRejectedError) as raised:
        validate_upload(filename, content, settings)
    return raised.value.code


def test_type_mismatch_and_binary_txt_rejected(settings: Settings) -> None:
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as archive:
        archive.writestr("readme.md", "not a pdf")

    assert _rejection("report.pdf", zip_buffer.getvalue(), settings) == "type_mismatch"
    assert _rejection("spec.docx", pdf_bytes(["x"]), settings) == "type_mismatch"
    assert _rejection("deck.pptx", docx_bytes([("Normal", "x")]), settings) == "type_mismatch"
    assert _rejection("notes.txt", b"\x89PNG\r\n\x1a\n\x00\x00binary", settings) == "type_mismatch"


@pytest.mark.parametrize(
    ("filename", "content", "code"),
    [
        ("empty.pdf", b"", "empty_file"),
        ("photo.png", b"\x89PNG\r\n", "unsupported_type"),
        ("noext", b"hello", "unsupported_type"),
        ("broken.pdf", b"%PDF-1.7\n1 0 obj << /Type /Catalog", "corrupt_file"),
        ("prices.csv", "café,prix\n".encode("latin-1"), "not_utf8"),
        ("legacy.docx", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64, "encrypted_file"),
    ],
)
def test_rejections_are_actionable(
    filename: str, content: bytes, code: str, settings: Settings
) -> None:
    with pytest.raises(UploadRejectedError) as raised:
        validate_upload(filename, content, settings)

    assert raised.value.code == code
    assert raised.value.status_code == 422
    assert raised.value.message.endswith(".")


def test_encrypted_pdf_rejected(settings: Settings) -> None:
    assert _rejection("locked.pdf", pdf_bytes(["secret"], password="pw"), settings) == (
        "encrypted_file"
    )


def test_page_and_row_limits(settings: Settings) -> None:
    limited = settings.model_copy(update={"max_pages": 2, "max_table_rows": 3})

    assert _rejection("long.pdf", pdf_bytes(["a", "b", "c"]), limited) == "too_many_pages"
    assert _rejection("big.csv", b"h\n1\n2\n3\n4\n", limited) == "too_many_rows"
    rows: list[list[object]] = [["h"], [1], [2], [3], [4]]
    assert _rejection("big.xlsx", xlsx_bytes({"S": rows}), limited) == "too_many_rows"


def test_oversized_file_is_413(settings: Settings) -> None:
    tiny = settings.model_copy(update={"max_file_bytes": 4})

    with pytest.raises(PayloadTooLargeError):
        validate_upload("notes.txt", b"12345", tiny)
