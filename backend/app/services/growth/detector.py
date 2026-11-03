"""Growth opportunity detection.

Entirely deterministic. Each detector inspects computed metrics, decides whether a
pattern is present, and quantifies it with an explicit, auditable formula. The LLM
is never asked to size an opportunity - it only explains one that has already been
measured.

Every opportunity carries the evidence rows that produced it, so the UI can trace
each claim back to a number.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.growth import ImpactLevel, OpportunityKind, OpportunityStatus
from app.db.models.review import ReviewTopic
from app.repositories.opportunity import OpportunityRepository
from app.repositories.review import ReviewRepository
from app.repositories.transaction import _pct_change
from app.schemas.analytics import DaypartBreakdown, PeriodInfo, ProductPerformance
from app.services.analytics.service import AnalyticsService

log = get_logger(__name__)

# --------------------------------------------------------------------------- #
# Modelling assumptions. Stated explicitly so every number is auditable.
# --------------------------------------------------------------------------- #
#: Share of lapsed customers a well-targeted win-back realistically recovers.
#: Deliberately conservative - industry win-back campaigns land well below half.
RECOVERY_RATE = 0.35
#: Share of the observed co-purchase lift a bundle can realistically capture.
BUNDLE_CAPTURE_RATE = 0.30
#: Share of a declining product's lost revenue a targeted push can recover.
PRODUCT_RECOVERY_RATE = 0.25
#: Minimum monthly value before an opportunity is worth showing at all.
MIN_OPPORTUNITY_VALUE = 800.0

IMPACT_THRESHOLDS = ((8000.0, ImpactLevel.HIGH), (3000.0, ImpactLevel.MEDIUM))


def _impact_for(value: float) -> str:
    for threshold, level in IMPACT_THRESHOLDS:
        if value >= threshold:
            return level
    return ImpactLevel.LOW


def _money(value: float) -> str:
    return f"Rs {value:,.0f}"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.1f}%"


@dataclass(slots=True)
class DetectedOpportunity:
    """A quantified opportunity, before it is persisted."""

    key: str
    title: str
    summary: str
    kind: str
    estimated_value_monthly: float
    confidence: float
    impact: str
    effort: str
    risk: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    hypothesis: str = ""
    recommended_action: str = ""
    reasoning: str = ""
    graph_path: list[str] = field(default_factory=list)
    target_segment: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    requires_approval: bool = True

    @property
    def priority_score(self) -> float:
        """Rank by expected value, discounted by effort."""
        effort_penalty = {"LOW": 1.0, "MEDIUM": 0.85, "HIGH": 0.65}.get(self.effort, 0.85)
        return round(self.estimated_value_monthly * self.confidence * effort_penalty, 3)


class OpportunityDetector:
    def __init__(self, session: AsyncSession, merchant_id: uuid.UUID) -> None:
        self.session = session
        self.merchant_id = merchant_id
        self.analytics = AnalyticsService(session, merchant_id)
        self.reviews = ReviewRepository(session, merchant_id)
        self.repo = OpportunityRepository(session, merchant_id)

    # ------------------------------------------------------------------ entry
    async def detect(self, *, days: int = 30) -> list[DetectedOpportunity]:
        period = await self.analytics.resolve_period(days=days)
        dayparts = await self.analytics.daypart_breakdown(period)
        products = await self.analytics.product_performance(period)
        kpis, current, previous = await self.analytics.kpis(period)

        found: list[DetectedOpportunity] = []
        found.extend(await self._detect_lapsed_segment(period, dayparts))
        found.extend(await self._detect_bundle(period))
        found.extend(self._detect_declining_products(period, products))
        found.extend(await self._detect_service_pressure(period, dayparts))

        viable = [o for o in found if o.estimated_value_monthly >= MIN_OPPORTUNITY_VALUE]
        viable.sort(key=lambda o: o.priority_score, reverse=True)

        log.info(
            "opportunities_detected",
            count=len(viable),
            total_value=round(sum(o.estimated_value_monthly for o in viable), 2),
            days=days,
        )
        return viable

    # ------------------------------------------------------------------ 1. retention
    async def _detect_lapsed_segment(
        self, period: PeriodInfo, dayparts: list[DaypartBreakdown]
    ) -> list[DetectedOpportunity]:
        """A daypart losing its repeat customers faster than the business overall.

        Value = lapsed repeat customers x their historic monthly spend x recovery rate.
        """
        results: list[DetectedOpportunity] = []
        overall_revenue_change = _pct_change(
            sum(d.revenue for d in dayparts),
            sum(
                d.revenue / (1 + (d.change_pct or 0) / 100)
                for d in dayparts
                if d.change_pct != -100
            ),
        )

        for part in dayparts:
            change = part.repeat_customers_change_pct
            revenue_change = part.change_pct
            if change is None or change >= -8:
                continue
            if revenue_change is None or revenue_change >= -10:
                continue

            previous_repeat = (
                round(part.repeat_customers / (1 + change / 100)) if change != -100 else 0
            )
            lapsed = max(previous_repeat - part.repeat_customers, 0)
            if lapsed <= 0:
                continue

            # Historic monthly value of one repeat customer in this slot.
            prev_revenue = (
                part.revenue / (1 + revenue_change / 100)
                if revenue_change != -100
                else part.revenue
            )
            value_per_repeat_customer = (
                prev_revenue / previous_repeat if previous_repeat else part.aov
            )
            estimated = round(lapsed * value_per_repeat_customer * RECOVERY_RATE, 2)

            evidence = [
                {
                    "metric": f"{part.label} revenue",
                    "value": _money(part.revenue),
                    "change": _pct(revenue_change),
                    "source": "analytics",
                    "detail": (f"Versus {_pct(overall_revenue_change)} for the business overall."),
                    "reference": "dashboard",
                },
                {
                    "metric": f"{part.label} repeat customers",
                    "value": str(part.repeat_customers),
                    "change": _pct(change),
                    "source": "analytics",
                    "detail": f"{lapsed} repeat customers stopped ordering in this slot.",
                    "reference": "customers",
                },
                {
                    "metric": f"{part.label} average order value",
                    "value": _money(part.aov),
                    "change": None,
                    "source": "analytics",
                    "detail": f"Historic value per repeat customer {_money(value_per_repeat_customer)}/month.",
                    "reference": "dashboard",
                },
            ]

            # Corroborating evidence from an independent source: the review corpus.
            review_evidence = await self._review_signal_for(period, part.daypart)
            evidence.extend(review_evidence)

            if part.service_minutes_change_pct and part.service_minutes_change_pct > 5:
                evidence.append(
                    {
                        "metric": f"{part.label} average service time",
                        "value": f"{part.avg_service_minutes:.1f} min"
                        if part.avg_service_minutes
                        else "n/a",
                        "change": _pct(part.service_minutes_change_pct),
                        "source": "analytics",
                        "detail": "Order-to-handover time measured on completed orders.",
                        "reference": "dashboard",
                    }
                )

            # Confidence rises with the strength and independence of the evidence.
            confidence = 0.55
            confidence += min(abs(change) / 100, 0.15)
            if review_evidence:
                confidence += 0.12
            if part.service_minutes_change_pct and part.service_minutes_change_pct > 10:
                confidence += 0.10
            confidence = round(min(confidence, 0.93), 2)

            slot = part.label.split(" (")[0]
            results.append(
                DetectedOpportunity(
                    key=f"recover-lapsed-{part.daypart.lower()}-repeat-customers",
                    title=f"Recover lost {slot.lower()} repeat customers",
                    summary=(
                        f"{lapsed} repeat customers who used to order in the {slot.lower()} slot "
                        f"have stopped. That slot's revenue is {_pct(revenue_change)} while the "
                        f"rest of the business is close to flat."
                    ),
                    kind=OpportunityKind.RETENTION,
                    estimated_value_monthly=estimated,
                    confidence=confidence,
                    impact=_impact_for(estimated),
                    effort="MEDIUM",
                    risk="medium",
                    evidence=evidence,
                    hypothesis=self._retention_hypothesis(part, review_evidence),
                    recommended_action=(
                        f"Run a targeted {slot.lower()} win-back experiment against the lapsed "
                        "segment, with a held-out control group so the lift is measurable."
                    ),
                    graph_path=[
                        "revenue",
                        "repeat_customers",
                        f"daypart:{part.daypart}",
                        f"evidence:{part.daypart}:service",
                    ],
                    target_segment={
                        # Behavioural, not habitual: anyone who actually used to order in
                        # this slot, including customers who have since drifted elsewhere.
                        # `preferred_daypart` alone would miss exactly the people who left.
                        "active_dayparts": [part.daypart],
                        "active_within_days": 180,
                        "opted_in_only": True,
                        "limit": 5000,
                    },
                    tags=["retention", part.daypart.lower(), "win-back"],
                )
            )
        return results

    def _retention_hypothesis(
        self, part: DaypartBreakdown, review_evidence: list[dict[str, Any]]
    ) -> str:
        slot = part.label.split(" (")[0].lower()
        bits = [
            f"Repeat customers in the {slot} slot are lapsing faster than anywhere else in the business."
        ]
        if part.service_minutes_change_pct and part.service_minutes_change_pct > 5:
            bits.append(
                f"Average service time in that slot moved {_pct(part.service_minutes_change_pct)} "
                "over the same window."
            )
        if review_evidence:
            bits.append("Negative review volume for the same slot moved in step with it.")
        bits.append(
            "These are correlated signals observed over the same period, not a demonstrated "
            "cause. A controlled experiment is the way to test whether acting on them recovers "
            "the segment."
        )
        return " ".join(bits)

    async def _review_signal_for(self, period: PeriodInfo, daypart: str) -> list[dict[str, Any]]:
        """Independent corroboration from reviews for a given slot."""
        current = await self.reviews.topic_stats(
            period.current.start, period.current.end, daypart=daypart
        )
        previous = await self.reviews.topic_stats(
            period.previous.start, period.previous.end, daypart=daypart
        )
        prev_by_topic = {row["topic"]: row for row in previous}

        evidence: list[dict[str, Any]] = []
        for row in current:
            prior = prev_by_topic.get(row["topic"], {})
            prior_negative = int(prior.get("negative_count", 0) or 0)
            change = _pct_change(float(row["negative_count"]), float(prior_negative))
            # Only surface a topic whose negative volume is both material and rising.
            if row["negative_count"] < 4 or change is None or change < 20:
                continue
            evidence.append(
                {
                    "metric": f"{ReviewTopic.LABELS.get(row['topic'], row['topic'])} complaints",
                    "value": f"{row['negative_count']} reviews",
                    "change": _pct(change),
                    "source": "reviews",
                    "detail": (
                        f"Negative {row['topic'].replace('_', ' ')} reviews in the "
                        f"{daypart.lower()} slot rose from {prior_negative} to {row['negative_count']}."
                    ),
                    "reference": f"reviews?topic={row['topic']}&daypart={daypart}",
                }
            )
        evidence.sort(key=lambda item: item["metric"])
        return evidence[:3]

    # ------------------------------------------------------------------ 2. bundle
    async def _detect_bundle(self, period: PeriodInfo) -> list[DetectedOpportunity]:
        """Two products bought together far more often than chance would predict."""
        pairs = await self.analytics.product_mix(period.current, limit=5)
        results: list[DetectedOpportunity] = []
        for pair in pairs[:2]:
            if pair.lift <= 1.15 or pair.co_occurrences < 12:
                continue
            estimated = round(pair.combined_revenue * (pair.lift - 1.0) * BUNDLE_CAPTURE_RATE, 2)
            if estimated < MIN_OPPORTUNITY_VALUE:
                continue
            results.append(
                DetectedOpportunity(
                    key=f"bundle-{pair.product_a_name.lower().replace(' ', '-')}-{pair.product_b_name.lower().replace(' ', '-')}",
                    title=f"Bundle {pair.product_a_name} + {pair.product_b_name}",
                    summary=(
                        f"{pair.product_a_name} and {pair.product_b_name} appear together in "
                        f"{pair.co_occurrences} orders - {pair.lift:.2f}x more often than their "
                        "individual rates would predict."
                    ),
                    kind=OpportunityKind.BUNDLE,
                    estimated_value_monthly=estimated,
                    confidence=round(min(0.55 + (pair.lift - 1) * 0.25, 0.85), 2),
                    impact=_impact_for(estimated),
                    effort="LOW",
                    risk="low",
                    evidence=[
                        {
                            "metric": "Co-purchase lift",
                            "value": f"{pair.lift:.2f}x",
                            "change": None,
                            "source": "analytics",
                            "detail": (
                                f"Observed in {pair.co_occurrences} orders "
                                f"({pair.support_pct:.1f}% of all orders)."
                            ),
                            "reference": "products",
                        },
                        {
                            "metric": "Attach confidence",
                            "value": f"{pair.confidence_pct:.1f}%",
                            "change": None,
                            "source": "analytics",
                            "detail": (
                                f"Share of {pair.product_a_name} orders that also contain "
                                f"{pair.product_b_name}."
                            ),
                            "reference": "products",
                        },
                        {
                            "metric": "Combined pair revenue",
                            "value": _money(pair.combined_revenue),
                            "change": None,
                            "source": "analytics",
                            "detail": "Revenue from orders containing both products this period.",
                            "reference": "products",
                        },
                    ],
                    hypothesis=(
                        "These two items are already bought together well above chance. Pricing "
                        "them as one combo should raise the attach rate further and lift average "
                        "order value without discounting either item on its own."
                    ),
                    recommended_action=(
                        f"Create a {pair.product_a_name} + {pair.product_b_name} combo priced "
                        "below the sum of the parts and test it against a control group."
                    ),
                    graph_path=["revenue", "aov", "product_mix"],
                    target_segment={"product_ids": [str(pair.product_a_id)], "opted_in_only": True},
                    tags=["bundle", "aov", "product-mix"],
                )
            )
        return results

    # ------------------------------------------------------------------ 3. products
    def _detect_declining_products(
        self, period: PeriodInfo, products: list[ProductPerformance]
    ) -> list[DetectedOpportunity]:
        declining = [
            p for p in products if (p.change_pct or 0) <= -12 and (p.previous_revenue or 0) > 4000
        ]
        declining.sort(key=lambda p: (p.previous_revenue or 0) - p.revenue, reverse=True)

        results: list[DetectedOpportunity] = []
        for product in declining[:2]:
            lost = max((product.previous_revenue or 0) - product.revenue, 0)
            estimated = round(lost * PRODUCT_RECOVERY_RATE, 2)
            if estimated < MIN_OPPORTUNITY_VALUE:
                continue
            results.append(
                DetectedOpportunity(
                    key=f"recover-product-{product.sku.lower()}",
                    title=f"Arrest the decline in {product.name}",
                    summary=(
                        f"{product.name} revenue fell {_pct(product.change_pct)} this period, "
                        f"a loss of {_money(lost)} against the previous window."
                    ),
                    kind=OpportunityKind.PRODUCT,
                    estimated_value_monthly=estimated,
                    confidence=0.62,
                    impact=_impact_for(estimated),
                    effort="LOW",
                    risk="low",
                    evidence=[
                        {
                            "metric": f"{product.name} revenue",
                            "value": _money(product.revenue),
                            "change": _pct(product.change_pct),
                            "source": "analytics",
                            "detail": f"Down from {_money(product.previous_revenue or 0)}.",
                            "reference": "products",
                        },
                        {
                            "metric": f"{product.name} units sold",
                            "value": str(product.units_sold),
                            "change": None,
                            "source": "analytics",
                            "detail": f"Attach rate {product.attach_rate_pct:.1f}% of orders.",
                            "reference": "products",
                        },
                    ],
                    hypothesis=(
                        f"{product.name} is losing volume while the rest of the menu holds up. "
                        "It may be a merchandising or availability problem rather than a demand one."
                    ),
                    recommended_action=(
                        f"Feature {product.name} in the app and test a limited-time offer with a "
                        "control group before changing its price."
                    ),
                    graph_path=["revenue", "product_mix", f"product:{product.sku}"],
                    target_segment={
                        "product_ids": [str(product.product_id)],
                        "opted_in_only": True,
                    },
                    tags=["product", "merchandising"],
                )
            )
        return results

    # ------------------------------------------------------------------ 4. service
    async def _detect_service_pressure(
        self, period: PeriodInfo, dayparts: list[DaypartBreakdown]
    ) -> list[DetectedOpportunity]:
        """A slot where service time is degrading and complaints are rising with it."""
        results: list[DetectedOpportunity] = []
        for part in dayparts:
            drift = part.service_minutes_change_pct
            if drift is None or drift < 12:
                continue
            review_evidence = await self._review_signal_for(period, part.daypart)
            if not review_evidence:
                continue

            # Value = the revenue exposed to the degrading experience, at the rate the
            # slot is currently bleeding, partially recoverable.
            exposure = part.revenue * min(abs(part.change_pct or 0) / 100, 0.35)
            estimated = round(exposure * 0.4, 2)
            if estimated < MIN_OPPORTUNITY_VALUE:
                continue

            slot = part.label.split(" (")[0]
            results.append(
                DetectedOpportunity(
                    key=f"service-pressure-{part.daypart.lower()}",
                    title=f"Address the {slot.lower()} service slowdown",
                    summary=(
                        f"Average {slot.lower()} service time is {_pct(drift)} versus the previous "
                        "period, and complaints about it are rising in step."
                    ),
                    kind=OpportunityKind.SERVICE,
                    estimated_value_monthly=estimated,
                    confidence=0.70,
                    impact=_impact_for(estimated),
                    effort="MEDIUM",
                    risk="low",
                    evidence=[
                        {
                            "metric": f"{slot} service time",
                            "value": f"{part.avg_service_minutes:.1f} min"
                            if part.avg_service_minutes
                            else "n/a",
                            "change": _pct(drift),
                            "source": "analytics",
                            "detail": "Measured order-to-handover time on completed orders.",
                            "reference": "dashboard",
                        },
                        *review_evidence,
                    ],
                    hypothesis=(
                        f"Throughput in the {slot.lower()} slot is not keeping up with demand. "
                        "Service time and complaint volume are moving together over the same window."
                    ),
                    recommended_action=(
                        "Test a pre-assembled combo that can be handed over quickly in this slot, "
                        "and measure both service time and conversion against a control."
                    ),
                    graph_path=[
                        "revenue",
                        f"daypart:{part.daypart}",
                        f"evidence:{part.daypart}:service",
                    ],
                    target_segment={
                        "active_dayparts": [part.daypart],
                        "active_within_days": 180,
                        "opted_in_only": True,
                        "limit": 5000,
                    },
                    tags=["service", part.daypart.lower(), "operations"],
                )
            )
        return results

    # ------------------------------------------------------------------ persistence
    async def detect_and_store(self, *, days: int = 30) -> list[Any]:
        """Detect, then upsert. Idempotent - re-running refreshes rather than duplicates."""
        period = await self.analytics.resolve_period(days=days)
        detected = await self.detect(days=days)
        stored = []
        for opportunity in detected:
            stored.append(
                await self.repo.upsert(
                    key=opportunity.key,
                    title=opportunity.title,
                    summary=opportunity.summary,
                    kind=opportunity.kind,
                    estimated_value_monthly=opportunity.estimated_value_monthly,
                    confidence=opportunity.confidence,
                    impact=opportunity.impact,
                    effort=opportunity.effort,
                    risk=opportunity.risk,
                    priority_score=opportunity.priority_score,
                    status=OpportunityStatus.DETECTED,
                    evidence=opportunity.evidence,
                    hypothesis=opportunity.hypothesis,
                    recommended_action=opportunity.recommended_action,
                    reasoning=opportunity.reasoning,
                    graph_path=opportunity.graph_path,
                    target_segment=opportunity.target_segment,
                    tags=opportunity.tags,
                    requires_approval=opportunity.requires_approval,
                    detected_at=datetime.now(tz=UTC),
                    period_start=period.current.start,
                    period_end=period.current.end,
                )
            )
        return stored
