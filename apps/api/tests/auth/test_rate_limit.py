import pytest

from provenance.auth.rate_limit import LoginRateLimiter
from provenance.core.errors import RateLimitedError


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


def test_blocks_after_max_failures_per_email_then_recovers() -> None:
    clock = FakeClock()
    limiter = LoginRateLimiter(max_per_email=5, max_per_ip=30, window_s=900, clock=clock)

    for _ in range(5):
        limiter.check("maya@example.com", "10.0.0.1")
        limiter.record_attempt("10.0.0.1")
        limiter.record_failure("maya@example.com")

    with pytest.raises(RateLimitedError):
        limiter.check("maya@example.com", "10.0.0.1")
    limiter.check("arun@example.com", "10.0.0.2")  # other accounts and clients unaffected

    clock.now += 901
    limiter.check("maya@example.com", "10.0.0.1")


def test_blocks_after_max_attempts_per_ip() -> None:
    limiter = LoginRateLimiter(max_per_email=5, max_per_ip=3, window_s=900, clock=FakeClock())

    for index in range(3):
        limiter.check(f"user{index}@example.com", "10.0.0.9")
        limiter.record_attempt("10.0.0.9")

    with pytest.raises(RateLimitedError):
        limiter.check("someone-new@example.com", "10.0.0.9")
