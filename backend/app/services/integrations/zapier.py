"""Zapier delivery: fan business events out to a Catch Hook, exactly once.

Runs beside the n8n outbox relay, never inside it:

  1. ``enqueue`` finds high-signal ``business.*`` events that have no Zapier
     delivery yet and gives each a row in ``integration_deliveries``
     (``UNIQUE(event_id, target)`` makes this idempotent, even with two workers);
  2. ``deliver_due`` posts each pending row, signed, with exponential backoff, and
     marks it ``DELIVERED`` or - after ``MAX_ATTEMPTS`` - ``FAILED``.

Only a short allow-list of event types leaves the system, and only events from the
last day are enqueued the first time the integration is switched on, so enabling
Zapier never replays a merchant's whole history into a Zap.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.automation import DomainEvent
from app.db.models.integrations import (
    DeliveryTarget,
    IntegrationDelivery,
    IntegrationDeliveryStatus,
)
from app.db.session import SessionLocal
from app.integrations.sponsors import SponsorError, get_zapier
from app.services.intelligence.events import BusinessEvent

log = get_logger(__name__)

ZAPIER_EVENT_TYPES = frozenset({
    BusinessEvent.REVENUE_ANOMALY_DETECTED,
    BusinessEvent.STOCKOUT_RISK_DETECTED,
    BusinessEvent.PROCUREMENT_REQUIRED,
    BusinessEvent.SUPPLIER_SELECTED,
    BusinessEvent.PURCHASE_APPROVED,
    BusinessEvent.PAYMENT_RECONCILED,
    BusinessEvent.PRODUCT_MARGIN_CHANGED,
})
ENQUEUE_WINDOW = timedelta(hours=24)
MAX_ATTEMPTS = 5
BASE_BACKOFF_SECONDS = 30
INTERVAL_SECONDS = 15


def _now() -> datetime:
    return datetime.now(UTC)


def event_body(event: DomainEvent) -> bytes:
    """The exact bytes that are signed and posted. Stable key order, no n8n internals."""
    document = {
        "event_id": str(event.id),
        "event_type": event.event_type,
        "label": BusinessEvent.LABELS.get(event.event_type, event.event_type),
        "module": BusinessEvent.MODULE.get(event.event_type, "business"),
        "merchant_id": str(event.merchant_id),
        "correlation_id": event.correlation_id,
        "entity_type": event.entity_type,
        "entity_id": str(event.entity_id) if event.entity_id else None,
        "occurred_at": (event.created_at or _now()).isoformat(),
        "data": event.payload or {},
        "source": "paypilot",
    }
    return json.dumps(document, sort_keys=True, default=str, separators=(",", ":")).encode()


async def enqueue(session: AsyncSession, *, limit: int = 50) -> int:
    already = exists().where(
        IntegrationDelivery.event_id == DomainEvent.id, IntegrationDelivery.target == DeliveryTarget.ZAPIER
    )
    events = (await session.execute(
        select(DomainEvent)
        .where(DomainEvent.event_type.in_(ZAPIER_EVENT_TYPES), DomainEvent.created_at >= _now() - ENQUEUE_WINDOW, ~already)
        .order_by(DomainEvent.created_at).limit(limit)
    )).scalars().all()
    queued = 0
    for event in events:
        try:
            async with session.begin_nested():
                session.add(IntegrationDelivery(merchant_id=event.merchant_id, event_id=event.id,
                                                target=DeliveryTarget.ZAPIER, next_attempt_at=_now()))
            queued += 1
        except IntegrityError:
            continue  # another worker queued it first - exactly what the unique key is for
    await session.commit()
    return queued


async def deliver_due(session: AsyncSession, *, limit: int = 25) -> dict[str, int]:
    client = get_zapier()
    rows = (await session.execute(
        select(IntegrationDelivery)
        .where(IntegrationDelivery.target == DeliveryTarget.ZAPIER,
               IntegrationDelivery.status == IntegrationDeliveryStatus.PENDING,
               IntegrationDelivery.next_attempt_at <= _now())
        .order_by(IntegrationDelivery.next_attempt_at).limit(limit)
    )).scalars().all()
    delivered = failed = retried = 0
    for row in rows:
        event = await session.get(DomainEvent, row.event_id)
        row.attempts += 1
        if event is None:
            row.status, row.last_error = IntegrationDeliveryStatus.FAILED, "event no longer exists"
            failed += 1
            continue
        try:
            row.http_status = await client.post_event(event_body(event), event_id=str(event.id))
            row.status, row.delivered_at, row.last_error = IntegrationDeliveryStatus.DELIVERED, _now(), ""
            delivered += 1
        except SponsorError as exc:
            row.last_error = str(exc)[:400]
            row.http_status = exc.status_code
            if row.attempts >= MAX_ATTEMPTS:
                row.status = IntegrationDeliveryStatus.FAILED
                failed += 1
                log.error("zapier_delivery_exhausted", event_id=str(row.event_id), error=row.last_error)
            else:
                row.next_attempt_at = _now() + timedelta(seconds=BASE_BACKOFF_SECONDS * 2 ** (row.attempts - 1))
                retried += 1
    await session.commit()
    return {"delivered": delivered, "failed": failed, "retried": retried}


async def run_once(session: AsyncSession) -> dict[str, int]:
    if not get_zapier().configured:
        return {"queued": 0, "delivered": 0, "failed": 0, "retried": 0}
    queued = await enqueue(session)
    return {"queued": queued, **await deliver_due(session)}


async def delivery_summary(session: AsyncSession, merchant_id: Any) -> dict[str, Any]:
    rows = (await session.execute(
        select(IntegrationDelivery.status, func.count()).where(
            IntegrationDelivery.merchant_id == merchant_id, IntegrationDelivery.target == DeliveryTarget.ZAPIER
        ).group_by(IntegrationDelivery.status)
    )).all()
    counts = dict(rows)
    last = (await session.execute(
        select(func.max(IntegrationDelivery.delivered_at)).where(
            IntegrationDelivery.merchant_id == merchant_id, IntegrationDelivery.target == DeliveryTarget.ZAPIER
        )
    )).scalar_one_or_none()
    return {
        "configured": get_zapier().configured,
        "event_types": sorted(BusinessEvent.LABELS[t] for t in ZAPIER_EVENT_TYPES),
        "pending": counts.get(IntegrationDeliveryStatus.PENDING, 0),
        "delivered": counts.get(IntegrationDeliveryStatus.DELIVERED, 0),
        "failed": counts.get(IntegrationDeliveryStatus.FAILED, 0),
        "last_delivered_at": last.isoformat() if last else None,
    }


class ZapierRelay:
    """Delivers on a timer for the life of the process, like the outbox relay."""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.running:
            return
        if not get_zapier().configured:
            log.info("zapier_relay_disabled", reason="no ZAPIER_WEBHOOK_URL")
            return
        self._task = asyncio.create_task(self._run(), name="zapier-relay")
        log.info("zapier_relay_started", interval_seconds=INTERVAL_SECONDS)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await asyncio.sleep(INTERVAL_SECONDS)
                async with SessionLocal() as session:
                    result = await run_once(session)
                if result["delivered"] or result["failed"]:
                    log.info("zapier_relay_tick", **result)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # the relay must outlive any single failure
                log.error("zapier_relay_tick_failed", error=f"{type(exc).__name__}: {exc}"[:300])
                await asyncio.sleep(30)


zapier_relay = ZapierRelay()

__all__ = ["ZAPIER_EVENT_TYPES", "ZapierRelay", "deliver_due", "delivery_summary", "enqueue", "event_body",
           "run_once", "zapier_relay"]
