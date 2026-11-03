"""Dashboard, growth-graph and analytics endpoints.

``GET /dashboard/overview`` is deliberately one aggregated call. The Growth
Command Center renders from a single response rather than fanning out to a dozen
endpoints (spec section 52).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, Principal, require_permission
from app.core.permissions import Permission
from app.repositories.customer import CustomerRepository
from app.schemas.analytics import (
    CustomerMetrics,
    DashboardOverview,
    GrowthGraph,
    ProductAnalytics,
    SegmentDefinition,
    SegmentPreview,
)
from app.schemas.analytics import CustomerOut as CustomerSchema
from app.schemas.common import APIResponse, PageMeta, Paginated
from app.services.analytics.service import AnalyticsService
from app.services.growth.graph import GrowthGraphService

router = APIRouter(tags=["dashboard"])

DaysQuery = Annotated[int, Query(ge=7, le=180, description="Look-back window in days.")]


def _headline(overview_kpis, worst_daypart, opportunity_value: float) -> str:
    revenue = next((k for k in overview_kpis if k.key == "revenue"), None)
    if revenue is None or revenue.change_pct is None:
        return "Your business summary for this period."
    if revenue.change_pct < 0 and worst_daypart is not None:
        return (
            f"Revenue is {revenue.change_pct:+.1f}% this period, and the decline concentrates in "
            f"your {worst_daypart.label.split(' (')[0].lower()} segment "
            f"({worst_daypart.change_pct:+.1f}%)."
        )
    if revenue.change_pct >= 0:
        return f"Revenue is {revenue.change_pct:+.1f}% this period."
    return f"Revenue is {revenue.change_pct:+.1f}% this period."


@router.get(
    "/dashboard/overview",
    summary="Growth Command Center",
    description=(
        "Everything the main dashboard needs in one call: KPIs with period-over-period "
        "deltas, revenue and order trends, segment breakdown, top and declining "
        "products, customer health and detected anomalies."
    ),
)
async def dashboard_overview(
    session: DbSession,
    days: DaysQuery = 30,
    principal: Principal = Depends(require_permission(Permission.DASHBOARD_READ)),
) -> APIResponse[DashboardOverview]:
    service = AnalyticsService(session, principal.merchant_id)
    period = await service.resolve_period(days=days)

    kpis, current, previous = await service.kpis(period)
    dayparts = await service.daypart_breakdown(period)
    products = await service.product_performance(period)
    customers = await service.customer_metrics(period)
    anomalies = await service.detect_anomalies(period)

    declining = sorted(
        [p for p in products if (p.change_pct or 0) < 0], key=lambda p: p.change_pct or 0
    )[:5]
    worst_daypart = min(
        (d for d in dayparts if d.change_pct is not None),
        key=lambda d: d.change_pct or 0,
        default=None,
    )

    overview = DashboardOverview(
        merchant_id=principal.merchant_id,
        merchant_name=principal.merchant.name,
        period=period,
        kpis=kpis,
        summary=current,
        previous_summary=previous,
        revenue_trend=await service.revenue_trend(period.current),
        orders_trend=await service.orders_trend(period.current),
        daypart_breakdown=dayparts,
        top_products=products[:6],
        declining_products=declining,
        customer_metrics=customers,
        anomalies=anomalies,
        headline_insight=_headline(kpis, worst_daypart, 0.0),
        generated_at=datetime.now(tz=UTC),
    )
    return APIResponse(
        data=overview,
        meta={
            "period_days": days,
            "is_demo": principal.merchant.is_demo,
            "data_source": principal.merchant.data_source,
        },
    )


@router.get(
    "/growth/graph",
    summary="Interactive growth graph",
    description=(
        "Decomposition of the headline movement into metrics, segments and supporting "
        "evidence. Edges are decompositions or correlations - never causal claims."
    ),
)
async def growth_graph(
    session: DbSession,
    days: DaysQuery = 30,
    principal: Principal = Depends(require_permission(Permission.GROWTH_READ)),
) -> APIResponse[GrowthGraph]:
    graph = await GrowthGraphService(session, principal.merchant_id).build(days=days)
    return APIResponse(data=graph, meta={"period_days": days})


@router.get(
    "/customers/metrics",
    summary="Customer health",
    description="Repeat rate, retention, cohorts, churn risk and per-slot behaviour.",
)
async def customer_metrics(
    session: DbSession,
    days: DaysQuery = 30,
    principal: Principal = Depends(require_permission(Permission.CUSTOMERS_READ)),
) -> APIResponse[CustomerMetrics]:
    service = AnalyticsService(session, principal.merchant_id)
    period = await service.resolve_period(days=days)
    return APIResponse(data=await service.customer_metrics(period), meta={"period_days": days})


@router.get("/customers", summary="List customers")
async def list_customers(
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 25,
    segment: Annotated[str | None, Query()] = None,
    daypart: Annotated[str | None, Query()] = None,
    principal: Principal = Depends(require_permission(Permission.CUSTOMERS_READ)),
) -> APIResponse[Paginated[CustomerSchema]]:
    repo = CustomerRepository(session, principal.merchant_id)
    customers = await repo.resolve_segment(
        segments=[segment] if segment else [],
        dayparts=[daypart] if daypart else [],
        opted_in_only=False,
        limit=page_size * page,
    )
    total = await repo.count()
    window = customers[(page - 1) * page_size : page * page_size]
    return APIResponse(
        data=Paginated(
            items=[CustomerSchema.model_validate(c) for c in window],
            pagination=PageMeta.build(page=page, page_size=page_size, total=total),
        )
    )


@router.post(
    "/customers/segment/preview",
    summary="Preview a customer segment",
    description="Materialises a segment filter and reports its size and value, without saving it.",
)
async def preview_segment(
    payload: SegmentDefinition,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.CUSTOMERS_READ)),
) -> APIResponse[SegmentPreview]:
    repo = CustomerRepository(session, principal.merchant_id)
    filters = payload.model_dump(exclude={"name"})
    customers = await repo.resolve_segment(**filters)
    stats = await repo.segment_stats([c.id for c in customers])
    return APIResponse(
        data=SegmentPreview(
            definition=payload,
            size=stats["size"],
            estimated_revenue_30d=stats["total_spend"],
            avg_order_value=stats["avg_order_value"],
            sample=[CustomerSchema.model_validate(c) for c in customers[:8]],
        )
    )


@router.get(
    "/products/analytics",
    summary="Product analytics",
    description="Per-product performance plus market-basket pairs and category mix.",
)
async def product_analytics(
    session: DbSession,
    days: DaysQuery = 30,
    principal: Principal = Depends(require_permission(Permission.PRODUCTS_READ)),
) -> APIResponse[ProductAnalytics]:
    service = AnalyticsService(session, principal.merchant_id)
    period = await service.resolve_period(days=days)
    products = await service.product_performance(period)
    categories = await service.products.category_revenue(period.current.start, period.current.end)
    total = sum(row["revenue"] for row in categories) or 1.0

    from app.schemas.analytics import CustomerCohort

    return APIResponse(
        data=ProductAnalytics(
            period=period,
            products=products,
            top_by_revenue=products[:5],
            top_by_margin=sorted(products, key=lambda p: p.gross_margin, reverse=True)[:5],
            declining=sorted(
                [p for p in products if (p.change_pct or 0) < -5],
                key=lambda p: p.change_pct or 0,
            )[:5],
            growing=sorted(
                [p for p in products if (p.change_pct or 0) > 5],
                key=lambda p: p.change_pct or 0,
                reverse=True,
            )[:5],
            product_mix=await service.product_mix(period.current, limit=8),
            category_breakdown=[
                CustomerCohort(
                    key=row["category"],
                    label=row["category"].title(),
                    customers=0,
                    revenue=row["revenue"],
                    orders=row["orders"],
                    aov=round(row["revenue"] / row["orders"], 2) if row["orders"] else 0.0,
                    share_pct=round(row["revenue"] / total * 100, 2),
                )
                for row in categories
            ],
        ),
        meta={"period_days": days},
    )
