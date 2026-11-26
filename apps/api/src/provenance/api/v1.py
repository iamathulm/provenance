"""Version 1 API: every public route is mounted under /v1."""

from fastapi import APIRouter

from provenance.auth.router import router as auth_router
from provenance.storage.router import router as storage_router
from provenance.workspaces.router import router as workspaces_router

router = APIRouter(prefix="/v1")
router.include_router(auth_router)
router.include_router(workspaces_router)
router.include_router(storage_router)
