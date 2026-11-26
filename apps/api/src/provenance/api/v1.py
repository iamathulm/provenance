"""Version 1 API: every public route is mounted under /v1."""

from fastapi import APIRouter

from provenance.auth.router import router as auth_router

router = APIRouter(prefix="/v1")
router.include_router(auth_router)
