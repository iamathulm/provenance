"""Workspace endpoints."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, StringConstraints

from provenance.auth.dependencies import CurrentUser
from provenance.db.engine import DbSession
from provenance.workspaces.dependencies import OwnedWorkspace
from provenance.workspaces.service import create_workspace, list_workspaces, rename_workspace

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

WorkspaceName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
]
Profile = Literal["company", "research"]


class WorkspaceCreate(BaseModel):
    name: WorkspaceName
    profile: Profile = "company"


class WorkspaceRename(BaseModel):
    name: WorkspaceName


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    profile: str
    created_at: datetime


@router.post("", status_code=status.HTTP_201_CREATED)
async def create(body: WorkspaceCreate, user: CurrentUser, db: DbSession) -> WorkspaceOut:
    return WorkspaceOut.model_validate(await create_workspace(db, user, body.name, body.profile))


@router.get("")
async def list_owned(user: CurrentUser, db: DbSession) -> list[WorkspaceOut]:
    return [WorkspaceOut.model_validate(w) for w in await list_workspaces(db, user)]


@router.get("/{workspace_id}")
async def get(workspace: OwnedWorkspace) -> WorkspaceOut:
    return WorkspaceOut.model_validate(workspace)


@router.patch("/{workspace_id}")
async def rename(body: WorkspaceRename, workspace: OwnedWorkspace, db: DbSession) -> WorkspaceOut:
    return WorkspaceOut.model_validate(await rename_workspace(db, workspace, body.name))
