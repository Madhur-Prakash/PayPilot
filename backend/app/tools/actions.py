"""Action tools: segments, campaigns and experiments.

These are the tools that *change* things, so they carry the strictest guards:

  * a permission the caller must actually hold,
  * ``requires_approval`` on anything financially consequential,
  * execution refused at the service layer without a recorded human approval.

An agent can create and recommend. It cannot approve, and it cannot launch.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.core.exceptions import ApprovalRequiredError, NotFoundError
from app.core.permissions import Permission
from app.repositories.campaign import CampaignRepository
from app.repositories.customer import CustomerRepository
from app.repositories.experiment import ExperimentRepository
from app.repositories.opportunity import OpportunityRepository
from app.services.campaigns.service import CampaignService
from app.services.experiments.service import ExperimentService
from app.tools.base import ToolContext, registry


class SegmentArgs(BaseModel):
    name: str = Field(max_length=200, description="Human-readable segment name.")
    dayparts: list[str] = Field(
        default_factory=list, description="MORNING / AFTERNOON / EVENING / NIGHT."
    )
    segments: list[str] = Field(
        default_factory=list, description="NEW / REPEAT / LOYAL / AT_RISK / CHURNED."
    )
    min_orders: int | None = Field(default=None, ge=0)
    min_recency_days: int | None = Field(
        default=None, ge=0, description="Only customers who have not ordered for this many days."
    )
    max_recency_days: int | None = Field(default=None, ge=0)
    active_dayparts: list[str] = Field(
        default_factory=list,
        description="Customers who actually transacted in these slots (behavioural, not habitual).",
    )
    active_within_days: int | None = Field(
        default=None, ge=1, le=730, description="Limit the behavioural window to N days."
    )
    opted_in_only: bool = True
    limit: int = Field(default=2000, ge=1, le=20000)


class CreateCampaignArgs(BaseModel):
    name: str = Field(max_length=200)
    objective: str = Field(default="", max_length=1000)
    offer_description: str = Field(default="", max_length=500)
    offer_type: str = Field(default="COMBO")
    offer_value: float = Field(default=0, ge=0)
    message: str = Field(default="", max_length=500)
    channel: str = Field(default="paypal_app")
    estimated_impact: float = Field(default=0, ge=0)
    opportunity_id: str | None = None
    audience: SegmentArgs | None = None


class CreateExperimentArgs(BaseModel):
    name: str = Field(max_length=200)
    hypothesis: str = Field(min_length=10, max_length=1000)
    success_metric: str = Field(default="conversion_rate")
    success_threshold_pct: float = Field(default=10.0, ge=0, le=500)
    duration_days: int = Field(default=14, ge=1, le=120)
    control_split_pct: float = Field(default=50.0, gt=0, lt=100)
    test_offer_description: str = Field(default="", max_length=500)
    unit_cost: float = Field(default=0, ge=0, description="Cost per served offer, in rupees.")
    opportunity_id: str | None = None
    campaign_id: str | None = None
    audience: SegmentArgs | None = None


class ExperimentRefArgs(BaseModel):
    experiment_id: str = Field(description="UUID of the experiment.")


class EmptyArgs(BaseModel):
    pass


def _as_uuid(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        return None


# --------------------------------------------------------------------------- #
@registry.register(
    "create_customer_segment",
    description=(
        "Materialise a customer segment from a filter and report its size and value. "
        "Read-only: it previews who would be targeted without creating a campaign."
    ),
    args_model=SegmentArgs,
    permission=Permission.CUSTOMERS_READ,
)
async def create_customer_segment(
    ctx: ToolContext, args: SegmentArgs
) -> tuple[dict[str, Any], str]:
    repo = CustomerRepository(ctx.session, ctx.merchant_id)
    filters = args.model_dump(exclude={"name"})
    customers = await repo.resolve_segment(**filters)
    stats = await repo.segment_stats([c.id for c in customers])
    return (
        {
            "name": args.name,
            "definition": args.model_dump(),
            "size": stats["size"],
            "total_spend": stats["total_spend"],
            "avg_order_value": stats["avg_order_value"],
            "avg_orders": stats["avg_orders"],
            "sample": [
                {"name": c.name, "segment": c.segment, "orders": c.total_orders}
                for c in customers[:5]
            ],
        },
        (
            f"Segment '{args.name}' matches {stats['size']} customers with an average order "
            f"value of Rs {stats['avg_order_value']:,.0f}."
        ),
    )


@registry.register(
    "create_campaign",
    description=(
        "Create a campaign and build its audience. The campaign is created in "
        "PENDING_APPROVAL and is never delivered until a permitted user approves it."
    ),
    args_model=CreateCampaignArgs,
    permission=Permission.CAMPAIGN_CREATE,
)
async def create_campaign(ctx: ToolContext, args: CreateCampaignArgs) -> tuple[dict[str, Any], str]:
    service = CampaignService(ctx.session, ctx.merchant_id)
    campaign = await service.create(
        name=args.name,
        objective=args.objective,
        offer_type=args.offer_type,
        offer_value=args.offer_value,
        offer_description=args.offer_description,
        message=args.message,
        channel=args.channel,
        estimated_impact=args.estimated_impact,
        opportunity_id=_as_uuid(args.opportunity_id),
        audience=args.audience.model_dump() if args.audience else None,
        created_by_id=ctx.user_id,
        actor_label="Action Agent",
        agent_run_id=ctx.run.id if ctx.run else None,
    )
    audiences = await CampaignRepository(ctx.session, ctx.merchant_id).get_audience(
        campaign.id, "FULL"
    )
    size = audiences.size if audiences else 0
    return (
        {
            "campaign_id": str(campaign.id),
            "name": campaign.name,
            "status": campaign.status,
            "audience_size": size,
            "estimated_cost": float(campaign.estimated_cost or 0),
            "requires_approval": campaign.requires_approval,
            "is_simulated": campaign.is_simulated,
        },
        (
            f"Campaign '{campaign.name}' created for {size} customers. It is awaiting merchant "
            "approval and nothing has been sent."
        ),
    )


@registry.register(
    "create_experiment",
    description=(
        "Create a controlled experiment with deterministic control and test groups. "
        "Created in PENDING_APPROVAL: it does not start until a permitted user approves it."
    ),
    args_model=CreateExperimentArgs,
    permission=Permission.EXPERIMENT_CREATE,
)
async def create_experiment(
    ctx: ToolContext, args: CreateExperimentArgs
) -> tuple[dict[str, Any], str]:
    service = ExperimentService(ctx.session, ctx.merchant_id)
    experiment = await service.create(
        name=args.name,
        hypothesis=args.hypothesis,
        success_metric=args.success_metric,
        success_threshold_pct=args.success_threshold_pct,
        duration_days=args.duration_days,
        control_split_pct=args.control_split_pct,
        test_offer_description=args.test_offer_description,
        unit_cost=args.unit_cost,
        opportunity_id=_as_uuid(args.opportunity_id),
        campaign_id=_as_uuid(args.campaign_id),
        audience=args.audience.model_dump(exclude={"name"}) if args.audience else None,
        created_by_id=ctx.user_id,
        agent_run_id=ctx.run.id if ctx.run else None,
    )
    variants = await ExperimentRepository(ctx.session, ctx.merchant_id).get_variants(experiment.id)
    sizes = {v.role: v.audience_size for v in variants}
    return (
        {
            "experiment_id": str(experiment.id),
            "name": experiment.name,
            "status": experiment.status,
            "hypothesis": experiment.hypothesis,
            "control_size": sizes.get("CONTROL", 0),
            "test_size": sizes.get("TEST", 0),
            "duration_days": experiment.duration_days,
            "requires_approval": experiment.requires_approval,
        },
        (
            f"Experiment '{experiment.name}' created with {sizes.get('CONTROL', 0)} control and "
            f"{sizes.get('TEST', 0)} test customers. Awaiting merchant approval."
        ),
    )


@registry.register(
    "get_experiment_results",
    description=(
        "Measured results for an experiment: conversion by arm, lift, incremental "
        "revenue and profit, ROI, significance and the SCALE/STOP/CONTINUE/WATCH decision. "
        "Every figure is recomputed from the transaction ledger."
    ),
    args_model=ExperimentRefArgs,
    permission=Permission.EXPERIMENT_READ,
)
async def get_experiment_results(
    ctx: ToolContext, args: ExperimentRefArgs
) -> tuple[dict[str, Any], str]:
    experiment_id = _as_uuid(args.experiment_id)
    if experiment_id is None:
        raise NotFoundError("Invalid experiment id.")
    service = ExperimentService(ctx.session, ctx.merchant_id)
    summary = await service.summary_for(experiment_id)
    if summary is None:
        summary = await service.measure(experiment_id, user_id=ctx.user_id)
    data = summary.model_dump(mode="json")
    return (
        data,
        (
            f"{summary.name}: control {summary.control_conversion_rate:.1f}% vs test "
            f"{summary.test_conversion_rate:.1f}% ({summary.conversion_lift_pct:+.1f}% lift), "
            f"incremental revenue Rs {summary.incremental_revenue:,.0f}, "
            f"ROI {summary.roi:.1f}x. Decision: {summary.decision}."
        ),
    )


@registry.register(
    "list_active_experiments",
    description="Experiments currently running or awaiting measurement, with their status.",
    args_model=EmptyArgs,
    permission=Permission.EXPERIMENT_READ,
)
async def list_active_experiments(ctx: ToolContext, args: EmptyArgs) -> tuple[dict[str, Any], str]:
    repo = ExperimentRepository(ctx.session, ctx.merchant_id)
    experiments = await repo.list_recent(limit=10)
    rows = [
        {
            "experiment_id": str(e.id),
            "name": e.name,
            "status": e.status,
            "decision": e.decision,
            "start_date": str(e.start_date) if e.start_date else None,
            "end_date": str(e.end_date) if e.end_date else None,
        }
        for e in experiments
    ]
    running = [r for r in rows if r["status"] in ("RUNNING", "MEASURING")]
    return (
        {"experiments": rows, "running_count": len(running)},
        (
            f"{len(rows)} experiments, {len(running)} currently active."
            if rows
            else "No experiments yet."
        ),
    )


@registry.register(
    "execute_campaign",
    description=(
        "Launch an already-approved campaign. Fails unless a permitted user has "
        "recorded an approval - an agent cannot approve its own recommendation."
    ),
    args_model=EmptyArgs,
    permission=Permission.CAMPAIGN_EXECUTE,
    requires_approval=True,
)
async def execute_campaign(ctx: ToolContext, args: EmptyArgs) -> tuple[dict[str, Any], str]:
    raise ApprovalRequiredError(
        "Campaign execution is only available through the merchant approval endpoint, "
        "so that a human decision is always recorded before anything runs."
    )


@registry.register(
    "get_top_opportunity",
    description=(
        "The merchant's highest-priority open opportunity with its estimated monthly "
        "value, confidence, evidence and recommended action."
    ),
    args_model=EmptyArgs,
    permission=Permission.GROWTH_READ,
)
async def get_top_opportunity(ctx: ToolContext, args: EmptyArgs) -> tuple[dict[str, Any], str]:
    repo = OpportunityRepository(ctx.session, ctx.merchant_id)
    opportunity = await repo.top()
    if opportunity is None:
        return {"opportunity": None}, "No open opportunities have been detected yet."
    return (
        {
            "opportunity": {
                "id": str(opportunity.id),
                "key": opportunity.key,
                "title": opportunity.title,
                "summary": opportunity.summary,
                "estimated_value_monthly": float(opportunity.estimated_value_monthly),
                "confidence": float(opportunity.confidence),
                "impact": opportunity.impact,
                "status": opportunity.status,
                "hypothesis": opportunity.hypothesis,
                "recommended_action": opportunity.recommended_action,
                "evidence": opportunity.evidence,
            }
        },
        (
            f"{opportunity.title}: Rs {float(opportunity.estimated_value_monthly):,.0f}/month at "
            f"{float(opportunity.confidence):.0%} confidence."
        ),
    )


@registry.register(
    "get_growth_allocation",
    description=(
        "Where the growth budget has actually gone - business-side versus Paypal-side - and "
        "whether one surface has a measured incremental-ROI edge (a 'growth arbitrage') worth "
        "shifting budget toward. Answers 'where should my next rupee go'."
    ),
    args_model=EmptyArgs,
    permission=Permission.GROWTH_READ,
)
async def get_growth_allocation(ctx: ToolContext, args: EmptyArgs) -> tuple[dict[str, Any], str]:
    from app.services.growth.allocation import GrowthAllocationEngine

    engine = GrowthAllocationEngine(ctx.session, ctx.merchant_id)
    snapshot = await engine.allocation_snapshot()
    arbitrage = await engine.growth_arbitrage()

    data: dict[str, Any] = {"allocation": snapshot}
    if not snapshot["has_data"]:
        return data, "No campaigns have run yet, so there's no growth budget split to report."

    summary = (
        f"So far {snapshot['business_pct']:.0f}% of growth spend has gone to business-side "
        f"campaigns and {snapshot['paypal_pct']:.0f}% to Paypal-side, for Rs "
        f"{snapshot['total_incremental_revenue']:,.0f} in measured incremental revenue."
    )
    if arbitrage:
        data["arbitrage"] = {
            "better_surface": arbitrage.better_surface,
            "worse_surface": arbitrage.worse_surface,
            "better_roi": arbitrage.better_roi,
            "worse_roi": arbitrage.worse_roi,
            "confidence": arbitrage.confidence,
            "recommended_shift_pct": arbitrage.recommended_shift_pct,
        }
        summary += (
            f" {arbitrage.better_surface.title()} is outperforming {arbitrage.worse_surface.title()} "
            f"({arbitrage.better_roi:.1f}x vs {arbitrage.worse_roi:.1f}x ROI, {arbitrage.confidence} "
            f"confidence from {arbitrage.evidence_count} measured campaigns) - consider shifting "
            f"the next mission toward {arbitrage.recommended_shift_pct:.0f}% "
            f"{arbitrage.better_surface.lower()}."
        )
    else:
        summary += " Not enough measured campaigns on both surfaces yet to say which performs better."
    return data, summary
