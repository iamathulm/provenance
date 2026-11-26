"""The single guard every workspace-scoped route depends on."""

import uuid
from typing import Annotated

from fastapi import Depends

from provenance.auth.dependencies import CurrentUser
from provenance.db.engine import DbSession
from provenance.workspaces.models import Workspace
from provenance.workspaces.service import get_owned_workspace


async def require_workspace(workspace_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Workspace:
    """Resolve the path's workspace for the signed-in owner, or 404."""
    return await get_owned_workspace(db, user, workspace_id)


OwnedWorkspace = Annotated[Workspace, Depends(require_workspace)]
