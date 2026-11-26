"""Wires job kinds to their implementations."""

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from provenance.documents.service import purge_document
from provenance.ingest.indexing import (
    PERMANENT_ERRORS,
    IndexingDeps,
    index_version,
    mark_version_failed,
)
from provenance.ingest.jobs import INDEX_VERSION, PURGE_DOCUMENT
from provenance.ingest.models import Job
from provenance.ingest.worker import JobHandler


def build_handlers(
    session_factory: Callable[[], AsyncSession], deps: IndexingDeps
) -> dict[str, JobHandler]:
    async def run_index(job: Job, correlation_id: str) -> None:
        assert job.version_id is not None  # noqa: S101 - index jobs always carry a version
        await index_version(session_factory, deps, job.version_id, correlation_id)

    async def index_exhausted(job: Job) -> None:
        assert job.version_id is not None  # noqa: S101 - index jobs always carry a version
        async with session_factory() as db:
            await mark_version_failed(
                db,
                job.version_id,
                "indexing_failed",
                "Indexing failed after several attempts. Use Retry on the document to try again.",
            )

    async def run_purge(job: Job, _: str) -> None:
        assert job.document_id is not None  # noqa: S101 - purge jobs always carry a document
        async with session_factory() as db:
            await purge_document(db, deps.index, job.document_id)
            await db.commit()

    async def purge_exhausted(_: Job) -> None:
        """The document is already hidden; the failed job row is the retry/audit record."""

    return {
        INDEX_VERSION: JobHandler(run_index, index_exhausted, PERMANENT_ERRORS),
        PURGE_DOCUMENT: JobHandler(run_purge, purge_exhausted),
    }
