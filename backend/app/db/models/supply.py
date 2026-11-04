"""Supply Agents: the agent-to-agent procurement network.

The existing procurement tables (``vendors``, ``vendor_products``,
``purchase_orders``) already know *who* can supply *what*. These tables add the
part that makes procurement an agent workflow rather than a form:

* ``supplier_agents``       - an independent agent identity per vendor, with its
                              own private commercial policy;
* ``procurement_requests``  - a demand-driven requirement and its RFQ;
* ``negotiation_sessions``  - one buyer/supplier negotiation per request;
* ``negotiation_offers``    - every quote, counter and final offer, each one
                              independently validated by the backend;
* ``goods_receipts``, ``supplier_invoices``, ``invoice_matches`` and
  ``procurement_reconciliations`` - the back half of the lifecycle.

Money columns are ``Numeric`` and are read and written as ``Decimal``. Nothing in
this domain is ever computed in floating point, and no amount is ever produced by
a language model - see ``app/services/supply/policy.py``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
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


# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #
class SupplierStrategy:
    """How a supplier agent behaves at the table. Each is a deterministic policy."""

    #: High reliability, moderate price, fast delivery, small concessions.
    PREMIUM_RELIABLE = "PREMIUM_RELIABLE"
    #: Opens low, delivers slowly, has limited stock, barely moves on price.
    LOW_PRICE_LIMITED = "LOW_PRICE_LIMITED"
    #: Competitive, flexible, rewards volume, medium delivery.
    FLEXIBLE_VOLUME = "FLEXIBLE_VOLUME"

    ALL = (PREMIUM_RELIABLE, LOW_PRICE_LIMITED, FLEXIBLE_VOLUME)


class SupplierAgentStatus:
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    SUSPENDED = "SUSPENDED"


class PaymentTerms:
    DUE_ON_RECEIPT = "DUE_ON_RECEIPT"
    NET_15 = "NET_15"
    NET_30 = "NET_30"

    #: Days of credit each term gives the buyer - used by deterministic scoring.
    DAYS = {DUE_ON_RECEIPT: 0, NET_15: 15, NET_30: 30}


class ProcurementTrigger:
    STOCKOUT_RISK = "STOCKOUT_RISK"
    DEMAND_SPIKE = "DEMAND_SPIKE"
    REORDER_POINT = "REORDER_POINT"
    MANUAL = "MANUAL"


class ProcurementStatus:
    DRAFT = "DRAFT"
    SOURCING = "SOURCING"
    NEGOTIATING = "NEGOTIATING"
    RECOMMENDED = "RECOMMENDED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    ORDERED = "ORDERED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAID = "PAID"
    RECONCILED = "RECONCILED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    #: No supplier could meet the requirement within policy.
    NO_ELIGIBLE_OFFER = "NO_ELIGIBLE_OFFER"

    #: Still moving through the pipeline - used to stop duplicate requests.
    OPEN = (
        DRAFT,
        SOURCING,
        NEGOTIATING,
        RECOMMENDED,
        AWAITING_APPROVAL,
        APPROVED,
        ORDERED,
        PARTIALLY_RECEIVED,
        RECEIVED,
        PAYMENT_PENDING,
        PAID,
    )

    #: The lifecycle in order, as the UI draws it.
    PIPELINE = (
        SOURCING,
        NEGOTIATING,
        RECOMMENDED,
        AWAITING_APPROVAL,
        APPROVED,
        ORDERED,
        PARTIALLY_RECEIVED,
        RECEIVED,
        PAYMENT_PENDING,
        PAID,
        RECONCILED,
    )


class NegotiationStatus:
    INVITED = "INVITED"
    QUOTED = "QUOTED"
    COUNTERED = "COUNTERED"
    FINAL_OFFER = "FINAL_OFFER"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"

    TERMINAL = (ACCEPTED, REJECTED, DECLINED, EXPIRED)


class OfferKind:
    QUOTE = "QUOTE"
    COUNTER = "COUNTER"
    FINAL = "FINAL"
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    DECLINE = "DECLINE"


class OfferDirection:
    SUPPLIER_TO_BUYER = "SUPPLIER_TO_BUYER"
    BUYER_TO_SUPPLIER = "BUYER_TO_SUPPLIER"


class OfferValidation:
    #: Mathematically consistent and inside the merchant's policy.
    VALID = "VALID"
    #: Consistent, but outside policy (over budget, too slow, ...). Recorded, never selectable.
    OUT_OF_POLICY = "OUT_OF_POLICY"
    #: Internally inconsistent or malformed - rejected outright.
    INVALID = "INVALID"


class SupplierInvoiceStatus:
    RECEIVED = "RECEIVED"
    MATCHED = "MATCHED"
    DISCREPANCY = "DISCREPANCY"
    PAYMENT_APPROVAL_PENDING = "PAYMENT_APPROVAL_PENDING"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAID = "PAID"
    VOID = "VOID"


class MatchStatus:
    MATCHED = "MATCHED"
    WITHIN_TOLERANCE = "WITHIN_TOLERANCE"
    DISCREPANCY = "DISCREPANCY"

    PAYABLE = (MATCHED, WITHIN_TOLERANCE)


class ReconciliationStatus:
    RECONCILED = "RECONCILED"
    EXCEPTION = "EXCEPTION"


# --------------------------------------------------------------------------- #
# Supplier agents
# --------------------------------------------------------------------------- #
class SupplierAgent(BaseModel):
    """An independent supplier agent, bound to one vendor of one merchant.

    The commercial policy here (opening markup, concession rate, shipping terms)
    plus the private ``floor_price`` on each ``vendor_products`` row is the
    agent's *private* state. It is never serialised to the buyer side, to other
    supplier agents, or to the browser - see ``SupplierAgentView`` in the
    supply services, which is the only shape that leaves this table.
    """

    __tablename__ = "supplier_agents"
    __table_args__ = (
        UniqueConstraint("merchant_id", "vendor_id", name="uq_supplier_agents_vendor"),
        UniqueConstraint("merchant_id", "agent_key", name="uq_supplier_agents_key"),
        Index("ix_supplier_agents_merchant_status", "merchant_id", "status"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False, index=True
    )

    #: Public, stable identity on the protocol, e.g. ``supplier.roastworks``.
    agent_key: Mapped[str] = mapped_column(String(96), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    tagline: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    strategy: Mapped[str] = mapped_column(
        String(32), default=SupplierStrategy.FLEXIBLE_VOLUME, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), default=SupplierAgentStatus.ONLINE, nullable=False
    )
    #: True for the demo network: its replies are produced by a local policy engine.
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    region: Mapped[str] = mapped_column(String(64), default="", nullable=False)

    # ---- reputation (updated deterministically from completed orders) ----
    reliability_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), default=Decimal("0.9000"), nullable=False
    )
    quality_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), default=Decimal("0.9000"), nullable=False
    )
    on_time_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), default=Decimal("0.9000"), nullable=False
    )

    # ---- commercial terms (public) ----
    payment_terms: Mapped[str] = mapped_column(
        String(24), default=PaymentTerms.NET_30, nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    shipping_flat: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0"), nullable=False
    )
    shipping_per_unit: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), default=Decimal("0"), nullable=False
    )
    #: Order subtotal at or above which shipping is waived. 0 = never waived.
    free_shipping_threshold: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0"), nullable=False
    )
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=Decimal("0"), nullable=False)
    #: Fee for shaving ``expedite_days`` off the lead time, if the buyer asks.
    expedite_fee: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0"), nullable=False
    )
    expedite_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    #: Where a PayPal payment to this supplier is sent (Orders v2 payee).
    paypal_email: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    # ---- negotiation policy (private) ----
    #: Opening price as a markup over the list price (0.05 = list + 5%).
    opening_markup: Mapped[Decimal] = mapped_column(
        Numeric(6, 4), default=Decimal("0"), nullable=False
    )
    #: Share of the gap to the buyer's counter conceded per round.
    concession_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), default=Decimal("0.3000"), nullable=False
    )
    max_rounds: Mapped[int] = mapped_column(Integer, default=3, nullable=False)

    #: Public fingerprint of this agent's protocol signing key. The key itself is
    #: derived server-side and never stored.
    key_fingerprint: Mapped[str] = mapped_column(String(64), default="", nullable=False)

    # ---- performance counters (supplier learning) ----
    orders_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    orders_on_time: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    units_ordered: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0"), nullable=False
    )
    units_received: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0"), nullable=False
    )
    invoices_received: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    invoice_discrepancies: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    negotiations_won: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    negotiations_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_savings: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0"), nullable=False
    )
    last_performance_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


# --------------------------------------------------------------------------- #
# Procurement requests (and their RFQ)
# --------------------------------------------------------------------------- #
class ProcurementRequest(BaseModel):
    """A requirement to buy, its RFQ, its policy, and where it got to.

    The policy columns (``max_unit_cost``, ``max_budget`` ...) are computed by the
    deterministic financial engine *before* any agent speaks, and are frozen here
    with a ``policy_version`` so an approval can bind to exactly what was enforced.
    """

    __tablename__ = "procurement_requests"
    __table_args__ = (
        UniqueConstraint("merchant_id", "reference", name="uq_procurement_requests_reference"),
        Index("ix_procurement_requests_merchant_status", "merchant_id", "status"),
        Index("ix_procurement_requests_item", "inventory_item_id"),
        Index("ix_procurement_requests_correlation", "correlation_id"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reference: Mapped[str] = mapped_column(String(32), nullable=False)
    rfq_reference: Mapped[str] = mapped_column(String(32), default="", nullable=False)

    inventory_item_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("inventory_items.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    product_name: Mapped[str] = mapped_column(String(160), nullable=False)
    unit: Mapped[str] = mapped_column(String(24), default="units", nullable=False)

    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    required_by: Mapped[date | None] = mapped_column(Date)
    max_delivery_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)

    trigger: Mapped[str] = mapped_column(
        String(24), default=ProcurementTrigger.MANUAL, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(24), default=ProcurementStatus.DRAFT, nullable=False
    )
    #: AGENT when the Inventory Intelligence agent raised it, USER otherwise.
    source: Mapped[str] = mapped_column(String(16), default="USER", nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)

    # ---- deterministic policy (frozen at creation) ----
    expected_selling_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0"), nullable=False
    )
    target_margin: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), default=Decimal("0.4000"), nullable=False
    )
    max_unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), default=Decimal("0"), nullable=False
    )
    target_unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), default=Decimal("0"), nullable=False
    )
    max_budget: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0"), nullable=False
    )
    min_reliability: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), default=Decimal("0.8000"), nullable=False
    )
    max_rounds: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    policy: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    #: Velocity, days of cover, demand change - the evidence for the requirement.
    demand_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # ---- outcome ----
    recommended_session_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    recommended_offer_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    selected_supplier_agent_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    #: Deterministic score table + plain-language explanation.
    recommendation: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), index=True)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(GUID())

    #: Best landed total among opening quotes - the baseline savings are measured from.
    baseline_landed_total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    final_landed_total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    savings_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    rfq_issued_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    rfq_deadline: Mapped[datetime | None] = mapped_column(UTCDateTime())
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    failure_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


# --------------------------------------------------------------------------- #
# Negotiation
# --------------------------------------------------------------------------- #
class NegotiationSession(BaseModel):
    """One buyer agent <-> one supplier agent negotiation for one request."""

    __tablename__ = "negotiation_sessions"
    __table_args__ = (
        UniqueConstraint(
            "procurement_request_id", "supplier_agent_id", name="uq_negotiation_sessions_pair"
        ),
        Index("ix_negotiation_sessions_merchant_status", "merchant_id", "status"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    procurement_request_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("procurement_requests.id", ondelete="CASCADE"), nullable=False,
        index=True,
    )
    supplier_agent_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("supplier_agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)

    status: Mapped[str] = mapped_column(
        String(16), default=NegotiationStatus.INVITED, nullable=False
    )
    current_round: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_rounds: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    latest_offer_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    best_offer_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    outcome_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class NegotiationOffer(BaseModel):
    """One move at the table, from either side.

    ``unit_price``/``quantity``/``shipping_cost``/``lead_time_days`` are the terms;
    ``subtotal``/``tax_amount``/``landed_total``/``landed_unit_cost`` are *always*
    recomputed by the financial engine, never taken from the proposer. ``ai_proposal``
    keeps whatever a language model suggested, verbatim, so the UI can show the
    difference between what was proposed and what the backend validated.
    """

    __tablename__ = "negotiation_offers"
    __table_args__ = (
        Index("ix_negotiation_offers_session_seq", "session_id", "sequence"),
        Index("ix_negotiation_offers_request", "procurement_request_id"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("negotiation_sessions.id", ondelete="CASCADE"), nullable=False
    )
    procurement_request_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    supplier_agent_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)

    round: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    direction: Mapped[str] = mapped_column(String(24), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)

    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    shipping_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0"), nullable=False
    )
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    landed_total: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0"), nullable=False
    )
    landed_unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), default=Decimal("0"), nullable=False
    )
    lead_time_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    payment_terms: Mapped[str] = mapped_column(String(24), default="", nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(UTCDateTime())

    validation_status: Mapped[str] = mapped_column(
        String(16), default=OfferValidation.VALID, nullable=False
    )
    validation_errors: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    within_policy: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    #: SUPPLIER_POLICY | BUYER_STRATEGY | LLM - who proposed the terms.
    proposed_by: Mapped[str] = mapped_column(String(24), default="BUYER_STRATEGY", nullable=False)
    ai_proposal: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    #: Natural-language framing of the move. Language only - never the source of a number.
    rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)
    #: Deterministic score breakdown, filled in by evaluation.
    score: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    #: SHA-256 of the canonical financial terms - what an approval binds to.
    terms_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    message_id: Mapped[uuid.UUID | None] = mapped_column(GUID())


# --------------------------------------------------------------------------- #
# Receiving, invoices, matching, reconciliation
# --------------------------------------------------------------------------- #
class GoodsReceipt(BaseModel):
    """One delivery booked in against a purchase order (partial receipts allowed)."""

    __tablename__ = "goods_receipts"
    __table_args__ = (
        UniqueConstraint("merchant_id", "reference", name="uq_goods_receipts_reference"),
        Index("ix_goods_receipts_order", "purchase_order_id"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reference: Mapped[str] = mapped_column(String(32), nullable=False)
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False
    )
    procurement_request_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    received_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    received_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    #: [{line_id, sku, quantity_received, quantity_rejected, unit_price}]
    lines: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    total_quantity: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0"), nullable=False
    )
    received_value: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0"), nullable=False
    )
    is_partial: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    on_time: Mapped[bool | None] = mapped_column(Boolean)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)


class SupplierInvoice(BaseModel):
    """An invoice a supplier issued against a purchase order."""

    __tablename__ = "supplier_invoices"
    __table_args__ = (
        UniqueConstraint(
            "merchant_id", "vendor_id", "invoice_number", name="uq_supplier_invoices_number"
        ),
        Index("ix_supplier_invoices_merchant_status", "merchant_id", "status"),
        Index("ix_supplier_invoices_order", "purchase_order_id"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False
    )
    procurement_request_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    supplier_agent_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    vendor_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)

    invoice_number: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default=SupplierInvoiceStatus.RECEIVED, nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    shipping_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0"), nullable=False
    )
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    payment_terms: Mapped[str] = mapped_column(String(24), default="", nullable=False)
    #: [{sku, description, quantity, unit_price, line_total}]
    lines: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    #: Set when the supplier issued it through PayPal Invoicing from its own account.
    paypal_invoice_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    payer_view_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    message_id: Mapped[uuid.UUID | None] = mapped_column(GUID())

    latest_match_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    execution_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    paid_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    paid_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class InvoiceMatch(BaseModel):
    """A three-way match: purchase order x goods received x supplier invoice."""

    __tablename__ = "invoice_matches"
    __table_args__ = (Index("ix_invoice_matches_invoice", "supplier_invoice_id"),)

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    supplier_invoice_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("supplier_invoices.id", ondelete="CASCADE"), nullable=False
    )
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    #: Per line: ordered / received / invoiced quantities and prices, and the verdict.
    line_results: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    discrepancies: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    po_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    received_value: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0"), nullable=False
    )
    invoice_total: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0"), nullable=False
    )
    variance_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0"), nullable=False
    )
    tolerance: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    matched_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    matched_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class ProcurementReconciliation(BaseModel):
    """The closing record: order, receipt, invoice and payment all agree."""

    __tablename__ = "procurement_reconciliations"
    __table_args__ = (Index("ix_procurement_reconciliations_order", "purchase_order_id"),)

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    procurement_request_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    supplier_invoice_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    po_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    received_value: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0"), nullable=False
    )
    invoice_total: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0"), nullable=False
    )
    paid_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0"), nullable=False
    )
    variance_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0"), nullable=False
    )
    payment_reference: Mapped[str] = mapped_column(String(64), default="", nullable=False)

    #: Inventory valuation and product margin before and after - the hand-off to growth.
    previous_unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    new_unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    previous_margin_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    new_margin_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))

    summary: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    reconciled_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    reconciled_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
