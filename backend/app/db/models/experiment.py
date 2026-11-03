"""Experiments, variants and measured results.

Every number in ``ExperimentResult`` comes from SQL aggregation over
``transactions`` joined to the variant assignment - never from an LLM.
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


class ExperimentStatus:
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    RUNNING = "RUNNING"
    MEASURING = "MEASURING"
    COMPLETED = "COMPLETED"
    STOPPED = "STOPPED"
    REJECTED = "REJECTED"

    ALL = (
        DRAFT,
        PENDING_APPROVAL,
        APPROVED,
        RUNNING,
        MEASURING,
        COMPLETED,
        STOPPED,
        REJECTED,
    )


class ExperimentDecision:
    SCALE = "SCALE"
    STOP = "STOP"
    CONTINUE = "CONTINUE"
    WATCH = "WATCH"
    PENDING = "PENDING"


class VariantRole:
    CONTROL = "CONTROL"
    TEST = "TEST"


class Experiment(BaseModel):
    __tablename__ = "experiments"
    __table_args__ = (
        Index("ix_experiments_merchant_status", "merchant_id", "status"),
        Index("ix_experiments_merchant_start", "merchant_id", "start_date"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    hypothesis: Mapped[str] = mapped_column(Text, default="", nullable=False)
    success_metric: Mapped[str] = mapped_column(
        String(48), default="conversion_rate", nullable=False
    )
    success_threshold_pct: Mapped[float] = mapped_column(
        Numeric(8, 3), default=10.0, nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), default=ExperimentStatus.DRAFT, nullable=False)

    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    duration_days: Mapped[int] = mapped_column(Integer, default=14, nullable=False)

    campaign_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), index=True)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), index=True)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(GUID())

    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    launched_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID())

    decision: Mapped[str] = mapped_column(
        String(16), default=ExperimentDecision.PENDING, nullable=False
    )
    decision_rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)
    learning: Mapped[str] = mapped_column(Text, default="", nullable=False)

    #: True while an experiment's transactions come from a controlled test/control window
    #: rather than live traffic accrued over time.
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    variants: Mapped[list[ExperimentVariant]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan", lazy="selectin"
    )
    results: Mapped[list[ExperimentResult]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan", lazy="selectin"
    )


class ExperimentVariant(BaseModel):
    __tablename__ = "experiment_variants"
    __table_args__ = (
        UniqueConstraint("experiment_id", "key", name="uq_experiment_variants_key"),
        Index("ix_experiment_variants_experiment_role", "experiment_id", "role"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    experiment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    role: Mapped[str] = mapped_column(String(16), default=VariantRole.TEST, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    offer_description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    allocation_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=50, nullable=False)
    audience_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    customer_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    audience_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unit_cost: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)

    experiment: Mapped[Experiment] = relationship(back_populates="variants")


class ExperimentResult(BaseModel):
    """One measured row per variant, plus the derived lift on the test row."""

    __tablename__ = "experiment_results"
    __table_args__ = (
        UniqueConstraint("experiment_id", "variant_id", name="uq_experiment_results_variant"),
        Index("ix_experiment_results_experiment", "experiment_id"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    experiment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("experiment_variants.id", ondelete="CASCADE"), nullable=False
    )
    variant_key: Mapped[str] = mapped_column(String(32), nullable=False)
    variant_role: Mapped[str] = mapped_column(String(16), nullable=False)

    audience_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    converted_customers: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    conversion_rate: Mapped[float] = mapped_column(Numeric(8, 4), default=0, nullable=False)
    orders: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    revenue: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    gross_margin: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    avg_order_value: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    revenue_per_customer: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    cost: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)

    # Derived comparison vs. control (null on the control row itself)
    conversion_lift_pct: Mapped[float | None] = mapped_column(Numeric(10, 4))
    revenue_lift_pct: Mapped[float | None] = mapped_column(Numeric(10, 4))
    incremental_revenue: Mapped[float | None] = mapped_column(Numeric(14, 2))
    incremental_profit: Mapped[float | None] = mapped_column(Numeric(14, 2))
    roi: Mapped[float | None] = mapped_column(Numeric(10, 4))
    #: Two-proportion z-test on conversion; reported as a signal, not proof of cause.
    p_value: Mapped[float | None] = mapped_column(Numeric(10, 6))
    is_significant: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    measured_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    window_start: Mapped[date | None] = mapped_column(Date)
    window_end: Mapped[date | None] = mapped_column(Date)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    experiment: Mapped[Experiment] = relationship(back_populates="results")
