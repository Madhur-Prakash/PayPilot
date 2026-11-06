"""Product Discovery and Supply Intelligence persistence.

* ``product_searches``        - every discovery search: the request, the intent extracted
                                from it, what Channel3 was asked, and what came back.
* ``discovered_products``     - one row per Channel3 product a merchant has seen. A snapshot
                                for history and dashboards; prices and offer links are
                                re-fetched from Channel3 before they are shown as current.
* ``product_comparisons``     - side-by-side comparisons and the analysis behind them.
* ``merchant_recommendations``- AI recommendations with their evidence and lifecycle:
                                DETECTED -> ANALYZED -> RECOMMENDED -> APPROVED -> EXECUTED -> MEASURED.
* ``shopping_conversations``  - multi-turn conversations with Channel3's shopping agent and
                                the constraints PayPilot remembered across turns.

Agent executions, approvals and PayPal payments reuse ``agent_runs``,
``approval_requests`` and ``financial_executions`` - no parallel ledgers.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
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


class SearchSource:
    DISCOVERY = "discovery"
    SIMILAR = "similar"
    ENRICH = "enrich"
    ASSORTMENT = "assortment"
    ALTERNATIVES = "alternatives"
    PRICING = "pricing"
    AGENT = "agent"
    CONVERSATION = "conversation"


class ProductSearch(BaseModel):
    __tablename__ = "product_searches"
    __table_args__ = (Index("ix_product_searches_merchant_created", "merchant_id", "created_at"),)

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    source: Mapped[str] = mapped_column(String(24), default=SearchSource.DISCOVERY, nullable=False)
    query: Mapped[str] = mapped_column(Text, default="", nullable=False)
    #: What PayPilot understood (category, budget, brands, attributes, use case ...).
    intent: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    #: The exact request sent to Channel3 (never contains credentials).
    request: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    product_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), default="LIVE", nullable=False)
    used_llm: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(GUID())


class DiscoveredProduct(BaseModel):
    __tablename__ = "discovered_products"
    __table_args__ = (
        UniqueConstraint("merchant_id", "channel3_product_id", name="uq_discovered_products_product"),
        Index("ix_discovered_products_merchant_seen", "merchant_id", "last_seen_at"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel3_product_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    brand: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    category_slug: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    category_title: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    image_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    #: Snapshot prices at ``last_seen_at`` - context, not a live quote.
    min_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    max_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    offers_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    retailer: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    in_stock: Mapped[bool | None] = mapped_column(Boolean)
    #: Normalised product without offer URLs (those are short-lived and re-fetched).
    snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    times_seen: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_source: Mapped[str] = mapped_column(String(24), default=SearchSource.DISCOVERY, nullable=False)
    is_shortlisted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ProductComparison(BaseModel):
    __tablename__ = "product_comparisons"
    __table_args__ = (Index("ix_product_comparisons_merchant_created", "merchant_id", "created_at"),)

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    product_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    titles: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    #: Verdicts, the matrix of compared fields, and the evidence for each verdict.
    analysis: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    narrative: Mapped[str] = mapped_column(Text, default="", nullable=False)
    used_llm: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class RecommendationKind:
    ASSORTMENT_EXPANSION = "ASSORTMENT_EXPANSION"
    PRODUCT_ALTERNATIVE = "PRODUCT_ALTERNATIVE"
    PRICING_OPPORTUNITY = "PRICING_OPPORTUNITY"

    LABELS = {
        ASSORTMENT_EXPANSION: "Assortment expansion",
        PRODUCT_ALTERNATIVE: "Product alternative",
        PRICING_OPPORTUNITY: "Pricing opportunity",
    }


class RecommendationStatus:
    DETECTED = "DETECTED"
    ANALYZED = "ANALYZED"
    RECOMMENDED = "RECOMMENDED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    MEASURED = "MEASURED"
    #: A newer generation run replaced it before anyone decided.
    SUPERSEDED = "SUPERSEDED"

    LIFECYCLE = (DETECTED, ANALYZED, RECOMMENDED, APPROVED, EXECUTED, MEASURED)
    OPEN = (DETECTED, ANALYZED, RECOMMENDED)


class MerchantRecommendation(BaseModel):
    __tablename__ = "merchant_recommendations"
    __table_args__ = (
        Index("ix_merchant_recommendations_merchant_status", "merchant_id", "status"),
        Index("ix_merchant_recommendations_dedupe", "merchant_id", "dedupe_key"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reference: Mapped[str] = mapped_column(String(24), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    #: ``[{label, value, source}]`` - every number here comes from SQL or Channel3.
    evidence: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, default="", nullable=False)
    #: ``{metric, value, currency, period, is_estimate: true, assumptions: [...]}``.
    expected_impact: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0.5"), nullable=False)
    confidence_reasons: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=RecommendationStatus.DETECTED, nullable=False)
    #: ``[{status, at, actor, note}]`` - the visible lifecycle.
    lifecycle: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    anchor_product_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    anchor_product_name: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    category: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    #: Channel3 products supporting the recommendation (snapshots, no offer URLs).
    products: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    suggested_test_quantity: Mapped[int | None] = mapped_column(Integer)
    suggested_retail_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    narrative_source: Mapped[str] = mapped_column(String(16), default="deterministic", nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(160), nullable=False)

    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    decided_by_label: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    decision_note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    #: What execution produced: ``{catalog_product_id, approval_id, execution_id, ...}``.
    execution: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    measured_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    measurement: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class ShoppingConversation(BaseModel):
    __tablename__ = "shopping_conversations"
    __table_args__ = (Index("ix_shopping_conversations_merchant_updated", "merchant_id", "updated_at"),)

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    channel3_conversation_id: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    title: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    #: Constraints carried across turns (budget, category, use case, brands ...).
    constraints: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    #: ``[{role, text, products, suggestions, at}]``.
    messages: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    turn_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    credits_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_turn_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
