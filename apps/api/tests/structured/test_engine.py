import io

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.documents.models import Document
from provenance.structured.catalog import load_catalog, sql_name
from provenance.structured.engine import _execute
from tests.ingest.harness import Harness
from tests.ingest.samples import xlsx_bytes


def parquet(rows: int) -> bytes:
    buffer = io.BytesIO()
    pq.write_table(pa.table({"_row": list(range(2, rows + 2)), "n": list(range(rows))}), buffer)
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("filename", "sheet", "expected"),
    [
        ("price-list-2026.csv", "price-list-2026", "t_price_list_2026"),
        ("sales-q3-2026.xlsx", "By Region", "t_sales_q3_2026_by_region"),
        ("Ünïcode Report.xlsx", "Q3", "t_n_code_report_q3"),
    ],
)
def test_sql_names_are_readable_identifiers(filename: str, sheet: str, expected: str) -> None:
    assert sql_name(filename, sheet) == expected


def test_long_queries_are_interrupted() -> None:
    with pytest.raises(duckdb.InterruptException):
        _execute("SELECT count(*) FROM t a, t b, t c, t d", {"t": parquet(2000)}, 0.2)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM read_csv('pyproject.toml')",
        "SELECT * FROM 'pyproject.toml'",
        "COPY (SELECT 1) TO 'leak.csv'",
        "ATTACH 'other.db'",
        "SET enable_external_access = true",
    ],
)
def test_engine_blocks_files_and_config_even_without_the_guard(sql: str) -> None:
    with pytest.raises(duckdb.Error):
        _execute(sql, {}, 5)


def test_registered_tables_are_queryable() -> None:
    columns, rows = _execute("SELECT max(_row), sum(n) FROM t", {"t": parquet(10)}, 5)

    assert len(columns) == 2
    assert rows == [(11, 45)]


async def test_catalog_order_is_stable_when_uploads_share_a_timestamp(
    harness: Harness, db: AsyncSession
) -> None:
    # One seeding transaction gives every document the same created_at. The order must then come
    # from the file names, not from random ids, or prompts (and cassette keys) differ per database.
    for name in ("one.xlsx", "two.xlsx"):
        await harness.upload(name, xlsx_bytes({"Sheet": [["n"], [1]]}))
    await harness.worker.run_until_idle()
    documents = sorted(
        (
            await db.scalars(select(Document).where(Document.workspace_id == harness.workspace_id))
        ).all(),
        key=lambda d: d.id,
    )
    stamp = documents[0].created_at
    for document, filename in zip(documents, ("b_second.xlsx", "a_first.xlsx"), strict=True):
        document.filename = filename
        document.created_at = stamp
    await db.commit()

    entries = await load_catalog(db, harness.workspace_id)

    assert [e.filename for e in entries] == ["a_first.xlsx", "b_second.xlsx"]
