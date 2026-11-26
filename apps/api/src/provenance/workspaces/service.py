"""Workspace operations. Every lookup is scoped to the owner; foreign IDs look missing."""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.auth.models import User
from provenance.core.errors import ConflictError, NotFoundError
from provenance.workspaces.models import Workspace

_DUPLICATE_NAME = "You already have a workspace with this name."


async def _flush_unique(db: AsyncSession) -> None:
    try:
        await db.flush()
    except IntegrityError as error:
        raise ConflictError(_DUPLICATE_NAME) from error


async def create_workspace(db: AsyncSession, owner: User, name: str, profile: str) -> Workspace:
    workspace = Workspace(owner_id=owner.id, name=name, profile=profile)
    db.add(workspace)
    await _flush_unique(db)
    await db.refresh(workspace)
    return workspace


async def list_workspaces(db: AsyncSession, owner: User) -> list[Workspace]:
    rows = await db.scalars(
        select(Workspace)
        .where(Workspace.owner_id == owner.id)
        .order_by(Workspace.created_at.desc(), Workspace.id)
    )
    return list(rows)


async def get_owned_workspace(db: AsyncSession, owner: User, workspace_id: uuid.UUID) -> Workspace:
    workspace = await db.scalar(
        select(Workspace).where(Workspace.id == workspace_id, Workspace.owner_id == owner.id)
    )
    if workspace is None:
        msg = "Workspace not found."
        raise NotFoundError(msg)
    return workspace


async def rename_workspace(db: AsyncSession, workspace: Workspace, name: str) -> Workspace:
    workspace.name = name
    await _flush_unique(db)
    return workspace
