"""Governance: signed agent messages, human approvals, financial executions.

Three guarantees live in these tables:

1. **Every agent message is signed, typed, and replay-proof.** ``agent_messages``
   stores the envelope exactly as verified - sender, recipient, schema version,
   nonce, idempotency key and HMAC signature. A nonce or idempotency key can only
   ever be accepted once (unique indexes, not application logic).
2. **Every approval binds to exact financial terms.** ``approval_requests``
   stores the canonical details and their SHA-256. Execution recomputes the hash
   from live state; if anything material changed, the approval is invalidated.
3. **Every money movement is idempotent and attributable.** ``financial_executions``
   records which approval authorised it, the idempotency key sent to PayPal, and
   every PayPal reference that came back.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import BaseModel
from app.db.types import GUID, JSONB, UTCDateTime


# --------------------------------------------------------------------------- #
# Agent protocol
# --------------------------------------------------------------------------- #
class AgentMessageType:
    """The typed message vocabulary of the procurement protocol."""

    SUPPLIER_DISCOVERY = "SUPPLIER_DISCOVERY"
    PROCUREMENT_REQUEST = "PROCUREMENT_REQUEST"
    RFQ_CREATED = "RFQ_CREATED"
    RFQ_RESPONSE = "RFQ_RESPONSE"
    QUOTE_SUBMITTED = "QUOTE_SUBMITTED"
    COUNTEROFFER = "COUNTEROFFER"
    OFFER_ACCEPTED = "OFFER_ACCEPTED"
    OFFER_REJECTED = "OFFER_REJECTED"
    NEGOTIATION_EXPIRED = "NEGOTIATION_EXPIRED"
    PURCHASE_ORDER_CREATED = "PURCHASE_ORDER_CREATED"
    INVOICE_ISSUED = "INVOICE_ISSUED"
    DELIVERY_UPDATE = "DELIVERY_UPDATE"
    GOODS_RECEIVED = "GOODS_RECEIVED"
    INVOICE_MATCHED = "INVOICE_MATCHED"
    PAYMENT_REQUESTED = "PAYMENT_REQUESTED"
    PAYMENT_APPROVED = "PAYMENT_APPROVED"
    PAYMENT_COMPLETED = "PAYMENT_COMPLETED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    PROCUREMENT_CLOSED = "PROCUREMENT_CLOSED"

    ALL = (
        SUPPLIER_DISCOVERY,
        PROCUREMENT_REQUEST,
        RFQ_CREATED,
        RFQ_RESPONSE,
        QUOTE_SUBMITTED,
        COUNTEROFFER,
        OFFER_ACCEPTED,
        OFFER_REJECTED,
        NEGOTIATION_EXPIRED,
        PURCHASE_ORDER_CREATED,
        INVOICE_ISSUED,
        DELIVERY_UPDATE,
        GOODS_RECEIVED,
        INVOICE_MATCHED,
        PAYMENT_REQUESTED,
        PAYMENT_APPROVED,
        PAYMENT_COMPLETED,
        PAYMENT_FAILED,
        PROCUREMENT_CLOSED,
    )


class AgentKind:
    BUYER = "BUYER"
    SUPPLIER = "SUPPLIER"
    #: The platform itself (approvals, payments, reconciliation).
    SYSTEM = "SYSTEM"


class AgentMessage(BaseModel):
    """One verified protocol message. Append-only."""

    __tablename__ = "agent_messages"
    __table_args__ = (
        UniqueConstraint("merchant_id", "idempotency_key", name="uq_agent_messages_idempotency"),
        UniqueConstraint("sender", "nonce", name="uq_agent_messages_sender_nonce"),
        Index("ix_agent_messages_conversation", "merchant_id", "conversation_id", "sent_at"),
        Index("ix_agent_messages_request", "procurement_request_id"),
        Index("ix_agent_messages_type", "merchant_id", "message_type"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)

    sender: Mapped[str] = mapped_column(String(96), nullable=False)
    sender_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    recipient: Mapped[str] = mapped_column(String(96), nullable=False)
    recipient_kind: Mapped[str] = mapped_column(String(16), nullable=False)

    message_type: Mapped[str] = mapped_column(String(40), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(8), default="1.0", nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # ---- authenticated transport metadata ----
    transport: Mapped[str] = mapped_column(String(24), default="internal-hmac", nullable=False)
    key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    signature: Mapped[str] = mapped_column(String(128), nullable=False)
    nonce: Mapped[str] = mapped_column(String(48), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    procurement_request_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    session_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    #: Short human-readable line for the timeline (never used for logic).
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    #: True when the sender is a simulated agent - the UI labels it.
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


# --------------------------------------------------------------------------- #
# Approvals
# --------------------------------------------------------------------------- #
class ApprovalAction:
    """The financially consequential actions that need a human decision."""

    PROCUREMENT_PURCHASE = "PROCUREMENT_PURCHASE"
    SUPPLIER_PAYMENT = "SUPPLIER_PAYMENT"
    CASHBACK_PAYOUT = "CASHBACK_PAYOUT"
    CUSTOMER_INVOICE = "CUSTOMER_INVOICE"
    #: Pay for test stock of a product an AI recommendation proposed (PayPal Orders v2).
    MERCHANT_PURCHASE = "MERCHANT_PURCHASE"

    LABELS = {
        PROCUREMENT_PURCHASE: "Purchase from supplier",
        SUPPLIER_PAYMENT: "Pay supplier invoice",
        CASHBACK_PAYOUT: "Send cashback payouts",
        CUSTOMER_INVOICE: "Send customer invoice",
        MERCHANT_PURCHASE: "Buy test stock (AI recommendation)",
    }


class ApprovalStatus:
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    #: The underlying terms changed after the request was raised or approved.
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"
    #: Approved and consumed by exactly one execution.
    EXECUTED = "EXECUTED"

    OPEN = (PENDING, APPROVED)


class ApprovalRequest(BaseModel):
    """A request for a human to authorise one exact financial action."""

    __tablename__ = "approval_requests"
    __table_args__ = (
        UniqueConstraint("merchant_id", "reference", name="uq_approval_requests_reference"),
        Index("ix_approval_requests_merchant_status", "merchant_id", "status"),
        Index("ix_approval_requests_resource", "resource_type", "resource_id"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reference: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)

    #: The exact terms being authorised, canonicalised.
    details: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    #: SHA-256 of ``details`` - recomputed from live state before execution.
    details_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    required_permission: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_flags: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    status: Mapped[str] = mapped_column(String(16), default=ApprovalStatus.PENDING, nullable=False)
    requested_by_type: Mapped[str] = mapped_column(String(16), default="AGENT", nullable=False)
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    requested_by_label: Mapped[str] = mapped_column(String(160), default="", nullable=False)

    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    decided_by_label: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    decision_note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    invalidated_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    correlation_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    procurement_request_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), index=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


# --------------------------------------------------------------------------- #
# Financial executions
# --------------------------------------------------------------------------- #
class ExecutionKind:
    SUPPLIER_SETTLEMENT = "SUPPLIER_SETTLEMENT"
    CASHBACK_PAYOUT = "CASHBACK_PAYOUT"
    CUSTOMER_INVOICE = "CUSTOMER_INVOICE"
    MERCHANT_PURCHASE = "MERCHANT_PURCHASE"


class ExecutionMethod:
    #: Orders v2, intent CAPTURE, payee = supplier.
    ORDERS_CAPTURE = "ORDERS_V2_CAPTURE"
    #: Orders v2, intent AUTHORIZE: an authorization hold, captured after matching.
    ORDERS_AUTHORIZE = "ORDERS_V2_AUTHORIZE"
    PAYOUTS = "PAYOUTS"
    INVOICING = "INVOICING"


class ExecutionStatus:
    CREATED = "CREATED"
    #: PayPal needs the payer to approve in the PayPal UI (sandbox / live).
    PAYER_ACTION_REQUIRED = "PAYER_ACTION_REQUIRED"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    VOIDED = "VOIDED"

    SETTLED = (CAPTURED, COMPLETED)


class FinancialExecution(BaseModel):
    """One attempt to move money through PayPal, authorised by one approval."""

    __tablename__ = "financial_executions"
    __table_args__ = (
        UniqueConstraint(
            "merchant_id", "idempotency_key", name="uq_financial_executions_idempotency"
        ),
        Index("ix_financial_executions_merchant_status", "merchant_id", "status"),
        Index("ix_financial_executions_resource", "resource_type", "resource_id"),
        Index("ix_financial_executions_paypal_order", "paypal_order_id"),
        Index("ix_financial_executions_paypal_capture", "paypal_capture_id"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    approval_request_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("approval_requests.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)

    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    provider: Mapped[str] = mapped_column(String(16), default="PAYPAL", nullable=False)
    #: LIVE | SANDBOX | SIMULATED - never blurred in the UI.
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=ExecutionStatus.CREATED, nullable=False)

    #: Sent to PayPal as PayPal-Request-Id / sender_batch_id.
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payee_email: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    paypal_order_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    paypal_authorization_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    paypal_capture_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    paypal_payout_batch_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    approve_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    debug_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)

    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    executed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    reconciled_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    correlation_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    #: Trimmed PayPal response bodies, for the audit trail. Never credentials.
    response: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
