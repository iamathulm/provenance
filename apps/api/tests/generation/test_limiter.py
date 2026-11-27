import pytest

from provenance.generation.limiter import ModelLimits, TokenLimiter
from provenance.generation.providers import LLMRateLimitedError

A, B = "model-a", "model-b"


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def limiter(time: FakeTime, max_wait_s: float = 8.0) -> TokenLimiter:
    return TokenLimiter(ModelLimits(30, 8_000), max_wait_s, time.clock, time.sleep)


async def test_fails_over_to_the_next_model_when_tokens_run_out() -> None:
    time = FakeTime()
    limits = limiter(time)

    picked = [await limits.acquire([A, B], 3_000) for _ in range(4)]

    assert picked == [A, A, B, B]
    assert time.slept == []


async def test_waits_for_the_window_then_gives_up_past_max_wait() -> None:
    time = FakeTime()
    limits = limiter(time, max_wait_s=8)
    await limits.acquire([A], 6_000)
    time.now = 55.0

    waited = await limits.acquire([A], 6_000)  # frees at t=60, 5 s from now

    assert waited == A
    assert time.slept == [5.0]
    with pytest.raises(LLMRateLimitedError):
        await limits.acquire([A], 6_000)  # next free at t=120, 60 s away


async def test_requests_per_minute_and_server_cool_down() -> None:
    time = FakeTime()
    limits = TokenLimiter(ModelLimits(2, 100_000), 0, time.clock, time.sleep)
    await limits.acquire([A], 10)
    await limits.acquire([A], 10)

    with pytest.raises(LLMRateLimitedError):
        await limits.acquire([A], 10)
    limits.cool_down(B, 30)
    with pytest.raises(LLMRateLimitedError):
        await limits.acquire([B], 10)
