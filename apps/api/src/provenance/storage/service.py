"""Workspace-scoped file storage."""

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from provenance.core.config import Settings
from provenance.core.errors import NotFoundError, PayloadTooLargeError
from provenance.storage.models import StoredFile
from provenance.workspaces.models import Workspace


async def put_file(
    db: AsyncSession,
    workspace: Workspace,
    filename: str,
    media_type: str,
    content: bytes,
    settings: Settings,
) -> StoredFile:
    if len(content) > settings.max_file_bytes:
        limit_mb = settings.max_file_bytes // (1024 * 1024)
        msg = f"File is larger than the {limit_mb} MB limit."
        raise PayloadTooLargeError(msg)
    stored = StoredFile(
        workspace_id=workspace.id,
        filename=filename,
        media_type=media_type,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        content=content,
    )
    db.add(stored)
    await db.flush()
    return stored


async def get_file(
    db: AsyncSession, workspace: Workspace, file_id: uuid.UUID, *, include_content: bool = False
) -> StoredFile:
    query = select(StoredFile).where(
        StoredFile.id == file_id, StoredFile.workspace_id == workspace.id
    )
    if include_content:
        query = query.options(undefer(StoredFile.content))
    stored = await db.scalar(query)
    if stored is None:
        msg = "File not found."
        raise NotFoundError(msg)
    return stored
