import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import override

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.core.config import Settings
from provenance.documents.models import Chunk, Document, DocumentVersion
from provenance.documents.service import upload_document
from provenance.ingest import jobs
from provenance.ingest.handlers import build_handlers
from provenance.ingest.indexing import IndexingDeps
from provenance.ingest.models import Job
from provenance.ingest.worker import Worker
from provenance.observability.models import StageSpan
from provenance.retrieval.index import ChunkIndex
from provenance.seed import seed_demo
from provenance.workspaces.models import Workspace
from tests.ingest.samples import pdf_bytes
from tests.retrieval.fakes import FakeEmbedder

RUNBOOK = (
    b"# Drone recovery\n\n## Battery fault\n"
    b"Land within 90 seconds. Swap the pack before relaunch.\n"
    b"\n## Lost link\nThe drone returns home after 30 seconds without signal.\n"
)


class FailingEmbedder(FakeEmbedder):
    @override
    def embed_dense(self, texts: list[str]) -> list[list[float]]:
        msg = "embedding service unavailable"
        raise ConnectionError(msg)


@dataclass
class Harness:
    session_factory: Callable[[], AsyncSession]
    deps: IndexingDeps
    worker: Worker
    workspace_id: uuid.UUID

    async def upload(self, filename: str, content: bytes) -> tuple[uuid.UUID, uuid.UUID]:
        async with self.session_factory() as db:
            workspace = await db.get_one(Workspace, self.workspace_id)
            document = await upload_document(
                db, workspace, None, filename, content, self.deps.settings
            )
            await db.commit()
            version_id = await db.scalar(
                select(DocumentVersion.id).where(DocumentVersion.document_id == document.id)
            )
            assert version_id is not None
            return document.id, version_id


@pytest.fixture
async def harness(app: FastAPI, chunk_index: ChunkIndex, settings: Settings) -> Harness:
    await seed_demo(app.state.session_factory)
    async with app.state.session_factory() as db:
        workspace_id = await db.scalar(select(Workspace.id).where(Workspace.name == "Company KB"))
    assert workspace_id is not None
    deps = IndexingDeps(
        settings, app.state.profiles, FakeEmbedder(), chunk_index, app.state.telemetry
    )
    worker = Worker(app.state.session_factory, build_handlers(app.state.session_factory, deps))
    return Harness(app.state.session_factory, deps, worker, workspace_id)


async def test_upload_indexes_to_ready_and_activates(harness: Harness, db: AsyncSession) -> None:
    document_id, version_id = await harness.upload("runbook.txt", RUNBOOK)

    assert await harness.worker.run_until_idle() == 1
    version = await db.get_one(DocumentVersion, version_id)
    document = await db.get_one(Document, document_id)
    chunk_count = await db.scalar(
        select(func.count()).select_from(Chunk).where(Chunk.version_id == version_id)
    )

    assert (version.status, version.stage, version.page_count) == ("ready", None, 7)
    assert version.chunk_count == chunk_count == 2
    assert document.active_version_id == version_id
    assert document.title == "Drone recovery"
    assert await harness.deps.index.count(version_id, active=True) == 2


async def test_stage_spans_recorded_per_stage(harness: Harness, db: AsyncSession) -> None:
    await harness.upload("runbook.txt", RUNBOOK)
    await harness.worker.run_until_idle()

    stages = (await db.scalars(select(StageSpan.stage).order_by(StageSpan.created_at))).all()

    assert stages == ["parsing", "chunking", "embedding", "indexing", "activating"]


async def test_concurrent_claims_never_share_a_job(harness: Harness) -> None:
    await harness.upload("a.txt", b"alpha text")
    await harness.upload("b.txt", b"beta text")

    async def claim(worker_id: str) -> uuid.UUID | None:
        async with harness.session_factory() as db:
            job = await jobs.claim_next(db, worker_id)
            await asyncio.sleep(0.05)  # hold the row lock while the other worker claims
            await db.commit()
            return job.id if job else None

    first, second = await asyncio.gather(claim("w1"), claim("w2"))

    assert first is not None
    assert second is not None
    assert first != second


async def test_expired_lease_is_reclaimed(harness: Harness) -> None:
    await harness.upload("a.txt", b"alpha text")
    async with harness.session_factory() as session:
        crashed = await jobs.claim_next(session, "crashed-worker")
        await session.commit()
    assert crashed is not None

    async with harness.session_factory() as session:
        assert await jobs.claim_next(session, "w2") is None  # lease still held
        await session.execute(
            update(Job).values(locked_until=datetime.now(UTC) - timedelta(seconds=1))
        )
        reclaimed = await jobs.claim_next(session, "w2")
        await session.commit()

    assert reclaimed is not None
    assert (reclaimed.id, reclaimed.attempts, reclaimed.locked_by) == (crashed.id, 2, "w2")


async def test_transient_failure_requeues_then_marks_failed_when_exhausted(
    harness: Harness, db: AsyncSession
) -> None:
    harness.deps.embedder = FailingEmbedder()
    _, version_id = await harness.upload("runbook.txt", RUNBOOK)

    await harness.worker.run_until_idle()
    job = (await db.scalars(select(Job))).one()
    requeued = (job.status, job.attempts, job.last_error_class, job.run_after > datetime.now(UTC))

    await db.execute(update(Job).values(max_attempts=2, run_after=datetime.now(UTC)))
    await db.commit()
    await harness.worker.run_until_idle()
    await db.refresh(job)
    version = await db.get_one(DocumentVersion, version_id)
    await db.refresh(version)

    assert requeued == ("queued", 1, "ConnectionError", True)
    assert (job.status, job.attempts) == ("failed", 2)
    assert (version.status, version.error_code) == ("failed", "indexing_failed")


async def test_permanent_failure_fails_version_immediately(
    harness: Harness, db: AsyncSession
) -> None:
    _, version_id = await harness.upload("scan.pdf", pdf_bytes(["", ""]))

    await harness.worker.run_until_idle()
    job = (await db.scalars(select(Job))).one()
    version = await db.get_one(DocumentVersion, version_id)

    assert (job.status, job.attempts, job.last_error_class) == ("failed", 1, "ParseFailedError")
    assert (version.status, version.error_code) == ("failed", "no_text_extracted")
    assert version.error_message is not None
    assert "Scanned documents are not supported" in version.error_message


async def test_rerun_after_crash_leaves_no_duplicates(
    harness: Harness, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, version_id = await harness.upload("runbook.txt", RUNBOOK)
    original = harness.deps.index.set_version_active
    calls = {"n": 0}

    async def crash_once(version: uuid.UUID, active: bool) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            msg = "worker lost connection during activation"
            raise ConnectionError(msg)
        await original(version, active)

    monkeypatch.setattr(harness.deps.index, "set_version_active", crash_once)

    await harness.worker.run_until_idle()  # indexes chunks, then crashes before activating
    await db.execute(update(Job).values(run_after=datetime.now(UTC)))
    await db.commit()
    await harness.worker.run_until_idle()  # retry from scratch

    chunks = await db.scalar(
        select(func.count()).select_from(Chunk).where(Chunk.version_id == version_id)
    )
    version = await db.get_one(DocumentVersion, version_id)
    assert version.status == "ready"
    assert chunks == version.chunk_count == 2
    assert await harness.deps.index.count(version_id) == 2
    assert await harness.deps.index.count(version_id, active=True) == 2
