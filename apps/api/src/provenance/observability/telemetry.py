"""Writes telemetry rows. A telemetry failure is logged and swallowed — it never fails a request."""

import uuid
from collections.abc import Callable

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from provenance.core.context import RequestContext
from provenance.core.pipeline import SpanRecorder, StageOutcome
from provenance.db.base import Base
from provenance.generation.client import ProviderCall
from provenance.guardrails.guards import GuardrailDecision
from provenance.observability import metrics
from provenance.observability.models import (
    GuardrailEvent,
    ProviderCallLog,
    RequestLog,
    StageSpan,
)

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
        metrics.STAGE_DURATION.labels(stage, outcome).observe(duration_ms / 1000)
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

    async def record_provider_call(self, ctx: RequestContext, call: ProviderCall) -> None:
        metrics.LLM_CALLS.labels(call.model, call.purpose, call.status).inc()
        metrics.LLM_TOKENS.labels(call.model, "prompt").inc(call.prompt_tokens)
        metrics.LLM_TOKENS.labels(call.model, "completion").inc(call.completion_tokens)
        await self._write(
            ProviderCallLog(
                correlation_id=ctx.correlation_id,
                workspace_id=ctx.workspace_id,
                provider=call.provider,
                model=call.model,
                purpose=call.purpose,
                status=call.status,
                duration_ms=call.duration_ms,
                prompt_tokens=call.prompt_tokens,
                completion_tokens=call.completion_tokens,
            )
        )

    async def record_guardrails(
        self, ctx: RequestContext, decisions: list[GuardrailDecision]
    ) -> None:
        for decision in decisions:
            metrics.GUARDRAIL_ACTIONS.labels(decision.name, decision.action).inc()
            await self._write(
                GuardrailEvent(
                    correlation_id=ctx.correlation_id,
                    workspace_id=ctx.workspace_id,
                    name=decision.name,
                    stage=decision.stage,
                    action=decision.action,
                    rule=decision.rule,
                )
            )

    def record_answer(self, status: str, latency_ms: float) -> None:
        metrics.ANSWERS.labels(status).inc()
        metrics.ANSWER_LATENCY.observe(latency_ms / 1000)

    async def _write(self, row: Base) -> None:
        try:
            async with self._session_factory() as session:
                session.add(row)
                await session.commit()
        except Exception as error:
            log.warning("telemetry_write_failed", error_class=type(error).__name__)
