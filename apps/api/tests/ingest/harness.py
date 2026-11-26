"""Ingestion test harness: a seeded workspace, a fake embedder, a throwaway Qdrant collection and a
worker that drains jobs on demand."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from provenance.documents.service import upload_document
from provenance.ingest.indexing import IndexingDeps
from provenance.ingest.worker import Worker
from provenance.workspaces.models import Workspace


@dataclass
class Harness:
    session_factory: Callable[[], AsyncSession]
    deps: IndexingDeps
    worker: Worker
    workspace_id: uuid.UUID

    async def upload(self, filename: str, content: bytes) -> tuple[uuid.UUID, uuid.UUID]:
        """Upload through the service layer; returns (document_id, version_id)."""
        async with self.session_factory() as db:
            workspace = await db.get_one(Workspace, self.workspace_id)
            view = await upload_document(db, workspace, None, filename, content, self.deps.settings)
            await db.commit()
            return view.document.id, view.latest.id
