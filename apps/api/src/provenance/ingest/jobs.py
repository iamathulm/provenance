"""Postgres-backed job queue.

Workers claim jobs with `SELECT … FOR UPDATE SKIP LOCKED`, hold a lease they keep alive with
heartbeats, and a job whose lease expires (worker crashed) is claimed again. Each claim counts as
an attempt, so a job that keeps crashing still stops after `max_attempts`.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.ingest.models import Job

INDEX_VERSION = "index_version"
PURGE_DOCUMENT = "purge_document"

DEFAULT_LEASE_S = 60
MAX_BACKOFF_S = 60


def _now() -> datetime:
    return datetime.now(UTC)


async def enqueue(
    db: AsyncSession,
    kind: str,
    workspace_id: uuid.UUID,
    *,
    idempotency_key: str,
    version_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
) -> Job:
    """Queue a job once: an existing job with the same idempotency key is returned instead."""
    existing = await db.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
    if existing is not None:
        return existing
    job = Job(
        kind=kind,
        workspace_id=workspace_id,
        version_id=version_id,
        document_id=document_id,
        idempotency_key=idempotency_key,
        status="queued",
        attempts=0,
        max_attempts=5,
        run_after=_now(),
    )
    db.add(job)
    await db.flush()
    return job


async def claim_next(
    db: AsyncSession, worker_id: str, lease_s: int = DEFAULT_LEASE_S
) -> Job | None:
    now = _now()
    job = await db.scalar(
        select(Job)
        .where(
            or_(
                and_(Job.status == "queued", Job.run_after <= now),
                and_(
                    Job.status == "running",
                    Job.locked_until < now,
                    Job.attempts < Job.max_attempts,
                ),
            )
        )
        .order_by(Job.run_after)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        return None
    job.status = "running"
    job.locked_by = worker_id
    job.locked_until = now + timedelta(seconds=lease_s)
    job.attempts += 1
    await db.flush()
    return job


async def expire_exhausted(db: AsyncSession) -> list[Job]:
    """Fail jobs whose worker died holding the lease on their last allowed attempt (a job that
    keeps crashing its worker must not be reclaimed forever)."""
    jobs = (
        await db.scalars(
            select(Job)
            .where(
                Job.status == "running",
                Job.locked_until < _now(),
                Job.attempts >= Job.max_attempts,
            )
            .with_for_update(skip_locked=True)
        )
    ).all()
    for job in jobs:
        job.status = "failed"
        job.last_error_class = "LeaseExpired"
        job.locked_by = None
        job.locked_until = None
    return list(jobs)


def owns(job: Job, worker_id: str) -> bool:
    """A worker may only finish or extend a job whose lease it still holds."""
    return job.status == "running" and job.locked_by == worker_id


async def heartbeat(
    db: AsyncSession, job_id: uuid.UUID, worker_id: str, lease_s: int = DEFAULT_LEASE_S
) -> bool:
    """Extend the lease; returns False if another worker has taken the job over."""
    job = await db.get_one(Job, job_id)
    if not owns(job, worker_id):
        return False
    job.locked_until = _now() + timedelta(seconds=lease_s)
    return True


def complete(job: Job) -> None:
    job.status = "succeeded"
    job.locked_by = None
    job.locked_until = None


def fail(job: Job, error: Exception, *, transient: bool) -> bool:
    """Record a failure. Returns True if the job was re-queued with backoff."""
    job.last_error_class = type(error).__name__
    job.locked_by = None
    job.locked_until = None
    if transient and job.attempts < job.max_attempts:
        job.status = "queued"
        job.run_after = _now() + timedelta(seconds=min(2**job.attempts, MAX_BACKOFF_S))
        return True
    job.status = "failed"
    return False


def requeue(job: Job) -> None:
    """Give a failed job a fresh set of attempts (user-initiated retry)."""
    job.status = "queued"
    job.attempts = 0
    job.run_after = _now()
    job.locked_by = None
    job.locked_until = None
    job.last_error_class = None
