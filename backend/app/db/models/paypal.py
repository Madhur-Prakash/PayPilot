"""PayPal persistence: synced transactions, webhook events, invoices, subscriptions.

Every row carries ``mode`` (LIVE / SANDBOX / SIMULATED) so a simulated record can
never be mistaken for a real PayPal object - the UI badges it, and reconciliation
refuses to match a simulated payment against a live invoice.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import BaseModel
from app.db.types import GUID, JSONB, UTCDateTime


class PayPalTransactionRecord(BaseModel):
    """One transaction from the Transaction Search API.

    ``paypal_transaction_id`` is unique per merchant, which is what makes a sync
    safe to repeat: re-reading an overlapping window updates rows, never duplicates.
    """

    __tablename__ = "paypal_transactions"
    __table_args__ = (
        UniqueConstraint(
            "merchant_id", "paypal_transaction_id", name="uq_paypal_transactions_txn"
        ),
        Index("ix_paypal_transactions_merchant_initiated", "merchant_id", "initiated_at"),
        Index("ix_paypal_transactions_invoice", "merchant_id", "invoice_id"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    paypal_transaction_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_code: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    #: S (success), P (pending), V (reversed), D (denied) - PayPal's own codes.
    status_code: Mapped[str] = mapped_column(String(4), default="", nullable=False)
    #: Our classification: PAYMENT | REFUND | FEE | PAYOUT | TRANSFER | OTHER.
    category: Mapped[str] = mapped_column(String(16), default="OTHER", nullable=False)

    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    fee_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)

    initiated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at_paypal: Mapped[datetime | None] = mapped_column(UTCDateTime())
    invoice_id: Mapped[str] = mapped_column(String(127), default="", nullable=False)
    custom_field: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    #: A one-way hash of the payer email - enough to count repeat payers, nothing more.
    payer_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    payer_name: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    synced_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class PayPalSyncCheckpoint(BaseModel):
    """How far each PayPal resource has been synchronised, per merchant."""

    __tablename__ = "paypal_sync_checkpoints"
    __table_args__ = (
        UniqueConstraint("merchant_id", "resource", name="uq_paypal_sync_checkpoints_resource"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resource: Mapped[str] = mapped_column(String(32), nullable=False)
    synced_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_status: Mapped[str] = mapped_column(String(16), default="NEVER", nullable=False)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    items_last_run: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), default="SIMULATED", nullable=False)


class WebhookVerification:
    VERIFIED = "VERIFIED"
    SIMULATED_VERIFIED = "SIMULATED_VERIFIED"
    REJECTED = "REJECTED"


class WebhookProcessing:
    RECEIVED = "RECEIVED"
    PROCESSED = "PROCESSED"
    IGNORED = "IGNORED"
    FAILED = "FAILED"
    DUPLICATE = "DUPLICATE"


class PayPalWebhookEvent(BaseModel):
    """Every inbound webhook, verified or not. ``event_id`` is the replay guard."""

    __tablename__ = "paypal_webhook_events"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_paypal_webhook_events_event"),
        Index("ix_paypal_webhook_events_type", "event_type", "received_at"),
        Index("ix_paypal_webhook_events_resource", "resource_id"),
    )

    #: Resolved from the resource (custom_id / invoice id); null if unattributable.
    merchant_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), index=True
    )
    event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(48), default="", nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)

    transmission_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    verification_status: Mapped[str] = mapped_column(String(24), nullable=False)
    processing_status: Mapped[str] = mapped_column(
        String(16), default=WebhookProcessing.RECEIVED, nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)

    received_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class PayPalInvoiceRecord(BaseModel):
    """A merchant -> customer invoice issued through PayPal Invoicing v2."""

    __tablename__ = "paypal_invoices"
    __table_args__ = (
        UniqueConstraint("merchant_id", "paypal_invoice_id", name="uq_paypal_invoices_invoice"),
        Index("ix_paypal_invoices_merchant_status", "merchant_id", "status"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    paypal_invoice_id: Mapped[str] = mapped_column(String(64), nullable=False)
    invoice_number: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="DRAFT", nullable=False)
    recipient_email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    recipient_name: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    payer_view_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    paid_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class PayPalSubscriptionRecord(BaseModel):
    """A PayPal subscription this merchant sells, tracked from API calls and webhooks."""

    __tablename__ = "paypal_subscriptions"
    __table_args__ = (
        UniqueConstraint(
            "merchant_id", "paypal_subscription_id", name="uq_paypal_subscriptions_sub"
        ),
        Index("ix_paypal_subscriptions_merchant_status", "merchant_id", "status"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    paypal_subscription_id: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    plan_name: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", nullable=False)
    subscriber_name: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    subscriber_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    interval: Mapped[str] = mapped_column(String(16), default="MONTH", nullable=False)
    failed_payments: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_payment_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    next_billing_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
