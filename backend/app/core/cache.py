"""A small cache that lives in Redis when it can and in the process when it cannot.

Used for Channel3 responses, where a miss spends API credits. On Render the free
web service sleeps after 15 idle minutes and every deploy restarts it, so an
in-process cache is empty exactly when a demo starts; Key Value keeps it warm
across both.

Reads go to Redis first. When Redis is not configured or is being skipped by the
breaker they fall back to a bounded in-process dict - which is precisely how the
code behaved before Redis, so a missing Redis degrades to the old behaviour
rather than to an outage. Writes go to both so that fallback is never empty.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from typing import Any

import orjson

from app.core.redis import RedisUnavailable, redis_store

Encode = Callable[[Any], Any]
Decode = Callable[[Any], Any]


class SharedCache:
    def __init__(
        self,
        namespace: str,
        *,
        encode: Encode | None = None,
        decode: Decode | None = None,
        max_local: int = 512,
    ) -> None:
        self.namespace = namespace
        self._encode = encode
        self._decode = decode
        self._max_local = max_local
        self._local: dict[str, tuple[float, Any]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _redis_key(self, key: str) -> str:
        return redis_store.key("cache", self.namespace, key)

    # ------------------------------------------------------------------ reads
    async def get(self, key: str) -> Any | None:
        try:
            raw = await redis_store.run(lambda r: r.get(self._redis_key(key)))
        except RedisUnavailable:
            return self._get_local(key)
        if raw is None:
            return None
        try:
            value = orjson.loads(raw)
            return self._decode(value) if self._decode else value
        except Exception:
            # A value written by an older build with a different shape: a miss.
            return None

    def _get_local(self, key: str) -> Any | None:
        entry = self._local.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() >= expires_at:
            self._local.pop(key, None)
            return None
        return value

    # ------------------------------------------------------------------ writes
    async def set(self, key: str, value: Any, ttl: float) -> None:
        self._set_local(key, value, ttl)
        payload = orjson.dumps(self._encode(value) if self._encode else value, default=str)
        # The in-process copy above is the fallback when Redis is unavailable.
        with contextlib.suppress(RedisUnavailable):
            await redis_store.run(
                lambda r: r.set(self._redis_key(key), payload, px=max(1, int(ttl * 1000)))
            )

    def _set_local(self, key: str, value: Any, ttl: float) -> None:
        if len(self._local) >= self._max_local:
            now = time.monotonic()
            for stale in [k for k, (exp, _) in self._local.items() if exp <= now]:
                del self._local[stale]
            while len(self._local) >= self._max_local:
                self._local.pop(next(iter(self._local)))
        self._local[key] = (time.monotonic() + ttl, value)

    async def delete(self, key: str) -> None:
        self._local.pop(key, None)
        with contextlib.suppress(RedisUnavailable):
            await redis_store.run(lambda r: r.delete(self._redis_key(key)))

    def clear_local(self) -> None:
        """Forget the in-process copy only (tests, and a Redis-less reset)."""
        self._local.clear()

    # ------------------------------------------------------------------ single flight
    def lock(self, key: str) -> asyncio.Lock:
        """One lock per key, so concurrent misses build the value once, not N times.

        In-process only: a single API instance is what Render's plan runs, and a
        rare duplicate build during a deploy overlap costs one extra fetch.
        """
        if len(self._locks) > 1024:
            self._locks = {k: v for k, v in self._locks.items() if v.locked()}
        return self._locks.setdefault(key, asyncio.Lock())
