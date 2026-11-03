"""Inventory intelligence: stock levels, depletion risk, and recorded actions.

The system recommends. It never purchases.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import BaseModel
from app.db.types import GUID, JSONB, UTCDateTime


class StockStatus:
    """Authoritative stock state, decided by the backend and never the browser.

    The first five are the platform's original vocabulary and are unchanged, so
    existing rows, dashboards and agent tools keep working. The rest were added
    for automated replenishment and aging.
    """

    HEALTHY = "HEALTHY"
    WATCH = "WATCH"
    LOW = "LOW"
    CRITICAL = "CRITICAL"
    OUT_OF_STOCK = "OUT_OF_STOCK"

    REORDER_REQUIRED = "REORDER_REQUIRED"
    OVERSTOCKED = "OVERSTOCKED"
    AGING = "AGING"
    EXPIRING_SOON = "EXPIRING_SOON"
    EXPIRED = "EXPIRED"
    DISCONTINUED = "DISCONTINUED"


class InventoryItem(BaseModel):
    __tablename__ = "inventory_items"
    __table_args__ = (
        UniqueConstraint("merchant_id", "product_id", name="uq_inventory_merchant_product"),
        Index("ix_inventory_merchant_status", "merchant_id", "status"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_name: Mapped[str] = mapped_column(String(160), nullable=False)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    unit: Mapped[str] = mapped_column(String(24), default="units", nullable=False)

    quantity_on_hand: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    reorder_point: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    reorder_quantity: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    lead_time_days: Mapped[float] = mapped_column(Numeric(6, 2), default=2, nullable=False)
    unit_cost: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)

    # Computed by services/inventory from the last 14 days of transaction items.
    avg_daily_demand: Mapped[float] = mapped_column(Numeric(12, 3), default=0, nullable=False)
    days_of_cover: Mapped[float | None] = mapped_column(Numeric(8, 2))
    stockout_risk: Mapped[float] = mapped_column(Numeric(5, 3), default=0, nullable=False)
    revenue_at_risk: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default=StockStatus.HEALTHY, nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, default="", nullable=False)

    last_counted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_restocked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    supplier: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    is_tracked: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # ---------------------------------------------------------------- automation
    #: Committed to open orders but not yet shipped. Reorder decisions use
    #: `available_quantity`, never `quantity_on_hand`, so promised stock is not
    #: counted twice.
    reserved_quantity: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    #: Target for the TARGET_MAX_STOCK strategy. 0 means "not configured".
    maximum_stock: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    minimum_stock: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)

    #: FIXED_QUANTITY | TARGET_MAX_STOCK - see services/inventory/replenishment.
    reorder_strategy: Mapped[str] = mapped_column(
        String(24), default="FIXED_QUANTITY", nullable=False
    )
    #: Per-item switch. The organisation-level switch can still veto it.
    automatic_ordering_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    expiry_tracking_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    #: Set when the item is supplied by a real vendor record rather than the
    #: legacy free-text `supplier` name.
    default_vendor_id: Mapped[uuid.UUID | None] = mapped_column(GUID())

    #: Optimistic-concurrency guard: bumped on every stock write, so two
    #: simultaneous sales cannot both read 10 and both write 9.
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    movements: Mapped[list[InventoryMovement]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )
    batches: Mapped[list[InventoryBatch]] = relationship(
        back_populates="item", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def available_quantity(self) -> float:
        """What can actually be sold, or counted toward a reorder decision."""
        return float(self.quantity_on_hand) - float(self.reserved_quantity)


class MovementType:
    """Every reason stock can change.

    The ledger is append-only, so a correction is a new movement rather than an
    edit to an old one.
    """

    RESTOCK = "RESTOCK"
    CONSUMPTION = "CONSUMPTION"
    WASTAGE = "WASTAGE"
    ADJUSTMENT = "ADJUSTMENT"
    REORDER_RECOMMENDED = "REORDER_RECOMMENDED"
    REORDER_ACKNOWLEDGED = "REORDER_ACKNOWLEDGED"

    SALE = "SALE"
    PURCHASE_RECEIPT = "PURCHASE_RECEIPT"
    CUSTOMER_RETURN = "CUSTOMER_RETURN"
    VENDOR_RETURN = "VENDOR_RETURN"
    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"
    EXPIRY = "EXPIRY"
    DAMAGE = "DAMAGE"
    RESERVATION = "RESERVATION"
    RELEASE = "RELEASE"

    #: These move stock between the available and reserved buckets without
    #: changing quantity on hand.
    NON_STOCK_CHANGING = (RESERVATION, RELEASE)


class InventoryMovement(BaseModel):
    __tablename__ = "inventory_movements"
    __table_args__ = (
        Index("ix_inventory_movements_item_created", "inventory_item_id", "created_at"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    inventory_item_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("inventory_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    movement_type: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    balance_after: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    actor_type: Mapped[str] = mapped_column(String(16), default="SYSTEM", nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    quantity_units: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # ---------------------------------------------------------------- traceability
    #: The balance before this movement. Stored rather than derived so a single
    #: row can be audited without replaying the whole history.
    balance_before: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    unit_cost: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    total_value: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)

    #: What caused it, e.g. ("SALE", <transaction id>) or ("PURCHASE_ORDER", <po id>).
    reference_type: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    reference_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)

    batch_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    #: "backend" | "n8n" | "system" - which surface wrote the row.
    source: Mapped[str] = mapped_column(String(16), default="backend", nullable=False)
    correlation_id: Mapped[str] = mapped_column(
        String(64), default="", nullable=False, index=True
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(GUID())

    item: Mapped[InventoryItem] = relationship(back_populates="movements")


class BatchStatus:
    ACTIVE = "ACTIVE"
    AGING = "AGING"
    EXPIRING_SOON = "EXPIRING_SOON"
    EXPIRED = "EXPIRED"
    DEPLETED = "DEPLETED"
    QUARANTINED = "QUARANTINED"


class InventoryBatch(BaseModel):
    """One receipt of stock, kept separate so expiry and cost can be tracked.

    Batches are what make FEFO possible: consumption draws from the batch that
    expires first rather than treating the item as one undifferentiated pool.
    Expired stock is never deleted - it changes state, and a WASTAGE movement
    records the write-off.
    """

    __tablename__ = "inventory_batches"
    __table_args__ = (
        Index("ix_inventory_batches_item", "inventory_item_id"),
        Index("ix_inventory_batches_expiry", "merchant_id", "expiry_date"),
        Index("ix_inventory_batches_status", "merchant_id", "status"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    inventory_item_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("inventory_items.id", ondelete="CASCADE"), nullable=False
    )

    batch_code: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    quantity_received: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    unit_cost: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)

    received_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    manufactured_on: Mapped[date | None] = mapped_column(Date())
    expiry_date: Mapped[date | None] = mapped_column(Date())

    status: Mapped[str] = mapped_column(String(24), default=BatchStatus.ACTIVE, nullable=False)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    item: Mapped[InventoryItem] = relationship(back_populates="batches")
