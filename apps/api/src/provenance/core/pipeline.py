"""Typed stage orchestration: timeouts, fallbacks, degraded-mode tracking and one span per stage.

Each stage is a small class with a name, a timeout and an optional fallback. The pipeline never
hides failures: a successful fallback marks the request degraded (surfaced to the user, e.g.
"reranker unavailable, showing fusion order"), a failed fallback re-raises the original error.
"""

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Literal, Protocol

from provenance.core.context import RequestContext

StageOutcome = Literal["ok", "fallback", "error"]


class Stage[In, Out](ABC):
    name: str
    timeout_s: float = 10.0

    @abstractmethod
    async def run(self, ctx: RequestContext, data: In) -> Out: ...

    async def fallback(self, ctx: RequestContext, data: In, error: Exception) -> Out:  # noqa: ARG002 - interface signature
        """Default: no fallback, the original error propagates."""
        raise error


class SpanRecorder(Protocol):
    async def record(
        self,
        ctx: RequestContext,
        stage: str,
        outcome: StageOutcome,
        duration_ms: float,
        error_class: str | None,
    ) -> None: ...


class Pipeline:
    def __init__(self, recorder: SpanRecorder) -> None:
        self._recorder = recorder

    async def run_stage[In, Out](self, ctx: RequestContext, stage: Stage[In, Out], data: In) -> Out:
        started = time.perf_counter()
        try:
            async with asyncio.timeout(stage.timeout_s):
                result = await stage.run(ctx, data)
        except Exception as error:
            try:
                async with asyncio.timeout(stage.timeout_s):
                    recovered = await stage.fallback(ctx, data, error)
            except Exception as fallback_error:
                await self._record(ctx, stage.name, "error", started, error)
                if fallback_error is error:  # default fallback re-raised the original
                    raise
                raise error from fallback_error
            ctx.degraded.add(stage.name)
            await self._record(ctx, stage.name, "fallback", started, error)
            return recovered
        await self._record(ctx, stage.name, "ok", started, None)
        return result

    async def _record(
        self,
        ctx: RequestContext,
        stage_name: str,
        outcome: StageOutcome,
        started: float,
        error: Exception | None,
    ) -> None:
        duration_ms = (time.perf_counter() - started) * 1000
        error_class = type(error).__name__ if error else None
        await self._recorder.record(ctx, stage_name, outcome, duration_ms, error_class)
