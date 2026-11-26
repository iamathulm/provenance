"""Document lifecycle: upload and replace create immutable versions queued for indexing."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.audit.models import AuditEvent
from provenance.auth.models import User
from provenance.core.config import Settings
from provenance.documents.models import Document, DocumentVersion
from provenance.ingest.handlers import INDEX_VERSION
from provenance.ingest.jobs import enqueue
from provenance.ingest.validation import ValidatedFile, validate_upload
from provenance.storage.service import put_file
from provenance.workspaces.models import Workspace


async def _queue_version(
    db: AsyncSession,
    workspace: Workspace,
    document: Document,
    validated: ValidatedFile,
    settings: Settings,
) -> DocumentVersion:
    stored = await put_file(
        db, workspace, validated.filename, validated.media_type, validated.content, settings
    )
    latest = await db.scalar(
        select(func.max(DocumentVersion.number)).where(DocumentVersion.document_id == document.id)
    )
    version = DocumentVersion(
        document_id=document.id,
        workspace_id=workspace.id,
        number=(latest or 0) + 1,
        stored_file_id=stored.id,
        status="queued",
        warnings=[],
    )
    db.add(version)
    await db.flush()
    await enqueue(
        db,
        INDEX_VERSION,
        workspace.id,
        version_id=version.id,
        document_id=document.id,
        idempotency_key=f"{INDEX_VERSION}:{version.id}",
    )
    return version


def _audit(workspace: Workspace, user: User | None, action: str, document: Document) -> AuditEvent:
    return AuditEvent(
        workspace_id=workspace.id,
        actor_user_id=user.id if user else None,
        action=action,
        subject_id=document.id,
        detail={"filename": document.filename},
    )


async def upload_document(
    db: AsyncSession,
    workspace: Workspace,
    user: User | None,
    filename: str,
    content: bytes,
    settings: Settings,
) -> Document:
    """Validate, store and queue a new document. Invalid files raise before anything is saved."""
    validated = validate_upload(filename, content, settings)
    document = Document(
        workspace_id=workspace.id,
        title=filename,
        filename=filename,
        media_type=validated.media_type,
    )
    db.add(document)
    await db.flush()
    await _queue_version(db, workspace, document, validated, settings)
    db.add(_audit(workspace, user, "document.uploaded", document))
    await db.flush()
    return document
