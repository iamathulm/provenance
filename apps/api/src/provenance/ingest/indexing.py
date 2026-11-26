"""The `index_version` job: Parse → Chunk → Embed → Index → Activate, as recorded stages.

Re-running a version (after a crash or retry) first removes that version's chunks, points and
tables, so the outcome is identical however many times it runs. Activation flips the new version
on before the old one off, and the database pointer (`documents.active_version_id`) is what
retrieval trusts, so readers never see a document disappear mid-swap.
"""

import asyncio
import io
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, override

import pyarrow.parquet as pq
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.core.config import Settings
from provenance.core.context import RequestContext
from provenance.core.pipeline import Pipeline, SpanRecorder, Stage
from provenance.documents.locking import lock_document
from provenance.documents.models import Chunk, Document, DocumentVersion, VersionTable
from provenance.ingest.chunking import ChunkDraft, chunk_document
from provenance.ingest.parsers import parse
from provenance.ingest.parsers.base import ParsedDocument, ParseFailedError
from provenance.ingest.validation import UploadRejectedError, validate_upload
from provenance.profiles.loader import DomainProfile
from provenance.retrieval.embeddings import Embedder, SparseEmbedding
from provenance.retrieval.index import ChunkIndex, IndexPoint
from provenance.storage.models import StoredFile
from provenance.storage.service import put_file
from provenance.workspaces.models import Workspace

EMBED_BATCH = 64
PARTIAL_WARNINGS = frozenset({"low_text_extraction", "low_text_page"})
PERMANENT_ERRORS = (ParseFailedError, UploadRejectedError)


@dataclass
class IndexingDeps:
    settings: Settings
    profiles: dict[str, DomainProfile]
    embedder: Embedder
    index: ChunkIndex
    recorder: SpanRecorder


@dataclass
class VersionWork:
    """Everything one run of the job reads and produces."""

    db: AsyncSession
    workspace: Workspace
    document: Document
    version: DocumentVersion
    stored: StoredFile
    profile: DomainProfile
    parsed: ParsedDocument | None = None
    drafts: list[ChunkDraft] = field(default_factory=list)
    dense: list[list[float]] = field(default_factory=list)
    sparse: list[SparseEmbedding] = field(default_factory=list)


class _VersionStage(Stage[VersionWork, VersionWork]):
    stage_label: str

    def __init__(self, deps: IndexingDeps) -> None:
        self.deps = deps

    async def mark(self, work: VersionWork) -> None:
        work.version.stage = self.stage_label
        await work.db.commit()


class ParseStage(_VersionStage):
    name = stage_label = "parsing"
    timeout_s = 120

    @override
    async def run(self, ctx: RequestContext, data: VersionWork) -> VersionWork:
        await self.mark(data)
        validated = validate_upload(data.stored.filename, data.stored.content, self.deps.settings)
        data.parsed = await asyncio.to_thread(parse, validated, data.profile)
        return data


class ChunkStage(_VersionStage):
    name = stage_label = "chunking"
    timeout_s = 60

    @override
    async def run(self, ctx: RequestContext, data: VersionWork) -> VersionWork:
        await self.mark(data)
        assert data.parsed is not None  # noqa: S101 - set by ParseStage
        data.drafts = chunk_document(data.parsed, data.profile.chunking)
        return data


class EmbedStage(_VersionStage):
    name = stage_label = "embedding"
    timeout_s = 600

    @override
    async def run(self, ctx: RequestContext, data: VersionWork) -> VersionWork:
        await self.mark(data)
        texts = [draft.text for draft in data.drafts]
        for start in range(0, len(texts), EMBED_BATCH):
            batch = texts[start : start + EMBED_BATCH]
            data.dense.extend(await asyncio.to_thread(self.deps.embedder.embed_dense, batch))
            data.sparse.extend(await asyncio.to_thread(self.deps.embedder.embed_sparse, batch))
        return data


class IndexStage(_VersionStage):
    name = stage_label = "indexing"
    timeout_s = 300

    @override
    async def run(self, ctx: RequestContext, data: VersionWork) -> VersionWork:
        await self.mark(data)
        # Hold the document lock while replacing this version's rows and points, so a
        # concurrent run of the same version or a purge cannot interleave and leave orphans.
        document = await lock_document(data.db, data.document.id)
        if document is None or document.deleted_at is not None:
            raise DocumentGoneError
        await _clear_version(data.db, self.deps.index, data.version.id)
        chunks = [_chunk_row(data, draft) for draft in data.drafts]
        data.db.add_all(chunks)
        await _store_tables(data, self.deps.settings)
        await data.db.flush()
        await self.deps.index.upsert(
            [
                IndexPoint(
                    chunk.id,
                    data.workspace.id,
                    data.document.id,
                    data.version.id,
                    dense,
                    sparse,
                    active=False,
                )
                for chunk, dense, sparse in zip(chunks, data.dense, data.sparse, strict=True)
            ]
        )
        await data.db.commit()
        return data


class ActivateStage(_VersionStage):
    name = stage_label = "activating"
    timeout_s = 60

    @override
    async def run(self, ctx: RequestContext, data: VersionWork) -> VersionWork:
        assert data.parsed is not None  # noqa: S101 - set by ParseStage
        document = await lock_document(data.db, data.document.id)
        if document is None or document.deleted_at is not None:
            raise DocumentGoneError
        version = data.version
        codes = {warning.code for warning in data.parsed.warnings}
        version.status = "partial" if codes & PARTIAL_WARNINGS else "ready"
        version.stage = None
        version.page_count = data.parsed.unit_count
        version.chunk_count = len(data.drafts)
        version.warnings = [
            _warning_json(w.code, w.message, w.anchor) for w in data.parsed.warnings
        ]
        version.completed_at = datetime.now(UTC)
        if document.title == document.filename and data.parsed.title:
            document.title = data.parsed.title[:255]
        if not await _is_newest_ready(data.db, document, version):
            await data.db.commit()  # a newer version is already live; this one stays inactive
            return data
        await self.deps.index.set_version_active(version.id, True)
        document.active_version_id = version.id
        await data.db.commit()
        await self.deps.index.deactivate_other_versions(document.id, version.id)
        return data


class DocumentGoneError(Exception):
    """The document was deleted while its version was being indexed."""


async def _is_newest_ready(db: AsyncSession, document: Document, version: DocumentVersion) -> bool:
    """Only activate if no newer version of the document is already active."""
    if document.active_version_id is None or document.active_version_id == version.id:
        return True
    active = await db.get_one(DocumentVersion, document.active_version_id)
    return version.number > active.number


def _chunk_row(data: VersionWork, draft: ChunkDraft) -> Chunk:
    return Chunk(
        id=uuid.uuid4(),
        version_id=data.version.id,
        workspace_id=data.workspace.id,
        document_id=data.document.id,
        ordinal=draft.ordinal,
        text=draft.text,
        token_count=draft.token_count,
        anchor_kind=draft.anchor.kind,
        anchor_label=draft.anchor.label,
        page=draft.anchor.page,
        slide=draft.anchor.slide,
        section_path=draft.anchor.section_path,
        sheet=draft.anchor.sheet,
        row_start=draft.anchor.row_start,
        row_end=draft.anchor.row_end,
    )


def _warning_json(code: str, message: str, anchor: Any) -> dict[str, Any]:
    return {"code": code, "message": message, "anchor": anchor.label if anchor else None}


async def _clear_version(db: AsyncSession, index: ChunkIndex, version_id: uuid.UUID) -> None:
    """Remove anything a previous run of this version left behind (idempotent re-runs)."""
    await index.delete_version(version_id)
    await db.execute(delete(Chunk).where(Chunk.version_id == version_id))
    stale = (
        await db.scalars(
            select(VersionTable.stored_file_id).where(VersionTable.version_id == version_id)
        )
    ).all()
    await db.execute(delete(VersionTable).where(VersionTable.version_id == version_id))
    if stale:
        await db.execute(delete(StoredFile).where(StoredFile.id.in_(stale)))


async def _store_tables(work: VersionWork, settings: Settings) -> None:
    assert work.parsed is not None  # noqa: S101 - set by ParseStage
    for table in work.parsed.tables:
        buffer = io.BytesIO()
        pq.write_table(table.rows, buffer)
        stored = await put_file(
            work.db,
            work.workspace,
            f"{table.name}.parquet",
            "application/vnd.apache.parquet",
            buffer.getvalue(),
            settings,
        )
        work.db.add(
            VersionTable(
                version_id=work.version.id,
                workspace_id=work.workspace.id,
                name=table.name,
                stored_file_id=stored.id,
                row_count=table.rows.num_rows,
                columns=table.columns,
            )
        )


async def _load_work(
    db: AsyncSession, deps: IndexingDeps, version_id: uuid.UUID
) -> VersionWork | None:
    version = await db.get(DocumentVersion, version_id)
    if version is None:
        return None
    document = await db.get_one(Document, version.document_id)
    workspace = await db.get_one(Workspace, version.workspace_id)
    stored = await db.scalar(
        select(StoredFile)
        .where(StoredFile.id == version.stored_file_id)
        .execution_options(populate_existing=True)
    )
    if stored is None:
        return None
    await db.refresh(stored, ["content"])
    return VersionWork(db, workspace, document, version, stored, deps.profiles[workspace.profile])


async def index_version(
    session_factory: Callable[[], AsyncSession],
    deps: IndexingDeps,
    version_id: uuid.UUID,
    correlation_id: str,
) -> None:
    """Run the job. Permanent content errors fail the version; other errors propagate to the
    worker, which retries with backoff (and fails the version once attempts run out)."""
    async with session_factory() as db:
        work = await _load_work(db, deps, version_id)
        if work is None or work.document.deleted_at is not None:
            await deps.index.delete_version(version_id)
            return
        if work.document.active_version_id == version_id:
            # A retry after the database switch committed but Qdrant did not finish: complete
            # the vector-side switch instead of rebuilding (and briefly emptying) a live version.
            await deps.index.set_version_active(version_id, True)
            await deps.index.deactivate_other_versions(work.document.id, version_id)
            return
        work.version.status = "processing"
        work.version.error_code = work.version.error_message = None
        await db.commit()
        ctx = RequestContext(correlation_id=correlation_id, workspace_id=work.workspace.id)
        pipeline = Pipeline(deps.recorder)
        try:
            for stage in (
                ParseStage(deps),
                ChunkStage(deps),
                EmbedStage(deps),
                IndexStage(deps),
                ActivateStage(deps),
            ):
                work = await pipeline.run_stage(ctx, stage, work)
        except DocumentGoneError:
            await db.rollback()
            await deps.index.delete_version(version_id)  # purge may already have run
        except PERMANENT_ERRORS as error:
            await db.rollback()
            await mark_version_failed(db, version_id, error.code, error.message)
            raise


async def mark_version_failed(
    db: AsyncSession, version_id: uuid.UUID, code: str, message: str
) -> None:
    version = await db.get_one(DocumentVersion, version_id)
    version.status = "failed"
    version.stage = None
    version.error_code = code
    version.error_message = message[:500]
    version.completed_at = datetime.now(UTC)
    await db.commit()
