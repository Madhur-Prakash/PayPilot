"""Campaigns, their audiences and the (simulated) actions taken on them."""

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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import BaseModel
from app.db.types import GUID, JSONB, StringArray, UTCDateTime


class CampaignStatus:
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"

    ALL = (
        DRAFT,
        PENDING_APPROVAL,
        APPROVED,
        SCHEDULED,
        RUNNING,
        PAUSED,
        COMPLETED,
        REJECTED,
        CANCELLED,
    )


class CampaignChannel:
    PAYPAL_APP = "paypal_app"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    EMAIL = "email"
    IN_STORE = "in_store"


class OfferType:
    COMBO = "COMBO"
    PERCENT_DISCOUNT = "PERCENT_DISCOUNT"
    FLAT_DISCOUNT = "FLAT_DISCOUNT"
    CASHBACK = "CASHBACK"
    FREE_ITEM = "FREE_ITEM"
    NONE = "NONE"


class CampaignSurface:
    """Where the campaign's budget actually gets spent - the core distinction the
    Growth Allocation Engine reasons over (`services/growth/allocation.py`).

    BUSINESS: reaches the merchant's own customers, on the merchant's dime -
              WhatsApp, QR, checkout, loyalty.
    PAYPAL:    reaches customers through a Paypal-side surface - cashback, offers,
              promotional placement - funded from a Paypal-facing budget.
    HYBRID:   both, split across `business_budget` and `paypal_budget`.
    """

    BUSINESS = "BUSINESS"
    PAYPAL = "PAYPAL"
    HYBRID = "HYBRID"

    ALL = (BUSINESS, PAYPAL, HYBRID)


class CampaignObjective:
    """What the campaign is *for*. Free-text `objective` still holds the merchant-
    readable sentence; this is the controlled vocabulary the allocation engine and
    the UI's filters key off."""

    RETENTION = "RETENTION"
    REACTIVATION = "REACTIVATION"
    ACQUISITION = "ACQUISITION"
    CROSS_SELL = "CROSS_SELL"
    INVENTORY_CLEARANCE = "INVENTORY_CLEARANCE"
    CAPACITY_UTILIZATION = "CAPACITY_UTILIZATION"
    REVENUE_RECOVERY = "REVENUE_RECOVERY"
    PROFIT_OPTIMIZATION = "PROFIT_OPTIMIZATION"

    ALL = (
        RETENTION,
        REACTIVATION,
        ACQUISITION,
        CROSS_SELL,
        INVENTORY_CLEARANCE,
        CAPACITY_UTILIZATION,
        REVENUE_RECOVERY,
        PROFIT_OPTIMIZATION,
    )


class PaypalSurfaceType:
    """Which Paypal-side placement a PAYPAL/HYBRID campaign uses. Free text kept
    short deliberately - this is a label on a budget line, not an ad platform
    integration (none exists yet; see `services/growth/allocation.py`)."""

    OFFER = "OFFER"
    CASHBACK = "CASHBACK"
    ADS = "ADS"
    PROMOTIONAL = "PROMOTIONAL"


class Campaign(BaseModel):
    __tablename__ = "campaigns"
    __table_args__ = (
        Index("ix_campaigns_merchant_status", "merchant_id", "status"),
        Index("ix_campaigns_merchant_start", "merchant_id", "start_date"),
        Index("ix_campaigns_merchant_surface", "merchant_id", "surface"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    objective: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default=CampaignStatus.DRAFT, nullable=False)

    offer_type: Mapped[str] = mapped_column(String(32), default=OfferType.COMBO, nullable=False)
    offer_value: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    offer_description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    channel: Mapped[str] = mapped_column(
        String(32), default=CampaignChannel.PAYPAL_APP, nullable=False
    )

    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)

    budget: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    estimated_cost: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    actual_cost: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    estimated_impact: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)

    experiment_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), index=True)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), index=True)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(GUID())

    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    rejected_reason: Mapped[str | None] = mapped_column(Text)
    launched_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID())

    #: True until a messaging provider is connected. Never claims real delivery.
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    tags: Mapped[list[str]] = mapped_column(StringArray, default=list, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # ---------------------------------------------------------------- dual-market
    # Added for "Dual-Market Growth Intelligence" - backwards compatible: every
    # existing campaign row defaults to `surface=BUSINESS` (accurate; they were all
    # merchant-funded) with the rest at zero/blank, so nothing pre-existing changes.
    surface: Mapped[str] = mapped_column(
        String(16), default=CampaignSurface.BUSINESS, nullable=False
    )
    objective_type: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    business_budget: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    paypal_budget: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    paypal_surface: Mapped[str] = mapped_column(String(24), default="", nullable=False)
    #: Set from the Growth Allocation Engine at creation time; compared against
    #: `actual_incremental_revenue` (filled in once the linked experiment is
    #: measured) to show whether the mission delivered what it predicted.
    expected_incremental_revenue: Mapped[float | None] = mapped_column(Numeric(14, 2))
    actual_incremental_revenue: Mapped[float | None] = mapped_column(Numeric(14, 2))
    incremental_roi: Mapped[float | None] = mapped_column(Numeric(10, 4))
    #: PENDING | MEASURING | MEASURED - mirrors the linked experiment's state so the
    #: campaign card can show it without an extra join.
    measurement_status: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    #: Which agent proposed this campaign (e.g. "growth_scientist"), blank for a
    #: merchant-authored one.
    created_by_agent: Mapped[str] = mapped_column(String(48), default="", nullable=False)

    audiences: Mapped[list[CampaignAudience]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan", lazy="selectin"
    )
    actions: Mapped[list[CampaignAction]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )


class AudienceRole:
    TEST = "TEST"
    CONTROL = "CONTROL"
    FULL = "FULL"


class CampaignAudience(BaseModel):
    """A materialised customer segment attached to a campaign."""

    __tablename__ = "campaign_audiences"
    __table_args__ = (Index("ix_campaign_audiences_campaign_role", "campaign_id", "role"),)

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(16), default=AudienceRole.FULL, nullable=False)
    #: The filter that produced the member list (daypart, segment, recency, ...).
    definition: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    customer_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    campaign: Mapped[Campaign] = relationship(back_populates="audiences")


class CampaignActionType:
    CREATED = "CREATED"
    AUDIENCE_BUILT = "AUDIENCE_BUILT"
    SUBMITTED_FOR_APPROVAL = "SUBMITTED_FOR_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SCHEDULED = "SCHEDULED"
    LAUNCHED = "LAUNCHED"
    MESSAGE_SIMULATED = "MESSAGE_SIMULATED"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"


class CampaignAction(BaseModel):
    """An append-only log of everything done to a campaign, by a human or an agent."""

    __tablename__ = "campaign_actions"
    __table_args__ = (Index("ix_campaign_actions_campaign_created", "campaign_id", "created_at"),)

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action_type: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    actor_type: Mapped[str] = mapped_column(String(16), default="AGENT", nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    actor_label: Mapped[str] = mapped_column(String(96), default="", nullable=False)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    campaign: Mapped[Campaign] = relationship(back_populates="actions")
