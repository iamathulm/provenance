import uuid

import pytest

from provenance.conversations.limits import QuestionRateLimiter
from provenance.core.errors import RateLimitedError


class Clock:
    now = 0.0

    def __call__(self) -> float:
        return self.now


def test_limits_per_minute_and_per_hour_per_user() -> None:
    clock = Clock()
    limiter = QuestionRateLimiter(per_minute=2, per_hour=3, clock=clock)
    alice, bob = uuid.uuid4(), uuid.uuid4()

    limiter.check_and_record(alice)
    limiter.check_and_record(alice)
    with pytest.raises(RateLimitedError):
        limiter.check_and_record(alice)
    limiter.check_and_record(bob)  # other users are unaffected
    clock.now = 61
    limiter.check_and_record(alice)
    clock.now = 122
    with pytest.raises(RateLimitedError):
        limiter.check_and_record(alice)  # hourly budget spent
    clock.now = 3601
    limiter.check_and_record(alice)
