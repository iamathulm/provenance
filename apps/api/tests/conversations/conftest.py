import pytest
from httpx import AsyncClient

from tests.ingest.harness import Harness

RUNBOOK = b"# Battery fault\n\nLand within 90 seconds and swap the pack.\n"


@pytest.fixture
async def conversation(client: AsyncClient, harness: Harness) -> str:
    """Signed in as the primary demo user, with an indexed runbook and a new conversation."""
    await client.post("/v1/auth/demo-login", json={"account": "primary"})
    await harness.upload("runbook.txt", RUNBOOK)
    await harness.worker.run_until_idle()
    created = await client.post(f"/v1/workspaces/{harness.workspace_id}/conversations", json={})
    assert created.status_code == 201
    return f"/v1/workspaces/{harness.workspace_id}/conversations/{created.json()['id']}"
