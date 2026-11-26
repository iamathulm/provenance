"""Sliding-window login throttling.

In-process state: correct for the single API instance this project runs. A multi-instance
deployment would move these counters to shared storage.
"""

import time
from collections import deque
from collections.abc import Callable

from provenance.core.errors import RateLimitedError


class LoginRateLimiter:
    def __init__(
        self,
        max_per_email: int = 5,
        max_per_ip: int = 30,
        window_s: float = 900,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_per_email = max_per_email
        self._max_per_ip = max_per_ip
        self._window_s = window_s
        self._clock = clock
        self._failures_by_email: dict[str, deque[float]] = {}
        self._attempts_by_ip: dict[str, deque[float]] = {}

    def check(self, email: str, ip: str) -> None:
        """Raise `RateLimitedError` if this email or client has exceeded its budget."""
        if (
            self._count(self._failures_by_email, email) >= self._max_per_email
            or self._count(self._attempts_by_ip, ip) >= self._max_per_ip
        ):
            msg = "Too many sign-in attempts. Try again in a few minutes."
            raise RateLimitedError(msg)

    def record_attempt(self, ip: str) -> None:
        self._attempts_by_ip.setdefault(ip, deque()).append(self._clock())

    def record_failure(self, email: str) -> None:
        self._failures_by_email.setdefault(email, deque()).append(self._clock())

    def tracked_keys(self) -> int:
        """Number of emails and clients currently holding counters (bounded by activity)."""
        return len(self._failures_by_email) + len(self._attempts_by_ip)

    def _count(self, events_by_key: dict[str, deque[float]], key: str) -> int:
        events = events_by_key.get(key)
        if events is None:
            return 0
        cutoff = self._clock() - self._window_s
        while events and events[0] <= cutoff:
            events.popleft()
        if not events:
            del events_by_key[key]
        return len(events)
