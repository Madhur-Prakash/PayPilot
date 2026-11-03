"""Contextual external market signals.

A signal only exists in relation to a merchant: it carries the merchant's actual
*exposure* (share of revenue from the affected category) so the UI never becomes
a generic news feed.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import BaseModel
from app.db.types import GUID, JSONB, StringArray, UTCDateTime, Vector


class SignalCategory:
    INPUT_COST = "INPUT_COST"
    DEMAND = "DEMAND"
    WEATHER = "WEATHER"
    COMPETITION = "COMPETITION"
    REGULATION = "REGULATION"
    EVENT = "EVENT"
    TREND = "TREND"


class SignalRelevance:
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ExternalSignal(BaseModel):
    __tablename__ = "external_signals"
    __table_args__ = (
        Index("ix_external_signals_merchant_relevance", "merchant_id", "relevance"),
        Index("ix_external_signals_merchant_date", "merchant_id", "observed_on"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    category: Mapped[str] = mapped_column(String(32), default=SignalCategory.TREND, nullable=False)
    icon: Mapped[str] = mapped_column(String(32), default="trending-up", nullable=False)

    relevance: Mapped[str] = mapped_column(
        String(16), default=SignalRelevance.MEDIUM, nullable=False
    )
    relevance_score: Mapped[float] = mapped_column(Numeric(4, 3), default=0.5, nullable=False)

    # What links this signal to *this* merchant.
    linked_category: Mapped[str | None] = mapped_column(String(64))
    linked_product_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    exposure_pct: Mapped[float | None] = mapped_column(Numeric(6, 2))
    exposure_note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    potential_impact: Mapped[str] = mapped_column(Text, default="", nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, default="", nullable=False)
    direction: Mapped[str] = mapped_column(String(16), default="NEUTRAL", nullable=False)

    source_name: Mapped[str] = mapped_column(String(120), default="Market Digest", nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    observed_on: Mapped[date] = mapped_column(Date, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    expires_on: Mapped[date | None] = mapped_column(Date)

    #: True until a signal is sourced from a connected live search provider.
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_dismissed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tags: Mapped[list[str]] = mapped_column(StringArray, default=list, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector())
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
