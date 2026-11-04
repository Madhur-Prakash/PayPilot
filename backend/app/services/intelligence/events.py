"""Cross-module business events: the wiring between Growth and Supply.

Events are written to the existing transactional outbox (``domain_events``) in
the same transaction as the change that caused them, so they are both the audit
record and what the relay delivers to n8n. They are also pushed to connected
browsers over the realtime hub so the Command Center updates live.

Business events use the ``business.`` prefix; the inventory domain keeps its own
``inventory.`` events unchanged.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.automation import DomainEvent
from app.services.inventory import events as outbox
from app.services.supply.policy import serialisable

log = get_logger(__name__)


class BusinessEvent:
    REVENUE_ANOMALY_DETECTED = "business.revenue_anomaly_detected"
    PRODUCT_DEMAND_INCREASED = "business.product_demand_increased"
    STOCKOUT_RISK_DETECTED = "business.stockout_risk_detected"
    PROCUREMENT_REQUIRED = "business.procurement_required"
    RFQ_STARTED = "business.rfq_started"
    SUPPLIER_SELECTED = "business.supplier_selected"
    PURCHASE_APPROVED = "business.purchase_approved"
    INVOICE_RECEIVED = "business.invoice_received"
    GOODS_RECEIVED = "business.goods_received"
    PAYMENT_RECONCILED = "business.payment_reconciled"
    PRODUCT_MARGIN_CHANGED = "business.product_margin_changed"
    CAMPAIGN_PERFORMANCE_UPDATED = "business.campaign_performance_updated"
    EXPERIMENT_COMPLETED = "business.experiment_completed"

    LABELS = {
        REVENUE_ANOMALY_DETECTED: "Revenue anomaly detected",
        PRODUCT_DEMAND_INCREASED: "Product demand increased",
        STOCKOUT_RISK_DETECTED: "Stockout risk detected",
        PROCUREMENT_REQUIRED: "Procurement required",
        RFQ_STARTED: "RFQ started",
        SUPPLIER_SELECTED: "Supplier selected",
        PURCHASE_APPROVED: "Purchase approved",
        INVOICE_RECEIVED: "Invoice received",
        GOODS_RECEIVED: "Goods received",
        PAYMENT_RECONCILED: "Payment reconciled",
        PRODUCT_MARGIN_CHANGED: "Product margin changed",
        CAMPAIGN_PERFORMANCE_UPDATED: "Campaign performance updated",
        EXPERIMENT_COMPLETED: "Experiment completed",
    }
    #: Which side of the product raised it - for the unified timeline.
    MODULE = {
        REVENUE_ANOMALY_DETECTED: "growth",
        PRODUCT_DEMAND_INCREASED: "growth",
        STOCKOUT_RISK_DETECTED: "supply",
        PROCUREMENT_REQUIRED: "supply",
        RFQ_STARTED: "supply",
        SUPPLIER_SELECTED: "supply",
        PURCHASE_APPROVED: "governance",
        INVOICE_RECEIVED: "finance",
        GOODS_RECEIVED: "supply",
        PAYMENT_RECONCILED: "finance",
        PRODUCT_MARGIN_CHANGED: "growth",
        CAMPAIGN_PERFORMANCE_UPDATED: "growth",
        EXPERIMENT_COMPLETED: "growth",
    }
    ALL = tuple(LABELS)


async def emit_business_event(
    session: AsyncSession,
    *,
    merchant_id: uuid.UUID,
    event_type: str,
    correlation_id: str,
    entity_type: str = "",
    entity_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
    source: str = "backend",
) -> DomainEvent:
    event = await outbox.emit(
        session,
        merchant_id=merchant_id,
        event_type=event_type,
        correlation_id=correlation_id,
        entity_type=entity_type[:32],
        entity_id=entity_id,
        payload=serialisable(payload or {}),
        source=source,
    )
    try:
        from app.api.realtime import hub

        await hub.publish(
            merchant_id=merchant_id,
            event="business.event",
            payload={"event_type": event_type, "correlation_id": correlation_id, **describe_event(event)},
            required_permission="events:read",
        )
    except Exception as exc:  # the browser push is a convenience, never a dependency
        log.debug("business_event_push_skipped", detail=str(exc)[:120])
    return event


def describe_event(event: DomainEvent) -> dict[str, Any]:
    return {
        "event_id": str(event.id),
        "event_type": event.event_type,
        "label": BusinessEvent.LABELS.get(event.event_type, event.event_type.split(".", 1)[-1].replace("_", " ").capitalize()),
        "module": BusinessEvent.MODULE.get(event.event_type, event.event_type.split(".", 1)[0]),
        "entity_type": event.entity_type,
        "entity_id": str(event.entity_id) if event.entity_id else None,
        "correlation_id": event.correlation_id,
        "payload": event.payload or {},
        "delivery_status": event.delivery_status,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


async def recent_events(
    session: AsyncSession,
    merchant_id: uuid.UUID,
    *,
    limit: int = 50,
    prefix: str | None = None,
    correlation_id: str | None = None,
) -> list[DomainEvent]:
    stmt = select(DomainEvent).where(DomainEvent.merchant_id == merchant_id)
    if prefix:
        stmt = stmt.where(DomainEvent.event_type.like(f"{prefix}%"))
    if correlation_id:
        stmt = stmt.where(DomainEvent.correlation_id == correlation_id)
    stmt = stmt.order_by(DomainEvent.created_at.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars().all())
