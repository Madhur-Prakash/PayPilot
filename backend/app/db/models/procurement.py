"""Vendors and purchase orders.

The inventory module already knew a supplier only as a free-text name on the
item. Procurement needs a real counterparty: something with a lead time, a price,
an ordering channel and an audit trail. These tables carry that, and every one of
them is merchant-scoped so one tenant can never read or order against another's.

Nothing here decides *when* to order - that is the inventory domain. These models
record who can supply what, and what was actually ordered.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import BaseModel
from app.db.types import GUID, JSONB, UTCDateTime


class OrderingMethod:
    """How a purchase order reaches the vendor."""

    EMAIL = "EMAIL"
    WEBHOOK = "WEBHOOK"
    API = "API"
    MANUAL = "MANUAL"

    ALL = (EMAIL, WEBHOOK, API, MANUAL)


class PurchaseOrderStatus:
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    ORDERED = "ORDERED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"

    #: States that still count as "an order is already in flight for this item",
    #: which is what stops a second automatic reorder being raised.
    OPEN = (
        DRAFT,
        PENDING_APPROVAL,
        APPROVED,
        ORDERED,
        ACKNOWLEDGED,
        PARTIALLY_RECEIVED,
    )


class Vendor(BaseModel):
    """A supplier this merchant can raise orders against."""

    __tablename__ = "vendors"
    __table_args__ = (
        UniqueConstraint("merchant_id", "name", name="uq_vendors_merchant_name"),
        Index("ix_vendors_merchant_active", "merchant_id", "is_active"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    contact_name: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    phone: Mapped[str] = mapped_column(String(32), default="", nullable=False)

    #: How orders are delivered. EMAIL uses the platform's Gmail transport;
    #: WEBHOOK posts to `webhook_url`; MANUAL only records the order.
    ordering_method: Mapped[str] = mapped_column(
        String(16), default=OrderingMethod.EMAIL, nullable=False
    )
    webhook_url: Mapped[str] = mapped_column(Text, default="", nullable=False)

    lead_time_days: Mapped[float] = mapped_column(Numeric(6, 2), default=3, nullable=False)
    minimum_order_value: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    supplies: Mapped[list[VendorProduct]] = relationship(
        back_populates="vendor", cascade="all, delete-orphan", lazy="selectin"
    )


class VendorProduct(BaseModel):
    """What one vendor can supply for one inventory item, and on what terms.

    Selection is deterministic (see ``VendorSelector``): preferred first, then
    active, then cheapest that can meet the quantity. There is no guessing.
    """

    __tablename__ = "vendor_products"
    __table_args__ = (
        UniqueConstraint(
            "vendor_id", "inventory_item_id", name="uq_vendor_products_vendor_item"
        ),
        Index("ix_vendor_products_item", "inventory_item_id"),
        Index("ix_vendor_products_merchant", "merchant_id"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    inventory_item_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("inventory_items.id", ondelete="CASCADE"), nullable=False
    )

    vendor_sku: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    minimum_order_quantity: Mapped[float] = mapped_column(
        Numeric(12, 2), default=0, nullable=False
    )
    lead_time_days: Mapped[float | None] = mapped_column(Numeric(6, 2))

    is_preferred: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    automatic_ordering_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    # ---- supplier-agent private terms (Supply Agents) ----
    #: The lowest unit price the supplier agent will accept. PRIVATE to that
    #: agent: never serialised to the buyer, other suppliers or the browser.
    floor_price: Mapped[float | None] = mapped_column(Numeric(12, 4))
    #: Units the supplier can ship right now. Null = not tracked (unlimited).
    available_quantity: Mapped[float | None] = mapped_column(Numeric(12, 2))
    #: [{"min_quantity": 200, "discount_pct": "0.05"}] - volume price breaks.
    volume_breaks: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    vendor: Mapped[Vendor] = relationship(back_populates="supplies", lazy="joined")


class PurchaseOrder(BaseModel):
    """One order raised against one vendor.

    ``idempotency_key`` is what makes automatic reordering safe: the replenishment
    path derives it from the triggering event, so a webhook delivered three times
    still produces one order.
    """

    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint(
            "merchant_id", "idempotency_key", name="uq_purchase_orders_idempotency"
        ),
        UniqueConstraint("merchant_id", "reference", name="uq_purchase_orders_reference"),
        Index("ix_purchase_orders_merchant_status", "merchant_id", "status"),
        Index("ix_purchase_orders_correlation", "correlation_id"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("vendors.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    #: Human-facing identifier, e.g. PO-000123.
    reference: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default=PurchaseOrderStatus.DRAFT, nullable=False
    )

    #: "AUTOMATION" when raised by the replenishment workflow, "USER" otherwise.
    source: Mapped[str] = mapped_column(String(16), default="USER", nullable=False)
    #: Set only for automatic orders; null for anything a human raised by hand.
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    correlation_id: Mapped[str | None] = mapped_column(String(64), index=True)

    total_value: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)

    # ---- negotiated orders (Supply Agents) ----
    #: Set when the order came out of an agent negotiation.
    procurement_request_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), index=True)
    #: The approval this order was created under - binds it to exact terms.
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    shipping_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    tax_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    payment_terms: Mapped[str] = mapped_column(String(24), default="", nullable=False)

    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    approval_note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    expected_at: Mapped[date | None] = mapped_column()
    received_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    #: True when the run was a dry run: everything computed, nothing sent.
    is_dry_run: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    failure_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    lines: Mapped[list[PurchaseOrderLine]] = relationship(
        back_populates="purchase_order", cascade="all, delete-orphan", lazy="selectin"
    )
    vendor: Mapped[Vendor] = relationship(lazy="joined")


class PurchaseOrderLine(BaseModel):
    """One inventory item on a purchase order.

    ``quantity_received`` is what makes partial receiving work: the order is
    RECEIVED only once every line is satisfied.
    """

    __tablename__ = "purchase_order_lines"
    __table_args__ = (Index("ix_po_lines_order", "purchase_order_id"),)

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False
    )
    inventory_item_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    product_name: Mapped[str] = mapped_column(String(160), nullable=False)

    quantity_ordered: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    quantity_received: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    line_total: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)

    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="lines")

    @property
    def quantity_outstanding(self) -> float:
        return max(float(self.quantity_ordered) - float(self.quantity_received), 0.0)
