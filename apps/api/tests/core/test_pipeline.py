import asyncio
from dataclasses import dataclass, field
from typing import override

import pytest

from provenance.core.context import RequestContext
from provenance.core.pipeline import Pipeline, SpanRecorder, Stage, StageOutcome


@dataclass
class RecordedSpan:
    stage: str
    outcome: StageOutcome
    duration_ms: float
    error_class: str | None


@dataclass
class MemoryRecorder(SpanRecorder):
    spans: list[RecordedSpan] = field(default_factory=list)

    @override
    async def record(
        self,
        ctx: RequestContext,
        stage: str,
        outcome: StageOutcome,
        duration_ms: float,
        error_class: str | None,
    ) -> None:
        self.spans.append(RecordedSpan(stage, outcome, duration_ms, error_class))


class Double(Stage[int, int]):
    name = "double"

    @override
    async def run(self, ctx: RequestContext, data: int) -> int:
        return data * 2


class SlowWithFallback(Stage[int, int]):
    name = "slow"
    timeout_s = 0.01

    @override
    async def run(self, ctx: RequestContext, data: int) -> int:
        await asyncio.sleep(1)
        return data

    @override
    async def fallback(self, ctx: RequestContext, data: int, error: Exception) -> int:
        return -1


class BrokenFallback(Stage[int, int]):
    name = "broken"

    @override
    async def run(self, ctx: RequestContext, data: int) -> int:
        msg = "secret detail in message"
        raise ValueError(msg)

    @override
    async def fallback(self, ctx: RequestContext, data: int, error: Exception) -> int:
        msg = "fallback also failed"
        raise RuntimeError(msg)


class NoFallback(Stage[int, int]):
    name = "strict"

    @override
    async def run(self, ctx: RequestContext, data: int) -> int:
        msg = "upstream unavailable"
        raise ConnectionError(msg)


@pytest.fixture
def recorder() -> MemoryRecorder:
    return MemoryRecorder()


@pytest.fixture
def ctx() -> RequestContext:
    return RequestContext(correlation_id="test-correlation")


async def test_successful_stage_records_ok_span(
    recorder: MemoryRecorder, ctx: RequestContext
) -> None:
    result = await Pipeline(recorder).run_stage(ctx, Double(), 21)

    assert result == 42
    assert [(s.stage, s.outcome, s.error_class) for s in recorder.spans] == [("double", "ok", None)]
    assert recorder.spans[0].duration_ms >= 0
    assert ctx.degraded == set()


async def test_timeout_triggers_fallback_and_marks_degraded(
    recorder: MemoryRecorder, ctx: RequestContext
) -> None:
    result = await Pipeline(recorder).run_stage(ctx, SlowWithFallback(), 5)

    assert result == -1
    assert ctx.degraded == {"slow"}
    assert [(s.outcome, s.error_class) for s in recorder.spans] == [("fallback", "TimeoutError")]


async def test_failing_fallback_reraises_original_and_records_error(
    recorder: MemoryRecorder, ctx: RequestContext
) -> None:
    with pytest.raises(ValueError, match="secret detail"):
        await Pipeline(recorder).run_stage(ctx, BrokenFallback(), 1)

    assert [(s.outcome, s.error_class) for s in recorder.spans] == [("error", "ValueError")]
    assert ctx.degraded == set()


async def test_stage_without_fallback_reraises(
    recorder: MemoryRecorder, ctx: RequestContext
) -> None:
    with pytest.raises(ConnectionError):
        await Pipeline(recorder).run_stage(ctx, NoFallback(), 1)

    assert [(s.outcome, s.error_class) for s in recorder.spans] == [("error", "ConnectionError")]


async def test_span_has_error_class_not_message(
    recorder: MemoryRecorder, ctx: RequestContext
) -> None:
    with pytest.raises(ValueError, match="secret detail"):
        await Pipeline(recorder).run_stage(ctx, BrokenFallback(), 1)

    assert "secret" not in repr(recorder.spans)


async def test_default_fallback_reraises_without_self_chaining(
    recorder: MemoryRecorder, ctx: RequestContext
) -> None:
    with pytest.raises(ConnectionError) as raised:
        await Pipeline(recorder).run_stage(ctx, NoFallback(), 1)

    assert raised.value.__cause__ is None
