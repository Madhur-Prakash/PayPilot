"""The realtime hub's registry and permission filter.

No database and no real socket - the hub is process-local state plus a send
call, so a stub socket is enough.

The first test here exists because of a live bug: ``Connection`` was a plain
``@dataclass``, which sets ``__hash__ = None``, and the hub keeps connections in
a ``set`` per merchant. Every browser socket was therefore accepted and *then*
died with ``TypeError: unhashable type: 'Connection'`` on the line that
registered it, so the UI sat in a two-second reconnect loop. The traceback was
being swallowed by the log formatter at the time, which is why it survived as
long as it did.
"""

from __future__ import annotations

import uuid

import pytest

from app.api.realtime import Connection, RealtimeHub
from app.core.permissions import Permission


class StubSocket:
    """Enough of a WebSocket for the hub: accept, and collect what is sent."""

    def __init__(self, *, fails: bool = False) -> None:
        self.frames: list[dict] = []
        self.accepted = False
        self._fails = fails

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, frame: dict) -> None:
        if self._fails:
            raise RuntimeError("socket is gone")
        self.frames.append(frame)


def _connection(**over):
    return Connection(
        socket=over.get("socket", StubSocket()),
        merchant_id=over.get("merchant_id", uuid.uuid4()),
        user_id=over.get("user_id", uuid.uuid4()),
        permissions=over.get("permissions", frozenset()),
    )


class TestConnectionIsHashable:
    def test_a_connection_can_go_into_a_set(self):
        """The hub stores connections in a set; an unhashable one breaks every socket."""
        assert Connection.__hash__ is not None
        assert len({_connection()}) == 1

    def test_two_connections_with_equal_fields_stay_distinct(self):
        """Same user, same merchant, two tabs - that is two sockets, not one."""
        shared = {"merchant_id": uuid.uuid4(), "user_id": uuid.uuid4()}
        a, b = _connection(**shared), _connection(**shared)
        assert a != b
        assert len({a, b}) == 2


@pytest.mark.asyncio
class TestHub:
    async def test_connect_accepts_and_registers(self):
        hub, merchant = RealtimeHub(), uuid.uuid4()
        socket = StubSocket()

        await hub.connect(
            socket, merchant_id=merchant, user_id=uuid.uuid4(), permissions=frozenset()
        )

        assert socket.accepted is True
        assert hub.connection_count(merchant) == 1

    async def test_disconnect_removes_the_connection(self):
        hub, merchant = RealtimeHub(), uuid.uuid4()
        connection = await hub.connect(
            StubSocket(), merchant_id=merchant, user_id=uuid.uuid4(), permissions=frozenset()
        )

        await hub.disconnect(connection)

        assert hub.connection_count(merchant) == 0

    async def test_publish_skips_sockets_without_the_permission(self):
        """Hiding a value in the UI is not the same as not sending it."""
        hub, merchant = RealtimeHub(), uuid.uuid4()
        allowed, denied = StubSocket(), StubSocket()
        await hub.connect(
            allowed,
            merchant_id=merchant,
            user_id=uuid.uuid4(),
            permissions=frozenset({str(Permission.INVENTORY_READ)}),
        )
        await hub.connect(
            denied, merchant_id=merchant, user_id=uuid.uuid4(), permissions=frozenset()
        )

        delivered = await hub.publish(
            merchant_id=merchant, event="inventory.updated", payload={"sku": "X"}
        )

        assert delivered == 1
        assert allowed.frames[0]["event"] == "inventory.updated"
        assert denied.frames == []

    async def test_publish_never_crosses_merchants(self):
        hub = RealtimeHub()
        mine, theirs = uuid.uuid4(), uuid.uuid4()
        other = StubSocket()
        await hub.connect(
            other,
            merchant_id=theirs,
            user_id=uuid.uuid4(),
            permissions=frozenset({str(Permission.INVENTORY_READ)}),
        )

        delivered = await hub.publish(
            merchant_id=mine, event="inventory.updated", payload={}
        )

        assert delivered == 0
        assert other.frames == []

    async def test_a_dead_socket_is_dropped_rather_than_retried(self):
        hub, merchant = RealtimeHub(), uuid.uuid4()
        perms = frozenset({str(Permission.INVENTORY_READ)})
        await hub.connect(
            StubSocket(fails=True), merchant_id=merchant, user_id=uuid.uuid4(), permissions=perms
        )

        delivered = await hub.publish(
            merchant_id=merchant, event="inventory.updated", payload={}
        )

        assert delivered == 0
        assert hub.connection_count(merchant) == 0
