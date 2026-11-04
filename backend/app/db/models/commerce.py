"""Products, customers, transactions and line items - the ground truth the
analytics layer computes over. Nothing here is ever summarised by an LLM.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

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
from app.db.types import GUID, JSONB, StringArray, UTCDateTime

if TYPE_CHECKING:
    pass


class DayPart:
    """Canonical trading slots. Growth analysis segments on these."""

    MORNING = "MORNING"  # 06:00 - 11:59
    AFTERNOON = "AFTERNOON"  # 12:00 - 16:59
    EVENING = "EVENING"  # 17:00 - 20:59
    NIGHT = "NIGHT"  # 21:00 - 05:59

    ALL = (MORNING, AFTERNOON, EVENING, NIGHT)

    @staticmethod
    def from_hour(hour: int) -> str:
        if 6 <= hour < 12:
            return DayPart.MORNING
        if 12 <= hour < 17:
            return DayPart.AFTERNOON
        if 17 <= hour < 21:
            return DayPart.EVENING
        return DayPart.NIGHT


class Product(BaseModel):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("merchant_id", "sku", name="uq_products_merchant_sku"),
        Index("ix_products_merchant_active", "merchant_id", "is_active"),
        Index("ix_products_merchant_category", "merchant_id", "category"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(64), default="general", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    cost_price: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tags: Mapped[list[str]] = mapped_column(StringArray, default=list, nullable=False)
    prep_time_minutes: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    image_url: Mapped[str | None] = mapped_column(Text)
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    @property
    def margin(self) -> float:
        price = float(self.price or 0)
        return price - float(self.cost_price or 0)

    @property
    def margin_pct(self) -> float:
        price = float(self.price or 0)
        return round((self.margin / price) * 100, 2) if price else 0.0


class CustomerSegment:
    NEW = "NEW"
    REPEAT = "REPEAT"
    LOYAL = "LOYAL"
    AT_RISK = "AT_RISK"
    CHURNED = "CHURNED"


class Customer(BaseModel):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("merchant_id", "external_ref", name="uq_customers_merchant_ref"),
        Index("ix_customers_merchant_segment", "merchant_id", "segment"),
        Index("ix_customers_merchant_last_order", "merchant_id", "last_order_at"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    masked_phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(320))

    segment: Mapped[str] = mapped_column(String(24), default=CustomerSegment.NEW, nullable=False)
    #: The day-part this customer usually transacts in - drives segment targeting.
    preferred_daypart: Mapped[str] = mapped_column(
        String(16), default=DayPart.AFTERNOON, nullable=False
    )
    acquisition_channel: Mapped[str] = mapped_column(String(32), default="walk_in", nullable=False)

    first_order_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    last_order_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    total_orders: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_spend: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    avg_order_value: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    recency_days: Mapped[int | None] = mapped_column(Integer)

    is_opted_in: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class TransactionStatus:
    COMPLETED = "COMPLETED"
    REFUNDED = "REFUNDED"
    CANCELLED = "CANCELLED"


class Transaction(BaseModel):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_transactions_merchant_occurred", "merchant_id", "occurred_at"),
        Index("ix_transactions_merchant_day", "merchant_id", "business_date"),
        Index("ix_transactions_merchant_daypart", "merchant_id", "daypart"),
        Index("ix_transactions_customer", "customer_id", "occurred_at"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("customers.id", ondelete="SET NULL"), index=True
    )
    order_ref: Mapped[str] = mapped_column(String(48), nullable=False)

    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    daypart: Mapped[str] = mapped_column(String(16), nullable=False)
    hour_of_day: Mapped[int] = mapped_column(Integer, nullable=False)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=Monday

    gross_amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    discount_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    net_amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    cost_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    payment_method: Mapped[str] = mapped_column(String(32), default="paypal", nullable=False)
    channel: Mapped[str] = mapped_column(String(32), default="in_store", nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default=TransactionStatus.COMPLETED, nullable=False
    )
    #: True when this was the customer's 2nd+ order with this merchant.
    is_repeat: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    service_minutes: Mapped[float | None] = mapped_column(Numeric(6, 2))

    campaign_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), index=True)
    experiment_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), index=True)
    experiment_variant: Mapped[str | None] = mapped_column(String(32))

    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    items: Mapped[list[TransactionItem]] = relationship(
        back_populates="transaction", cascade="all, delete-orphan"
    )


class TransactionItem(BaseModel):
    __tablename__ = "transaction_items"
    __table_args__ = (
        Index("ix_transaction_items_product", "product_id"),
        Index("ix_transaction_items_merchant_product", "merchant_id", "product_id"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    product_name: Mapped[str] = mapped_column(String(160), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    unit_cost: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    line_total: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    discount_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)

    transaction: Mapped[Transaction] = relationship(back_populates="items")
