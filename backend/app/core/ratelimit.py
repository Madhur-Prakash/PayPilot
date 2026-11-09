"""Request-rate limiting that is shared when Redis is available.

One implementation serves two callers: the API-wide HTTP limiter
(``RateLimitMiddleware``) and the per-merchant Channel3 call budget in product
discovery. Both are cost-sensitive abuse guards, not billing meters.

* **Redis** - a fixed window: ``INCRBY`` on ``<name>:<key>:<window index>`` with a
  TTL, one tiny key per active caller. A sorted-set sliding window would hold up
  to ``limit`` members per caller, which matters on a 25 MB free Key Value
  instance. The cost of a fixed window is that a caller can burst up to twice the
  limit across a boundary - acceptable for a guard set at 300/min.
  The counter survives restarts and is shared by every API process.
* **In-process** - the original sliding window, used when Redis is not configured
  or is being skipped by the circuit breaker. Limiting degrades to per-process
  rather than to "off".
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass

from app.core.redis import RedisUnavailable, redis_store


@dataclass(frozen=True, slots=True)
class LimitResult:
    allowed: bool
    remaining: int
    retry_after: int  # seconds; meaningful when not allowed


class WindowLimiter:
    def __init__(self, name: str, *, limit: int, window_seconds: int) -> None:
        self.name = name
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}

    async def hit(self, key: str, cost: int = 1) -> LimitResult:
        """Spend ``cost`` from ``key``'s budget. A rejected call spends nothing."""
        try:
            return await self._hit_redis(key, cost)
        except RedisUnavailable:
            return self._hit_local(key, cost)

    # ------------------------------------------------------------------ redis
    async def _hit_redis(self, key: str, cost: int) -> LimitResult:
        now = time.time()
        index = int(now // self.window)
        redis_key = redis_store.key("rl", self.name, key, str(index))

        async def op(r):  # type: ignore[no-untyped-def]
            pipe = r.pipeline(transaction=True)
            pipe.incrby(redis_key, cost)
            pipe.expire(redis_key, self.window + 1)
            count, _ = await pipe.execute()
            if count > self.limit:
                await r.decrby(redis_key, cost)  # a rejected call must not eat the budget
            return int(count)

        count = await redis_store.run(op)
        if count > self.limit:
            return LimitResult(False, 0, max(1, math.ceil(self.window - (now % self.window))))
        return LimitResult(True, max(0, self.limit - count), 0)

    # ------------------------------------------------------------------ in-process
    def _hit_local(self, key: str, cost: int) -> LimitResult:
        now = time.monotonic()
        if len(self._hits) > 10_000:  # callers come and go; do not keep every one forever
            self._hits = {k: v for k, v in self._hits.items() if v and v[-1] > now - self.window}
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if len(hits) + cost > self.limit:
            retry = max(1, math.ceil(self.window - (now - hits[0]))) if hits else self.window
            return LimitResult(False, 0, retry)
        hits.extend([now] * cost)
        return LimitResult(True, max(0, self.limit - len(hits)), 0)

    def reset(self) -> None:
        """Forget in-process state (tests)."""
        self._hits.clear()
