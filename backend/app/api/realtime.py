"""The realtime hub: backend to browser.

Webhooks carry system-to-system triggers; this carries state to the UI. The two
are deliberately separate - a browser is not a webhook endpoint, and n8n is not a
websocket client.

Two rules hold here:

* **Tenant isolation.** Sockets are bucketed by merchant. A broadcast can only
  reach the merchant it names, so there is no global fan-out to filter after the
  fact.
* **Permission filtering.** Each event declares the permission it requires, and a
  socket that lacks it never receives the frame. Hiding a value in the UI is not
  the same as not sending it.

The socket is a *notification* channel, not a source of truth: it tells the
client something changed and carries enough to update a row, and the client
re-reads the authoritative snapshot on reconnect.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import orjson
from fastapi import WebSocket

from app.core.config import settings
from app.core.logging import get_logger
from app.core.permissions import Permission
from app.core.redis import RedisUnavailable, redis_store

log = get_logger(__name__)


@dataclass(slots=True, eq=False)
class Connection:
    """One live socket.

    ``eq=False`` is load-bearing, not tidiness: connections are held in a ``set``
    per merchant, and a value-comparing dataclass sets ``__hash__ = None``, which
    makes registering a socket raise ``TypeError: unhashable type``. Identity is
    also the semantics we want - two sockets from the same user on the same
    merchant are two connections, not one.
    """

    socket: WebSocket
    merchant_id: uuid.UUID
    user_id: uuid.UUID
    permissions: frozenset[str]
    subscriptions: set[str] = field(default_factory=lambda: {"inventory"})

    def may_receive(self, required: str | None) -> bool:
        return required is None or required in self.permissions


class RealtimeHub:
    """Socket registry, with an optional Redis pub/sub bridge between processes.

    Sockets are process-local - a WebSocket lives in the process that accepted it.
    What Redis adds is reach: ``publish`` delivers to this process's sockets
    immediately, and also announces the event on a Redis channel so every *other*
    API process delivers it to theirs. That covers Render's deploy overlap (the old
    and new instance are briefly both live) and any scale-out, and it lets a
    separate worker push to browsers.

    Local delivery never waits on Redis, and a Redis outage only costs cross-process
    reach: the socket is a notification channel and clients re-read the snapshot on
    reconnect. Each message carries its origin so a process ignores its own echo.
    """

    CHANNEL_SUFFIX = ("realtime",)

    def __init__(self) -> None:
        self._by_merchant: dict[uuid.UUID, set[Connection]] = {}
        self._lock = asyncio.Lock()
        self._origin = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self._bridge: asyncio.Task[None] | None = None

    async def connect(
        self,
        socket: WebSocket,
        *,
        merchant_id: uuid.UUID,
        user_id: uuid.UUID,
        permissions: frozenset[str],
    ) -> Connection:
        await socket.accept()
        connection = Connection(
            socket=socket,
            merchant_id=merchant_id,
            user_id=user_id,
            permissions=permissions,
        )
        async with self._lock:
            self._by_merchant.setdefault(merchant_id, set()).add(connection)
        log.info(
            "realtime_connected",
            merchant_id=str(merchant_id),
            user_id=str(user_id),
            sockets=len(self._by_merchant.get(merchant_id, ())),
        )
        return connection

    async def disconnect(self, connection: Connection) -> None:
        async with self._lock:
            peers = self._by_merchant.get(connection.merchant_id)
            if peers:
                peers.discard(connection)
                if not peers:
                    self._by_merchant.pop(connection.merchant_id, None)
        log.info("realtime_disconnected", merchant_id=str(connection.merchant_id))

    def connection_count(self, merchant_id: uuid.UUID) -> int:
        return len(self._by_merchant.get(merchant_id, ()))

    async def publish(
        self,
        *,
        merchant_id: uuid.UUID,
        event: str,
        payload: dict[str, Any],
        required_permission: str | None = Permission.INVENTORY_READ,
    ) -> int:
        """Send to every authorised socket for one merchant.

        Returns how many of *this process's* sockets received it. A dead socket is
        dropped rather than retried - the client reconnects and re-reads the
        snapshot. Other processes are reached through Redis when it is configured.
        """
        frame = {
            "event": event,
            "merchant_id": str(merchant_id),
            "at": datetime.now(tz=UTC).isoformat(),
            "payload": payload,
        }
        delivered = await self._deliver(merchant_id, frame, required_permission)
        await self._announce(merchant_id, frame, required_permission)
        return delivered

    async def _deliver(
        self, merchant_id: uuid.UUID, frame: dict[str, Any], required_permission: str | None
    ) -> int:
        peers = list(self._by_merchant.get(merchant_id, ()))
        if not peers:
            return 0

        delivered = 0
        stale: list[Connection] = []
        for connection in peers:
            if not connection.may_receive(required_permission):
                continue
            try:
                await connection.socket.send_json(frame)
                delivered += 1
            except Exception:
                stale.append(connection)

        for connection in stale:
            await self.disconnect(connection)

        return delivered

    # ------------------------------------------------------------------ redis bridge
    @property
    def _channel(self) -> str:
        return redis_store.key(*self.CHANNEL_SUFFIX)

    @property
    def bridge_enabled(self) -> bool:
        return settings.realtime_redis_enabled and redis_store.enabled

    async def _announce(
        self, merchant_id: uuid.UUID, frame: dict[str, Any], required_permission: str | None
    ) -> None:
        if not self.bridge_enabled:
            return
        message = orjson.dumps(
            {
                "origin": self._origin,
                "merchant_id": str(merchant_id),
                "permission": str(required_permission) if required_permission else None,
                "frame": frame,
            },
            default=str,
        )
        # Local sockets were already served; other processes catch up on reconnect.
        with contextlib.suppress(RedisUnavailable):
            await redis_store.run(lambda r: r.publish(self._channel, message))

    def start_bridge(self) -> None:
        """Subscribe to other processes' events. A no-op without Redis."""
        if not self.bridge_enabled or (self._bridge is not None and not self._bridge.done()):
            return
        self._bridge = asyncio.create_task(self._listen(), name="realtime-redis-bridge")
        log.info("realtime_bridge_started", channel=self._channel)

    async def stop_bridge(self) -> None:
        task, self._bridge = self._bridge, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _listen(self) -> None:
        backoff = 1.0
        while True:
            client = None
            pubsub = None
            try:
                client = redis_store.new_pubsub_client()
                pubsub = client.pubsub()
                await pubsub.subscribe(self._channel)
                backoff = 1.0
                while True:
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=5.0)
                    if message is not None:
                        await self._relay(message.get("data"))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning(
                    "realtime_bridge_disconnected",
                    error=f"{type(exc).__name__}: {exc}"[:200],
                    retry_in_seconds=backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
            finally:
                with contextlib.suppress(Exception):
                    if pubsub is not None:
                        await pubsub.aclose()
                with contextlib.suppress(Exception):
                    await redis_store.release_pubsub_client(client)

    async def _relay(self, raw: Any) -> None:
        """Deliver one message another process announced."""
        try:
            message = orjson.loads(raw)
            if message["origin"] == self._origin:
                return  # our own echo - already delivered locally
            await self._deliver(
                uuid.UUID(message["merchant_id"]), message["frame"], message.get("permission")
            )
        except Exception as exc:  # one malformed message must not kill the bridge
            log.warning("realtime_bridge_bad_message", detail=f"{type(exc).__name__}: {exc}"[:160])


hub = RealtimeHub()
