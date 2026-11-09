"""Redis (Render Key Value) - the shared-state seam.

What Redis is used for here, and what it is deliberately not:

* **Used for** state that is cheap to lose and expensive to recompute or that
  must be shared: rate-limit counters, Channel3 response caches (every miss
  spends API credits), and pub/sub for the realtime hub.
* **Never** a source of truth. Postgres keeps everything that matters, so
  Render's free Key Value plan (25 MB, no persistence) costs a cold cache after
  a restart - nothing else.

It is also never a hard dependency. With no ``REDIS_URL`` every caller keeps its
in-process behaviour, and when Redis is configured but unreachable a circuit
breaker sends callers to that same fallback for ``REDIS_RETRY_SECONDS`` rather
than letting each request wait out a timeout. Callers see one exception type,
``RedisUnavailable``, and decide what "degraded" means for them.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

T = TypeVar("T")


class RedisUnavailable(Exception):
    """Redis is not configured, is being skipped by the breaker, or just failed."""


class RedisStore:
    """One lazily-created client plus a circuit breaker."""

    def __init__(self) -> None:
        self._client: aioredis.Redis | None = None
        self._retry_at = 0.0
        self._last_error = ""

    # ------------------------------------------------------------------ state
    @property
    def enabled(self) -> bool:
        return bool(settings.redis_url) or self._client is not None

    @property
    def last_error(self) -> str:
        return self._last_error

    def key(self, *parts: str) -> str:
        """A namespaced key: ``paypilot:cache:shelf:<merchant>``."""
        return ":".join((settings.redis_key_prefix, *parts))

    def use_client(self, client: Any) -> None:
        """Inject a client (tests use fakeredis). Resets the breaker."""
        self._client = client
        self._retry_at = 0.0
        self._last_error = ""

    # ------------------------------------------------------------------ client
    def _get_client(self) -> aioredis.Redis:
        if self._client is None:
            self._client = aioredis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=settings.redis_connect_timeout_seconds,
                socket_timeout=settings.redis_command_timeout_seconds,
                health_check_interval=30,
                max_connections=20,
            )
        return self._client

    def new_pubsub_client(self) -> aioredis.Redis:
        """A dedicated connection for subscribing.

        Separate from the command client: a subscriber blocks on reads, so it must
        not inherit the short command timeout, and it should not occupy a pooled
        connection the request path needs.
        """
        if self._client is not None and not settings.redis_url:
            return self._client  # injected test client
        return aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=settings.redis_connect_timeout_seconds,
            socket_keepalive=True,
            health_check_interval=25,
        )

    async def release_pubsub_client(self, client: Any) -> None:
        """Close a client from :meth:`new_pubsub_client` (never the shared command client)."""
        if client is not None and client is not self._client:
            await client.aclose()

    # ------------------------------------------------------------------ calls
    def _trip(self, exc: BaseException) -> None:
        self._last_error = f"{type(exc).__name__}: {exc}"[:200]
        first = time.monotonic() >= self._retry_at
        self._retry_at = time.monotonic() + settings.redis_retry_seconds
        if first:
            log.warning(
                "redis_unavailable",
                error=self._last_error,
                retry_in_seconds=settings.redis_retry_seconds,
            )

    async def run(self, op: Callable[[aioredis.Redis], Awaitable[T]]) -> T:
        """Run one Redis operation, or raise ``RedisUnavailable``."""
        if not self.enabled:
            raise RedisUnavailable("REDIS_URL is not set")
        if time.monotonic() < self._retry_at:
            raise RedisUnavailable(self._last_error or "circuit open")
        try:
            result = await op(self._get_client())
        except (RedisError, OSError, TimeoutError) as exc:
            self._trip(exc)
            raise RedisUnavailable(self._last_error) from exc
        if self._last_error:
            log.info("redis_recovered")
            self._last_error = ""
        return result

    async def ping(self) -> bool:
        try:
            return bool(await self.run(lambda r: r.ping()))
        except RedisUnavailable:
            return False

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                await client.aclose()
            except Exception as exc:  # pragma: no cover - shutdown only
                log.debug("redis_close_failed", detail=str(exc)[:120])

    def status(self) -> str:
        """``not_configured`` | ``ok`` | ``unreachable`` - for /health, no I/O."""
        if not self.enabled:
            return "not_configured"
        return "unreachable" if self._last_error else "ok"


redis_store = RedisStore()

__all__ = ["RedisStore", "RedisUnavailable", "redis_store"]
