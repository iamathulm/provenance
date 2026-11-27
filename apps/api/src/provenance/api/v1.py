"""Version 1 API: every public route is mounted under /v1."""

from fastapi import APIRouter

from provenance.auth.router import router as auth_router
from provenance.documents.router import router as documents_router
from provenance.profiles.router import router as profiles_router
from provenance.storage.router import router as storage_router
from provenance.structured.router import router as tables_router
from provenance.workspaces.router import router as workspaces_router

router = APIRouter(prefix="/v1")
router.include_router(auth_router)
router.include_router(profiles_router)
router.include_router(workspaces_router)
router.include_router(storage_router)
router.include_router(documents_router)
router.include_router(tables_router)
