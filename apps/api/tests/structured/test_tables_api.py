from collections.abc import Callable

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from tests.ingest.harness import Harness
from tests.ingest.samples import xlsx_bytes

SALES = {
    "Q3": [
        ["region", "revenue"],
        ["EMEA", 120],
        [None, None],
        ["APAC", 80],
        ["AMER", 200],
    ]
}
PRICES = b"sku,price\nHM-1,1200\nTX-2,4800\n"


@pytest.fixture
async def tables(client: AsyncClient, harness: Harness) -> str:
    await client.post("/v1/auth/demo-login", json={"account": "primary"})
    await harness.upload("sales-q3.xlsx", xlsx_bytes(SALES))
    await harness.upload("prices.csv", PRICES)
    await harness.worker.run_until_idle()
    return f"/v1/workspaces/{harness.workspace_id}/tables"


async def test_lists_tables_with_sql_names(client: AsyncClient, tables: str) -> None:
    listed = (await client.get(tables)).json()

    assert {(t["sql_name"], t["row_count"]) for t in listed} == {
        ("t_sales_q3_q3", 3),
        ("t_prices", 2),
    }
    assert next(t for t in listed if t["sql_name"] == "t_prices")["columns"] == ["sku", "price"]


async def test_aggregate_is_exact(client: AsyncClient, tables: str) -> None:
    response = await client.post(
        f"{tables}/query", json={"sql": "SELECT SUM(revenue) AS total FROM t_sales_q3_q3"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["columns"] == ["total"]
    assert body["rows"] == [[400]]
    assert body["row_refs"] == []
    assert body["sql"].endswith("LIMIT 201")  # max rows + 1 to detect truncation


async def test_row_refs_point_at_spreadsheet_rows(client: AsyncClient, tables: str) -> None:
    response = await client.post(
        f"{tables}/query",
        json={"sql": "SELECT _row, region FROM t_sales_q3_q3 WHERE revenue >= 100 ORDER BY _row"},
    )

    refs = response.json()["row_refs"]
    assert [(r["sheet"], r["row"]) for r in refs] == [("Q3", 2), ("Q3", 5)]


async def test_hostile_and_broken_sql_get_actionable_errors(
    client: AsyncClient, tables: str
) -> None:
    rejected = await client.post(
        f"{tables}/query", json={"sql": "SELECT * FROM read_csv('/etc/passwd')"}
    )
    failed = await client.post(f"{tables}/query", json={"sql": "SELECT nope FROM t_prices"})

    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "sql_rejected"
    assert failed.status_code == 422
    assert failed.json()["error"]["code"] == "sql_failed"


async def test_sql_sees_only_own_tables(
    tables: str, client_factory: Callable[[], AsyncClient]
) -> None:
    async with client_factory() as tenant_b:
        await tenant_b.post("/v1/auth/demo-login", json={"account": "secondary"})
        own = (await tenant_b.get("/v1/workspaces")).json()[0]["id"]
        foreign = await tenant_b.post(f"{tables}/query", json={"sql": "SELECT 1"})
        guessed = await tenant_b.post(
            f"/v1/workspaces/{own}/tables/query", json={"sql": "SELECT * FROM t_prices"}
        )

    assert foreign.status_code == 404
    assert guessed.status_code == 422
    assert "unknown table 't_prices'" in guessed.json()["error"]["message"]


async def test_deleted_document_tables_unavailable(
    client: AsyncClient, tables: str, harness: Harness
) -> None:
    documents = (await client.get(f"/v1/workspaces/{harness.workspace_id}/documents")).json()
    prices = next(d for d in documents if d["filename"] == "prices.csv")
    await client.delete(f"/v1/workspaces/{harness.workspace_id}/documents/{prices['id']}")

    listed = (await client.get(tables)).json()
    query = await client.post(f"{tables}/query", json={"sql": "SELECT * FROM t_prices"})

    assert [t["sql_name"] for t in listed] == ["t_sales_q3_q3"]
    assert query.status_code == 422


async def test_replaced_spreadsheet_exposes_only_new_version(
    client: AsyncClient, tables: str, harness: Harness
) -> None:
    base = f"/v1/workspaces/{harness.workspace_id}/documents"
    prices = next(d for d in (await client.get(base)).json() if d["filename"] == "prices.csv")
    await client.post(
        f"{base}/{prices['id']}/versions",
        files={"file": ("prices.csv", b"sku,price\nHM-1,1300\n")},
    )
    await harness.worker.run_until_idle()

    response = await client.post(f"{tables}/query", json={"sql": "SELECT price FROM t_prices"})

    assert response.json()["rows"] == [[1300]]


async def test_truncated_only_when_rows_were_cut(
    app: FastAPI, client: AsyncClient, tables: str, harness: Harness
) -> None:
    app.state.settings = harness.deps.settings.model_copy(update={"sql_max_rows": 2})

    complete = await client.post(f"{tables}/query", json={"sql": "SELECT * FROM t_prices"})
    cut = await client.post(f"{tables}/query", json={"sql": "SELECT * FROM t_sales_q3_q3"})

    assert (len(complete.json()["rows"]), complete.json()["truncated"]) == (2, False)
    assert (len(cut.json()["rows"]), cut.json()["truncated"]) == (2, True)


async def test_listing_names_the_row_column(client: AsyncClient, tables: str) -> None:
    assert {t["row_column"] for t in (await client.get(tables)).json()} == {"_row"}
