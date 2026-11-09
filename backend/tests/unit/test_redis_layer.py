"""Redis (Render Key Value) - rate limits, caches and the realtime bridge.

Runs against fakeredis, so no server is needed. Every behaviour is checked twice
where it matters: with Redis, and with Redis missing or broken - because the
property that makes this safe to deploy is that losing Redis degrades to the
in-process behaviour the app had before, never to an error.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import fakeredis
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.api.realtime import RealtimeHub
from app.core.cache import SharedCache
from app.core.config import settings
from app.core.permissions import Permission
from app.core.ratelimit import WindowLimiter
from app.core.redis import RedisStore, RedisUnavailable, redis_store
from app.integrations.sponsors.channel3_catalog import (
    CatalogOffer,
    CatalogProduct,
    product_from_cache,
    product_to_cache,
)


def _snapshot():
    return redis_store._client, redis_store._retry_at, redis_store._last_error


def _restore(state) -> None:
    redis_store._client, redis_store._retry_at, redis_store._last_error = state


@pytest.fixture
def server() -> fakeredis.FakeServer:
    return fakeredis.FakeServer()


@pytest.fixture
def redis(server):
    """The shared store, pointed at fakeredis and restored afterwards."""
    state = _snapshot()
    redis_store.use_client(fakeredis.FakeAsyncRedis(server=server, decode_responses=True))
    yield redis_store
    _restore(state)


class BrokenClient:
    """Every command fails like a dropped connection."""

    calls = 0

    def __getattr__(self, name):
        def fail(*_a, **_k):
            BrokenClient.calls += 1
            raise RedisConnectionError("connection refused")

        return fail


@pytest.fixture
def broken():
    state = _snapshot()
    BrokenClient.calls = 0
    redis_store.use_client(BrokenClient())
    yield redis_store
    _restore(state)


class TestStore:
    async def test_unconfigured_store_raises_unavailable(self):
        store = RedisStore()
        assert store.enabled is False and store.status() == "not_configured"
        with pytest.raises(RedisUnavailable):
            await store.run(lambda r: r.ping())

    async def test_breaker_stops_hammering_a_dead_redis(self, broken):
        async def get(r):
            return await r.get("k")

        with pytest.raises(RedisUnavailable):
            await broken.run(get)
        assert BrokenClient.calls == 1 and broken.status() == "unreachable"
        for _ in range(5):  # inside the retry window: skipped, not attempted
            with pytest.raises(RedisUnavailable):
                await broken.run(get)
        assert BrokenClient.calls == 1

    async def test_it_recovers_once_the_window_passes(self, redis):
        redis._trip(RedisConnectionError("blip"))
        with pytest.raises(RedisUnavailable):
            await redis.run(lambda r: r.ping())
        redis._retry_at = 0.0
        assert await redis.ping() is True and redis.status() == "ok"

    def test_keys_are_namespaced(self):
        assert redis_store.key("cache", "shelf", "x") == f"{settings.redis_key_prefix}:cache:shelf:x"


class TestLimiter:
    async def test_it_allows_up_to_the_limit_then_refuses(self, redis):
        limiter = WindowLimiter("t", limit=3, window_seconds=60)
        results = [await limiter.hit("a") for _ in range(4)]
        assert [r.allowed for r in results] == [True, True, True, False]
        assert results[2].remaining == 0 and results[3].retry_after >= 1

    async def test_a_refused_call_does_not_eat_the_budget(self, redis):
        limiter = WindowLimiter("t", limit=2, window_seconds=60)
        await limiter.hit("a", 2)
        for _ in range(5):
            assert (await limiter.hit("a")).allowed is False
        keys = [k async for k in redis._client.scan_iter("*:rl:t:*")]
        assert len(keys) == 1 and int(await redis._client.get(keys[0])) == 2

    async def test_cost_and_isolation(self, redis):
        limiter = WindowLimiter("t", limit=5, window_seconds=60)
        assert (await limiter.hit("a", 5)).allowed
        assert (await limiter.hit("a", 1)).allowed is False
        assert (await limiter.hit("b", 1)).allowed  # another caller is unaffected

    async def test_the_budget_is_shared_between_processes(self, redis):
        """Two limiter instances = two API processes: one Redis budget."""
        one = WindowLimiter("shared", limit=2, window_seconds=60)
        two = WindowLimiter("shared", limit=2, window_seconds=60)
        assert (await one.hit("m")).allowed and (await two.hit("m")).allowed
        assert (await one.hit("m")).allowed is False
        assert (await two.hit("m")).allowed is False

    async def test_counters_expire_with_their_window(self, redis):
        limiter = WindowLimiter("t", limit=1, window_seconds=60)
        await limiter.hit("a")
        keys = [k async for k in redis._client.scan_iter("*:rl:t:*")]
        assert 0 < await redis._client.ttl(keys[0]) <= 61

    async def test_without_redis_it_falls_back_to_the_process(self):
        limiter = WindowLimiter("t", limit=2, window_seconds=60)
        assert [(await limiter.hit("a")).allowed for _ in range(3)] == [True, True, False]
        assert (await limiter.hit("b")).allowed

    async def test_a_broken_redis_fails_open_to_the_process_limit(self, broken):
        limiter = WindowLimiter("t", limit=2, window_seconds=60)
        assert [(await limiter.hit("a")).allowed for _ in range(3)] == [True, True, False]


def _product() -> CatalogProduct:
    return CatalogProduct(
        id="prod_1",
        title="Burr grinder",
        brand="Acme",
        images=[{"url": "u", "is_main": True}],
        structured_attributes={"material": ["steel"]},
        ratings={"value": 4.5, "count": 10},
        offers=[
            CatalogOffer(
                domain="shop.test",
                url="https://shop.test/p",
                price=Decimal("49.90"),
                currency="USD",
                compare_at_price=Decimal("59.90"),
                availability="InStock",
                commission_rate=Decimal("0.05"),
            )
        ],
    )


class TestCache:
    async def test_a_value_round_trips_through_redis(self, redis):
        cache = SharedCache("t")
        await cache.set("k", {"a": [1, 2]}, ttl=60)
        cache.clear_local()  # prove the read came from Redis, not the process
        assert await cache.get("k") == {"a": [1, 2]}
        assert 0 < await redis._client.pttl(redis.key("cache", "t", "k")) <= 60_000

    async def test_two_processes_see_the_same_entry(self, redis):
        a, b = SharedCache("t"), SharedCache("t")
        await a.set("k", "warm", ttl=60)
        assert await b.get("k") == "warm"

    async def test_a_miss_is_none_and_delete_removes(self, redis):
        cache = SharedCache("t")
        assert await cache.get("nope") is None
        await cache.set("k", 1, ttl=60)
        await cache.delete("k")
        assert await cache.get("k") is None

    async def test_a_catalog_product_survives_the_trip_exactly(self, redis):
        cache = SharedCache("p", encode=product_to_cache, decode=product_from_cache)
        original = _product()
        await cache.set("k", original, ttl=60)
        cache.clear_local()
        restored = await cache.get("k")
        assert restored == original
        assert restored.offers[0].price == Decimal("49.90") and restored.best_offer.in_stock is True

    async def test_an_unreadable_entry_is_a_miss_not_an_error(self, redis):
        cache = SharedCache("p", encode=product_to_cache, decode=product_from_cache)
        await redis._client.set(redis.key("cache", "p", "k"), '{"unexpected": true}')
        assert await cache.get("k") is None

    async def test_without_redis_the_process_copy_serves_and_expires(self):
        cache = SharedCache("t")
        await cache.set("k", "v", ttl=60)
        assert await cache.get("k") == "v"
        await cache.set("short", "v", ttl=0.01)
        await asyncio.sleep(0.03)
        assert await cache.get("short") is None

    async def test_a_broken_redis_still_serves_from_the_process(self, broken):
        cache = SharedCache("t")
        await cache.set("k", "v", ttl=60)  # must not raise
        assert await cache.get("k") == "v"

    async def test_the_process_copy_is_bounded(self):
        cache = SharedCache("t", max_local=4)
        for i in range(10):
            await cache.set(str(i), i, ttl=60)
        assert len(cache._local) <= 4 and await cache.get("9") == 9

    async def test_concurrent_misses_share_one_lock(self):
        cache = SharedCache("t")
        assert cache.lock("k") is cache.lock("k") and cache.lock("k") is not cache.lock("j")


class StubSocket:
    def __init__(self) -> None:
        self.frames: list[dict] = []

    async def accept(self) -> None: ...

    async def send_json(self, frame: dict) -> None:
        self.frames.append(frame)


PERM = frozenset({str(Permission.INVENTORY_READ)})


async def _settle(predicate, timeout=3.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return predicate()


class TestRealtimeBridge:
    async def test_an_event_reaches_sockets_on_another_process_exactly_once(self, redis):
        merchant = uuid.uuid4()
        here, there = RealtimeHub(), RealtimeHub()
        near, far = StubSocket(), StubSocket()
        await here.connect(near, merchant_id=merchant, user_id=uuid.uuid4(), permissions=PERM)
        await there.connect(far, merchant_id=merchant, user_id=uuid.uuid4(), permissions=PERM)
        here.start_bridge()
        there.start_bridge()
        try:
            await asyncio.sleep(0.3)  # let both subscribe
            delivered = await here.publish(
                merchant_id=merchant, event="inventory.updated", payload={"n": 1}
            )
            assert delivered == 1  # this process's own socket, immediately
            assert await _settle(lambda: len(far.frames) == 1)
            await asyncio.sleep(0.2)
            assert len(near.frames) == 1, "the publisher must not receive its own echo"
            assert len(far.frames) == 1 and far.frames[0]["payload"] == {"n": 1}
        finally:
            await here.stop_bridge()
            await there.stop_bridge()

    async def test_the_bridge_keeps_tenant_and_permission_isolation(self, redis):
        merchant, other = uuid.uuid4(), uuid.uuid4()
        here, there = RealtimeHub(), RealtimeHub()
        allowed, denied, stranger = StubSocket(), StubSocket(), StubSocket()
        await there.connect(allowed, merchant_id=merchant, user_id=uuid.uuid4(), permissions=PERM)
        await there.connect(
            denied, merchant_id=merchant, user_id=uuid.uuid4(), permissions=frozenset()
        )
        await there.connect(stranger, merchant_id=other, user_id=uuid.uuid4(), permissions=PERM)
        there.start_bridge()
        try:
            await asyncio.sleep(0.3)
            await here.publish(merchant_id=merchant, event="inventory.updated", payload={})
            assert await _settle(lambda: len(allowed.frames) == 1)
            await asyncio.sleep(0.2)
            assert denied.frames == [] and stranger.frames == []
        finally:
            await there.stop_bridge()

    async def test_local_delivery_never_waits_on_a_broken_redis(self, broken):
        hub, merchant, sock = RealtimeHub(), uuid.uuid4(), StubSocket()
        await hub.connect(sock, merchant_id=merchant, user_id=uuid.uuid4(), permissions=PERM)
        assert await hub.publish(merchant_id=merchant, event="e", payload={}) == 1
        assert len(sock.frames) == 1

    async def test_a_malformed_message_does_not_kill_the_bridge(self, redis):
        merchant, hub, sock = uuid.uuid4(), RealtimeHub(), StubSocket()
        await hub.connect(sock, merchant_id=merchant, user_id=uuid.uuid4(), permissions=PERM)
        hub.start_bridge()
        try:
            await asyncio.sleep(0.3)
            await redis._client.publish(hub._channel, "not json")
            await RealtimeHub().publish(merchant_id=merchant, event="after", payload={})
            assert await _settle(lambda: len(sock.frames) == 1)
            assert sock.frames[0]["event"] == "after"
        finally:
            await hub.stop_bridge()

    async def test_no_bridge_without_redis(self):
        hub = RealtimeHub()
        hub.start_bridge()
        assert hub._bridge is None


class TestApi:
    async def test_health_reports_redis_without_degrading(self, client):
        data = (await client.get("/health")).json()["data"]
        assert data["checks"]["redis"] == "not_configured" and data["status"] == "ok"

    async def test_health_when_redis_is_configured(self, client, redis):
        data = (await client.get("/health")).json()["data"]
        assert data["checks"]["redis"] == "ok" and data["status"] == "ok"

    async def test_health_when_redis_is_down_still_ok(self, client, broken):
        data = (await client.get("/health")).json()["data"]
        assert data["checks"]["redis"] == "unreachable" and data["status"] == "ok"


class TestRateLimitMiddleware:
    """The HTTP limiter, switched on (the suite normally turns it off)."""

    @staticmethod
    def _app(limit: int):
        import httpx
        from fastapi import FastAPI

        from app.core.middleware import RateLimitMiddleware

        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, limit=limit, window_seconds=60)

        @app.get("/api/v1/thing")
        async def thing() -> dict:
            return {"ok": True}

        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")

    @pytest.fixture(autouse=True)
    def _enabled(self, monkeypatch):
        monkeypatch.setattr(settings, "rate_limit_enabled", True)

    async def test_it_limits_through_redis_and_reports_headers(self, redis):
        async with self._app(2) as http:
            first = await http.get("/api/v1/thing")
            await http.get("/api/v1/thing")
            third = await http.get("/api/v1/thing")
        assert first.status_code == 200 and first.headers["X-RateLimit-Remaining"] == "1"
        assert third.status_code == 429 and int(third.headers["Retry-After"]) >= 1
        assert third.json()["error"]["code"] == "RATE_LIMITED"
        # The bucket key carries no part of the bearer token.
        keys = [k async for k in redis._client.scan_iter("*:rl:http:*")]
        assert keys and not any("Bearer" in k for k in keys)

    async def test_callers_are_bucketed_separately(self, redis):
        async with self._app(1) as http:
            a = {"Authorization": "Bearer aaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
            b = {"Authorization": "Bearer bbbbbbbbbbbbbbbbbbbbbbbbbbbb"}
            assert (await http.get("/api/v1/thing", headers=a)).status_code == 200
            assert (await http.get("/api/v1/thing", headers=a)).status_code == 429
            assert (await http.get("/api/v1/thing", headers=b)).status_code == 200

    async def test_a_broken_redis_is_never_a_5xx(self, broken):
        async with self._app(2) as http:
            codes = [(await http.get("/api/v1/thing")).status_code for _ in range(3)]
        assert codes == [200, 200, 429]  # still limited, per process
