"""Workspace endpoints."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, ConfigDict, StringConstraints

from provenance.auth.dependencies import CurrentUser
from provenance.db.engine import DbSession
from provenance.documents.service import reindex_workspace
from provenance.profiles.loader import UnknownProfileError
from provenance.profiles.router import loaded_profiles
from provenance.workspaces.dependencies import OwnedWorkspace
from provenance.workspaces.service import create_workspace, list_workspaces, rename_workspace

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _require_known_profile(request: Request, profile: str) -> None:
    if profile not in loaded_profiles(request):
        msg = f"Unknown profile '{profile}'. See GET /v1/profiles for available profiles."
        raise UnknownProfileError(msg)


WorkspaceName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
]


class WorkspaceCreate(BaseModel):
    name: WorkspaceName
    profile: str = "company"


class WorkspaceUpdate(BaseModel):
    name: WorkspaceName | None = None
    profile: str | None = None


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    profile: str
    created_at: datetime


@router.post("", status_code=status.HTTP_201_CREATED)
async def create(
    body: WorkspaceCreate, request: Request, user: CurrentUser, db: DbSession
) -> WorkspaceOut:
    _require_known_profile(request, body.profile)
    return WorkspaceOut.model_validate(await create_workspace(db, user, body.name, body.profile))


@router.get("")
async def list_owned(user: CurrentUser, db: DbSession) -> list[WorkspaceOut]:
    return [WorkspaceOut.model_validate(w) for w in await list_workspaces(db, user)]


@router.get("/{workspace_id}")
async def get(workspace: OwnedWorkspace) -> WorkspaceOut:
    return WorkspaceOut.model_validate(workspace)


@router.patch("/{workspace_id}")
async def update(
    body: WorkspaceUpdate, request: Request, workspace: OwnedWorkspace, db: DbSession
) -> WorkspaceOut:
    """Rename and/or change the domain profile. A profile change re-indexes every document;
    current versions stay searchable until their replacements are ready."""
    if body.name is not None:
        await rename_workspace(db, workspace, body.name)
    if body.profile is not None and body.profile != workspace.profile:
        _require_known_profile(request, body.profile)
        workspace.profile = body.profile
        await reindex_workspace(db, workspace)
    return WorkspaceOut.model_validate(workspace)
