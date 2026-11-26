import uuid
from collections.abc import Callable
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.core.config import Settings
from provenance.core.errors import PayloadTooLargeError
from provenance.storage.models import StoredFile
from provenance.storage.service import put_file
from provenance.workspaces.models import Workspace

CONTENT = b"%PDF-1.7 quarterly report bytes \x00\x01"


async def sign_in_with_workspace(client: AsyncClient, account: str = "primary") -> uuid.UUID:
    await client.post("/v1/auth/demo-login", json={"account": account})
    created = await client.post("/v1/workspaces", json={"name": f"{account} KB"})
    return uuid.UUID(created.json()["id"])


async def store(db: AsyncSession, workspace_id: uuid.UUID, settings: Settings) -> StoredFile:
    workspace = await db.get_one(Workspace, workspace_id)
    stored = await put_file(
        db, workspace, "Q3 report (final).pdf", "application/pdf", CONTENT, settings
    )
    await db.commit()
    return stored


async def test_link_then_download_returns_exact_bytes_and_headers(
    client: AsyncClient, db: AsyncSession, settings: Settings
) -> None:
    workspace_id = await sign_in_with_workspace(client)
    stored = await store(db, workspace_id, settings)

    link = await client.post(f"/v1/workspaces/{workspace_id}/files/{stored.id}/link")
    download = await client.get(link.json()["url"])

    assert link.status_code == 200
    assert download.status_code == 200
    assert download.content == CONTENT
    assert download.headers["content-type"] == "application/pdf"
    assert download.headers["cache-control"] == "private, no-store"
    assert download.headers["x-content-type-options"] == "nosniff"
    assert "Q3%20report%20%28final%29.pdf" in download.headers["content-disposition"]
    assert stored.size_bytes == len(CONTENT)


async def test_signed_link_rejects_tamper_expiry_and_other_user(
    client: AsyncClient,
    client_factory: Callable[[], AsyncClient],
    db: AsyncSession,
    settings: Settings,
) -> None:
    workspace_id = await sign_in_with_workspace(client)
    stored = await store(db, workspace_id, settings)
    url = (await client.post(f"/v1/workspaces/{workspace_id}/files/{stored.id}/link")).json()["url"]
    parsed = urlparse(url)
    query = {key: values[0] for key, values in parse_qs(parsed.query).items()}

    tampered = await client.get(
        parsed.path, params={**query, "signature": "0" * len(query["signature"])}
    )
    extended = await client.get(
        parsed.path, params={**query, "expires": str(int(query["expires"]) + 3600)}
    )
    expired = await client.get(parsed.path, params={**query, "expires": "1"})
    unsigned = await client.get(parsed.path)
    async with client_factory() as other:
        await other.post("/v1/auth/demo-login", json={"account": "secondary"})
        other_user = await other.get(url)

    assert [r.status_code for r in (tampered, extended, expired, other_user)] == [404] * 4
    assert unsigned.status_code == 422
    assert CONTENT not in other_user.content


async def test_file_from_another_workspace_is_not_found(
    client: AsyncClient,
    client_factory: Callable[[], AsyncClient],
    db: AsyncSession,
    settings: Settings,
) -> None:
    workspace_id = await sign_in_with_workspace(client)
    stored = await store(db, workspace_id, settings)

    async with client_factory() as other:
        other_workspace = await sign_in_with_workspace(other, "secondary")
        response = await other.post(f"/v1/workspaces/{other_workspace}/files/{stored.id}/link")

    assert response.status_code == 404


async def test_oversize_file_rejected(
    client: AsyncClient, db: AsyncSession, settings: Settings
) -> None:
    workspace_id = await sign_in_with_workspace(client)
    workspace = await db.get_one(Workspace, workspace_id)
    small_limit = settings.model_copy(update={"max_file_bytes": 8})

    with pytest.raises(PayloadTooLargeError):
        await put_file(db, workspace, "big.txt", "text/plain", b"123456789", small_limit)


async def test_malformed_signature_is_rejected_not_crashing(
    client: AsyncClient, db: AsyncSession, settings: Settings
) -> None:
    workspace_id = await sign_in_with_workspace(client)
    stored = await store(db, workspace_id, settings)

    response = await client.get(
        f"/v1/workspaces/{workspace_id}/files/{stored.id}/raw",
        params={"expires": "9999999999", "signature": "é" * 64},
    )

    assert response.status_code == 422
