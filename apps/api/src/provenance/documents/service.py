"""Document lifecycle (PRD FR-02/FR-04, NFR-07).

Uploads and replacements create immutable versions queued for indexing; the previous version stays
active until the new one is ready. Deletion hides a document immediately (database flag plus
deactivated vectors) and queues a purge that removes originals, chunks, tables and vectors, with an
audit trail of both steps.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.audit.models import AuditEvent
from provenance.auth.models import User
from provenance.core.config import Settings
from provenance.core.errors import ConflictError, NotFoundError
from provenance.documents.models import Chunk, Document, DocumentVersion, VersionTable
from provenance.ingest.jobs import INDEX_VERSION, PURGE_DOCUMENT, enqueue, requeue
from provenance.ingest.models import Job
from provenance.ingest.validation import validate_upload
from provenance.retrieval.index import ChunkIndex
from provenance.storage.models import StoredFile
from provenance.storage.service import put_file
from provenance.workspaces.models import Workspace


@dataclass(frozen=True)
class DocumentView:
    document: Document
    latest: DocumentVersion


def _audit(
    workspace_id: uuid.UUID, user: User | None, action: str, document: Document
) -> AuditEvent:
    return AuditEvent(
        workspace_id=workspace_id,
        actor_user_id=user.id if user else None,
        action=action,
        subject_id=document.id,
        detail={"filename": document.filename},
    )


async def _queue_version(
    db: AsyncSession, document: Document, stored_file_id: uuid.UUID
) -> DocumentVersion:
    latest = await db.scalar(
        select(func.max(DocumentVersion.number)).where(DocumentVersion.document_id == document.id)
    )
    version = DocumentVersion(
        document_id=document.id,
        workspace_id=document.workspace_id,
        number=(latest or 0) + 1,
        stored_file_id=stored_file_id,
        status="queued",
        warnings=[],
    )
    db.add(version)
    await db.flush()
    await enqueue(
        db,
        INDEX_VERSION,
        document.workspace_id,
        version_id=version.id,
        document_id=document.id,
        idempotency_key=f"{INDEX_VERSION}:{version.id}",
    )
    return version


async def upload_document(
    db: AsyncSession,
    workspace: Workspace,
    user: User | None,
    filename: str,
    content: bytes,
    settings: Settings,
) -> DocumentView:
    """Validate, store and queue a new document. Invalid files raise before anything is saved."""
    validated = validate_upload(filename, content, settings)
    stored = await put_file(db, workspace, filename, validated.media_type, content, settings)
    document = Document(
        workspace_id=workspace.id, title=filename, filename=filename, media_type=stored.media_type
    )
    db.add(document)
    await db.flush()
    version = await _queue_version(db, document, stored.id)
    db.add(_audit(workspace.id, user, "document.uploaded", document))
    return DocumentView(document, version)


async def replace_document(
    db: AsyncSession,
    workspace: Workspace,
    user: User | None,
    document_id: uuid.UUID,
    filename: str,
    content: bytes,
    settings: Settings,
) -> DocumentView:
    document = await _live_document(db, workspace, document_id)
    validated = validate_upload(filename, content, settings)
    stored = await put_file(db, workspace, filename, validated.media_type, content, settings)
    version = await _queue_version(db, document, stored.id)
    document.filename, document.media_type = filename, stored.media_type
    db.add(_audit(workspace.id, user, "document.replaced", document))
    return DocumentView(document, version)


async def _live_document(
    db: AsyncSession, workspace: Workspace, document_id: uuid.UUID
) -> Document:
    document = await db.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.workspace_id == workspace.id,
            Document.deleted_at.is_(None),
        )
    )
    if document is None:
        msg = "Document not found."
        raise NotFoundError(msg)
    return document


async def _latest_version(db: AsyncSession, document_id: uuid.UUID) -> DocumentVersion:
    return await db.get_one(
        DocumentVersion,
        await db.scalar(
            select(DocumentVersion.id)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.number.desc())
            .limit(1)
        ),
    )


async def get_document(
    db: AsyncSession, workspace: Workspace, document_id: uuid.UUID
) -> DocumentView:
    document = await _live_document(db, workspace, document_id)
    return DocumentView(document, await _latest_version(db, document.id))


async def list_documents(
    db: AsyncSession, workspace: Workspace, status: str | None = None
) -> list[DocumentView]:
    latest = (
        select(DocumentVersion.document_id, func.max(DocumentVersion.number).label("number"))
        .group_by(DocumentVersion.document_id)
        .subquery()
    )
    query = (
        select(Document, DocumentVersion)
        .join(latest, latest.c.document_id == Document.id)
        .join(
            DocumentVersion,
            (DocumentVersion.document_id == Document.id)
            & (DocumentVersion.number == latest.c.number),
        )
        .where(Document.workspace_id == workspace.id, Document.deleted_at.is_(None))
        .order_by(Document.created_at.desc(), Document.id)
    )
    if status is not None:
        query = query.where(DocumentVersion.status == status)
    return [DocumentView(document, version) for document, version in await db.execute(query)]


async def retry_document(
    db: AsyncSession, workspace: Workspace, user: User | None, document_id: uuid.UUID
) -> DocumentView:
    document = await _live_document(db, workspace, document_id)
    version = await _latest_version(db, document.id)
    if version.status != "failed":
        msg = "Only a failed version can be retried."
        raise ConflictError(msg)
    job = await db.scalar(select(Job).where(Job.idempotency_key == f"{INDEX_VERSION}:{version.id}"))
    if job is None:
        await _queue_version(db, document, version.stored_file_id)
    else:
        requeue(job)
        version.status, version.error_code, version.error_message = "queued", None, None
    db.add(_audit(workspace.id, user, "document.retried", document))
    return DocumentView(document, await _latest_version(db, document.id))


async def delete_document(
    db: AsyncSession,
    workspace: Workspace,
    user: User | None,
    document_id: uuid.UUID,
    index: ChunkIndex,
) -> None:
    """Hide now (flag + deactivated vectors), purge later (job), audit both."""
    document = await _live_document(db, workspace, document_id)
    document.deleted_at = datetime.now(UTC)
    db.add(_audit(workspace.id, user, "document.delete_requested", document))
    await enqueue(
        db,
        PURGE_DOCUMENT,
        workspace.id,
        document_id=document.id,
        idempotency_key=f"{PURGE_DOCUMENT}:{document.id}",
    )
    await db.flush()
    await index.set_document_active(document.id, False)


async def active_chunks(
    db: AsyncSession, workspace: Workspace, document_id: uuid.UUID, offset: int, limit: int
) -> list[Chunk]:
    document = await _live_document(db, workspace, document_id)
    if document.active_version_id is None:
        return []
    rows = await db.scalars(
        select(Chunk)
        .where(Chunk.version_id == document.active_version_id)
        .order_by(Chunk.ordinal)
        .offset(offset)
        .limit(limit)
    )
    return list(rows)


async def reindex_workspace(db: AsyncSession, workspace: Workspace) -> int:
    """Queue a fresh version (same original file) for every live document, e.g. after a
    profile change. The current versions stay searchable until each replacement is ready."""
    documents = (
        await db.scalars(
            select(Document).where(
                Document.workspace_id == workspace.id, Document.deleted_at.is_(None)
            )
        )
    ).all()
    for document in documents:
        latest = await _latest_version(db, document.id)
        await _queue_version(db, document, latest.stored_file_id)
    return len(documents)


async def purge_document(db: AsyncSession, index: ChunkIndex, document_id: uuid.UUID) -> None:
    """Remove a deleted document's vectors, chunks, tables, originals and rows."""
    document = await db.get(Document, document_id)
    if document is None or document.deleted_at is None:
        return
    versions = (
        await db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == document_id))
    ).all()
    file_ids = {v.stored_file_id for v in versions}
    for version in versions:
        await index.delete_version(version.id)
        file_ids.update(
            (
                await db.scalars(
                    select(VersionTable.stored_file_id).where(VersionTable.version_id == version.id)
                )
            ).all()
        )
    document.active_version_id = None
    await db.flush()
    await db.execute(delete(DocumentVersion).where(DocumentVersion.document_id == document_id))
    await db.execute(delete(StoredFile).where(StoredFile.id.in_(file_ids)))
    db.add(_audit(document.workspace_id, None, "document.purged", document))
    await db.delete(document)
