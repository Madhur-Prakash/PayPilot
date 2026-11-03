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
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket

from app.core.logging import get_logger
from app.core.permissions import Permission

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
    """Process-local socket registry.

    Single-process by design: the platform runs one API process, and reaching for
    Redis pub/sub before there is a second one would be infrastructure without a
    problem. The publish surface is narrow enough to swap later.
    """

    def __init__(self) -> None:
        self._by_merchant: dict[uuid.UUID, set[Connection]] = {}
        self._lock = asyncio.Lock()

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

        Returns how many sockets received it. A dead socket is dropped rather
        than retried - the client reconnects and re-reads the snapshot.
        """
        peers = list(self._by_merchant.get(merchant_id, ()))
        if not peers:
            return 0

        frame = {
            "event": event,
            "merchant_id": str(merchant_id),
            "at": datetime.now(tz=UTC).isoformat(),
            "payload": payload,
        }

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


hub = RealtimeHub()
