"""CSV/XLSX: each sheet becomes a typed table (Parquet for SQL) plus searchable text blocks —
one table card describing it, then row groups that repeat the header and anchor to row ranges."""

import csv
import io
import re
from collections.abc import Iterable
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

import pyarrow as pa
from openpyxl import load_workbook

from provenance.ingest.parsers.base import Anchor, Block, ParsedDocument, ParsedTable

_SAMPLE_ROWS = 3
Cell = str | int | float | bool | None


def _column_names(header: list[Cell]) -> list[str]:
    names: list[str] = []
    for index, raw in enumerate(header, start=1):
        base = re.sub(r"\s+", " ", str(raw).strip()) if raw not in (None, "") else ""
        name = base or f"column_{index}"
        candidate, suffix = name, 2
        while candidate in names:
            candidate, suffix = f"{name}_{suffix}", suffix + 1
        names.append(candidate)
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


def _add_table(
    parsed: ParsedDocument, name: str, rows: list[list[Cell]], rows_per_chunk: int
) -> None:
    non_empty = [r for r in rows if any(v not in (None, "") for v in r)]
    if not non_empty:
        return
    header, *data = non_empty
    columns = _column_names(header)
    width = len(columns)
    data = [(list(r) + [None] * width)[:width] for r in data]
    arrays = [_typed_column([r[i] for r in data]) for i in range(width)]
    parsed.tables.append(ParsedTable(name, columns, pa.table(arrays, names=columns)))

    sample = "\n".join(_row_text(columns, r) for r in data[:_SAMPLE_ROWS])
    card = f"Table {name}: {len(data)} rows. Columns: {', '.join(columns)}." + (
        f"\nSample rows:\n{sample}" if sample else ""
    )
    parsed.blocks.append(
        Block(card, Anchor.for_rows(name, 1, min(len(data), _SAMPLE_ROWS) or 1), is_table=True)
    )
    for start in range(0, len(data), rows_per_chunk):
        group = data[start : start + rows_per_chunk]
        first, last = start + 1, start + len(group)
        lines = [f"Table {name}, rows {first}–{last}. Columns: {', '.join(columns)}."]
        lines.extend(f"Row {first + i}: {_row_text(columns, r)}" for i, r in enumerate(group))
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


def _sheet_rows(values: Iterable[tuple[object, ...]]) -> list[list[Cell]]:
    return [[_cell(v) for v in row] for row in values]


def parse_csv(content: bytes, fallback_title: str, rows_per_chunk: int) -> ParsedDocument:
    text = content.decode("utf-8-sig")
    try:
        dialect: type[csv.Dialect] = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows: list[list[str]] = [list(r) for r in csv.reader(io.StringIO(text), dialect)]
    parsed = ParsedDocument(title=fallback_title, unit_count=0)
    _add_table(parsed, fallback_title, [[_coerce(v) for v in r] for r in rows], rows_per_chunk)
    return parsed


def _coerce(value: str) -> Cell:
    stripped = value.strip()
    if re.fullmatch(r"-?\d+", stripped):
        return int(stripped)
    if re.fullmatch(r"-?\d*\.\d+", stripped):
        return float(stripped)
    return stripped


def parse_xlsx(content: bytes, fallback_title: str, rows_per_chunk: int) -> ParsedDocument:
    workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    parsed = ParsedDocument(title=workbook.properties.title or fallback_title, unit_count=0)
    try:
        for sheet in workbook.worksheets:
            rows = _sheet_rows(sheet.iter_rows(values_only=True))
            _add_table(parsed, sheet.title, rows, rows_per_chunk)
    finally:
        workbook.close()
    return parsed
