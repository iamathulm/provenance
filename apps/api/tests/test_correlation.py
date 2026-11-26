import re

import pytest
from httpx import AsyncClient

GENERATED_ID = re.compile(r"^[0-9a-f]{32}$")


async def test_request_id_echoed(client: AsyncClient) -> None:
    response = await client.get("/healthz", headers={"X-Request-ID": "trace-abc-123"})

    assert response.headers["x-request-id"] == "trace-abc-123"


async def test_request_id_generated_when_missing(client: AsyncClient) -> None:
    response = await client.get("/healthz")

    assert GENERATED_ID.match(response.headers["x-request-id"])


@pytest.mark.parametrize("bad_value", ["bad id; drop", "a" * 10_000, "short"])
async def test_invalid_request_id_replaced(client: AsyncClient, bad_value: str) -> None:
    response = await client.get("/healthz", headers={"X-Request-ID": bad_value})

    assert GENERATED_ID.match(response.headers["x-request-id"])
