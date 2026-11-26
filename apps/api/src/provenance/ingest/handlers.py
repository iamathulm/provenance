"""Wires job kinds to their implementations."""

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from provenance.ingest.indexing import (
    PERMANENT_ERRORS,
    IndexingDeps,
    index_version,
    mark_version_failed,
)
from provenance.ingest.models import Job
from provenance.ingest.worker import JobHandler

INDEX_VERSION = "index_version"


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

    return {
        INDEX_VERSION: JobHandler(run_index, index_exhausted, PERMANENT_ERRORS),
    }
