"""Original-file access through short-lived, user-bound signed links."""

import uuid
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel

from provenance.api.dependencies import AppSettings
from provenance.auth.dependencies import CurrentUser, DbSession
from provenance.core.errors import NotFoundError
from provenance.storage.service import get_file
from provenance.storage.signing import sign, verify
from provenance.workspaces.dependencies import OwnedWorkspace

router = APIRouter(prefix="/workspaces/{workspace_id}/files", tags=["files"])


class FileLinkOut(BaseModel):
    url: str
    expires_at: datetime


@router.post("/{file_id}/link")
async def create_link(
    file_id: uuid.UUID,
    workspace: OwnedWorkspace,
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
) -> FileLinkOut:
    stored = await get_file(db, workspace, file_id)
    link = sign(
        stored.id,
        workspace.id,
        user.id,
        settings.session_secret.get_secret_value(),
        ttl_s=settings.file_link_ttl_s,
    )
    query = urlencode({"expires": link.expires, "signature": link.signature})
    return FileLinkOut(
        url=f"/v1/workspaces/{workspace.id}/files/{stored.id}/raw?{query}",
        expires_at=datetime.fromtimestamp(link.expires, tz=UTC),
    )


@router.get("/{file_id}/raw")
async def download(
    file_id: uuid.UUID,
    expires: Annotated[int, Query()],
    signature: Annotated[str, Query(max_length=64)],
    workspace: OwnedWorkspace,
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
) -> Response:
    secret = settings.session_secret.get_secret_value()
    if not verify(file_id, workspace.id, user.id, expires, signature, secret):
        msg = "File not found."
        raise NotFoundError(msg)
    stored = await get_file(db, workspace, file_id, include_content=True)
    return Response(
        content=stored.content,
        media_type=stored.media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(stored.filename)}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
