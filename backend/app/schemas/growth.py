"""Growth opportunity, review, competitor and signal schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import (
    EvidenceItem,
    ProvenanceMeta,
    SchemaBase,
    TrendPoint,
)

OpportunityStatusLiteral = Literal[
    "DETECTED",
    "INVESTIGATING",
    "RECOMMENDED",
    "APPROVAL_REQUIRED",
    "RUNNING",
    "MEASURING",
    "SCALED",
    "STOPPED",
    "DISMISSED",
]


# --------------------------------------------------------------------------- #
# Dual-market growth intelligence
# --------------------------------------------------------------------------- #
class InterventionOptionOut(SchemaBase):
    surface: Literal["BUSINESS", "PAYPAL", "HYBRID"]
    label: str
    audience_label: str
    audience_size: int
    historical_conversion_pct: float | None = None
    offer_type: str
    offer_description: str
    channel: str
    budget: float
    expected_customers: float
    expected_incremental_revenue: float
    provenance: str


class DontDiscountOut(SchemaBase):
    high_propensity_pct: float
    recommendation: str
    reasoning: str


class ArbitrageFindingOut(SchemaBase):
    better_surface: Literal["BUSINESS", "PAYPAL", "HYBRID"]
    worse_surface: Literal["BUSINESS", "PAYPAL", "HYBRID"]
    better_roi: float
    worse_roi: float
    evidence_count: int
    confidence: Literal["low", "medium", "high"]
    recommended_shift_pct: float


class GrowthMissionOut(SchemaBase):
    """The output of the Growth Allocation Engine for one opportunity: three
    candidate interventions, a recommended split, and why."""

    opportunity_id: uuid.UUID | None = None
    title: str
    business_option: InterventionOptionOut
    paypal_option: InterventionOptionOut
    hybrid_option: InterventionOptionOut
    recommended_surface: Literal["BUSINESS", "PAYPAL", "HYBRID"]
    recommendation_reason: str
    allocation_basis: Literal["historical", "default"]
    business_pct: float
    paypal_pct: float
    dont_discount: DontDiscountOut | None = None
    arbitrage: ArbitrageFindingOut | None = None


class AllocationSnapshotOut(SchemaBase):
    """Where the growth budget has actually gone, by surface - for the Command
    Center's Growth Allocation widget."""

    by_surface: dict[str, dict[str, float]] = Field(default_factory=dict)
    business_pct: float
    paypal_pct: float
    hybrid_pct: float
    total_spend: float
    total_incremental_revenue: float
    has_data: bool


# --------------------------------------------------------------------------- #
# Opportunities
# --------------------------------------------------------------------------- #
class OpportunityOut(SchemaBase):
    id: uuid.UUID
    key: str
    title: str
    summary: str
    kind: str
    estimated_value_monthly: float
    confidence: float
    impact: Literal["HIGH", "MEDIUM", "LOW"]
    effort: Literal["HIGH", "MEDIUM", "LOW"]
    priority_score: float
    risk: str
    status: OpportunityStatusLiteral
    evidence: list[EvidenceItem] = Field(default_factory=list)
    hypothesis: str = ""
    recommended_action: str = ""
    reasoning: str = ""
    graph_path: list[str] = Field(default_factory=list)
    target_segment: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    requires_approval: bool = True
    detected_at: datetime | None = None
    period_start: date | None = None
    period_end: date | None = None
    agent_run_id: uuid.UUID | None = None
    campaign_id: uuid.UUID | None = None
    experiment_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class OpportunityRadar(SchemaBase):
    opportunities: list[OpportunityOut]
    total_detected: int
    total_estimated_value_monthly: float
    open_count: int
    provenance: ProvenanceMeta = Field(default_factory=ProvenanceMeta)
    generated_at: datetime


class OpportunityStatusUpdate(SchemaBase):
    status: OpportunityStatusLiteral
    note: str = Field(default="", max_length=500)


class DetectOpportunitiesRequest(SchemaBase):
    days: int = Field(default=30, ge=7, le=180)
    #: Re-run detection even when fresh opportunities already exist.
    force: bool = False


# --------------------------------------------------------------------------- #
# Reviews
# --------------------------------------------------------------------------- #
class ReviewOut(SchemaBase):
    id: uuid.UUID
    source: str
    author_name: str
    rating: int
    title: str | None = None
    body: str
    sentiment: str
    sentiment_score: float
    primary_topic: str
    topics: list[str] = Field(default_factory=list)
    daypart: str | None = None
    review_date: date
    reviewed_at: datetime
    is_verified_purchase: bool
    is_simulated: bool
    product_id: uuid.UUID | None = None


class TopicStat(SchemaBase):
    topic: str
    label: str
    count: int
    share_pct: float
    avg_rating: float
    negative_count: int
    positive_count: int
    negative_share_pct: float
    previous_count: int = 0
    change_pct: float | None = None
    trend: Literal["UP", "DOWN", "FLAT"] = "FLAT"
    is_emerging_complaint: bool = False
    sample_review_ids: list[uuid.UUID] = Field(default_factory=list)


class SentimentBreakdown(SchemaBase):
    positive: int
    neutral: int
    negative: int
    positive_pct: float
    neutral_pct: float
    negative_pct: float
    avg_rating: float
    previous_avg_rating: float | None = None
    avg_rating_change: float | None = None


class ReviewIntelligence(SchemaBase):
    total_reviews: int
    period_reviews: int
    sentiment: SentimentBreakdown
    topics: list[TopicStat]
    emerging_complaints: list[TopicStat]
    positive_themes: list[TopicStat]
    rating_trend: list[TrendPoint]
    negative_topic_trend: list[TrendPoint]
    by_daypart: list[TopicStat] = Field(default_factory=list)
    recent_reviews: list[ReviewOut] = Field(default_factory=list)
    provenance: ProvenanceMeta = Field(default_factory=ProvenanceMeta)
    generated_at: datetime


class ReviewSearchRequest(SchemaBase):
    """Semantic search over review embeddings (pgvector)."""

    query: str = Field(min_length=2, max_length=400)
    limit: int = Field(default=10, ge=1, le=50)
    topic: str | None = None
    sentiment: Literal["POSITIVE", "NEUTRAL", "NEGATIVE"] | None = None


class ReviewSearchHit(SchemaBase):
    review: ReviewOut
    similarity: float


# --------------------------------------------------------------------------- #
# Competitors
# --------------------------------------------------------------------------- #
class CompetitorOut(SchemaBase):
    id: uuid.UUID
    name: str
    slug: str
    category: str
    distance_km: float
    price_tier: str
    avg_rating: float
    review_count: int
    perception_scores: dict = Field(default_factory=dict)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    data_source: str
    notes: str = ""


class PerceptionComparison(SchemaBase):
    dimension: str
    label: str
    merchant_score: float
    competitor_avg_score: float
    gap: float
    leader: str
    is_merchant_ahead: bool


class CompetitorIntelligence(SchemaBase):
    merchant_name: str
    merchant_scores: dict = Field(default_factory=dict)
    merchant_avg_rating: float
    competitors: list[CompetitorOut]
    comparisons: list[PerceptionComparison]
    biggest_gap: PerceptionComparison | None = None
    topic_share: list[TopicStat] = Field(default_factory=list)
    summary: str = ""
    provenance: ProvenanceMeta = Field(
        default_factory=lambda: ProvenanceMeta(
            data_source="SEEDED",
            is_simulated=True,
            note=(
                "Competitor reviews are representative baseline data. "
                "No competitor platform is scraped or integrated yet."
            ),
        )
    )
    generated_at: datetime


# --------------------------------------------------------------------------- #
# External signals
# --------------------------------------------------------------------------- #
class SignalOut(SchemaBase):
    id: uuid.UUID
    title: str
    summary: str
    category: str
    icon: str
    relevance: Literal["HIGH", "MEDIUM", "LOW"]
    relevance_score: float
    linked_category: str | None = None
    linked_product_id: uuid.UUID | None = None
    exposure_pct: float | None = None
    exposure_note: str = ""
    potential_impact: str = ""
    recommended_action: str = ""
    direction: str = "NEUTRAL"
    source_name: str
    source_url: str | None = None
    observed_on: date
    is_simulated: bool = True


class SignalFeed(SchemaBase):
    signals: list[SignalOut]
    high_relevance_count: int
    provenance: ProvenanceMeta = Field(default_factory=ProvenanceMeta)
    generated_at: datetime
