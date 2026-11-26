import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.audit.models import AuditEvent
from provenance.documents.models import Chunk, Document, DocumentVersion
from provenance.ingest.models import Job
from provenance.storage.models import StoredFile
from tests.ingest.harness import Harness
from tests.ingest.samples import pdf_bytes, xlsx_bytes

RUNBOOK = b"# Drone recovery\n\n## Battery fault\nLand within 90 seconds and swap the pack.\n"
RUNBOOK_V2 = b"# Drone recovery\n\n## Battery fault\nLand within 60 seconds. Never hot-swap.\n"


@pytest.fixture
async def signed_in(client: AsyncClient, harness: Harness) -> str:
    await client.post("/v1/auth/demo-login", json={"account": "primary"})
    return f"/v1/workspaces/{harness.workspace_id}/documents"


async def upload(client: AsyncClient, base: str, name: str, content: bytes) -> dict[str, Any]:
    response = await client.post(base, files={"file": (name, content)})
    assert response.status_code == 202, response.text
    body: dict[str, Any] = response.json()
    return body


async def count(db: AsyncSession, model: type[Any], *conditions: Any) -> int:
    return await db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0


async def test_upload_index_and_inspect(
    client: AsyncClient, harness: Harness, signed_in: str
) -> None:
    created = await upload(client, signed_in, "runbook.txt", RUNBOOK)
    queued = (created["latest_version"]["status"], created["searchable"])

    await harness.worker.run_until_idle()
    detail = (await client.get(f"{signed_in}/{created['id']}")).json()
    ready = (await client.get(signed_in, params={"status": "ready"})).json()
    failed = (await client.get(signed_in, params={"status": "failed"})).json()
    chunks = (await client.get(f"{signed_in}/{created['id']}/chunks")).json()

    assert queued == ("queued", False)
    assert detail["searchable"] is True
    assert detail["title"] == "Drone recovery"
    assert detail["latest_version"]["status"] == "ready"
    assert detail["active_version_id"] == detail["latest_version"]["id"]
    assert [d["id"] for d in ready] == [created["id"]]
    assert failed == []
    assert chunks[0]["anchor"]["label"] == "Drone recovery > Battery fault"
    assert "swap the pack" in chunks[0]["text"]


async def test_invalid_upload_saves_nothing(
    client: AsyncClient, signed_in: str, db: AsyncSession
) -> None:
    response = await client.post(signed_in, files={"file": ("report.pdf", b"PK\x03\x04 zip")})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "type_mismatch"
    assert await count(db, Document) == 0
    assert await count(db, Job) == 0
    assert await count(db, StoredFile) == 0


async def test_oversized_upload_is_413(
    app: FastAPI, client: AsyncClient, signed_in: str, harness: Harness
) -> None:
    app.state.settings = harness.deps.settings.model_copy(update={"max_file_bytes": 10})

    response = await client.post(signed_in, files={"file": ("notes.txt", b"x" * 11)})

    assert response.status_code == 413


async def test_failed_replacement_keeps_prior_version_active(
    client: AsyncClient, harness: Harness, signed_in: str
) -> None:
    created = await upload(client, signed_in, "runbook.txt", RUNBOOK)
    await harness.worker.run_until_idle()
    first_version = uuid.UUID(created["latest_version"]["id"])

    replaced = await client.post(
        f"{signed_in}/{created['id']}/versions",
        files={"file": ("runbook.pdf", pdf_bytes(["", ""]))},
    )
    await harness.worker.run_until_idle()
    detail = (await client.get(f"{signed_in}/{created['id']}")).json()

    assert replaced.status_code == 202
    assert detail["latest_version"]["number"] == 2
    assert detail["latest_version"]["status"] == "failed"
    assert detail["latest_version"]["error_code"] == "no_text_extracted"
    assert detail["active_version_id"] == str(first_version)
    assert await harness.deps.index.count(first_version, active=True) > 0


async def test_successful_replacement_swaps_active_version(
    client: AsyncClient, harness: Harness, signed_in: str
) -> None:
    created = await upload(client, signed_in, "runbook.txt", RUNBOOK)
    await harness.worker.run_until_idle()
    first = uuid.UUID(created["latest_version"]["id"])

    replaced = await client.post(
        f"{signed_in}/{created['id']}/versions", files={"file": ("runbook.txt", RUNBOOK_V2)}
    )
    second = uuid.UUID(replaced.json()["latest_version"]["id"])
    still_first = (await client.get(f"{signed_in}/{created['id']}")).json()["active_version_id"]
    await harness.worker.run_until_idle()
    chunks = (await client.get(f"{signed_in}/{created['id']}/chunks")).json()

    assert still_first == str(first)
    assert await harness.deps.index.count(first, active=True) == 0
    assert await harness.deps.index.count(second, active=True) > 0
    assert "Never hot-swap" in chunks[0]["text"]


async def test_delete_blocks_reads_before_purge(
    client: AsyncClient, harness: Harness, signed_in: str, db: AsyncSession
) -> None:
    created = await upload(
        client, signed_in, "sales.xlsx", xlsx_bytes({"Q3": [["r", "v"], ["A", 1]]})
    )
    await harness.worker.run_until_idle()
    version = uuid.UUID(created["latest_version"]["id"])
    document_id = uuid.UUID(created["id"])

    deleted = await client.delete(f"{signed_in}/{created['id']}")
    hidden = [
        (await client.get(f"{signed_in}/{created['id']}")).status_code,
        (await client.get(f"{signed_in}/{created['id']}/chunks")).status_code,
        len((await client.get(signed_in)).json()),
        await harness.deps.index.count(version, active=True),
    ]
    rows_before_purge = await count(db, Chunk, Chunk.version_id == version)

    await harness.worker.run_until_idle()
    actions = (
        await db.scalars(
            select(AuditEvent.action)
            .where(AuditEvent.subject_id == document_id)
            .order_by(AuditEvent.created_at)
        )
    ).all()

    assert deleted.status_code == 202
    assert hidden == [404, 404, 0, 0]
    assert rows_before_purge > 0
    assert await count(db, Chunk, Chunk.version_id == version) == 0
    assert await count(db, DocumentVersion, DocumentVersion.document_id == document_id) == 0
    assert await count(db, Document, Document.id == document_id) == 0
    assert await count(db, StoredFile) == 0  # original and the extracted Parquet table
    assert await harness.deps.index.count(version) == 0
    assert list(actions) == ["document.uploaded", "document.delete_requested", "document.purged"]


async def test_retry_failed_version(client: AsyncClient, harness: Harness, signed_in: str) -> None:
    created = await upload(client, signed_in, "scan.pdf", pdf_bytes(["", ""]))
    await harness.worker.run_until_idle()

    retried = await client.post(f"{signed_in}/{created['id']}/retry")
    await harness.worker.run_until_idle()
    good = await upload(client, signed_in, "runbook.txt", RUNBOOK)
    await harness.worker.run_until_idle()
    not_failed = await client.post(f"{signed_in}/{good['id']}/retry")

    assert retried.status_code == 202
    assert retried.json()["latest_version"]["status"] == "queued"
    assert not_failed.status_code == 409


async def test_profile_change_reindexes_documents(
    client: AsyncClient, harness: Harness, signed_in: str
) -> None:
    created = await upload(client, signed_in, "runbook.txt", RUNBOOK)
    await harness.worker.run_until_idle()
    first = uuid.UUID(created["latest_version"]["id"])

    changed = await client.patch(
        f"/v1/workspaces/{harness.workspace_id}", json={"profile": "research"}
    )
    await harness.worker.run_until_idle()
    detail = (await client.get(f"{signed_in}/{created['id']}")).json()

    assert changed.json()["profile"] == "research"
    assert detail["latest_version"]["number"] == 2
    assert detail["active_version_id"] == detail["latest_version"]["id"]
    assert await harness.deps.index.count(first, active=True) == 0
