"""Guarded, read-only SQL over the caller's workspace tables with DuckDB.

Each query gets a fresh in-memory DuckDB connection holding only this workspace's active tables,
with external access (files, network, extensions) disabled and configuration locked. A timer
interrupts queries that run past the timeout.
"""

import asyncio
import io
import threading
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal

import duckdb
import pyarrow.parquet as pq
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.core.config import Settings
from provenance.core.errors import AppError
from provenance.ingest.parsers.tables import ROW_COLUMN
from provenance.storage.models import StoredFile
from provenance.structured.catalog import TableEntry, load_catalog
from provenance.structured.sql_guard import guard_sql

Value = str | int | float | bool | None


class SqlTimeoutError(AppError):
    status_code = 422
    code = "sql_timeout"


class SqlFailedError(AppError):
    status_code = 422
    code = "sql_failed"


@dataclass(frozen=True)
class RowRef:
    """The spreadsheet row a result row came from, for row-level citations."""

    sql_name: str
    document_id: uuid.UUID
    sheet: str
    row: int


@dataclass(frozen=True)
class QueryResult:
    sql: str
    columns: list[str]
    rows: list[list[Value]]
    row_refs: list[RowRef]
    truncated: bool


def _json_value(value: object) -> Value:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date | datetime | time):
        return value.isoformat()
    return str(value)


def _execute(
    sql: str, tables: dict[str, bytes], timeout_s: float
) -> tuple[list[str], list[tuple[object, ...]]]:
    connection = duckdb.connect(
        ":memory:", config={"enable_external_access": False, "lock_configuration": True}
    )
    timer = threading.Timer(timeout_s, connection.interrupt)
    try:
        for name, content in tables.items():
            connection.register(name, pq.read_table(io.BytesIO(content)))
        timer.start()
        cursor = connection.execute(sql)
        columns = [column[0] for column in cursor.description or []]
        return columns, cursor.fetchall()
    finally:
        timer.cancel()
        connection.close()


async def run_query(
    db: AsyncSession, workspace_id: uuid.UUID, sql: str, settings: Settings
) -> QueryResult:
    catalog = {entry.sql_name: entry for entry in await load_catalog(db, workspace_id)}
    # One extra row tells a complete result of exactly `sql_max_rows` from a truncated one.
    guarded = guard_sql(sql, set(catalog), settings.sql_max_rows + 1)
    used = [catalog[name] for name in guarded.tables]
    files = await db.execute(
        select(StoredFile.id, StoredFile.content).where(
            StoredFile.id.in_([entry.stored_file_id for entry in used]),
            StoredFile.workspace_id == workspace_id,
        )
    )
    content = {row.id: row.content for row in files}
    tables = {entry.sql_name: content[entry.stored_file_id] for entry in used}
    try:
        columns, rows = await asyncio.to_thread(
            _execute, guarded.sql, tables, settings.sql_timeout_s
        )
    except duckdb.InterruptException as error:
        msg = f"The query ran longer than {settings.sql_timeout_s:g} s. Narrow it and retry."
        raise SqlTimeoutError(msg) from error
    except duckdb.Error as error:
        raise SqlFailedError(f"The query failed: {str(error).splitlines()[0]}") from error
    truncated = len(rows) > settings.sql_max_rows
    values = [[_json_value(v) for v in row] for row in rows[: settings.sql_max_rows]]
    refs = _row_refs(used[0], columns, values) if len(used) == 1 else []
    return QueryResult(guarded.sql, columns, values, refs, truncated)


def _row_refs(entry: TableEntry, columns: list[str], rows: list[list[Value]]) -> list[RowRef]:
    """Row references when a single-table result carries the `_row` column."""
    if ROW_COLUMN not in columns:
        return []
    position = columns.index(ROW_COLUMN)
    numbers = [row[position] for row in rows]
    return [
        RowRef(entry.sql_name, entry.document_id, entry.sheet, number)
        for number in numbers
        if isinstance(number, int)
    ]
