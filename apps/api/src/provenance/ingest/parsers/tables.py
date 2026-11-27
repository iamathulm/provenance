"""CSV/XLSX: each sheet becomes a typed table (Parquet for SQL) plus searchable text blocks —
one table card describing it, then row groups that repeat the header and anchor to row ranges.

Row numbers are the ones the user sees in their spreadsheet (1-based, counting the header and any
blank rows), so a citation like "Q3 · rows 3–4" points at the right cells.
"""

import csv
import io
import re
from collections.abc import Iterable, Iterator
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

import pyarrow as pa
from openpyxl import load_workbook

from provenance.ingest.parsers.base import (
    Anchor,
    Block,
    ParsedDocument,
    ParsedTable,
    ParseFailedError,
)
from provenance.ingest.validation import csv_dialect

_SAMPLE_ROWS = 3
ROW_COLUMN = "_row"  # spreadsheet row number of each record, for row-level SQL citations
Cell = str | int | float | bool | None
NumberedRow = tuple[int, list[Cell]]


def too_many_rows(limit: int) -> ParseFailedError:
    return ParseFailedError(
        "too_many_rows", f"The table has more than {limit} rows. Split it into smaller files."
    )


def _column_names(header: list[Cell]) -> list[str]:
    names: list[str] = []
    taken = {ROW_COLUMN}
    for index, raw in enumerate(header, start=1):
        base = re.sub(r"\s+", " ", str(raw).strip()) if raw not in (None, "") else ""
        name = base or f"column_{index}"
        candidate, suffix = name, 2
        while candidate in taken:
            candidate, suffix = f"{name}_{suffix}", suffix + 1
        names.append(candidate)
        taken.add(candidate)
    return names


def _typed_column(values: list[Cell]) -> "pa.Array[Any]":
    present = [v for v in values if v is not None and v != ""]
    if present and all(isinstance(v, bool) for v in present):
        return pa.array([v if v != "" else None for v in values], pa.bool_())
    if present and all(isinstance(v, int) and not isinstance(v, bool) for v in present):
        return pa.array([v if v != "" else None for v in values], pa.int64())
    if present and all(isinstance(v, int | float) and not isinstance(v, bool) for v in present):
        return pa.array([float(v) if v not in (None, "") else None for v in values], pa.float64())
    return pa.array([None if v in (None, "") else str(v) for v in values], pa.string())


def _format(value: Cell) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return "" if value is None else str(value)


def _row_text(columns: list[str], row: list[Cell]) -> str:
    return "; ".join(f"{c}: {_format(v)}" for c, v in zip(columns, row, strict=False) if v != "")


def _non_empty(rows: Iterable[NumberedRow], max_rows: int) -> list[NumberedRow]:
    """Drop blank rows; stop as soon as the data rows (after the header) exceed `max_rows`."""
    kept: list[NumberedRow] = []
    for number, row in rows:
        if any(v not in (None, "") for v in row):
            kept.append((number, row))
            if len(kept) - 1 > max_rows:
                raise too_many_rows(max_rows)
    return kept


def _add_table(
    parsed: ParsedDocument,
    name: str,
    rows: Iterable[NumberedRow],
    rows_per_chunk: int,
    max_rows: int,
) -> None:
    numbered = _non_empty(rows, max_rows)
    if not numbered:
        return
    (header_number, header), *data = numbered
    columns = _column_names(header)
    width = len(columns)
    data = [(number, (list(row) + [None] * width)[:width]) for number, row in data]
    arrays = [_typed_column([row[i] for _, row in data]) for i in range(width)]
    row_numbers = pa.array([number for number, _ in data], pa.int64())
    table = pa.table([row_numbers, *arrays], names=[ROW_COLUMN, *columns])
    parsed.tables.append(ParsedTable(name, columns, table))

    sample = "\n".join(_row_text(columns, row) for _, row in data[:_SAMPLE_ROWS])
    card = f"Table {name}: {len(data)} rows. Columns: {', '.join(columns)}." + (
        f"\nSample rows:\n{sample}" if sample else ""
    )
    sample_end = data[min(len(data), _SAMPLE_ROWS) - 1][0] if data else header_number
    parsed.blocks.append(Block(card, Anchor.for_rows(name, header_number, sample_end), True))
    for start in range(0, len(data), rows_per_chunk):
        group = data[start : start + rows_per_chunk]
        first, last = group[0][0], group[-1][0]
        lines = [f"Table {name}, rows {first}–{last}. Columns: {', '.join(columns)}."]
        lines.extend(f"Row {number}: {_row_text(columns, row)}" for number, row in group)
        parsed.blocks.append(Block("\n".join(lines), Anchor.for_rows(name, first, last), True))
    parsed.unit_count += len(data)


def _cell(value: object) -> Cell:
    """Normalize spreadsheet values: dates become ISO strings, decimals floats, others text."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date | datetime | time):
        return value.isoformat()
    return str(value)


def _coerce(value: str) -> Cell:
    stripped = value.strip()
    if re.fullmatch(r"-?\d+", stripped):
        return int(stripped)
    if re.fullmatch(r"-?\d*\.\d+", stripped):
        return float(stripped)
    return stripped


def _csv_rows(text: str) -> Iterator[NumberedRow]:
    reader = csv.reader(io.StringIO(text), csv_dialect(text))
    try:
        for row in reader:
            yield reader.line_num, [_coerce(v) for v in row]
    except csv.Error as error:
        raise ParseFailedError(
            "corrupt_file", "The CSV could not be read. Check quoting and very long fields."
        ) from error


def parse_csv(
    content: bytes, fallback_title: str, rows_per_chunk: int, max_rows: int
) -> ParsedDocument:
    parsed = ParsedDocument(title=fallback_title, unit_count=0)
    rows = _csv_rows(content.decode("utf-8-sig"))
    _add_table(parsed, fallback_title, rows, rows_per_chunk, max_rows)
    return parsed


def parse_xlsx(
    content: bytes, fallback_title: str, rows_per_chunk: int, max_rows: int
) -> ParsedDocument:
    workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    parsed = ParsedDocument(title=workbook.properties.title or fallback_title, unit_count=0)
    try:
        for sheet in workbook.worksheets:
            rows = (
                (number, [_cell(v) for v in values])
                for number, values in enumerate(sheet.iter_rows(values_only=True), start=1)
            )
            _add_table(parsed, sheet.title, rows, rows_per_chunk, max_rows)
            if parsed.unit_count > max_rows:
                raise too_many_rows(max_rows)
    finally:
        workbook.close()
    return parsed
