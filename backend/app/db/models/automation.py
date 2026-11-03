"""Domain events, the delivery outbox, and n8n execution tracking.

**Why an outbox rather than calling n8n inline.** A stock change writes the item,
the ledger row and the event in one transaction. If the webhook were fired inside
that transaction, a network stall would hold a row lock open; if it were fired
after commit, a crash between the two would lose the event and the reorder would
never happen. The outbox makes the event part of the same commit, and a separate
dispatcher delivers it. Worst case is a duplicate delivery, which the consumer is
required to tolerate - see ``ProcessedEvent``.

**Correlation.** Every automated chain carries one ``correlation_id`` from the
sale that started it through to the ledger row the receipt writes. That single
value is what lets the UI draw the whole trace.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import BaseModel
from app.db.types import GUID, JSONB, UTCDateTime


class EventType:
    """The inventory domain events the platform publishes."""

    STOCK_CHANGED = "inventory.stock_changed"
    LOW_STOCK = "inventory.low_stock"
    REORDER_REQUIRED = "inventory.reorder_required"
    PO_CREATED = "inventory.purchase_order_created"
    PO_APPROVED = "inventory.purchase_order_approved"
    PO_SENT = "inventory.purchase_order_sent"
    PO_FAILED = "inventory.purchase_order_failed"
    PURCHASE_RECEIVED = "inventory.purchase_received"
    STOCK_EXPIRING = "inventory.stock_expiring"
    STOCK_EXPIRED = "inventory.stock_expired"
    ADJUSTMENT_CREATED = "inventory.adjustment_created"
    RECONCILIATION_DISCREPANCY = "inventory.reconciliation_discrepancy"

    ALL = (
        STOCK_CHANGED,
        LOW_STOCK,
        REORDER_REQUIRED,
        PO_CREATED,
        PO_APPROVED,
        PO_SENT,
        PO_FAILED,
        PURCHASE_RECEIVED,
        STOCK_EXPIRING,
        STOCK_EXPIRED,
        ADJUSTMENT_CREATED,
        RECONCILIATION_DISCREPANCY,
    )


class DeliveryStatus:
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    #: Nothing is listening - no n8n URL configured. Recorded, not retried.
    SKIPPED = "SKIPPED"


class DomainEvent(BaseModel):
    """An event, written in the same transaction as the change that caused it.

    This is both the audit record of what happened and the outbox row the
    dispatcher delivers to n8n.
    """

    __tablename__ = "domain_events"
    __table_args__ = (
        Index("ix_domain_events_merchant_type", "merchant_id", "event_type"),
        Index("ix_domain_events_delivery", "delivery_status", "next_attempt_at"),
        Index("ix_domain_events_correlation", "correlation_id"),
        Index("ix_domain_events_entity", "entity_type", "entity_id"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)

    entity_type: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(GUID())

    #: Ties this event to every other step of the same automated chain.
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    #: What produced it: "backend", "n8n", "system".
    source: Mapped[str] = mapped_column(String(16), default="backend", nullable=False)

    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    delivery_status: Mapped[str] = mapped_column(
        String(16), default=DeliveryStatus.PENDING, nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)


class ProcessedEvent(BaseModel):
    """The idempotency ledger for inbound work.

    An at-least-once outbox means the same event can arrive more than once. A
    consumer claims an event by inserting its key here inside the same
    transaction as its side effect; the unique constraint is what makes the
    second delivery a no-op rather than a second purchase order.
    """

    __tablename__ = "processed_events"
    __table_args__ = (
        UniqueConstraint("merchant_id", "scope", "event_key", name="uq_processed_events_key"),
        Index("ix_processed_events_merchant", "merchant_id"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Which consumer claimed it, e.g. "replenishment". Two consumers may each
    #: process the same event once.
    scope: Mapped[str] = mapped_column(String(48), nullable=False)
    event_key: Mapped[str] = mapped_column(String(128), nullable=False)
    result_ref: Mapped[str] = mapped_column(String(128), default="", nullable=False)


class AutomationStatus:
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    SKIPPED = "SKIPPED"


class AutomationRun(BaseModel):
    """One n8n workflow execution, as this platform sees it.

    n8n has its own execution log, but it is a separate system with separate
    access control. Mirroring the run here means the automation trace in the UI
    works from the platform's own data, under the platform's own RBAC.
    """

    __tablename__ = "automation_runs"
    __table_args__ = (
        Index("ix_automation_runs_merchant_status", "merchant_id", "status"),
        Index("ix_automation_runs_correlation", "correlation_id"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    workflow_name: Mapped[str] = mapped_column(String(96), nullable=False)
    #: n8n's own execution id, so a support question can be traced into n8n.
    n8n_execution_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)

    trigger_event_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    trigger_event_type: Mapped[str] = mapped_column(String(64), default="", nullable=False)

    entity_type: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(GUID())

    status: Mapped[str] = mapped_column(
        String(24), default=AutomationStatus.RUNNING, nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    #: Ordered, human-readable trace: [{"at", "step", "detail", "status"}].
    steps: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_dry_run: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
