"""Campaign and experiment schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import Field, model_validator

from app.schemas.analytics import SegmentDefinition
from app.schemas.common import ProvenanceMeta, SchemaBase

CampaignStatusLiteral = Literal[
    "DRAFT",
    "PENDING_APPROVAL",
    "APPROVED",
    "SCHEDULED",
    "RUNNING",
    "PAUSED",
    "COMPLETED",
    "REJECTED",
    "CANCELLED",
]
ChannelLiteral = Literal["paypal_app", "sms", "whatsapp", "email", "in_store"]
OfferTypeLiteral = Literal[
    "COMBO", "PERCENT_DISCOUNT", "FLAT_DISCOUNT", "CASHBACK", "FREE_ITEM", "NONE"
]
CampaignSurfaceLiteral = Literal["BUSINESS", "PAYPAL", "HYBRID"]
CampaignObjectiveLiteral = Literal[
    "",
    "RETENTION",
    "REACTIVATION",
    "ACQUISITION",
    "CROSS_SELL",
    "INVENTORY_CLEARANCE",
    "CAPACITY_UTILIZATION",
    "REVENUE_RECOVERY",
    "PROFIT_OPTIMIZATION",
]


# --------------------------------------------------------------------------- #
# Campaigns
# --------------------------------------------------------------------------- #
class CampaignAudienceOut(SchemaBase):
    id: uuid.UUID
    name: str
    role: Literal["TEST", "CONTROL", "FULL"]
    size: int
    definition: dict = Field(default_factory=dict)


class CampaignActionOut(SchemaBase):
    id: uuid.UUID
    action_type: str
    description: str
    actor_type: str
    actor_label: str
    is_simulated: bool
    payload: dict = Field(default_factory=dict)
    created_at: datetime


class CampaignOut(SchemaBase):
    id: uuid.UUID
    name: str
    objective: str
    status: CampaignStatusLiteral
    offer_type: OfferTypeLiteral
    offer_value: float
    offer_description: str
    message: str
    channel: ChannelLiteral
    start_date: date | None = None
    end_date: date | None = None
    budget: float
    estimated_cost: float
    actual_cost: float
    estimated_impact: float
    experiment_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None
    agent_run_id: uuid.UUID | None = None
    requires_approval: bool
    approved_at: datetime | None = None
    launched_at: datetime | None = None
    completed_at: datetime | None = None
    rejected_reason: str | None = None
    is_simulated: bool = True
    tags: list[str] = Field(default_factory=list)
    audiences: list[CampaignAudienceOut] = Field(default_factory=list)
    # ---- dual-market growth intelligence ----
    surface: CampaignSurfaceLiteral = "BUSINESS"
    objective_type: CampaignObjectiveLiteral = ""
    business_budget: float = 0
    paypal_budget: float = 0
    paypal_surface: str = ""
    expected_incremental_revenue: float | None = None
    actual_incremental_revenue: float | None = None
    incremental_roi: float | None = None
    measurement_status: str = ""
    created_by_agent: str = ""
    created_at: datetime
    updated_at: datetime


class CampaignDetail(CampaignOut):
    actions: list[CampaignActionOut] = Field(default_factory=list)
    provenance: ProvenanceMeta = Field(
        default_factory=lambda: ProvenanceMeta(
            data_source="SIMULATED",
            is_simulated=True,
            note=(
                "Delivery preview - no messaging provider is connected yet, so no messages "
                "are sent and no funds move."
            ),
        )
    )


class CampaignCreateRequest(SchemaBase):
    name: str = Field(min_length=3, max_length=200)
    objective: str = Field(default="", max_length=1000)
    offer_type: OfferTypeLiteral = "COMBO"
    offer_value: float = Field(default=0, ge=0, le=100000)
    offer_description: str = Field(default="", max_length=500)
    message: str = Field(default="", max_length=500)
    channel: ChannelLiteral = "paypal_app"
    start_date: date | None = None
    end_date: date | None = None
    budget: float = Field(default=0, ge=0)
    estimated_impact: float = Field(default=0, ge=0)
    opportunity_id: uuid.UUID | None = None
    audience: SegmentDefinition | None = None
    tags: list[str] = Field(default_factory=list)
    # ---- dual-market growth intelligence (all optional; default preserves the
    # pre-existing single-surface, merchant-funded campaign behaviour) ----
    surface: CampaignSurfaceLiteral = "BUSINESS"
    objective_type: CampaignObjectiveLiteral = ""
    business_budget: float = Field(default=0, ge=0)
    paypal_budget: float = Field(default=0, ge=0)
    paypal_surface: str = Field(default="", max_length=24)
    expected_incremental_revenue: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _dates_ordered(self) -> CampaignCreateRequest:
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self

    @model_validator(mode="after")
    def _hybrid_needs_both_legs(self) -> CampaignCreateRequest:
        if self.surface == "HYBRID" and not (self.business_budget and self.paypal_budget):
            raise ValueError(
                "A HYBRID campaign needs both business_budget and paypal_budget set."
            )
        return self


class CampaignApprovalRequest(SchemaBase):
    approve: bool = True
    note: str = Field(default="", max_length=500)


# --------------------------------------------------------------------------- #
# Experiments
# --------------------------------------------------------------------------- #
ExperimentStatusLiteral = Literal[
    "DRAFT",
    "PENDING_APPROVAL",
    "APPROVED",
    "RUNNING",
    "MEASURING",
    "COMPLETED",
    "STOPPED",
    "REJECTED",
]
DecisionLiteral = Literal["SCALE", "STOP", "CONTINUE", "WATCH", "PENDING"]


class ExperimentVariantOut(SchemaBase):
    id: uuid.UUID
    key: str
    name: str
    role: Literal["CONTROL", "TEST"]
    description: str
    offer_description: str
    allocation_pct: float
    audience_size: int
    unit_cost: float


class ExperimentResultOut(SchemaBase):
    id: uuid.UUID
    variant_id: uuid.UUID
    variant_key: str
    variant_role: Literal["CONTROL", "TEST"]
    audience_size: int
    converted_customers: int
    conversion_rate: float
    orders: int
    revenue: float
    gross_margin: float
    avg_order_value: float
    revenue_per_customer: float
    cost: float
    conversion_lift_pct: float | None = None
    revenue_lift_pct: float | None = None
    incremental_revenue: float | None = None
    incremental_profit: float | None = None
    roi: float | None = None
    p_value: float | None = None
    is_significant: bool = False
    measured_at: datetime | None = None
    window_start: date | None = None
    window_end: date | None = None


class ExperimentOut(SchemaBase):
    id: uuid.UUID
    name: str
    hypothesis: str
    success_metric: str
    success_threshold_pct: float
    status: ExperimentStatusLiteral
    start_date: date | None = None
    end_date: date | None = None
    duration_days: int
    campaign_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None
    agent_run_id: uuid.UUID | None = None
    requires_approval: bool
    approved_at: datetime | None = None
    launched_at: datetime | None = None
    completed_at: datetime | None = None
    decision: DecisionLiteral
    decision_rationale: str = ""
    learning: str = ""
    is_simulated: bool = True
    variants: list[ExperimentVariantOut] = Field(default_factory=list)
    results: list[ExperimentResultOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ExperimentSummary(SchemaBase):
    """Flattened control-vs-test view, exactly as the results screen renders it."""

    experiment_id: uuid.UUID
    name: str
    status: ExperimentStatusLiteral
    hypothesis: str
    control_conversion_rate: float
    test_conversion_rate: float
    conversion_lift_pct: float
    control_revenue: float
    test_revenue: float
    incremental_revenue: float
    incremental_profit: float
    roi: float
    cost: float
    p_value: float | None = None
    is_significant: bool
    decision: DecisionLiteral
    decision_rationale: str
    learning: str = ""
    window_start: date | None = None
    window_end: date | None = None
    provenance: ProvenanceMeta = Field(
        default_factory=lambda: ProvenanceMeta(
            data_source="SIMULATED",
            is_simulated=True,
            note=(
                "Results are computed deterministically from the controlled test/control "
                "transactions recorded for this experiment."
            ),
        )
    )


class ExperimentArmRequest(SchemaBase):
    """One treatment arm of a multi-arm growth experiment (business/paypal/hybrid)."""

    key: str = Field(min_length=1, max_length=32, pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=500)
    offer_description: str = Field(default="", max_length=500)
    allocation_pct: float = Field(default=25.0, gt=0, lt=100)
    unit_cost: float = Field(default=0, ge=0)


class ExperimentCreateRequest(SchemaBase):
    name: str = Field(min_length=3, max_length=200)
    hypothesis: str = Field(min_length=10, max_length=1000)
    success_metric: Literal["conversion_rate", "revenue_per_customer", "aov"] = "conversion_rate"
    success_threshold_pct: float = Field(default=10.0, ge=0, le=500)
    duration_days: int = Field(default=14, ge=1, le=120)
    start_date: date | None = None
    opportunity_id: uuid.UUID | None = None
    campaign_id: uuid.UUID | None = None
    audience: SegmentDefinition | None = None
    control_split_pct: float = Field(default=50.0, gt=0, lt=100)
    test_offer_description: str = Field(default="", max_length=500)
    unit_cost: float = Field(default=0, ge=0)
    #: Additional treatment arms beyond the ordinary control/test pair - a
    #: business-vs-paypal-vs-hybrid growth mission passes 2-3 of these instead of
    #: relying on `test_offer_description`/`unit_cost`. Omit for a plain 2-arm
    #: experiment, exactly as before.
    extra_arms: list[ExperimentArmRequest] = Field(default_factory=list, max_length=4)


class ExperimentApprovalRequest(SchemaBase):
    approve: bool = True
    note: str = Field(default="", max_length=500)


class ExperimentMeasureRequest(SchemaBase):
    """Re-run measurement. Recomputes every number from transactions."""

    window_start: date | None = None
    window_end: date | None = None
