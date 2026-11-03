"""Analytics service - deterministic business metrics.

This is the layer the spec's "critical AI engineering rule" protects: every
number the product shows (and every number an agent reasons over) is computed
here in Python/SQL. The LLM receives these structured results; it never sees raw
rows and never does arithmetic.
"""

from __future__ import annotations

import statistics
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.commerce import DayPart
from app.db.models.growth import MetricDirection, MetricKey
from app.repositories.customer import CustomerRepository
from app.repositories.product import ProductRepository
from app.repositories.transaction import SalesAggregate, TransactionRepository, _pct_change
from app.schemas.analytics import (
    Anomaly,
    CustomerCohort,
    CustomerMetrics,
    DaypartBreakdown,
    PeriodInfo,
    ProductMix,
    ProductPerformance,
    RetentionPoint,
    SalesSummary,
)
from app.schemas.common import DateRange, MetricDelta, TrendPoint

log = get_logger(__name__)

DAYPART_LABELS = {
    DayPart.MORNING: "Morning (6am-12pm)",
    DayPart.AFTERNOON: "Afternoon (12pm-5pm)",
    DayPart.EVENING: "Evening (5pm-9pm)",
    DayPart.NIGHT: "Night (9pm-6am)",
}

#: A metric must move at least this much before it is worth a merchant's attention.
ANOMALY_MIN_CHANGE_PCT = 8.0
ANOMALY_HIGH_CHANGE_PCT = 15.0


class AnalyticsService:
    """All deterministic analytics for one merchant."""

    def __init__(self, session: AsyncSession, merchant_id: uuid.UUID) -> None:
        self.session = session
        self.merchant_id = merchant_id
        self.transactions = TransactionRepository(session, merchant_id)
        self.customers = CustomerRepository(session, merchant_id)
        self.products = ProductRepository(session, merchant_id)

    # ------------------------------------------------------------------ periods
    async def resolve_period(self, *, days: int = 30, end: date | None = None) -> PeriodInfo:
        """Anchor the analysis window to the data, not to wall-clock today.

        The dataset is generated relative to its own build date, so anchoring
        on the last transaction keeps the analysis correct whenever it is run.
        """
        anchor = end or await self.transactions.last_transaction_date() or date.today()
        current = DateRange(start=anchor - timedelta(days=days - 1), end=anchor)
        previous = current.previous()
        return PeriodInfo(
            current=current,
            previous=previous,
            days=days,
            label=f"Last {days} days",
        )

    # ------------------------------------------------------------------ summary
    async def sales_summary(self, period: DateRange, *, daypart: str | None = None) -> SalesSummary:
        aggregate = await self.transactions.sales_summary(period.start, period.end, daypart=daypart)
        return _to_summary(aggregate)

    async def kpis(
        self, period: PeriodInfo
    ) -> tuple[list[MetricDelta], SalesSummary, SalesSummary]:
        """The four headline KPIs plus both raw summaries."""
        current = await self.transactions.sales_summary(period.current.start, period.current.end)
        previous = await self.transactions.sales_summary(period.previous.start, period.previous.end)

        specs = [
            (
                MetricKey.REVENUE,
                "Revenue",
                current.revenue,
                previous.revenue,
                "currency",
                MetricDirection.UP_IS_GOOD,
            ),
            (
                MetricKey.ORDERS,
                "Orders",
                current.orders,
                previous.orders,
                "number",
                MetricDirection.UP_IS_GOOD,
            ),
            (
                MetricKey.AOV,
                "Average Order Value",
                current.aov,
                previous.aov,
                "currency",
                MetricDirection.UP_IS_GOOD,
            ),
            (
                MetricKey.REPEAT_RATE,
                "Repeat Rate",
                current.repeat_rate,
                previous.repeat_rate,
                "percent",
                MetricDirection.UP_IS_GOOD,
            ),
        ]

        kpis: list[MetricDelta] = []
        for key, label, cur, prev, unit, direction in specs:
            change_pct = _pct_change(float(cur), float(prev))
            kpis.append(
                MetricDelta(
                    key=key,
                    label=label,
                    value=round(float(cur), 2),
                    previous_value=round(float(prev), 2),
                    change_abs=round(float(cur) - float(prev), 2),
                    change_pct=change_pct,
                    unit=unit,  # type: ignore[arg-type]
                    direction=direction,  # type: ignore[arg-type]
                    is_anomaly=bool(
                        change_pct is not None and abs(change_pct) >= ANOMALY_MIN_CHANGE_PCT
                    ),
                    sample_size=current.orders,
                )
            )
        return kpis, _to_summary(current), _to_summary(previous)

    # ------------------------------------------------------------------ trends
    async def revenue_trend(self, period: DateRange) -> list[TrendPoint]:
        rows = await self.transactions.daily_trend(period.start, period.end)
        return [
            TrendPoint(date=row["date"], value=row["revenue"], secondary_value=float(row["orders"]))
            for row in rows
        ]

    async def orders_trend(self, period: DateRange) -> list[TrendPoint]:
        rows = await self.transactions.daily_trend(period.start, period.end)
        return [
            TrendPoint(
                date=row["date"],
                value=float(row["orders"]),
                secondary_value=float(row["customers"]),
            )
            for row in rows
        ]

    # ------------------------------------------------------------------ dayparts
    async def daypart_breakdown(self, period: PeriodInfo) -> list[DaypartBreakdown]:
        """Per-slot performance with its own period-over-period deltas.

        This is what surfaces "evening is falling much faster than the rest".
        """
        current = await self.transactions.daypart_breakdown(
            period.current.start, period.current.end
        )
        previous = await self.transactions.daypart_breakdown(
            period.previous.start, period.previous.end
        )
        prev_by_part = {row["daypart"]: row for row in previous}
        total_revenue = sum(row["revenue"] for row in current) or 1.0

        results: list[DaypartBreakdown] = []
        for row in current:
            prior = prev_by_part.get(row["daypart"], {})
            results.append(
                DaypartBreakdown(
                    daypart=row["daypart"],
                    label=DAYPART_LABELS.get(row["daypart"], row["daypart"].title()),
                    revenue=row["revenue"],
                    orders=row["orders"],
                    aov=row["aov"],
                    unique_customers=row["unique_customers"],
                    repeat_customers=row["repeat_customers"],
                    revenue_share_pct=round((row["revenue"] / total_revenue) * 100, 2),
                    change_pct=_pct_change(row["revenue"], float(prior.get("revenue", 0) or 0)),
                    repeat_customers_change_pct=_pct_change(
                        float(row["repeat_customers"]), float(prior.get("repeat_customers", 0) or 0)
                    ),
                    avg_service_minutes=row.get("avg_service_minutes"),
                    service_minutes_change_pct=_pct_change(
                        float(row.get("avg_service_minutes") or 0),
                        float(prior.get("avg_service_minutes") or 0),
                    ),
                )
            )
        results.sort(key=lambda item: item.revenue, reverse=True)
        return results

    # ------------------------------------------------------------------ products
    async def product_performance(self, period: PeriodInfo) -> list[ProductPerformance]:
        current = await self.transactions.product_performance(
            period.current.start, period.current.end
        )
        previous = await self.transactions.product_performance(
            period.previous.start, period.previous.end
        )
        prev_by_id = {row["product_id"]: row for row in previous}

        total_revenue = sum(row["revenue"] for row in current) or 1.0
        total_orders = await self.transactions.count_orders(
            period.current.start, period.current.end
        )

        results: list[ProductPerformance] = []
        for row in current:
            prior_revenue = float(prev_by_id.get(row["product_id"], {}).get("revenue", 0) or 0)
            change_pct = _pct_change(row["revenue"], prior_revenue)
            results.append(
                ProductPerformance(
                    product_id=row["product_id"],
                    name=row["name"],
                    sku=row["sku"],
                    category=row["category"],
                    price=row["price"],
                    units_sold=row["units_sold"],
                    revenue=row["revenue"],
                    gross_margin=row["gross_margin"],
                    margin_pct=round((row["gross_margin"] / row["revenue"]) * 100, 2)
                    if row["revenue"]
                    else 0.0,
                    revenue_share_pct=round((row["revenue"] / total_revenue) * 100, 2),
                    orders=row["orders"],
                    attach_rate_pct=round((row["orders"] / total_orders) * 100, 2)
                    if total_orders
                    else 0.0,
                    previous_revenue=round(prior_revenue, 2),
                    change_pct=change_pct,
                    trend=_trend(change_pct),
                )
            )
        return results

    async def product_mix(self, period: DateRange, *, limit: int = 8) -> list[ProductMix]:
        pairs = await self.transactions.product_pairs(period.start, period.end, limit=limit)
        results: list[ProductMix] = []
        for pair in pairs:
            # A bundle's upside is modelled as lifting attach rate toward the pair's
            # observed confidence - deliberately conservative, and fully deterministic.
            uplift = (
                pair["combined_revenue"] * min(pair["lift"] - 1.0, 0.35)
                if pair["lift"] > 1
                else 0.0
            )
            results.append(
                ProductMix(
                    product_a_id=pair["product_a_id"],
                    product_a_name=pair["product_a_name"],
                    product_b_id=pair["product_b_id"],
                    product_b_name=pair["product_b_name"],
                    co_occurrences=pair["co_occurrences"],
                    support_pct=pair["support_pct"],
                    confidence_pct=pair["confidence_pct"],
                    lift=pair["lift"],
                    combined_revenue=pair["combined_revenue"],
                    estimated_bundle_uplift=round(max(uplift, 0.0), 2),
                )
            )
        return results

    # ------------------------------------------------------------------ customers
    async def customer_metrics(self, period: PeriodInfo) -> CustomerMetrics:
        current = await self.transactions.sales_summary(period.current.start, period.current.end)
        await self.transactions.sales_summary(period.previous.start, period.previous.end)

        retention = await self.transactions.retention_between(
            period.previous.start, period.previous.end, period.current.start, period.current.end
        )
        total_customers = await self.customers.total_customers()
        churn_risk = await self.customers.churn_risk_count()

        segment_counts = await self.customers.segment_counts()
        segment_total = sum(segment_counts.values()) or 1
        cohorts = [
            CustomerCohort(
                key=key,
                label=key.replace("_", " ").title(),
                customers=count,
                revenue=0.0,
                orders=0,
                aov=0.0,
                share_pct=round((count / segment_total) * 100, 2),
            )
            for key, count in sorted(segment_counts.items(), key=lambda kv: -kv[1])
        ]

        retention_curve = [
            RetentionPoint(**row) for row in await self.transactions.cohort_retention(months=6)
        ]

        return CustomerMetrics(
            total_customers=total_customers,
            active_customers=current.unique_customers,
            new_customers=current.new_customers,
            repeat_customers=current.repeat_customers,
            repeat_rate=current.repeat_rate,
            retention_rate=retention["retention_pct"],
            churn_risk_customers=churn_risk,
            avg_orders_per_customer=round(current.orders / current.unique_customers, 2)
            if current.unique_customers
            else 0.0,
            avg_customer_value=round(current.revenue / current.unique_customers, 2)
            if current.unique_customers
            else 0.0,
            cohorts=cohorts,
            by_daypart=await self.daypart_breakdown(period),
            retention_curve=retention_curve,
        )

    # ------------------------------------------------------------------ anomalies
    async def detect_anomalies(self, period: PeriodInfo) -> list[Anomaly]:
        """Flag metrics whose period-over-period move is materially outside normal.

        Two complementary checks:
          1. Headline metrics whose change exceeds a materiality threshold.
          2. Daily revenue points more than 2 standard deviations from the mean.
        """
        anomalies: list[Anomaly] = []
        kpis, current, _previous = await self.kpis(period)

        for kpi in kpis:
            if kpi.change_pct is None or abs(kpi.change_pct) < ANOMALY_MIN_CHANGE_PCT:
                continue
            if kpi.is_improving:
                continue
            anomalies.append(
                Anomaly(
                    metric=kpi.key,
                    label=kpi.label,
                    value=kpi.value,
                    expected=kpi.previous_value or 0.0,
                    deviation_pct=kpi.change_pct,
                    severity="HIGH" if abs(kpi.change_pct) >= ANOMALY_HIGH_CHANGE_PCT else "MEDIUM",
                    detected_on=period.current.end,
                    description=(
                        f"{kpi.label} moved {kpi.change_pct:+.1f}% versus the previous "
                        f"{period.days} days."
                    ),
                )
            )

        # Segment-level: any daypart falling materially faster than the business overall.
        overall_change = next((k.change_pct for k in kpis if k.key == MetricKey.REVENUE), None)
        for part in await self.daypart_breakdown(period):
            if part.change_pct is None or overall_change is None:
                continue
            if part.change_pct >= 0 or part.change_pct > overall_change - 5:
                continue
            anomalies.append(
                Anomaly(
                    metric=f"revenue.{part.daypart.lower()}",
                    label=f"{part.label} revenue",
                    value=part.revenue,
                    expected=round(part.revenue / (1 + part.change_pct / 100), 2)
                    if part.change_pct != -100
                    else 0.0,
                    deviation_pct=part.change_pct,
                    severity="HIGH" if part.change_pct <= -20 else "MEDIUM",
                    dimension="daypart",
                    dimension_value=part.daypart,
                    detected_on=period.current.end,
                    description=(
                        f"{part.label} revenue fell {abs(part.change_pct):.1f}%, against "
                        f"{overall_change:+.1f}% for the business overall."
                    ),
                )
            )

        # Daily outliers.
        trend = await self.transactions.daily_trend(period.current.start, period.current.end)
        values = [row["revenue"] for row in trend]
        if len(values) >= 7:
            mean = statistics.fmean(values)
            stdev = statistics.pstdev(values)
            if stdev > 0:
                for row in trend:
                    z = (row["revenue"] - mean) / stdev
                    if z <= -2.0:
                        anomalies.append(
                            Anomaly(
                                metric="revenue.daily",
                                label="Daily revenue dip",
                                value=row["revenue"],
                                expected=round(mean, 2),
                                deviation_pct=round(((row["revenue"] - mean) / mean) * 100, 2)
                                if mean
                                else 0.0,
                                z_score=round(z, 2),
                                severity="MEDIUM",
                                dimension="date",
                                dimension_value=str(row["date"]),
                                detected_on=row["date"],
                                description=(
                                    f"Revenue on {row['date']} was {abs(z):.1f} standard "
                                    "deviations below the period average."
                                ),
                            )
                        )

        anomalies.sort(key=lambda item: abs(item.deviation_pct), reverse=True)
        return anomalies[:10]

    # ------------------------------------------------------------------ snapshot
    async def metrics_snapshot(self, period: PeriodInfo) -> dict[str, Any]:
        """Compact, fully-computed fact sheet handed to the LLM.

        This is the *only* numeric surface the agents reason over.
        """
        kpis, current, previous = await self.kpis(period)
        dayparts = await self.daypart_breakdown(period)
        products = await self.product_performance(period)
        customers = await self.customer_metrics(period)

        declining = [p for p in products if (p.change_pct or 0) < -5][:5]
        growing = [p for p in products if (p.change_pct or 0) > 5][:5]

        return {
            "period": {
                "current": {"start": str(period.current.start), "end": str(period.current.end)},
                "previous": {"start": str(period.previous.start), "end": str(period.previous.end)},
                "days": period.days,
            },
            "headline": {
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
            "dayparts": [
                {
                    "daypart": d.daypart,
                    "label": d.label,
                    "revenue": d.revenue,
                    "revenue_change_pct": d.change_pct,
                    "repeat_customers": d.repeat_customers,
                    "repeat_customers_change_pct": d.repeat_customers_change_pct,
                    "revenue_share_pct": d.revenue_share_pct,
                }
                for d in dayparts
            ],
            "customers": {
                "total": customers.total_customers,
                "active": customers.active_customers,
                "new": customers.new_customers,
                "repeat": customers.repeat_customers,
                "repeat_rate": customers.repeat_rate,
                "retention_rate": customers.retention_rate,
                "churn_risk": customers.churn_risk_customers,
                "avg_customer_value": customers.avg_customer_value,
            },
            "declining_products": [
                {"name": p.name, "revenue": p.revenue, "change_pct": p.change_pct}
                for p in declining
            ],
            "growing_products": [
                {"name": p.name, "revenue": p.revenue, "change_pct": p.change_pct} for p in growing
            ],
            "top_products": [
                {"name": p.name, "revenue": p.revenue, "revenue_share_pct": p.revenue_share_pct}
                for p in products[:5]
            ],
        }


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _to_summary(aggregate: SalesAggregate) -> SalesSummary:
    return SalesSummary(
        revenue=aggregate.revenue,
        orders=aggregate.orders,
        aov=aggregate.aov,
        unique_customers=aggregate.unique_customers,
        new_customers=aggregate.new_customers,
        repeat_customers=aggregate.repeat_customers,
        repeat_rate=aggregate.repeat_rate,
        gross_margin=aggregate.gross_margin,
        gross_margin_pct=aggregate.gross_margin_pct,
        discount_total=aggregate.discount_total,
        avg_service_minutes=aggregate.avg_service_minutes,
    )


def _trend(change_pct: float | None) -> str:
    if change_pct is None:
        return "FLAT"
    if change_pct > 3:
        return "UP"
    if change_pct < -3:
        return "DOWN"
    return "FLAT"


def utcnow() -> datetime:
    return datetime.now(tz=UTC)
