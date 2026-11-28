"""Workspace analytics (owner only) and the operator overview (operator emails only)."""

from typing import Annotated, Any

from fastapi import APIRouter, Query, Request

from provenance.analytics.service import operator_overview, workspace_analytics
from provenance.api.dependencies import AppSettings
from provenance.auth.dependencies import CurrentUser
from provenance.core.config import REPO_ROOT
from provenance.core.errors import ForbiddenError
from provenance.db.engine import DbSession
from provenance.workspaces.dependencies import OwnedWorkspace

router = APIRouter(tags=["analytics"])
REPORTS_DIR = REPO_ROOT / "eval" / "reports"


@router.get("/workspaces/{workspace_id}/analytics")
async def analytics(
    workspace: OwnedWorkspace, db: DbSession, days: Annotated[int, Query(ge=1, le=90)] = 7
) -> dict[str, Any]:
    return await workspace_analytics(db, workspace.id, days)


@router.get("/operator/overview")
async def overview(
    request: Request, user: CurrentUser, db: DbSession, settings: AppSettings
) -> dict[str, Any]:
    if user.email.casefold() not in {email.casefold() for email in settings.operator_emails}:
        msg = "The operator view is limited to operator accounts."
        raise ForbiddenError(msg)
    index = request.app.state.chunk_index
    return await operator_overview(db, index.client, index.collection, settings, REPORTS_DIR)
