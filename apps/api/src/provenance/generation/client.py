"""The LLM client the answer pipeline uses: rate limiting, model failover and call telemetry around
a provider.

A call reserves its estimated tokens on the first model with free-tier room. If the server still
answers 429 before any text has streamed, that model cools down for the server's retry-after and
the call moves to the next model. The final delta always carries the model used and the token
usage, which are recorded (never the prompt or answer text).
"""

import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from provenance.core.context import RequestContext
from provenance.generation.limiter import TokenLimiter
from provenance.generation.providers import (
    ChatRequest,
    Delta,
    LLMProvider,
    LLMRateLimitedError,
    LLMUnavailableError,
    Usage,
)

CallStatus = Literal["ok", "rate_limited", "unavailable", "failed"]
DEFAULT_COOL_DOWN_S = 10.0
CHARS_PER_TOKEN = 4  # conservative estimate for English prose


@dataclass(frozen=True)
class ProviderCall:
    provider: str
    model: str
    purpose: str
    status: CallStatus
    duration_ms: float
    prompt_tokens: int
    completion_tokens: int


class ProviderCallRecorder(Protocol):
    async def record_provider_call(self, ctx: RequestContext, call: ProviderCall) -> None: ...


@dataclass(frozen=True)
class StreamEnd(Delta):
    """The last item of `LLMClient.stream`: the model that answered and the total usage."""

    model: str = ""


def estimate_tokens(request: ChatRequest) -> int:
    prompt = sum(len(message.content) for message in request.messages) // CHARS_PER_TOKEN
    return prompt + request.max_tokens


class LLMClient:
    def __init__(
        self, provider: LLMProvider, limiter: TokenLimiter, recorder: ProviderCallRecorder
    ) -> None:
        self._provider = provider
        self._limiter = limiter
        self._recorder = recorder

    async def stream(
        self, ctx: RequestContext, request: ChatRequest, models: Sequence[str]
    ) -> AsyncIterator[Delta]:
        remaining = list(models)
        while True:
            model = await self._limiter.acquire(remaining, estimate_tokens(request))
            remaining.remove(model)
            started = time.perf_counter()
            usage = Usage()
            emitted = False
            try:
                async for delta in self._provider.stream(request, model):
                    if delta.usage is not None:
                        usage = delta.usage
                    if delta.text:
                        emitted = True
                        yield Delta(delta.text)
            except LLMRateLimitedError as error:
                self._limiter.cool_down(model, error.retry_after_s or DEFAULT_COOL_DOWN_S)
                await self._record(ctx, request, model, "rate_limited", started, usage)
                if emitted or not remaining:
                    raise
                continue
            except Exception as error:
                status: CallStatus = (
                    "unavailable" if isinstance(error, LLMUnavailableError) else "failed"
                )
                await self._record(ctx, request, model, status, started, usage)
                raise
            await self._record(ctx, request, model, "ok", started, usage)
            yield StreamEnd(usage=usage, model=model)
            return

    async def complete(
        self, ctx: RequestContext, request: ChatRequest, models: Sequence[str]
    ) -> tuple[str, StreamEnd]:
        parts: list[str] = []
        end = StreamEnd()
        async for delta in self.stream(ctx, request, models):
            if isinstance(delta, StreamEnd):
                end = delta
            else:
                parts.append(delta.text)
        return "".join(parts), end

    async def _record(
        self,
        ctx: RequestContext,
        request: ChatRequest,
        model: str,
        status: CallStatus,
        started: float,
        usage: Usage,
    ) -> None:
        await self._recorder.record_provider_call(
            ctx,
            ProviderCall(
                provider=self._provider.name,
                model=model,
                purpose=request.purpose,
                status=status,
                duration_ms=(time.perf_counter() - started) * 1000,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
            ),
        )
