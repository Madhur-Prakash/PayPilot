"""Dashboard, customer, product and inventory analytics schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import (
    DateRange,
    EvidenceItem,
    MetricDelta,
    ProvenanceMeta,
    SchemaBase,
    TrendPoint,
)


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
class PeriodInfo(SchemaBase):
    current: DateRange
    previous: DateRange
    days: int
    label: str


class SalesSummary(SchemaBase):
    revenue: float
    orders: int
    aov: float
    unique_customers: int
    new_customers: int
    repeat_customers: int
    repeat_rate: float
    gross_margin: float
    gross_margin_pct: float
    discount_total: float
    avg_service_minutes: float | None = None


class DaypartBreakdown(SchemaBase):
    daypart: str
    label: str
    revenue: float
    orders: int
    aov: float
    unique_customers: int
    repeat_customers: int
    revenue_share_pct: float
    change_pct: float | None = None
    repeat_customers_change_pct: float | None = None
    avg_service_minutes: float | None = None
    service_minutes_change_pct: float | None = None
    negative_review_share_pct: float | None = None


class ProductPerformance(SchemaBase):
    product_id: uuid.UUID
    name: str
    sku: str
    category: str
    units_sold: int
    revenue: float
    gross_margin: float
    margin_pct: float
    revenue_share_pct: float
    orders: int
    attach_rate_pct: float
    previous_revenue: float | None = None
    change_pct: float | None = None
    trend: Literal["UP", "DOWN", "FLAT"] = "FLAT"
    price: float


class CustomerCohort(SchemaBase):
    key: str
    label: str
    customers: int
    revenue: float
    orders: int
    aov: float
    share_pct: float
    change_pct: float | None = None


class RetentionPoint(SchemaBase):
    cohort_month: str
    cohort_size: int
    month_index: int
    retained: int
    retention_pct: float


class CustomerMetrics(SchemaBase):
    total_customers: int
    active_customers: int
    new_customers: int
    repeat_customers: int
    repeat_rate: float
    retention_rate: float
    churn_risk_customers: int
    avg_orders_per_customer: float
    avg_customer_value: float
    cohorts: list[CustomerCohort] = Field(default_factory=list)
    by_daypart: list[DaypartBreakdown] = Field(default_factory=list)
    retention_curve: list[RetentionPoint] = Field(default_factory=list)


class Anomaly(SchemaBase):
    metric: str
    label: str
    value: float
    expected: float
    deviation_pct: float
    z_score: float | None = None
    severity: Literal["HIGH", "MEDIUM", "LOW"]
    dimension: str = "overall"
    dimension_value: str = "all"
    detected_on: date | None = None
    description: str = ""


class DashboardOverview(SchemaBase):
    """Single aggregated payload for the Growth Command Center.

    One request instead of a dozen - see the performance rule in the architecture doc.
    """

    merchant_id: uuid.UUID
    merchant_name: str
    period: PeriodInfo
    kpis: list[MetricDelta]
    summary: SalesSummary
    previous_summary: SalesSummary
    revenue_trend: list[TrendPoint]
    orders_trend: list[TrendPoint]
    daypart_breakdown: list[DaypartBreakdown]
    top_products: list[ProductPerformance]
    declining_products: list[ProductPerformance]
    customer_metrics: CustomerMetrics
    anomalies: list[Anomaly] = Field(default_factory=list)
    headline_insight: str = ""
    provenance: ProvenanceMeta = Field(default_factory=ProvenanceMeta)
    generated_at: datetime


# --------------------------------------------------------------------------- #
# Customers
# --------------------------------------------------------------------------- #
class CustomerOut(SchemaBase):
    id: uuid.UUID
    external_ref: str
    name: str
    masked_phone: str | None = None
    segment: str
    preferred_daypart: str
    total_orders: int
    total_spend: float
    avg_order_value: float
    first_order_at: datetime | None = None
    last_order_at: datetime | None = None
    recency_days: int | None = None
    acquisition_channel: str
    is_opted_in: bool = True


class SegmentDefinition(SchemaBase):
    """The filter used to materialise an audience. Validated server-side."""

    name: str = Field(max_length=200)
    dayparts: list[str] = Field(default_factory=list)
    segments: list[str] = Field(default_factory=list)
    min_orders: int | None = Field(default=None, ge=0)
    max_orders: int | None = Field(default=None, ge=0)
    min_recency_days: int | None = Field(default=None, ge=0)
    max_recency_days: int | None = Field(default=None, ge=0)
    min_total_spend: float | None = Field(default=None, ge=0)
    product_ids: list[uuid.UUID] = Field(default_factory=list)
    #: Behavioural membership - customers who actually transacted in these slots.
    active_dayparts: list[str] = Field(default_factory=list)
    active_within_days: int | None = Field(default=None, ge=1, le=730)
    opted_in_only: bool = True
    limit: int = Field(default=5000, ge=1, le=20000)


class SegmentPreview(SchemaBase):
    definition: SegmentDefinition
    size: int
    estimated_revenue_30d: float
    avg_order_value: float
    sample: list[CustomerOut] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Products
# --------------------------------------------------------------------------- #
class ProductOut(SchemaBase):
    id: uuid.UUID
    sku: str
    name: str
    category: str
    description: str
    price: float
    cost_price: float
    margin_pct: float
    is_active: bool
    is_featured: bool
    tags: list[str] = Field(default_factory=list)
    prep_time_minutes: int


class ProductMix(SchemaBase):
    """Pairs frequently bought together - the evidence behind a bundle opportunity."""

    product_a_id: uuid.UUID
    product_a_name: str
    product_b_id: uuid.UUID
    product_b_name: str
    co_occurrences: int
    support_pct: float
    confidence_pct: float
    lift: float
    combined_revenue: float
    estimated_bundle_uplift: float


class ProductAnalytics(SchemaBase):
    period: PeriodInfo
    products: list[ProductPerformance]
    top_by_revenue: list[ProductPerformance]
    top_by_margin: list[ProductPerformance]
    declining: list[ProductPerformance]
    growing: list[ProductPerformance]
    product_mix: list[ProductMix] = Field(default_factory=list)
    category_breakdown: list[CustomerCohort] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Inventory
# --------------------------------------------------------------------------- #
class InventoryItemOut(SchemaBase):
    id: uuid.UUID
    product_id: uuid.UUID
    product_name: str
    sku: str
    unit: str
    quantity_on_hand: float
    reorder_point: float
    reorder_quantity: float
    lead_time_days: float
    unit_cost: float
    avg_daily_demand: float
    days_of_cover: float | None = None
    stockout_risk: float
    revenue_at_risk: float
    status: str
    recommendation: str
    supplier: str
    last_restocked_at: datetime | None = None


class InventoryOverview(SchemaBase):
    items: list[InventoryItemOut]
    total_items: int
    at_risk_items: int
    total_revenue_at_risk: float
    total_stock_value: float
    critical: list[InventoryItemOut] = Field(default_factory=list)
    provenance: ProvenanceMeta = Field(default_factory=ProvenanceMeta)


class InventoryActionRequest(SchemaBase):
    """Records a *human* decision. The system never purchases autonomously."""

    action: Literal["ACKNOWLEDGE_REORDER", "RECORD_RESTOCK", "ADJUST"] = "ACKNOWLEDGE_REORDER"
    quantity: float = Field(default=0, ge=0)
    note: str = Field(default="", max_length=500)


# --------------------------------------------------------------------------- #
# Growth graph
# --------------------------------------------------------------------------- #
class GraphNode(SchemaBase):
    id: str
    label: str
    metric_key: str | None = None
    value: float | None = None
    formatted_value: str = ""
    change_pct: float | None = None
    direction: Literal["UP", "DOWN", "FLAT"] = "FLAT"
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"] = "INFO"
    depth: int = 0
    #: `signal` | `correlation` | `evidence` | `hypothesis` - never "cause".
    node_kind: Literal["metric", "segment", "signal", "evidence", "hypothesis"] = "metric"
    source: str = "analytics"
    interpretation: str = ""
    evidence: list[EvidenceItem] = Field(default_factory=list)
    related_metrics: list[str] = Field(default_factory=list)
    reference: str | None = None


class GraphEdge(SchemaBase):
    source: str
    target: str
    #: Deliberately *not* "causes". Correlation strength only.
    relationship: Literal["decomposes_into", "correlates_with", "evidenced_by"] = "decomposes_into"
    strength: float = Field(default=0.5, ge=0, le=1)
    label: str = ""


class GrowthGraph(SchemaBase):
    root_id: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    period: PeriodInfo
    caveat: str = (
        "Relationships shown are statistical signals and correlations observed in the "
        "current dataset. They are not causal claims."
    )
    generated_at: datetime
