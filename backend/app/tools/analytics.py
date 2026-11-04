"""Analytics tools - the Growth Scientist's read surface.

Each returns already-computed figures. The model never sees a transaction row.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.core.permissions import Permission
from app.services.analytics.service import AnalyticsService
from app.services.growth.detector import OpportunityDetector
from app.services.growth.graph import GrowthGraphService
from app.tools.base import ToolContext, registry


class WindowArgs(BaseModel):
    days: int = Field(default=30, ge=7, le=180, description="Look-back window in days.")


class DaypartArgs(WindowArgs):
    daypart: str | None = Field(
        default=None,
        description="Optional slot filter: MORNING, AFTERNOON, EVENING or NIGHT.",
    )


def _money(value: float) -> str:
    return f"${value:,.0f}"


# --------------------------------------------------------------------------- #
@registry.register(
    "get_sales_summary",
    description=(
        "Headline business performance for a window: revenue, orders, average order "
        "value, repeat rate and margin, each with its change versus the previous "
        "equivalent period."
    ),
    args_model=WindowArgs,
    permission=Permission.DASHBOARD_READ,
)
async def get_sales_summary(ctx: ToolContext, args: WindowArgs) -> tuple[dict[str, Any], str]:
    service = AnalyticsService(ctx.session, ctx.merchant_id)
    period = await service.resolve_period(days=args.days)
    kpis, current, previous = await service.kpis(period)

    data = {
        "period": {"start": str(period.current.start), "end": str(period.current.end)},
        "previous_period": {"start": str(period.previous.start), "end": str(period.previous.end)},
        "metrics": {
            kpi.key: {
                "label": kpi.label,
                "value": kpi.value,
                "previous": kpi.previous_value,
                "change_pct": kpi.change_pct,
                "unit": kpi.unit,
            }
            for kpi in kpis
        },
        "summary": current.model_dump(),
        "previous_summary": previous.model_dump(),
    }
    revenue = next(k for k in kpis if k.key == "revenue")
    summary = (
        f"Revenue {_money(current.revenue)} ({revenue.change_pct:+.1f}%), "
        f"{current.orders:,} orders, AOV {_money(current.aov)}, "
        f"repeat rate {current.repeat_rate:.1f}%."
        if revenue.change_pct is not None
        else f"Revenue {_money(current.revenue)} across {current.orders:,} orders."
    )
    return data, summary


@registry.register(
    "get_revenue_trend",
    description="Daily revenue and order counts across the window, for trend inspection.",
    args_model=WindowArgs,
    permission=Permission.GROWTH_READ,
)
async def get_revenue_trend(ctx: ToolContext, args: WindowArgs) -> tuple[dict[str, Any], str]:
    service = AnalyticsService(ctx.session, ctx.merchant_id)
    period = await service.resolve_period(days=args.days)
    points = await service.transactions.daily_trend(period.current.start, period.current.end)
    values = [p["revenue"] for p in points]
    first_half = sum(values[: len(values) // 2])
    second_half = sum(values[len(values) // 2 :])
    direction = "declining" if second_half < first_half else "improving"
    return (
        {
            "points": [
                {"date": str(p["date"]), "revenue": p["revenue"], "orders": p["orders"]}
                for p in points
            ],
            "total_revenue": round(sum(values), 2),
            "first_half_revenue": round(first_half, 2),
            "second_half_revenue": round(second_half, 2),
        },
        (
            f"{len(points)} days of revenue totalling {_money(sum(values))}. "
            f"Second half of the window is {direction} versus the first half."
        ),
    )


@registry.register(
    "get_customer_segments",
    description=(
        "Customer performance broken down by trading slot (morning, afternoon, evening, "
        "night), including repeat-customer counts and their change. Use this to find "
        "which segment is moving differently from the rest of the business."
    ),
    args_model=WindowArgs,
    permission=Permission.CUSTOMERS_READ,
)
async def get_customer_segments(ctx: ToolContext, args: WindowArgs) -> tuple[dict[str, Any], str]:
    service = AnalyticsService(ctx.session, ctx.merchant_id)
    period = await service.resolve_period(days=args.days)
    dayparts = await service.daypart_breakdown(period)

    rows = [
        {
            "daypart": d.daypart,
            "label": d.label,
            "revenue": d.revenue,
            "revenue_change_pct": d.change_pct,
            "orders": d.orders,
            "aov": d.aov,
            "unique_customers": d.unique_customers,
            "repeat_customers": d.repeat_customers,
            "repeat_customers_change_pct": d.repeat_customers_change_pct,
            "revenue_share_pct": d.revenue_share_pct,
            "avg_service_minutes": d.avg_service_minutes,
            "service_minutes_change_pct": d.service_minutes_change_pct,
        }
        for d in dayparts
    ]
    worst = min(
        (r for r in rows if r["revenue_change_pct"] is not None),
        key=lambda r: r["revenue_change_pct"],
        default=None,
    )
    summary = (
        f"{worst['label']} is the weakest slot at {worst['revenue_change_pct']:+.1f}% revenue "
        f"with repeat customers {worst['repeat_customers_change_pct']:+.1f}%."
        if worst and worst["repeat_customers_change_pct"] is not None
        else "Segment breakdown by trading slot."
    )
    return {"segments": rows}, summary


@registry.register(
    "get_customer_metrics",
    description=(
        "Customer base health: total and active customers, new versus repeat, repeat "
        "rate, period-over-period retention, churn-risk count and average customer value."
    ),
    args_model=WindowArgs,
    permission=Permission.CUSTOMERS_READ,
)
async def get_customer_metrics(ctx: ToolContext, args: WindowArgs) -> tuple[dict[str, Any], str]:
    service = AnalyticsService(ctx.session, ctx.merchant_id)
    period = await service.resolve_period(days=args.days)
    metrics = await service.customer_metrics(period)
    data = metrics.model_dump(mode="json", exclude={"retention_curve", "by_daypart"})
    return (
        data,
        (
            f"{metrics.active_customers:,} active customers, {metrics.repeat_customers:,} repeat "
            f"({metrics.repeat_rate:.1f}%), retention {metrics.retention_rate:.1f}%, "
            f"{metrics.churn_risk_customers:,} at churn risk."
        ),
    )


@registry.register(
    "get_product_performance",
    description=(
        "Per-product revenue, units, margin and attach rate with period-over-period "
        "change. Identifies which products are growing and which are declining."
    ),
    args_model=WindowArgs,
    permission=Permission.PRODUCTS_READ,
)
async def get_product_performance(ctx: ToolContext, args: WindowArgs) -> tuple[dict[str, Any], str]:
    service = AnalyticsService(ctx.session, ctx.merchant_id)
    period = await service.resolve_period(days=args.days)
    products = await service.product_performance(period)
    rows = [
        {
            "name": p.name,
            "sku": p.sku,
            "category": p.category,
            "revenue": p.revenue,
            "change_pct": p.change_pct,
            "units_sold": p.units_sold,
            "margin_pct": p.margin_pct,
            "revenue_share_pct": p.revenue_share_pct,
            "attach_rate_pct": p.attach_rate_pct,
            "trend": p.trend,
        }
        for p in products
    ]
    declining = [r for r in rows if (r["change_pct"] or 0) < -10]
    growing = [r for r in rows if (r["change_pct"] or 0) > 10]
    return (
        {"products": rows, "declining": declining, "growing": growing},
        (
            f"{len(rows)} products. {len(growing)} growing, {len(declining)} declining. "
            f"Top seller: {rows[0]['name']} at {_money(rows[0]['revenue'])}."
            if rows
            else "No product sales in this window."
        ),
    )


@registry.register(
    "analyze_product_mix",
    description=(
        "Market-basket analysis: which product pairs are bought together more often "
        "than chance predicts, with support, confidence and lift. Use this to find "
        "bundle opportunities."
    ),
    args_model=WindowArgs,
    permission=Permission.PRODUCTS_READ,
)
async def analyze_product_mix(ctx: ToolContext, args: WindowArgs) -> tuple[dict[str, Any], str]:
    service = AnalyticsService(ctx.session, ctx.merchant_id)
    period = await service.resolve_period(days=args.days)
    pairs = await service.product_mix(period.current, limit=8)
    rows = [p.model_dump(mode="json") for p in pairs]
    best = pairs[0] if pairs else None
    return (
        {"pairs": rows},
        (
            f"Strongest pair: {best.product_a_name} + {best.product_b_name} at {best.lift:.2f}x "
            f"lift across {best.co_occurrences} orders."
            if best
            else "No product pairs met the minimum support threshold."
        ),
    )


@registry.register(
    "detect_anomalies",
    description=(
        "Metrics and segments whose movement is materially outside the normal range "
        "for this merchant, ranked by deviation."
    ),
    args_model=WindowArgs,
    permission=Permission.GROWTH_READ,
)
async def detect_anomalies(ctx: ToolContext, args: WindowArgs) -> tuple[dict[str, Any], str]:
    service = AnalyticsService(ctx.session, ctx.merchant_id)
    period = await service.resolve_period(days=args.days)
    anomalies = await service.detect_anomalies(period)
    rows = [a.model_dump(mode="json") for a in anomalies]
    return (
        {"anomalies": rows, "count": len(rows)},
        (
            f"{len(rows)} anomalies. Largest: {anomalies[0].label} at "
            f"{anomalies[0].deviation_pct:+.1f}%."
            if anomalies
            else "No material anomalies detected in this window."
        ),
    )


@registry.register(
    "get_growth_metrics",
    description=(
        "The complete computed fact sheet for the period: headline KPIs, per-slot "
        "breakdown, customer health and product movers. Prefer this single call over "
        "several narrower ones when starting an investigation."
    ),
    args_model=WindowArgs,
    permission=Permission.GROWTH_READ,
)
async def get_growth_metrics(ctx: ToolContext, args: WindowArgs) -> tuple[dict[str, Any], str]:
    service = AnalyticsService(ctx.session, ctx.merchant_id)
    period = await service.resolve_period(days=args.days)
    snapshot = await service.metrics_snapshot(period)
    headline = snapshot["headline"]
    return (
        snapshot,
        (
            f"Revenue {headline['revenue']['change_pct']:+.1f}%, "
            f"orders {headline['orders']['change_pct']:+.1f}%, "
            f"AOV {headline['aov']['change_pct']:+.1f}%, "
            f"repeat rate {headline['repeat_rate']['change_pct']:+.1f}%."
            if headline["revenue"]["change_pct"] is not None
            else "Computed metrics snapshot."
        ),
    )


@registry.register(
    "detect_growth_opportunities",
    description=(
        "Run the deterministic opportunity detector: returns quantified, evidence-backed "
        "growth opportunities with estimated monthly value and confidence."
    ),
    args_model=WindowArgs,
    permission=Permission.GROWTH_READ,
)
async def detect_growth_opportunities(
    ctx: ToolContext, args: WindowArgs
) -> tuple[dict[str, Any], str]:
    detector = OpportunityDetector(ctx.session, ctx.merchant_id)
    found = await detector.detect(days=args.days)
    rows = [
        {
            "key": o.key,
            "title": o.title,
            "summary": o.summary,
            "kind": o.kind,
            "estimated_value_monthly": o.estimated_value_monthly,
            "confidence": o.confidence,
            "impact": o.impact,
            "effort": o.effort,
            "evidence": o.evidence,
            "hypothesis": o.hypothesis,
            "recommended_action": o.recommended_action,
        }
        for o in found
    ]
    total = round(sum(o.estimated_value_monthly for o in found), 2)
    return (
        {"opportunities": rows, "count": len(rows), "total_value_monthly": total},
        (
            f"{len(rows)} opportunities worth {_money(total)}/month. "
            f"Largest: {found[0].title} at {_money(found[0].estimated_value_monthly)}/month."
            if found
            else "No opportunities above the minimum value threshold."
        ),
    )


@registry.register(
    "get_growth_graph",
    description=(
        "The growth graph: how the headline movement decomposes into metrics and "
        "segments, with independent evidence attached to the branch that moved most. "
        "Relationships are signals and correlations, never causal claims."
    ),
    args_model=WindowArgs,
    permission=Permission.GROWTH_READ,
)
async def get_growth_graph(ctx: ToolContext, args: WindowArgs) -> tuple[dict[str, Any], str]:
    service = GrowthGraphService(ctx.session, ctx.merchant_id)
    graph = await service.build(days=args.days)
    return (
        {
            "nodes": [
                {
                    "id": n.id,
                    "label": n.label,
                    "value": n.formatted_value,
                    "change_pct": n.change_pct,
                    "kind": n.node_kind,
                    "severity": n.severity,
                    "interpretation": n.interpretation,
                }
                for n in graph.nodes
            ],
            "edges": [
                {"source": e.source, "target": e.target, "relationship": e.relationship}
                for e in graph.edges
            ],
            "caveat": graph.caveat,
        },
        f"Growth graph with {len(graph.nodes)} nodes across {len({n.depth for n in graph.nodes})} levels.",
    )


class OpportunityValueArgs(BaseModel):
    lapsed_customers: int = Field(ge=0, description="Number of customers who stopped ordering.")
    monthly_value_per_customer: float = Field(
        ge=0, description="Historic monthly revenue per one of those customers."
    )
    recovery_rate: float = Field(
        default=0.35, ge=0, le=1, description="Share realistically recoverable (0-1)."
    )


@registry.register(
    "calculate_opportunity_value",
    description=(
        "Compute the monthly value of recovering a lapsed segment. Always use this "
        "rather than doing the arithmetic yourself."
    ),
    args_model=OpportunityValueArgs,
    permission=Permission.GROWTH_READ,
)
async def calculate_opportunity_value(
    ctx: ToolContext, args: OpportunityValueArgs
) -> tuple[dict[str, Any], str]:
    value = round(args.lapsed_customers * args.monthly_value_per_customer * args.recovery_rate, 2)
    return (
        {
            "estimated_value_monthly": value,
            "inputs": args.model_dump(),
            "formula": "lapsed_customers x monthly_value_per_customer x recovery_rate",
        },
        (
            f"{args.lapsed_customers} customers x {_money(args.monthly_value_per_customer)} x "
            f"{args.recovery_rate:.0%} = {_money(value)}/month."
        ),
    )
