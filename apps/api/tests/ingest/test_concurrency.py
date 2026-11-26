"""Races between indexing, replacement, deletion and purge (P2 review findings 1-3)."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.documents.models import Chunk, Document, DocumentVersion
from provenance.documents.service import delete_document, replace_document
from provenance.ingest.indexing import ChunkStage, VersionWork, index_version
from provenance.ingest.models import Job
from provenance.workspaces.models import Workspace
from tests.ingest.harness import Harness

V1 = b"# Runbook\n\n## Steps\nLand within 90 seconds.\n"
V2 = b"# Runbook\n\n## Steps\nLand within 60 seconds.\n"
V3 = b"# Runbook\n\n## Steps\nLand within 30 seconds.\n"


async def ready_document(harness: Harness) -> tuple[uuid.UUID, uuid.UUID]:
    document_id, version_id = await harness.upload("runbook.txt", V1)
    await harness.worker.run_until_idle()
    return document_id, version_id


async def replace(harness: Harness, document_id: uuid.UUID, content: bytes) -> uuid.UUID:
    async with harness.session_factory() as db:
        workspace = await db.get_one(Workspace, harness.workspace_id)
        view = await replace_document(
            db, workspace, None, document_id, "runbook.txt", content, harness.deps.settings
        )
        await db.commit()
        return view.latest.id


async def chunk_rows(db: AsyncSession, version_id: uuid.UUID) -> int:
    return (
        await db.scalar(
            select(func.count()).select_from(Chunk).where(Chunk.version_id == version_id)
        )
        or 0
    )


async def test_delete_during_indexing_leaves_no_vectors(
    harness: Harness, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id, version_id = await harness.upload("runbook.txt", V1)
    original = ChunkStage.run

    async def delete_mid_pipeline(self: ChunkStage, ctx: object, data: VersionWork) -> VersionWork:
        result = await original(self, ctx, data)  # type: ignore[arg-type]
        async with harness.session_factory() as other:
            workspace = await other.get_one(Workspace, harness.workspace_id)
            await delete_document(other, workspace, None, document_id, harness.deps.index)
        return result

    monkeypatch.setattr(ChunkStage, "run", delete_mid_pipeline)

    await harness.worker.run_until_idle()  # index job (sees the delete), then purge job

    assert await harness.deps.index.count(version_id) == 0
    assert await db.get(Document, document_id) is None
    assert await chunk_rows(db, version_id) == 0


async def test_out_of_order_activation_keeps_the_newest_version(
    harness: Harness, db: AsyncSession
) -> None:
    document_id, v1 = await ready_document(harness)
    v2 = await replace(harness, document_id, V2)
    v3 = await replace(harness, document_id, V3)

    await index_version(harness.session_factory, harness.deps, v3, "test-v3")
    await index_version(harness.session_factory, harness.deps, v2, "test-v2")

    document = await db.get_one(Document, document_id)
    assert document.active_version_id == v3
    assert await harness.deps.index.count(v3, active=True) > 0
    assert await harness.deps.index.count(v2, active=True) == 0
    assert await harness.deps.index.count(v1, active=True) == 0
    assert (await db.get_one(DocumentVersion, v2)).status == "ready"  # indexed, just not live


async def test_retry_after_failed_deactivation_finishes_the_switch(
    harness: Harness, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id, v1 = await ready_document(harness)
    v2 = await replace(harness, document_id, V2)
    original = harness.deps.index.deactivate_other_versions
    calls = {"n": 0}

    async def fail_once(document: uuid.UUID, keep: uuid.UUID) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            msg = "qdrant unavailable"
            raise ConnectionError(msg)
        await original(document, keep)

    monkeypatch.setattr(harness.deps.index, "deactivate_other_versions", fail_once)

    await harness.worker.run_until_idle()
    half_switched = await harness.deps.index.count(v1, active=True)
    await db.execute(update(Job).values(run_after=datetime.now(UTC)))
    await db.commit()
    await harness.worker.run_until_idle()

    version = await db.get_one(DocumentVersion, v2)
    await db.refresh(version)
    assert half_switched > 0  # old version still live in Qdrant after the failure
    assert (await db.get_one(Document, document_id)).active_version_id == v2
    assert await harness.deps.index.count(v1, active=True) == 0
    assert await harness.deps.index.count(v2, active=True) == version.chunk_count
    assert await chunk_rows(db, v2) == version.chunk_count  # live version never rebuilt
