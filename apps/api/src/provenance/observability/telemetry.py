"""Writes telemetry rows. A telemetry failure is logged and swallowed — it never fails a request."""

import uuid
from collections.abc import Callable

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.core.context import RequestContext
from provenance.core.pipeline import SpanRecorder, StageOutcome
from provenance.db.base import Base
from provenance.observability.models import RequestLog, StageSpan

log = structlog.get_logger()


class TelemetryRecorder(SpanRecorder):
    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record(
        self,
        ctx: RequestContext,
        stage: str,
        outcome: StageOutcome,
        duration_ms: float,
        error_class: str | None,
    ) -> None:
        await self._write(
            StageSpan(
                correlation_id=ctx.correlation_id,
                workspace_id=ctx.workspace_id,
                stage=stage,
                outcome=outcome,
                duration_ms=duration_ms,
                error_class=error_class,
            )
        )

    async def record_request(
        self,
        correlation_id: str,
        method: str,
        route: str,
        status_code: int,
        duration_ms: float,
        user_id: uuid.UUID | None,
    ) -> None:
        await self._write(
            RequestLog(
                correlation_id=correlation_id,
                method=method,
                route=route,
                status_code=status_code,
                duration_ms=duration_ms,
                user_id=user_id,
            )
        )

    async def _write(self, row: Base) -> None:
        try:
            async with self._session_factory() as session:
                session.add(row)
                await session.commit()
        except Exception as error:
            log.warning("telemetry_write_failed", error_class=type(error).__name__)
