"""Opportunities, reviews, competitors, signals and inventory endpoints."""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import Field

from app.api.deps import DbSession, Principal, require_permission
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.core.permissions import Permission
from app.db.models.growth import OpportunityKind, OpportunityStatus
from app.repositories.opportunity import OpportunityRepository, SignalRepository
from app.repositories.review import CompetitorRepository, ReviewRepository
from app.schemas.analytics import InventoryActionRequest, InventoryItemOut, InventoryOverview
from app.schemas.common import ActionAck, APIResponse, PageMeta, Paginated, SchemaBase
from app.schemas.growth import (
    AllocationSnapshotOut,
    ArbitrageFindingOut,
    CompetitorIntelligence,
    DetectOpportunitiesRequest,
    DontDiscountOut,
    GrowthMissionOut,
    InterventionOptionOut,
    OpportunityOut,
    OpportunityRadar,
    OpportunityStatusUpdate,
    ReviewIntelligence,
    ReviewOut,
    ReviewSearchHit,
    ReviewSearchRequest,
    SignalFeed,
)
from app.services.competitors.service import CompetitorService
from app.services.external.signals import SignalService
from app.services.growth.allocation import GrowthAllocationEngine
from app.services.growth.detector import OpportunityDetector
from app.services.inventory.service import InventoryService
from app.services.reviews.service import ReviewService

log = get_logger(__name__)
router = APIRouter(tags=["growth"])

class ManualOpportunityRequest(SchemaBase):
    """An opportunity a person spotted, not the detector."""

    title: str = Field(min_length=4, max_length=200)
    summary: str = Field(default="", max_length=2000)
    kind: str = Field(default=OpportunityKind.RETENTION, max_length=32)
    estimated_value_monthly: float = Field(default=0.0, ge=0, le=100_000_000)
    confidence: float = Field(default=0.5, ge=0, le=1)
    effort: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    impact: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    recommended_action: str = Field(default="", max_length=2000)



DaysQuery = Annotated[int, Query(ge=7, le=180, description="Look-back window in days.")]


# --------------------------------------------------------------------------- #
# Opportunities
# --------------------------------------------------------------------------- #
@router.get(
    "/opportunities",
    summary="Opportunity Radar",
    description="Detected growth opportunities ranked by expected value, discounted by effort.",
)
async def list_opportunities(
    session: DbSession,
    status: Annotated[str | None, Query(description="Filter by status.")] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    principal: Principal = Depends(require_permission(Permission.GROWTH_READ)),
) -> APIResponse[OpportunityRadar]:
    repo = OpportunityRepository(session, principal.merchant_id)
    rows = await repo.list_all_ranked(limit=limit, status=status)
    counts = await repo.count_by_status()
    open_count = sum(counts.get(s, 0) for s in OpportunityStatus.OPEN)
    return APIResponse(
        data=OpportunityRadar(
            opportunities=[OpportunityOut.model_validate(row) for row in rows],
            total_detected=sum(counts.values()),
            total_estimated_value_monthly=await repo.total_open_value(),
            open_count=open_count,
            generated_at=datetime.now(tz=UTC),
        ),
        meta={"status_counts": counts},
    )


@router.post(
    "/opportunities/detect",
    summary="Run opportunity detection",
    description=(
        "Runs the deterministic detector and upserts the results. Idempotent: "
        "re-running refreshes existing opportunities rather than duplicating them, "
        "and never rolls back an opportunity a human has already acted on."
    ),
)
async def detect_opportunities(
    payload: DetectOpportunitiesRequest,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.GROWTH_READ)),
) -> APIResponse[OpportunityRadar]:
    detector = OpportunityDetector(session, principal.merchant_id)
    stored = await detector.detect_and_store(days=payload.days)
    repo = detector.repo
    counts = await repo.count_by_status()
    return APIResponse(
        data=OpportunityRadar(
            opportunities=[OpportunityOut.model_validate(row) for row in stored],
            total_detected=len(stored),
            total_estimated_value_monthly=await repo.total_open_value(),
            open_count=sum(counts.get(s, 0) for s in OpportunityStatus.OPEN),
            generated_at=datetime.now(tz=UTC),
        )
    )


@router.get("/opportunities/{opportunity_id}", summary="Opportunity detail")
async def get_opportunity(
    opportunity_id: uuid.UUID,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.GROWTH_READ)),
) -> APIResponse[OpportunityOut]:
    row = await OpportunityRepository(session, principal.merchant_id).get(opportunity_id)
    if row is None:
        raise NotFoundError("Opportunity not found.")
    return APIResponse(data=OpportunityOut.model_validate(row))


@router.patch("/opportunities/{opportunity_id}/status", summary="Update opportunity status")
async def update_opportunity_status(
    opportunity_id: uuid.UUID,
    payload: OpportunityStatusUpdate,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.GROWTH_RECOMMEND)),
) -> APIResponse[OpportunityOut]:
    repo = OpportunityRepository(session, principal.merchant_id)
    row = await repo.get(opportunity_id)
    if row is None:
        raise NotFoundError("Opportunity not found.")
    await repo.set_status(row, payload.status)
    return APIResponse(data=OpportunityOut.model_validate(row))


# --------------------------------------------------------------------------- #
# Dual-market growth intelligence (Growth Allocation Engine)
# --------------------------------------------------------------------------- #
@router.get(
    "/opportunities/{opportunity_id}/missions",
    summary="Generate a Growth Mission for an opportunity",
    description=(
        "Compares a business-side, a PayPal-side and a hybrid intervention for this "
        "opportunity's target segment - audience size, offer, budget and expected "
        "customers, each grounded in this merchant's own transaction and "
        "acquisition-channel history. Read-only: nothing is created until the "
        "merchant picks an option and calls POST /campaigns."
    ),
)
async def opportunity_missions(
    opportunity_id: uuid.UUID,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.GROWTH_READ)),
) -> APIResponse[GrowthMissionOut]:
    opportunity = await OpportunityRepository(session, principal.merchant_id).get(opportunity_id)
    if opportunity is None:
        raise NotFoundError("Opportunity not found.")

    engine = GrowthAllocationEngine(session, principal.merchant_id)
    mission = await engine.generate_mission(
        title=opportunity.title,
        target_segment=opportunity.target_segment or {},
        opportunity_id=opportunity.id,
    )
    return APIResponse(
        data=GrowthMissionOut(
            opportunity_id=mission.opportunity_id,
            title=mission.title,
            business_option=InterventionOptionOut(**asdict(mission.business_option)),
            paypal_option=InterventionOptionOut(**asdict(mission.paypal_option)),
            hybrid_option=InterventionOptionOut(**asdict(mission.hybrid_option)),
            recommended_surface=mission.recommended_surface,
            recommendation_reason=mission.recommendation_reason,
            allocation_basis=mission.allocation_basis,
            business_pct=mission.business_pct,
            paypal_pct=mission.paypal_pct,
            dont_discount=(
                DontDiscountOut(**asdict(mission.dont_discount)) if mission.dont_discount else None
            ),
            arbitrage=(
                ArbitrageFindingOut(**asdict(mission.arbitrage)) if mission.arbitrage else None
            ),
        )
    )


@router.get(
    "/growth/arbitrage",
    summary="Growth arbitrage",
    description=(
        "Compares measured incremental ROI between the business and PayPal surfaces "
        "across this merchant's past campaigns. Returns null until at least one "
        "campaign of each surface has actually been measured - never a guessed ratio."
    ),
)
async def growth_arbitrage(
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.GROWTH_READ)),
) -> APIResponse[ArbitrageFindingOut | None]:
    engine = GrowthAllocationEngine(session, principal.merchant_id)
    finding = await engine.growth_arbitrage()
    return APIResponse(data=ArbitrageFindingOut(**asdict(finding)) if finding else None)


@router.get(
    "/growth/allocation",
    summary="Growth budget allocation",
    description="Where the growth budget has actually gone, by surface - for the Command Center.",
)
async def growth_allocation(
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.GROWTH_READ)),
) -> APIResponse[AllocationSnapshotOut]:
    engine = GrowthAllocationEngine(session, principal.merchant_id)
    snapshot = await engine.allocation_snapshot()
    return APIResponse(data=AllocationSnapshotOut(**snapshot))


# --------------------------------------------------------------------------- #
# Reviews
# --------------------------------------------------------------------------- #
@router.get(
    "/reviews/intelligence",
    summary="Review intelligence",
    description=(
        "Sentiment, topic distribution, emerging complaints and positive themes. "
        "Complaint trends are normalised per 100 orders so a shrinking segment "
        "cannot mask a worsening experience."
    ),
)
async def review_intelligence(
    session: DbSession,
    days: DaysQuery = 30,
    principal: Principal = Depends(require_permission(Permission.REVIEWS_READ)),
) -> APIResponse[ReviewIntelligence]:
    data = await ReviewService(session, principal.merchant_id).intelligence(days=days)
    return APIResponse(data=data, meta={"period_days": days})


@router.get(
    "/reviews",
    summary="List reviews",
    description=(
        "Paginated review browser. Every filter is applied identically to the rows "
        "and to the total, so the page count always matches what is listed."
    ),
)
async def list_reviews(
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    topic: Annotated[str | None, Query()] = None,
    sentiment: Annotated[str | None, Query()] = None,
    daypart: Annotated[str | None, Query()] = None,
    rating: Annotated[int | None, Query(ge=1, le=5)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    principal: Principal = Depends(require_permission(Permission.REVIEWS_READ)),
) -> APIResponse[Paginated[ReviewOut]]:
    repo = ReviewRepository(session, principal.merchant_id)
    filters = {
        "topic": topic,
        "sentiment": sentiment,
        "daypart": daypart,
        "rating": rating,
        "q": q,
    }
    rows = await repo.list_recent(
        limit=page_size,
        offset=(page - 1) * page_size,
        **filters,
    )
    total = await repo.count_filtered(**filters)
    facets = await repo.rating_breakdown(topic=topic, sentiment=sentiment, daypart=daypart, q=q)
    return APIResponse(
        data=Paginated(
            items=[ReviewOut.model_validate(r) for r in rows],
            pagination=PageMeta.build(page=page, page_size=page_size, total=total),
        ),
        meta={"rating_counts": facets},
    )


@router.post(
    "/reviews/search",
    summary="Semantic review search",
    description="Vector similarity search over review embeddings (pgvector).",
)
async def search_reviews(
    payload: ReviewSearchRequest,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.REVIEWS_READ)),
) -> APIResponse[list[ReviewSearchHit]]:
    hits = await ReviewService(session, principal.merchant_id).search(
        payload.query, limit=payload.limit, topic=payload.topic, sentiment=payload.sentiment
    )
    return APIResponse(data=hits, meta={"query": payload.query, "count": len(hits)})


# --------------------------------------------------------------------------- #
# Competitors
# --------------------------------------------------------------------------- #
@router.get(
    "/competitors/intelligence",
    summary="Competitor intelligence",
    description=(
        "Perception comparison across speed, service, quality, taste, price, packaging "
        "and ambience. Competitor data is representative baseline data - no platform is scraped."
    ),
)
async def competitor_intelligence(
    session: DbSession,
    days: DaysQuery = 90,
    principal: Principal = Depends(require_permission(Permission.COMPETITORS_READ)),
) -> APIResponse[CompetitorIntelligence]:
    data = await CompetitorService(session, principal.merchant_id).intelligence(
        merchant_name=principal.merchant.name, days=days
    )
    return APIResponse(data=data, meta={"period_days": days})


@router.get("/competitors", summary="List competitors")
async def list_competitors(
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.COMPETITORS_READ)),
) -> APIResponse[list[dict]]:
    rows = await CompetitorRepository(session, principal.merchant_id).list_active()
    return APIResponse(
        data=[
            {
                "id": str(c.id),
                "name": c.name,
                "distance_km": float(c.distance_km),
                "price_tier": c.price_tier,
                "avg_rating": float(c.avg_rating),
                "review_count": c.review_count,
                "perception_scores": c.perception_scores,
                "strengths": c.strengths,
                "weaknesses": c.weaknesses,
                "data_source": c.data_source,
            }
            for c in rows
        ]
    )


# --------------------------------------------------------------------------- #
# External signals
# --------------------------------------------------------------------------- #
@router.get(
    "/signals",
    summary="Contextual market signals",
    description=(
        "External signals scored against this merchant's actual revenue exposure. "
        "Deliberately not a general news feed."
    ),
)
async def list_signals(
    session: DbSession,
    days: DaysQuery = 30,
    principal: Principal = Depends(require_permission(Permission.SIGNALS_READ)),
) -> APIResponse[SignalFeed]:
    feed = await SignalService(session, principal.merchant_id).feed(days=days)
    return APIResponse(data=feed)


@router.post("/signals/{signal_id}/dismiss", summary="Dismiss a signal")
async def dismiss_signal(
    signal_id: uuid.UUID,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.SIGNALS_READ)),
) -> APIResponse[ActionAck]:
    repo = SignalRepository(session, principal.merchant_id)
    signal = await repo.get(signal_id)
    if signal is None:
        raise NotFoundError("Signal not found.")
    await repo.dismiss(signal)
    return APIResponse(data=ActionAck(message="Signal dismissed."))


# --------------------------------------------------------------------------- #
# Inventory
# --------------------------------------------------------------------------- #
@router.get(
    "/inventory",
    summary="Inventory intelligence",
    description=(
        "Stock levels with days of cover, stockout risk, revenue at risk and a "
        "recommended action. The system never purchases anything itself."
    ),
)
async def inventory_overview(
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.INVENTORY_READ)),
) -> APIResponse[InventoryOverview]:
    data = await InventoryService(session, principal.merchant_id).overview()
    return APIResponse(data=data)


@router.post(
    "/inventory/{item_id}/action",
    summary="Record an inventory decision",
    description=(
        "Records a decision the merchant took (acknowledging a reorder, logging a "
        "restock, correcting a count). No purchase order is ever placed by the system."
    ),
)
async def inventory_action(
    item_id: uuid.UUID,
    payload: InventoryActionRequest,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.INVENTORY_WRITE)),
) -> APIResponse[InventoryItemOut]:
    item = await InventoryService(session, principal.merchant_id).record_action(
        item_id,
        action=payload.action,
        quantity=payload.quantity,
        note=payload.note,
        user_id=principal.user_id,
        actor_label=principal.label,
    )
    return APIResponse(data=InventoryItemOut.model_validate(item))


@router.post(
    "/opportunities",
    summary="Add an opportunity by hand",
    description=(
        "For something the detector cannot see - a lease ending, a competitor "
        "closing, a supplier deal. It behaves like any detected opportunity from "
        "here on: it can be approved, turned into a campaign and measured. The "
        "nightly detection pass upserts by key and never touches a manual one."
    ),
)
async def create_manual_opportunity(
    payload: ManualOpportunityRequest,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.GROWTH_RECOMMEND)),
) -> APIResponse[dict]:
    repo = OpportunityRepository(session, principal.merchant_id)

    # A "manual-" prefix keeps these in a namespace the detector never generates,
    # so a nightly pass can neither overwrite nor resurrect one.
    base = "manual-" + re.sub(r"[^a-z0-9]+", "-", payload.title.lower()).strip("-")[:70]
    key = base or "manual-opportunity"
    suffix = 2
    while await repo.get_by_key(key) is not None:
        key = f"{base}-{suffix}"
        suffix += 1

    effort_penalty = {"LOW": 1.0, "MEDIUM": 0.85, "HIGH": 0.65}[payload.effort]
    opportunity = await repo.create(
        key=key,
        title=payload.title.strip(),
        summary=payload.summary.strip(),
        kind=payload.kind,
        estimated_value_monthly=payload.estimated_value_monthly,
        confidence=payload.confidence,
        impact=payload.impact,
        effort=payload.effort,
        # Same formula the detector uses, so manual and detected rank together
        # rather than manual ones always floating to the top or sinking.
        priority_score=round(
            payload.estimated_value_monthly * payload.confidence * effort_penalty, 3
        ),
        status=OpportunityStatus.DETECTED,
        recommended_action=payload.recommended_action.strip(),
        evidence=[
            {
                "metric": "Added by",
                "value": principal.label or "a user",
                "source": "manual",
            }
        ],
        hypothesis="",
        reasoning="Added by hand; not derived from the transaction data.",
        graph_path=[],
    )
    await session.commit()

    log.info(
        "manual_opportunity_created",
        merchant_id=str(principal.merchant_id),
        key=key,
        value=payload.estimated_value_monthly,
    )
    return APIResponse(
        data={
            "id": str(opportunity.id),
            "key": opportunity.key,
            "title": opportunity.title,
            "status": opportunity.status,
        }
    )
