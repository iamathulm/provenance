"""Client-side rate limiting for free-tier models: queue briefly instead of collecting 429s.

Each model gets a sliding 60-second window of requests and estimated tokens (Groq's free limits are
per model). `acquire` takes the first listed model with room now; otherwise it waits for the
earliest one to free up, up to `max_wait_s`, then gives up with an actionable error. A 429 from the
server still happens (estimates are estimates, limits are per organization) and `cool_down`
honours its retry-after.
"""

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

from provenance.generation.providers import LLMRateLimitedError

WINDOW_S = 60.0


@dataclass(frozen=True)
class ModelLimits:
    requests_per_minute: int
    tokens_per_minute: int


@dataclass
class _Window:
    events: deque[tuple[float, int]] = field(default_factory=deque)
    blocked_until: float = 0.0

    def trim(self, now: float) -> None:
        while self.events and self.events[0][0] <= now - WINDOW_S:
            self.events.popleft()

    def wait_for(self, now: float, tokens: int, limits: ModelLimits) -> float:
        """Seconds until this model can take the call (0 = now)."""
        self.trim(now)
        wait = max(0.0, self.blocked_until - now)
        used = sum(t for _, t in self.events)
        if len(self.events) >= limits.requests_per_minute:
            wait = max(wait, self.events[0][0] + WINDOW_S - now)
        if used + tokens > limits.tokens_per_minute:
            freed, at = used, now
            for stamp, spent in self.events:
                freed -= spent
                at = stamp + WINDOW_S
                if freed + tokens <= limits.tokens_per_minute:
                    break
            wait = max(wait, at - now)
        return wait


class TokenLimiter:
    def __init__(
        self,
        limits: ModelLimits,
        max_wait_s: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._limits = limits
        self._max_wait_s = max_wait_s
        self._clock = clock
        self._sleep = sleep
        self._windows: dict[str, _Window] = {}
        self._lock = asyncio.Lock()

    def _window(self, model: str) -> _Window:
        return self._windows.setdefault(model, _Window())

    async def acquire(self, models: Sequence[str], tokens: int) -> str:
        """Reserve `tokens` on the first model with room, waiting up to `max_wait_s`."""
        tokens = min(tokens, self._limits.tokens_per_minute)
        deadline = self._clock() + self._max_wait_s
        while True:
            async with self._lock:
                now = self._clock()
                waits = {m: self._window(m).wait_for(now, tokens, self._limits) for m in models}
                ready = next((m for m in models if waits[m] == 0), None)
                if ready is not None:
                    self._window(ready).events.append((now, tokens))
                    return ready
                soonest = min(waits.values())
            if now + soonest > deadline:
                raise LLMRateLimitedError(
                    "The free Groq quota is busy. Wait about a minute and ask again.", soonest
                )
            await self._sleep(soonest)

    def cool_down(self, model: str, retry_after_s: float) -> None:
        """Respect a server-side 429 for this model."""
        window = self._window(model)
        window.blocked_until = max(window.blocked_until, self._clock() + retry_after_s)
