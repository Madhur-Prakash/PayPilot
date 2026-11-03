"""Growth metrics (deterministic snapshots) and detected growth opportunities."""

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
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import BaseModel
from app.db.types import GUID, JSONB, StringArray, UTCDateTime


class MetricKey:
    REVENUE = "revenue"
    ORDERS = "orders"
    AOV = "aov"
    REPEAT_RATE = "repeat_rate"
    RETENTION_RATE = "retention_rate"
    UNIQUE_CUSTOMERS = "unique_customers"
    NEW_CUSTOMERS = "new_customers"
    REPEAT_CUSTOMERS = "repeat_customers"
    GROSS_MARGIN = "gross_margin"
    AVG_SERVICE_MINUTES = "avg_service_minutes"


class MetricDirection:
    """Which way is good. Used to colour a delta without hardcoding it in the UI."""

    UP_IS_GOOD = "UP_IS_GOOD"
    DOWN_IS_GOOD = "DOWN_IS_GOOD"
    NEUTRAL = "NEUTRAL"


class GrowthMetric(BaseModel):
    """A computed metric snapshot for a period.

    Written by the analytics service, never by an LLM. ``dimension``/``dimension_value``
    let the same metric be stored overall and per segment (e.g. daypart=EVENING).
    """

    __tablename__ = "growth_metrics"
    __table_args__ = (
        UniqueConstraint(
            "merchant_id",
            "metric_key",
            "period_start",
            "period_end",
            "dimension",
            "dimension_value",
            name="uq_growth_metrics_snapshot",
        ),
        Index("ix_growth_metrics_merchant_key", "merchant_id", "metric_key"),
        Index("ix_growth_metrics_period", "merchant_id", "period_end"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    metric_key: Mapped[str] = mapped_column(String(48), nullable=False)
    label: Mapped[str] = mapped_column(String(96), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), default="number", nullable=False)

    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    granularity: Mapped[str] = mapped_column(String(16), default="period", nullable=False)

    dimension: Mapped[str] = mapped_column(String(32), default="overall", nullable=False)
    dimension_value: Mapped[str] = mapped_column(String(64), default="all", nullable=False)

    value: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    previous_value: Mapped[float | None] = mapped_column(Numeric(18, 4))
    change_abs: Mapped[float | None] = mapped_column(Numeric(18, 4))
    change_pct: Mapped[float | None] = mapped_column(Numeric(10, 4))
    direction: Mapped[str] = mapped_column(
        String(16), default=MetricDirection.UP_IS_GOOD, nullable=False
    )
    is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sample_size: Mapped[int | None] = mapped_column(Integer)
    computed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class OpportunityStatus:
    DETECTED = "DETECTED"
    INVESTIGATING = "INVESTIGATING"
    RECOMMENDED = "RECOMMENDED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    RUNNING = "RUNNING"
    MEASURING = "MEASURING"
    SCALED = "SCALED"
    STOPPED = "STOPPED"
    DISMISSED = "DISMISSED"

    ALL = (
        DETECTED,
        INVESTIGATING,
        RECOMMENDED,
        APPROVAL_REQUIRED,
        RUNNING,
        MEASURING,
        SCALED,
        STOPPED,
        DISMISSED,
    )
    #: Statuses the Opportunity Radar treats as still in-flight.
    OPEN = (DETECTED, INVESTIGATING, RECOMMENDED, APPROVAL_REQUIRED, RUNNING, MEASURING)


class ImpactLevel:
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class OpportunityKind:
    RETENTION = "RETENTION"
    BUNDLE = "BUNDLE"
    DAYPART = "DAYPART"
    PRODUCT = "PRODUCT"
    PRICING = "PRICING"
    SERVICE = "SERVICE"
    INVENTORY = "INVENTORY"


class GrowthOpportunity(BaseModel):
    """A detected, quantified growth opportunity.

    ``estimated_value_monthly`` and ``confidence`` are produced by the deterministic
    detector in services/growth; the LLM only writes the narrative fields.
    """

    __tablename__ = "growth_opportunities"
    __table_args__ = (
        UniqueConstraint("merchant_id", "key", name="uq_growth_opportunities_merchant_key"),
        Index("ix_growth_opportunities_merchant_status", "merchant_id", "status"),
        Index("ix_growth_opportunities_value", "merchant_id", "estimated_value_monthly"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(96), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default=OpportunityKind.RETENTION, nullable=False)

    estimated_value_monthly: Mapped[float] = mapped_column(
        Numeric(14, 2), default=0, nullable=False
    )
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), default=0.5, nullable=False)
    impact: Mapped[str] = mapped_column(String(16), default=ImpactLevel.MEDIUM, nullable=False)
    effort: Mapped[str] = mapped_column(String(16), default="MEDIUM", nullable=False)
    priority_score: Mapped[float] = mapped_column(Numeric(8, 3), default=0, nullable=False)
    risk: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)

    status: Mapped[str] = mapped_column(
        String(24), default=OpportunityStatus.DETECTED, nullable=False
    )
    #: Structured evidence rows: [{metric, value, change, source, ...}]
    evidence: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    hypothesis: Mapped[str] = mapped_column(Text, default="", nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, default="", nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, default="", nullable=False)
    #: Nodes/edges of the growth graph branch that produced this opportunity.
    graph_path: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    target_segment: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    tags: Mapped[list[str]] = mapped_column(StringArray, default=list, nullable=False)

    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    detected_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)

    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), index=True)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    experiment_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
