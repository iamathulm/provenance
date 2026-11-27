"""Document endpoints: upload, list, inspect, replace, retry, delete, preview chunks."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request, Response, UploadFile, status
from pydantic import BaseModel

from provenance.api.dependencies import AppSettings
from provenance.auth.dependencies import CurrentUser
from provenance.core.config import Settings
from provenance.core.errors import PayloadTooLargeError
from provenance.db.engine import DbSession
from provenance.documents.models import Chunk
from provenance.documents.service import (
    DocumentView,
    active_chunks,
    delete_document,
    get_document,
    list_documents,
    replace_document,
    retry_document,
    upload_document,
)
from provenance.workspaces.dependencies import OwnedWorkspace

router = APIRouter(prefix="/workspaces/{workspace_id}/documents", tags=["documents"])

VersionStatus = Literal["queued", "processing", "ready", "partial", "failed"]


class VersionOut(BaseModel):
    id: uuid.UUID
    number: int
    status: str
    stage: str | None
    error_code: str | None
    error_message: str | None
    page_count: int | None
    chunk_count: int | None
    warnings: list[dict[str, Any]]
    stored_file_id: uuid.UUID
    created_at: datetime
    completed_at: datetime | None


class DocumentOut(BaseModel):
    id: uuid.UUID
    title: str
    filename: str
    media_type: str
    created_at: datetime
    searchable: bool
    active_version_id: uuid.UUID | None
    latest_version: VersionOut


class AnchorOut(BaseModel):
    kind: str
    label: str
    page: int | None
    slide: int | None
    section_path: str | None
    sheet: str | None
    row_start: int | None
    row_end: int | None


class ChunkOut(BaseModel):
    id: uuid.UUID
    ordinal: int
    text: str
    token_count: int
    anchor: AnchorOut


def _document_out(view: DocumentView) -> DocumentOut:
    latest = view.latest
    return DocumentOut(
        id=view.document.id,
        title=view.document.title,
        filename=view.document.filename,
        media_type=view.document.media_type,
        created_at=view.document.created_at,
        searchable=view.document.active_version_id is not None,
        active_version_id=view.document.active_version_id,
        latest_version=VersionOut.model_validate(latest, from_attributes=True),
    )


def anchor_out(chunk: Chunk) -> AnchorOut:
    return AnchorOut(
        kind=chunk.anchor_kind,
        label=chunk.anchor_label,
        page=chunk.page,
        slide=chunk.slide,
        section_path=chunk.section_path,
        sheet=chunk.sheet,
        row_start=chunk.row_start,
        row_end=chunk.row_end,
    )


def _chunk_out(chunk: Chunk) -> ChunkOut:
    return ChunkOut(
        id=chunk.id,
        ordinal=chunk.ordinal,
        text=chunk.text,
        token_count=chunk.token_count,
        anchor=anchor_out(chunk),
    )


async def _read_upload(file: UploadFile, settings: Settings) -> tuple[str, bytes]:
    """Read at most one byte past the limit so oversized uploads fail without buffering it all."""
    content = await file.read(settings.max_file_bytes + 1)
    if len(content) > settings.max_file_bytes:
        limit_mb = settings.max_file_bytes // (1024 * 1024)
        msg = f"File is larger than the {limit_mb} MB limit. Split it or compress images."
        raise PayloadTooLargeError(msg)
    return file.filename or "upload", content


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def upload(
    file: UploadFile,
    workspace: OwnedWorkspace,
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
) -> DocumentOut:
    filename, content = await _read_upload(file, settings)
    return _document_out(await upload_document(db, workspace, user, filename, content, settings))


@router.get("")
async def list_all(
    workspace: OwnedWorkspace, db: DbSession, status: VersionStatus | None = None
) -> list[DocumentOut]:
    return [_document_out(view) for view in await list_documents(db, workspace, status)]


@router.get("/{document_id}")
async def get(document_id: uuid.UUID, workspace: OwnedWorkspace, db: DbSession) -> DocumentOut:
    return _document_out(await get_document(db, workspace, document_id))


@router.post("/{document_id}/versions", status_code=status.HTTP_202_ACCEPTED)
async def replace(
    document_id: uuid.UUID,
    file: UploadFile,
    workspace: OwnedWorkspace,
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
) -> DocumentOut:
    filename, content = await _read_upload(file, settings)
    view = await replace_document(db, workspace, user, document_id, filename, content, settings)
    return _document_out(view)


@router.post("/{document_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry(
    document_id: uuid.UUID, workspace: OwnedWorkspace, user: CurrentUser, db: DbSession
) -> DocumentOut:
    return _document_out(await retry_document(db, workspace, user, document_id))


@router.delete("/{document_id}", status_code=status.HTTP_202_ACCEPTED)
async def remove(
    document_id: uuid.UUID,
    request: Request,
    workspace: OwnedWorkspace,
    user: CurrentUser,
    db: DbSession,
) -> Response:
    await delete_document(db, workspace, user, document_id, request.app.state.chunk_index)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.get("/{document_id}/chunks")
async def chunks(
    document_id: uuid.UUID,
    workspace: OwnedWorkspace,
    db: DbSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[ChunkOut]:
    rows = await active_chunks(db, workspace, document_id, offset, limit)
    return [_chunk_out(chunk) for chunk in rows]
