"""Background worker: claims jobs, keeps their lease alive, runs the handler, records the outcome.

Handlers raise to signal failure. Permanent content errors (bad or unparseable files) fail the job
at once; anything else is treated as transient and retried with backoff until attempts run out,
after which the handler's `on_exhausted` callback lets it mark its subject failed for the user.
"""

import asyncio
import contextlib
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.ingest import jobs
from provenance.ingest.models import Job

log = structlog.get_logger()


@dataclass(frozen=True)
class JobHandler:
    run: Callable[[Job, str], Awaitable[None]]
    on_exhausted: Callable[[Job], Awaitable[None]]
    permanent_errors: tuple[type[Exception], ...] = ()


class Worker:
    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        handlers: dict[str, JobHandler],
        worker_id: str | None = None,
        *,
        lease_s: int = jobs.DEFAULT_LEASE_S,
        poll_interval_s: float = 1.0,
    ) -> None:
        self._session_factory = session_factory
        self._handlers = handlers
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self._lease_s = lease_s
        self._poll_interval_s = poll_interval_s

    async def run(self, stop: asyncio.Event) -> None:
        log.info("worker_started", worker_id=self.worker_id)
        while not stop.is_set():
            if not await self.run_once():
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=self._poll_interval_s)
        log.info("worker_stopped", worker_id=self.worker_id)

    async def run_until_idle(self) -> int:
        """Process jobs until none is ready now; returns how many ran (tests, seeding)."""
        processed = 0
        while await self.run_once():
            processed += 1
        return processed

    async def run_once(self) -> bool:
        async with self._session_factory() as db:
            exhausted = await jobs.expire_exhausted(db)
            job = await jobs.claim_next(db, self.worker_id, self._lease_s)
            await db.commit()
        for dead in exhausted:
            log.warning("job_lease_exhausted", job_kind=dead.kind, attempts=dead.attempts)
            await self._handlers[dead.kind].on_exhausted(dead)
        if job is None:
            return False
        correlation_id = f"job-{job.id.hex}"
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id, job_kind=job.kind)
        heartbeat = asyncio.create_task(self._keep_alive(job.id))
        try:
            await self._execute(job, correlation_id)
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat
            structlog.contextvars.unbind_contextvars("correlation_id", "job_kind")
        return True

    async def _execute(self, job: Job, correlation_id: str) -> None:
        handler = self._handlers[job.kind]
        try:
            await handler.run(job, correlation_id)
        except Exception as error:
            transient = not isinstance(error, handler.permanent_errors)
            async with self._session_factory() as db:
                fresh = await db.get_one(Job, job.id)
                if not jobs.owns(fresh, self.worker_id):
                    log.warning("job_lease_lost", error_class=type(error).__name__)
                    return
                requeued = jobs.fail(fresh, error, transient=transient)
                await db.commit()
            log.warning(
                "job_failed",
                error_class=type(error).__name__,
                attempt=job.attempts,
                requeued=requeued,
            )
            if not requeued and transient:
                await handler.on_exhausted(job)
            return
        async with self._session_factory() as db:
            fresh = await db.get_one(Job, job.id)
            if not jobs.owns(fresh, self.worker_id):
                log.warning("job_lease_lost")
                return
            jobs.complete(fresh)
            await db.commit()

    async def _keep_alive(self, job_id: uuid.UUID) -> None:
        while True:
            await asyncio.sleep(self._lease_s / 4)
            try:
                async with self._session_factory() as db:
                    held = await jobs.heartbeat(db, job_id, self.worker_id, self._lease_s)
                    await db.commit()
            except Exception as error:
                log.warning("heartbeat_failed", error_class=type(error).__name__)
                continue
            if not held:
                log.warning("job_lease_lost")
                return
