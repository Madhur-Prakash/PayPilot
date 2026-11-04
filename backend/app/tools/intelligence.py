"""Review, competitor, external-signal and inventory tools."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.core.permissions import Permission
from app.services.analytics.service import AnalyticsService
from app.services.competitors.service import CompetitorService
from app.services.external.signals import SignalService
from app.services.inventory.service import InventoryService
from app.services.reviews.service import ReviewService
from app.tools.base import ToolContext, registry


class WindowArgs(BaseModel):
    days: int = Field(default=30, ge=7, le=180, description="Look-back window in days.")


class EmptyArgs(BaseModel):
    pass


class ReviewSearchArgs(BaseModel):
    query: str = Field(min_length=2, max_length=300, description="What to look for in reviews.")
    limit: int = Field(default=6, ge=1, le=20)
    topic: str | None = Field(default=None, description="Optional topic filter.")


# --------------------------------------------------------------------------- #
# Reviews
# --------------------------------------------------------------------------- #
@registry.register(
    "get_review_summary",
    description=(
        "Review intelligence for the window: sentiment split, topic distribution, "
        "emerging complaints (normalised per 100 orders so a shrinking segment cannot "
        "hide a worsening one), positive themes and negative share by trading slot."
    ),
    args_model=WindowArgs,
    permission=Permission.REVIEWS_READ,
)
async def get_review_summary(ctx: ToolContext, args: WindowArgs) -> tuple[dict[str, Any], str]:
    service = ReviewService(ctx.session, ctx.merchant_id)
    analytics = AnalyticsService(ctx.session, ctx.merchant_id)
    period = await analytics.resolve_period(days=args.days)
    data = await service.summary_for_agent(period)

    emerging = data.get("emerging_complaints") or []
    if emerging:
        top = emerging[0]
        summary = (
            f"Average rating {data['avg_rating']:.2f} ({data['avg_rating_change']:+.2f}). "
            f"Emerging complaint: {top['label']} at {top['negative_reviews']} negative reviews, "
            f"rate {top['rate_change_pct']:+.0f}%."
        )
    else:
        summary = (
            f"Average rating {data['avg_rating']:.2f} "
            f"({data['avg_rating_change']:+.2f}). No emerging complaints."
        )
    return data, summary


@registry.register(
    "search_reviews",
    description=(
        "Semantic search across the review corpus using vector similarity. Use it to "
        "find the actual customer wording behind a topic, as quotable evidence."
    ),
    args_model=ReviewSearchArgs,
    permission=Permission.REVIEWS_READ,
)
async def search_reviews(ctx: ToolContext, args: ReviewSearchArgs) -> tuple[dict[str, Any], str]:
    service = ReviewService(ctx.session, ctx.merchant_id)
    hits = await service.search(args.query, limit=args.limit, topic=args.topic)
    rows = [
        {
            "rating": hit.review.rating,
            "topic": hit.review.primary_topic,
            "sentiment": hit.review.sentiment,
            "daypart": hit.review.daypart,
            "date": str(hit.review.review_date),
            "text": hit.review.body,
            "similarity": hit.similarity,
        }
        for hit in hits
    ]
    return (
        {"query": args.query, "results": rows, "count": len(rows)},
        f"{len(rows)} reviews matched '{args.query}'.",
    )


# --------------------------------------------------------------------------- #
# Competitors
# --------------------------------------------------------------------------- #
@registry.register(
    "get_competitor_summary",
    description=(
        "Competitor comparison across speed, service, quality, taste, price, packaging "
        "and ambience. Merchant scores are computed from its own reviews; competitor "
        "scores are seeded benchmark data, not scraped from any platform."
    ),
    args_model=WindowArgs,
    permission=Permission.COMPETITORS_READ,
)
async def get_competitor_summary(ctx: ToolContext, args: WindowArgs) -> tuple[dict[str, Any], str]:
    service = CompetitorService(ctx.session, ctx.merchant_id)
    data = await service.summary_for_agent(
        merchant_name=ctx.merchant_name or "This merchant", days=max(args.days, 60)
    )
    gap = data.get("biggest_gap")
    summary = (
        f"Largest gap is {gap['dimension'].lower()}: {gap['merchant_score']:.0f} versus "
        f"{gap['competitor_avg']:.0f} for nearby competitors ({gap['gap']:+.1f})."
        if gap
        else "Not enough review coverage to compare against competitors."
    )
    return data, summary


# --------------------------------------------------------------------------- #
# External signals
# --------------------------------------------------------------------------- #
@registry.register(
    "get_external_signals",
    description=(
        "Market signals relevant to this merchant, each scored against the share of "
        "revenue it actually exposes. Not a general news feed."
    ),
    args_model=WindowArgs,
    permission=Permission.SIGNALS_READ,
)
async def get_external_signals(ctx: ToolContext, args: WindowArgs) -> tuple[dict[str, Any], str]:
    service = SignalService(ctx.session, ctx.merchant_id)
    data = await service.summary_for_agent(days=args.days)
    signals = data.get("signals") or []
    summary = (
        f"{data['high_relevance_count']} high-relevance signals. " f"Top: {signals[0]['title']}."
        if signals
        else "No relevant external signals."
    )
    return data, summary


# --------------------------------------------------------------------------- #
# Inventory
# --------------------------------------------------------------------------- #
@registry.register(
    "get_inventory_status",
    description=(
        "Stock health: days of cover, stockout risk and revenue at risk per product, "
        "with a recommended action. The system never purchases anything itself."
    ),
    args_model=EmptyArgs,
    permission=Permission.INVENTORY_READ,
)
async def get_inventory_status(ctx: ToolContext, args: EmptyArgs) -> tuple[dict[str, Any], str]:
    service = InventoryService(ctx.session, ctx.merchant_id)
    data = await service.summary_for_agent()
    critical = data.get("critical_items") or []
    summary = (
        f"{data['items_at_risk']} of {data['items_tracked']} items at risk, "
        f"${data['total_revenue_at_risk']:,.0f} revenue exposed. "
        f"Most urgent: {critical[0]['product']} ({critical[0]['days_of_cover']} days cover)."
        if critical
        else f"All {data['items_tracked']} tracked items have healthy cover."
    )
    return data, summary
