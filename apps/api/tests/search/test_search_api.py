from collections.abc import Callable

import pytest
from httpx import AsyncClient

from tests.ingest.harness import Harness
from tests.ingest.samples import xlsx_bytes

RUNBOOK = b"# Drone recovery\n\n## Battery fault\nLand within 90 seconds and swap the pack.\n"


@pytest.fixture
async def search_url(client: AsyncClient, harness: Harness) -> str:
    await client.post("/v1/auth/demo-login", json={"account": "primary"})
    return f"/v1/workspaces/{harness.workspace_id}/search"


async def test_empty_workspace_returns_no_hits(client: AsyncClient, search_url: str) -> None:
    response = await client.post(search_url, json={"query": "battery fault"})

    assert response.status_code == 200
    body = response.json()
    assert body["hits"] == []
    assert body["route"] == {"kind": "docs", "reasons": ["workspace has no tables"]}


async def test_search_returns_anchored_hits_with_diagnostics(
    client: AsyncClient, harness: Harness, search_url: str
) -> None:
    await harness.upload("runbook.txt", RUNBOOK)
    await harness.upload("sales.xlsx", xlsx_bytes({"Q3": [["region", "revenue"], ["EMEA", 5]]}))
    await harness.worker.run_until_idle()

    body = (await client.post(search_url, json={"query": "swap the pack battery"})).json()
    top = body["hits"][0]

    assert body["mode"] == "hybrid_rerank"
    assert body["rerank_mode"] == "flashrank"
    assert body["degraded"] == []
    assert body["route"]["kind"] in {"docs", "both"}
    assert set(body["timings_ms"]) == {"embed_query", "retrieve", "authorize", "rerank"}
    assert top["rank"] == 1
    assert top["filename"] == "runbook.txt"
    assert top["anchor"]["label"] == "Drone recovery > Battery fault"
    assert top["scores"]["sparse_rank"] == 1
    assert top["scores"]["rerank_score"] is not None


async def test_aggregate_question_routes_to_table(
    client: AsyncClient, harness: Harness, search_url: str
) -> None:
    await harness.upload("sales.xlsx", xlsx_bytes({"Q3": [["region", "revenue"], ["EMEA", 5]]}))
    await harness.worker.run_until_idle()

    body = (
        await client.post(search_url, json={"query": "total of the table", "mode": "sparse"})
    ).json()

    assert body["rerank_mode"] == "off"
    assert body["route"]["kind"] == "table"


async def test_search_never_crosses_workspaces(
    harness: Harness,
    search_url: str,
    client_factory: Callable[[], AsyncClient],
) -> None:
    await harness.upload("runbook.txt", RUNBOOK)
    await harness.worker.run_until_idle()

    async with client_factory() as tenant_b:
        await tenant_b.post("/v1/auth/demo-login", json={"account": "secondary"})
        own = (await tenant_b.get("/v1/workspaces")).json()[0]["id"]
        foreign = await tenant_b.post(search_url, json={"query": "battery"})
        mine = await tenant_b.post(
            f"/v1/workspaces/{own}/search", json={"query": "swap the pack battery"}
        )

    assert foreign.status_code == 404
    assert mine.json()["hits"] == []


@pytest.mark.parametrize(
    "body",
    [{"query": ""}, {"query": "x" * 501}, {"query": "x", "top_k": 0}, {"query": "x", "mode": "?"}],
)
async def test_invalid_requests_use_the_error_shape(
    client: AsyncClient, search_url: str, body: dict[str, object]
) -> None:
    response = await client.post(search_url, json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
