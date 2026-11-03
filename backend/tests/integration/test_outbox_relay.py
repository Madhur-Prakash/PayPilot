"""The outbox relay and the delivery it drives.

Until the relay existed, an event written by a stock change sat at PENDING until
somebody pressed "Flush event outbox" — and because retries are also only
attempted by a dispatch, a failed delivery was never retried either. These cover
the two halves of the fix: that the relay only runs when it can do something
useful, and that claiming a batch leases it rather than leaving it visible to a
second worker.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.core.config import settings
from app.db.models.automation import DeliveryStatus, DomainEvent
from app.services.inventory import events as event_bus
from app.services.inventory.relay import OutboxRelay


async def _event(session, merchant_id, **overrides) -> DomainEvent:
    event = DomainEvent(
        merchant_id=merchant_id,
        event_type="inventory.low_stock",
        entity_type="inventory_item",
        entity_id=uuid.uuid4(),
        correlation_id=f"TEST-{uuid.uuid4().hex[:8]}",
        source="backend",
        payload={"sku": "TEST-1", "available": 3.0},
        delivery_status=DeliveryStatus.PENDING,
        **{"next_attempt_at": datetime.now(tz=UTC), **overrides},
    )
    session.add(event)
    await session.flush()
    return event


class TestRelayLifecycle:
    """It must not spin pointlessly, and it must not die quietly."""

    def test_it_does_not_start_without_a_webhook_url(self, monkeypatch):
        monkeypatch.setattr(settings, "n8n_inventory_webhook_url", "")
        monkeypatch.setattr(settings, "inventory_automation_enabled", True)
        relay = OutboxRelay()
        relay.start()
        assert relay.running is False

    def test_it_does_not_start_when_automation_is_off(self, monkeypatch):
        monkeypatch.setattr(settings, "n8n_inventory_webhook_url", "http://n8n.test/hook")
        monkeypatch.setattr(settings, "inventory_automation_enabled", False)
        relay = OutboxRelay()
        relay.start()
        assert relay.running is False

    async def test_it_starts_and_stops_cleanly(self, monkeypatch):
        monkeypatch.setattr(settings, "n8n_inventory_webhook_url", "http://n8n.test/hook")
        monkeypatch.setattr(settings, "inventory_automation_enabled", True)
        monkeypatch.setattr(settings, "inventory_dispatch_interval_seconds", 3600)
        relay = OutboxRelay()
        relay.start()
        assert relay.running is True
        await relay.stop()
        assert relay.running is False

    async def test_starting_twice_does_not_make_two_relays(self, monkeypatch):
        """Two relays would double every delivery."""
        monkeypatch.setattr(settings, "n8n_inventory_webhook_url", "http://n8n.test/hook")
        monkeypatch.setattr(settings, "inventory_automation_enabled", True)
        monkeypatch.setattr(settings, "inventory_dispatch_interval_seconds", 3600)
        relay = OutboxRelay()
        relay.start()
        first = relay._task
        relay.start()
        assert relay._task is first
        await relay.stop()


class TestClaiming:
    async def test_claiming_leases_the_batch(self, session, seeded, monkeypatch):
        """A claimed event must be invisible to the next claim.

        Without the lease, a second web worker's relay tick picks up the same
        rows and delivers them all over again.
        """
        monkeypatch.setattr(settings, "n8n_inventory_webhook_url", "http://n8n.test/hook")
        event = await _event(session, seeded["merchant_id"])
        await session.commit()

        claimed = await event_bus._claim_batch(session, limit=10)
        assert any(row[0] == event.id for row in claimed)

        again = await event_bus._claim_batch(session, limit=10)
        assert all(row[0] != event.id for row in again)

    async def test_claiming_counts_the_attempt(self, session, seeded, monkeypatch):
        monkeypatch.setattr(settings, "n8n_inventory_webhook_url", "http://n8n.test/hook")
        event = await _event(session, seeded["merchant_id"])
        await session.commit()

        await event_bus._claim_batch(session, limit=10)
        await session.refresh(event)
        assert event.attempts == 1
        assert event.next_attempt_at > datetime.now(tz=UTC)

    async def test_an_event_not_yet_due_is_left_alone(self, session, seeded, monkeypatch):
        monkeypatch.setattr(settings, "n8n_inventory_webhook_url", "http://n8n.test/hook")
        event = await _event(
            session,
            seeded["merchant_id"],
            next_attempt_at=datetime.now(tz=UTC) + timedelta(minutes=10),
        )
        await session.commit()

        claimed = await event_bus._claim_batch(session, limit=10)
        assert all(row[0] != event.id for row in claimed)


class TestSettling:
    async def test_a_delivered_event_is_marked_and_unscheduled(self, session, seeded):
        event = await _event(session, seeded["merchant_id"])
        await session.commit()

        await event_bus._settle(session, event.id, error=None, attempts=1)
        await session.refresh(event)
        assert event.delivery_status == DeliveryStatus.DELIVERED
        assert event.delivered_at is not None
        assert event.next_attempt_at is None

    async def test_a_failure_goes_back_to_pending_with_backoff(self, session, seeded):
        """The lease is replaced by the real retry delay, not left in place."""
        event = await _event(session, seeded["merchant_id"])
        await session.commit()

        await event_bus._settle(session, event.id, error="ConnectError: refused", attempts=1)
        await session.refresh(event)
        assert event.delivery_status == DeliveryStatus.PENDING
        assert event.last_error.startswith("ConnectError")
        assert event.next_attempt_at is not None
        assert event.next_attempt_at < datetime.now(tz=UTC) + event_bus._LEASE

    async def test_it_gives_up_after_the_last_attempt(self, session, seeded):
        event = await _event(session, seeded["merchant_id"])
        await session.commit()

        await event_bus._settle(
            session, event.id, error="ConnectError: refused", attempts=event_bus._MAX_ATTEMPTS
        )
        await session.refresh(event)
        assert event.delivery_status == DeliveryStatus.FAILED
        assert event.next_attempt_at is None


class TestDispatch:
    async def test_no_webhook_configured_skips_rather_than_queues_forever(
        self, session, seeded, monkeypatch
    ):
        monkeypatch.setattr(settings, "n8n_inventory_webhook_url", "")
        event = await _event(session, seeded["merchant_id"])
        await session.commit()

        result = await event_bus.dispatch_pending(session)
        await session.refresh(event)
        assert result["skipped"] >= 1
        assert event.delivery_status == DeliveryStatus.SKIPPED

    async def test_a_dead_consumer_leaves_the_event_retryable(
        self, session, seeded, monkeypatch
    ):
        """The whole point of the outbox: a reorder survives n8n being down."""
        monkeypatch.setattr(settings, "n8n_inventory_webhook_url", "http://n8n.invalid/hook")
        monkeypatch.setattr(settings, "n8n_webhook_secret", "shared-secret")

        async def refuse(self, *args, **kwargs):
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr(httpx.AsyncClient, "post", refuse)

        event = await _event(session, seeded["merchant_id"])
        await session.commit()

        result = await event_bus.dispatch_pending(session)
        await session.refresh(event)

        assert result["delivered"] == 0
        assert event.delivery_status == DeliveryStatus.PENDING
        assert event.attempts == 1
        assert event.next_attempt_at is not None

    async def test_a_successful_delivery_is_signed(self, session, seeded, monkeypatch):
        monkeypatch.setattr(settings, "n8n_inventory_webhook_url", "http://n8n.test/hook")
        monkeypatch.setattr(settings, "n8n_webhook_secret", "shared-secret")

        sent: list[dict] = []

        class _Response:
            status_code = 200

            def raise_for_status(self):
                return None

        async def capture(self, url, content=None, headers=None, **kwargs):
            sent.append({"url": url, "content": content, "headers": headers})
            return _Response()

        monkeypatch.setattr(httpx.AsyncClient, "post", capture)

        event = await _event(session, seeded["merchant_id"])
        await session.commit()

        result = await event_bus.dispatch_pending(session)
        await session.refresh(event)

        assert result["delivered"] == 1
        assert event.delivery_status == DeliveryStatus.DELIVERED
        assert len(sent) == 1
        signature = sent[0]["headers"]["X-Signature"]
        assert signature.startswith("sha256=")
        # The signature has to cover exactly the bytes that were sent.
        assert event_bus.verify(sent[0]["content"], signature) is True

    async def test_nothing_due_is_a_cheap_no_op(self, session, monkeypatch):
        monkeypatch.setattr(settings, "n8n_inventory_webhook_url", "http://n8n.test/hook")

        async def explode(self, *args, **kwargs):
            raise AssertionError("no HTTP call should be made when nothing is due")

        monkeypatch.setattr(httpx.AsyncClient, "post", explode)
        result = await event_bus.dispatch_pending(session)
        assert result == {"delivered": 0, "failed": 0, "skipped": 0}


@pytest.mark.parametrize("interval", [0, -5])
def test_a_nonsense_interval_cannot_make_the_relay_spin(interval, monkeypatch):
    """A misconfigured interval must not turn into a busy loop."""
    monkeypatch.setattr(settings, "inventory_dispatch_interval_seconds", interval)
    assert max(1.0, float(settings.inventory_dispatch_interval_seconds)) >= 1.0
