"""Competitors and their (seeded) review corpus.

The `data_source` column keeps provenance explicit: nothing in this table claims
to be scraped from a live competitor platform.
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
from app.db.types import GUID, JSONB, StringArray, UTCDateTime, Vector


class Competitor(BaseModel):
    __tablename__ = "competitors"
    __table_args__ = (
        UniqueConstraint("merchant_id", "slug", name="uq_competitors_merchant_slug"),
        Index("ix_competitors_merchant_active", "merchant_id", "is_active"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(64), default="cafe", nullable=False)
    distance_km: Mapped[float] = mapped_column(Numeric(6, 2), default=0, nullable=False)
    price_tier: Mapped[str] = mapped_column(String(16), default="mid", nullable=False)

    avg_rating: Mapped[float] = mapped_column(Numeric(4, 2), default=0, nullable=False)
    review_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    #: Per-dimension perception score 0-100 (price, service, quality, speed, ...).
    perception_scores: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    strengths: Mapped[list[str]] = mapped_column(StringArray, default=list, nullable=False)
    weaknesses: Mapped[list[str]] = mapped_column(StringArray, default=list, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    #: SEEDED | PUBLIC_WEB - never "scraped from partner platform".
    data_source: Mapped[str] = mapped_column(String(32), default="SEEDED", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    reviews: Mapped[list[CompetitorReview]] = relationship(
        back_populates="competitor", cascade="all, delete-orphan"
    )


class CompetitorReview(BaseModel):
    __tablename__ = "competitor_reviews"
    __table_args__ = (
        Index("ix_competitor_reviews_merchant_date", "merchant_id", "review_date"),
        Index("ix_competitor_reviews_competitor_topic", "competitor_id", "primary_topic"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    competitor_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("competitors.id", ondelete="CASCADE"), nullable=False, index=True
    )

    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    sentiment: Mapped[str] = mapped_column(String(16), default="NEUTRAL", nullable=False)
    sentiment_score: Mapped[float] = mapped_column(Numeric(5, 3), default=0, nullable=False)
    primary_topic: Mapped[str] = mapped_column(String(32), nullable=False)
    topics: Mapped[list[str]] = mapped_column(StringArray, default=list, nullable=False)

    review_date: Mapped[date] = mapped_column(Date, nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    embedding: Mapped[list[float] | None] = mapped_column(Vector())
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    competitor: Mapped[Competitor] = relationship(back_populates="reviews")
