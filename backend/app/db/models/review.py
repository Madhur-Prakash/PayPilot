"""Merchant reviews with topic classification and pgvector embeddings."""

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
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import BaseModel
from app.db.types import GUID, JSONB, StringArray, UTCDateTime, Vector


class ReviewTopic:
    """The fixed topic taxonomy the Review Intelligence agent classifies into."""

    TASTE = "taste"
    QUALITY = "quality"
    PRICE = "price"
    PACKAGING = "packaging"
    WAITING_TIME = "waiting_time"
    SERVICE = "service"
    STAFF = "staff"
    DELIVERY = "delivery"
    AVAILABILITY = "availability"
    AMBIENCE = "ambience"

    ALL = (
        TASTE,
        QUALITY,
        PRICE,
        PACKAGING,
        WAITING_TIME,
        SERVICE,
        STAFF,
        DELIVERY,
        AVAILABILITY,
        AMBIENCE,
    )

    LABELS = {
        TASTE: "Taste",
        QUALITY: "Quality",
        PRICE: "Price",
        PACKAGING: "Packaging",
        WAITING_TIME: "Waiting Time",
        SERVICE: "Service",
        STAFF: "Staff",
        DELIVERY: "Delivery",
        AVAILABILITY: "Availability",
        AMBIENCE: "Ambience",
    }


class Sentiment:
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"


class Review(BaseModel):
    __tablename__ = "reviews"
    __table_args__ = (
        Index("ix_reviews_merchant_date", "merchant_id", "review_date"),
        Index("ix_reviews_merchant_sentiment", "merchant_id", "sentiment"),
        Index("ix_reviews_merchant_primary_topic", "merchant_id", "primary_topic"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("customers.id", ondelete="SET NULL")
    )
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    product_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), index=True)

    source: Mapped[str] = mapped_column(String(32), default="paypal", nullable=False)
    external_ref: Mapped[str | None] = mapped_column(String(64))
    author_name: Mapped[str] = mapped_column(String(120), default="Customer", nullable=False)

    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, nullable=False)

    sentiment: Mapped[str] = mapped_column(String(16), default=Sentiment.NEUTRAL, nullable=False)
    sentiment_score: Mapped[float] = mapped_column(Numeric(5, 3), default=0, nullable=False)
    primary_topic: Mapped[str] = mapped_column(String(32), nullable=False)
    topics: Mapped[list[str]] = mapped_column(StringArray, default=list, nullable=False)

    daypart: Mapped[str | None] = mapped_column(String(16), index=True)
    review_date: Mapped[date] = mapped_column(Date, nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    is_verified_purchase: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    #: Honest provenance flag - True until a review is sourced from a live integration.
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    embedding: Mapped[list[float] | None] = mapped_column(Vector())
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
