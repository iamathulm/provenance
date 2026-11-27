"""Per-user question throttling, so one user or script cannot spend the shared free LLM quota.

In-process sliding windows, like the login limiter: correct for the single API instance this
project runs. A refused question costs nothing: it is rejected before any model call.
"""

import time
import uuid
from collections import deque
from collections.abc import Callable

from provenance.core.errors import RateLimitedError

MINUTE_S, HOUR_S = 60.0, 3600.0


class QuestionRateLimiter:
    def __init__(
        self,
        per_minute: int,
        per_hour: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._per_minute = per_minute
        self._per_hour = per_hour
        self._clock = clock
        self._asked: dict[uuid.UUID, deque[float]] = {}

    def check_and_record(self, user_id: uuid.UUID) -> None:
        now = self._clock()
        asked = self._asked.setdefault(user_id, deque())
        while asked and asked[0] <= now - HOUR_S:
            asked.popleft()
        last_minute = sum(1 for stamp in asked if stamp > now - MINUTE_S)
        if last_minute >= self._per_minute or len(asked) >= self._per_hour:
            msg = (
                "You're asking faster than the free model quota allows. "
                "Wait a minute and ask again."
            )
            raise RateLimitedError(msg)
        asked.append(now)
