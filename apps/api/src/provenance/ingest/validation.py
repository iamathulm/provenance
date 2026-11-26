"""Upload validation by content, not by extension.

Every rejection carries a stable code and a message that tells the user what to do next.
"""

import csv
import io
import zipfile
from dataclasses import dataclass
from pathlib import PurePath
from typing import Literal

import pymupdf
from openpyxl import load_workbook

from provenance.core.config import Settings
from provenance.core.errors import AppError, PayloadTooLargeError

FileKind = Literal["pdf", "docx", "pptx", "txt", "csv", "xlsx"]

_KIND_BY_EXTENSION: dict[str, FileKind] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
    ".txt": "txt",
    ".csv": "csv",
    ".xlsx": "xlsx",
}
MEDIA_TYPES: dict[FileKind, str] = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "txt": "text/plain",
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
_OOXML_MAIN_PART: dict[FileKind, str] = {
    "docx": "word/document.xml",
    "pptx": "ppt/presentation.xml",
    "xlsx": "xl/workbook.xml",
}
_OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # encrypted/legacy Office container
_MAX_UNPACKED_BYTES = 200 * 1024 * 1024
_SUPPORTED = ", ".join(_KIND_BY_EXTENSION)


class UploadRejectedError(AppError):
    status_code = 422

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ValidatedFile:
    kind: FileKind
    filename: str
    media_type: str
    content: bytes


def validate_upload(filename: str, content: bytes, settings: Settings) -> ValidatedFile:
    kind = _KIND_BY_EXTENSION.get(PurePath(filename).suffix.lower())
    if kind is None:
        raise UploadRejectedError(
            "unsupported_type", f"This file type is not supported. Upload one of: {_SUPPORTED}."
        )
    if not content:
        raise UploadRejectedError("empty_file", "The file is empty. Choose a file with content.")
    if len(content) > settings.max_file_bytes:
        limit_mb = settings.max_file_bytes // (1024 * 1024)
        msg = f"File is larger than the {limit_mb} MB limit. Split it or compress images."
        raise PayloadTooLargeError(msg)

    if kind == "pdf":
        _check_pdf(content, settings)
    elif kind in _OOXML_MAIN_PART:
        _check_ooxml(kind, content, settings)
    else:
        _check_text(kind, content, settings)
    return ValidatedFile(kind, filename, MEDIA_TYPES[kind], content)


def _mismatch(kind: FileKind) -> UploadRejectedError:
    return UploadRejectedError(
        "type_mismatch",
        f"The file's contents are not a valid .{kind} file. Check the extension or re-export it.",
    )


def _corrupt() -> UploadRejectedError:
    return UploadRejectedError(
        "corrupt_file", "The file could not be opened. It may be damaged; re-export and retry."
    )


def _encrypted() -> UploadRejectedError:
    return UploadRejectedError(
        "encrypted_file", "The file is password-protected. Remove the password and upload again."
    )


def _too_many_pages(settings: Settings) -> UploadRejectedError:
    return UploadRejectedError(
        "too_many_pages",
        f"The file has more than {settings.max_pages} pages or slides. Split it into parts.",
    )


def _too_many_rows(settings: Settings) -> UploadRejectedError:
    return UploadRejectedError(
        "too_many_rows",
        f"The table has more than {settings.max_table_rows} rows. Split it into smaller files.",
    )


def _check_pdf(content: bytes, settings: Settings) -> None:
    if not content.startswith(b"%PDF-"):
        raise _mismatch("pdf")
    try:
        document = pymupdf.open(stream=content, filetype="pdf")
    except (pymupdf.FileDataError, RuntimeError, ValueError) as error:
        raise _corrupt() from error
    with document:
        if document.needs_pass or document.is_encrypted:
            raise _encrypted()
        if document.page_count == 0:
            raise _corrupt()
        if document.page_count > settings.max_pages:
            raise _too_many_pages(settings)


def _check_ooxml(kind: FileKind, content: bytes, settings: Settings) -> None:
    if content.startswith(_OLE_SIGNATURE):
        raise _encrypted()
    if not zipfile.is_zipfile(io.BytesIO(content)):
        raise _mismatch(kind)
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = set(archive.namelist())
            if sum(info.file_size for info in archive.infolist()) > _MAX_UNPACKED_BYTES:
                raise _corrupt()
            if _OOXML_MAIN_PART[kind] not in names:
                raise _mismatch(kind)
            if kind == "pptx":
                slides = [n for n in names if n.startswith("ppt/slides/slide")]
                if len(slides) > settings.max_pages:
                    raise _too_many_pages(settings)
    except zipfile.BadZipFile as error:
        raise _corrupt() from error
    if kind == "xlsx":
        _check_xlsx_rows(content, settings)


def _check_xlsx_rows(content: bytes, settings: Settings) -> None:
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (zipfile.BadZipFile, KeyError, ValueError, OSError) as error:
        raise _corrupt() from error
    # Count rows by reading them: a sheet's declared <dimension> is supplied by the file itself.
    rows = 0
    try:
        for sheet in workbook.worksheets:
            for _ in sheet.iter_rows(min_row=2, values_only=True):
                rows += 1
                if rows > settings.max_table_rows:
                    raise _too_many_rows(settings)
    finally:
        workbook.close()


def _check_text(kind: FileKind, content: bytes, settings: Settings) -> None:
    if b"\x00" in content:
        raise _mismatch(kind)
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise UploadRejectedError(
            "not_utf8", "The file is not UTF-8 text. Re-save it with UTF-8 encoding."
        ) from error
    if kind == "csv":
        try:
            data_rows = sum(1 for _ in csv.reader(io.StringIO(text), csv_dialect(text))) - 1
        except csv.Error as error:
            raise _corrupt() from error
        if data_rows > settings.max_table_rows:
            raise _too_many_rows(settings)


def csv_dialect(text: str) -> type[csv.Dialect]:
    """The dialect both validation and parsing use for a CSV file."""
    try:
        return csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        return csv.excel
