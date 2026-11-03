"""Growth Allocation Engine: "Where should the next Rs 1 of growth budget go?"

A Paypal merchant has two growth surfaces - their own existing customers
(WhatsApp, QR, checkout, loyalty) and Paypal's side (cashback, offers,
promotional placement). This module is what compares them for one detected
opportunity and decides how to split a budget across BUSINESS / PAYPAL / HYBRID,
using this merchant's own real transaction data, not invented figures.

Three things this deliberately does *not* do:

1. It never calls a live Paypal ads/acquisition API - none exists. Every "Paypal"
   number is grounded in this merchant's own history of customers whose
   `acquisition_channel` is already `paypal_app` (a real, seeded column - see
   `app/seed/generators/dataset.py`), labelled honestly as an estimate rather
   than presented as live inventory.
2. It never reports a historical-performance ratio (the "growth arbitrage")
   until at least one campaign of *each* surface has actually been measured.
   Before that it says so and falls back to an even split - see
   `historical_performance` / `growth_arbitrage`.
3. It never invents a confidence score. Confidence is a direct function of how
   many measured campaigns back a claim (`_confidence_for`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.campaign import Campaign, CampaignSurface
from app.repositories.customer import CustomerRepository

log = get_logger(__name__)

#: Estimated incentive cost as a share of the segment's own average order value.
#: Stated explicitly so every budget figure is auditable rather than "AI magic".
INCENTIVE_COST_RATE = 0.15
#: Measured campaigns of a surface required before its history is trusted for an
#: allocation decision, rather than falling back to an even default split.
MIN_EVIDENCE_COUNT = 1
#: Share of a segment that must already be high-frequency (3+ past orders)
#: before the engine recommends against a blanket discount for it.
DONT_DISCOUNT_THRESHOLD_PCT = 55.0


@dataclass(slots=True)
class InterventionOption:
    surface: str
    label: str
    audience_label: str
    audience_size: int
    historical_conversion_pct: float | None
    offer_type: str
    offer_description: str
    channel: str
    budget: float
    expected_customers: float
    expected_incremental_revenue: float
    provenance: str


@dataclass(slots=True)
class DontDiscountFinding:
    high_propensity_pct: float
    recommendation: str
    reasoning: str


@dataclass(slots=True)
class SurfacePerformance:
    surface: str
    campaigns_measured: int
    avg_incremental_revenue: float
    avg_roi: float | None


@dataclass(slots=True)
class ArbitrageFinding:
    better_surface: str
    worse_surface: str
    better_roi: float
    worse_roi: float
    evidence_count: int
    confidence: str
    recommended_shift_pct: float


@dataclass(slots=True)
class GrowthMission:
    opportunity_id: uuid.UUID | None
    title: str
    business_option: InterventionOption
    paypal_option: InterventionOption
    hybrid_option: InterventionOption
    recommended_surface: str
    recommendation_reason: str
    allocation_basis: str  # "historical" | "default"
    business_pct: float
    paypal_pct: float
    dont_discount: DontDiscountFinding | None = None
    arbitrage: ArbitrageFinding | None = None


def _confidence_for(evidence_count: int) -> str:
    if evidence_count >= 5:
        return "high"
    if evidence_count >= 3:
        return "medium"
    return "low"


class GrowthAllocationEngine:
    def __init__(self, session: AsyncSession, merchant_id: uuid.UUID) -> None:
        self.session = session
        self.merchant_id = merchant_id
        self.customers = CustomerRepository(session, merchant_id)

    # ------------------------------------------------------------------ missions
    async def generate_mission(
        self,
        *,
        title: str,
        target_segment: dict[str, Any],
        opportunity_id: uuid.UUID | None = None,
    ) -> GrowthMission:
        """The core comparison: business-side vs Paypal-side vs both, for one
        opportunity's target segment, ending in a budget split and a reason."""
        segment_filter = dict(target_segment)
        segment_filter.pop("name", None)

        business_customers = await self.customers.resolve_segment(**segment_filter)
        business_ids = [c.id for c in business_customers]
        business_stats = await self.customers.segment_stats(business_ids)
        propensity_pct = await self.customers.high_propensity_share(business_ids)
        dont_discount = self._dont_discount(propensity_pct)

        dayparts = segment_filter.get("dayparts") or segment_filter.get("active_dayparts")
        paypal_stats = await self.customers.paypal_acquired_stats(dayparts=dayparts)

        business_aov = business_stats["avg_order_value"] or 0.0
        paypal_aov = paypal_stats["avg_order_value"] or business_aov
        business_cost = round(business_aov * INCENTIVE_COST_RATE, 2)
        paypal_cost = round(paypal_aov * INCENTIVE_COST_RATE, 2)

        # Paypal's reach is capped to a comparably sized cohort, so the mission
        # compares two right-sized options rather than "everyone Paypal has ever
        # brought in" against a small, specific segment.
        paypal_reach = min(paypal_stats["size"], max(len(business_ids), 10)) if paypal_stats["size"] else 0

        business_option = self._option(
            surface=CampaignSurface.BUSINESS,
            label=f"Win back {len(business_ids)} customers directly",
            audience_label=f"{len(business_ids)} customers matching this segment",
            audience_size=len(business_ids),
            conversion_pct=propensity_pct if business_ids else None,
            aov=business_aov,
            cost_per_customer=business_cost,
            channel="whatsapp",
            provenance=(
                f"Audience and average order value computed from {len(business_ids)} real "
                "customers matching this segment - not an estimate."
            ),
        )
        paypal_option = self._option(
            surface=CampaignSurface.PAYPAL,
            label="Acquire new customers through Paypal",
            audience_label=(
                f"~{paypal_reach} customers, sized from {paypal_stats['size']} customers this "
                "merchant has historically acquired via Paypal in this slot"
                if paypal_stats["size"]
                else "No historical Paypal-acquired customers yet for this slot"
            ),
            audience_size=paypal_reach,
            conversion_pct=paypal_stats["repeat_rate_pct"] if paypal_reach else None,
            aov=paypal_aov,
            cost_per_customer=paypal_cost,
            channel="paypal_app",
            provenance=(
                "Estimated from this merchant's own history of Paypal-acquired customers - "
                "not a live Paypal audience feed (no such integration exists yet)."
            ),
        )
        hybrid_option = InterventionOption(
            surface=CampaignSurface.HYBRID,
            label="Recover existing demand + acquire through Paypal",
            audience_label=(
                f"{business_option.audience_size} existing + up to "
                f"{paypal_option.audience_size} new"
            ),
            audience_size=business_option.audience_size + paypal_option.audience_size,
            historical_conversion_pct=None,
            offer_type="COMBO",
            offer_description="Both offers below, run as one mission with a 3-way split experiment.",
            channel="whatsapp + paypal_app",
            budget=round(business_option.budget + paypal_option.budget, 2),
            expected_customers=round(
                business_option.expected_customers + paypal_option.expected_customers, 1
            ),
            expected_incremental_revenue=round(
                business_option.expected_incremental_revenue
                + paypal_option.expected_incremental_revenue,
                2,
            ),
            provenance="Combines both options above; each arm is still measured independently.",
        )

        arbitrage = await self.growth_arbitrage()
        business_perf = await self.historical_performance(CampaignSurface.BUSINESS)
        paypal_perf = await self.historical_performance(CampaignSurface.PAYPAL)

        if business_perf and paypal_perf and business_perf.avg_roi and paypal_perf.avg_roi:
            total_roi = business_perf.avg_roi + paypal_perf.avg_roi
            business_pct = round((business_perf.avg_roi / total_roi) * 100, 1) if total_roi > 0 else 50.0
            allocation_basis = "historical"
        else:
            # Cold start: no measured history yet for at least one surface - an
            # even split is the honest default, never a guessed ratio.
            business_pct = 50.0
            allocation_basis = "default"
        paypal_pct = round(100 - business_pct, 1)

        recommended_surface, reason = self._recommend_surface(
            business_option, paypal_option, dont_discount
        )

        return GrowthMission(
            opportunity_id=opportunity_id,
            title=title,
            business_option=business_option,
            paypal_option=paypal_option,
            hybrid_option=hybrid_option,
            recommended_surface=recommended_surface,
            recommendation_reason=reason,
            allocation_basis=allocation_basis,
            business_pct=business_pct,
            paypal_pct=paypal_pct,
            dont_discount=dont_discount,
            arbitrage=arbitrage,
        )

    def _option(
        self,
        *,
        surface: str,
        label: str,
        audience_label: str,
        audience_size: int,
        conversion_pct: float | None,
        aov: float,
        cost_per_customer: float,
        channel: str,
        provenance: str,
    ) -> InterventionOption:
        expected_customers = round(audience_size * (conversion_pct or 0) / 100, 1)
        return InterventionOption(
            surface=surface,
            label=label,
            audience_label=audience_label,
            audience_size=audience_size,
            historical_conversion_pct=conversion_pct,
            offer_type="CASHBACK" if surface == CampaignSurface.PAYPAL else (
                "FREE_ITEM" if aov and aov < 500 else "CASHBACK"
            ),
            offer_description=(
                f"Rs {cost_per_customer:,.0f} incentive on orders near Rs {aov:,.0f} "
                f"({INCENTIVE_COST_RATE:.0%} of this group's average order value)"
                if aov
                else "Not enough order history to size an offer yet"
            ),
            channel=channel,
            budget=round(audience_size * cost_per_customer, 2),
            expected_customers=expected_customers,
            expected_incremental_revenue=round(expected_customers * aov, 2),
            provenance=provenance,
        )

    def _dont_discount(self, high_propensity_pct: float) -> DontDiscountFinding | None:
        if high_propensity_pct < DONT_DISCOUNT_THRESHOLD_PCT:
            return None
        return DontDiscountFinding(
            high_propensity_pct=high_propensity_pct,
            recommendation="Don't run a blanket discount for this segment.",
            reasoning=(
                f"{high_propensity_pct:.0f}% of this segment has already placed 3 or more "
                "orders - they historically buy without an incentive. A blanket discount "
                f"would mostly pay for orders that would have happened anyway. Target the "
                f"remaining {100 - high_propensity_pct:.0f}% specifically, or use Paypal "
                "acquisition to reach people who aren't already your customers."
            ),
        )

    def _recommend_surface(
        self,
        business: InterventionOption,
        paypal: InterventionOption,
        dont_discount: DontDiscountFinding | None,
    ) -> tuple[str, str]:
        if business.audience_size == 0 and paypal.audience_size == 0:
            return (
                CampaignSurface.BUSINESS,
                "No matching customers found on either surface yet - not enough data to "
                "recommend a specific split.",
            )
        if business.audience_size == 0:
            return (
                CampaignSurface.PAYPAL,
                "No existing customers match this segment, so there is nothing to win back - "
                "acquire through Paypal instead.",
            )
        if paypal.audience_size == 0:
            return (
                CampaignSurface.BUSINESS,
                "No historical Paypal-acquired customers for this slot yet - win back the "
                "existing segment directly.",
            )
        if dont_discount:
            return (
                CampaignSurface.PAYPAL,
                dont_discount.reasoning + " Lean toward Paypal acquisition for this mission.",
            )
        return (
            CampaignSurface.HYBRID,
            "Existing customers have a known reactivation rate and there is unused capacity "
            "in this slot to also acquire new ones - both at once outperforms either alone.",
        )

    # ------------------------------------------------------------------ history
    async def historical_performance(self, surface: str) -> SurfacePerformance | None:
        """Real, measured performance for one surface - `None`, not a fabricated
        number, until at least `MIN_EVIDENCE_COUNT` campaigns have actually been
        measured (`Campaign.actual_incremental_revenue` is only ever set by
        `ExperimentService._sync_campaign`, from a real measurement)."""
        stmt = select(
            func.count(Campaign.id),
            func.avg(Campaign.actual_incremental_revenue),
            func.avg(Campaign.incremental_roi),
        ).where(
            Campaign.merchant_id == self.merchant_id,
            Campaign.surface == surface,
            Campaign.actual_incremental_revenue.is_not(None),
        )
        row = (await self.session.execute(stmt)).one()
        count = int(row[0] or 0)
        if count < MIN_EVIDENCE_COUNT:
            return None
        return SurfacePerformance(
            surface=surface,
            campaigns_measured=count,
            avg_incremental_revenue=round(float(row[1] or 0), 2),
            avg_roi=round(float(row[2]), 4) if row[2] is not None else None,
        )

    async def growth_arbitrage(self) -> ArbitrageFinding | None:
        """The "same incentive, different return depending on where it runs"
        insight - only ever returned once both surfaces have measured evidence."""
        business = await self.historical_performance(CampaignSurface.BUSINESS)
        paypal = await self.historical_performance(CampaignSurface.PAYPAL)
        if not business or not paypal or business.avg_roi is None or paypal.avg_roi is None:
            return None
        if business.avg_roi == paypal.avg_roi:
            return None

        better, worse = (
            (business, paypal) if business.avg_roi > paypal.avg_roi else (paypal, business)
        )
        evidence = better.campaigns_measured + worse.campaigns_measured
        total_roi = (better.avg_roi or 0) + abs(worse.avg_roi or 0)
        shift_pct = round(((better.avg_roi or 0) / total_roi) * 100, 1) if total_roi else 50.0
        return ArbitrageFinding(
            better_surface=better.surface,
            worse_surface=worse.surface,
            better_roi=better.avg_roi,
            worse_roi=worse.avg_roi or 0.0,
            evidence_count=evidence,
            confidence=_confidence_for(evidence),
            recommended_shift_pct=shift_pct,
        )

    async def allocation_snapshot(self) -> dict[str, Any]:
        """Where the growth budget has actually gone, by surface - committed
        budget and measured incremental revenue from `RUNNING`/`COMPLETED`
        campaigns, for the Command Center's Growth Allocation widget.

        Uses `Campaign.budget` (what was committed to the mission), not
        `actual_cost` (a different, older number: simulated per-recipient
        messaging cost, which is 0 for any campaign without a built audience,
        including most dual-market missions that spend through an offer/cashback
        incentive rather than a priced message send).
        """
        stmt = (
            select(
                Campaign.surface,
                func.coalesce(func.sum(Campaign.budget), 0),
                func.coalesce(func.sum(Campaign.actual_incremental_revenue), 0),
                func.count(Campaign.id),
            )
            .where(
                Campaign.merchant_id == self.merchant_id,
                Campaign.status.in_(["RUNNING", "COMPLETED"]),
            )
            .group_by(Campaign.surface)
        )
        rows = (await self.session.execute(stmt)).all()
        by_surface: dict[str, dict[str, float]] = {
            row[0]: {
                "spend": round(float(row[1] or 0), 2),
                "incremental_revenue": round(float(row[2] or 0), 2),
                "campaigns": int(row[3] or 0),
            }
            for row in rows
        }
        total_spend = sum(v["spend"] for v in by_surface.values())
        business_spend = by_surface.get(CampaignSurface.BUSINESS, {}).get("spend", 0.0)
        paypal_spend = by_surface.get(CampaignSurface.PAYPAL, {}).get("spend", 0.0)
        hybrid_spend = by_surface.get(CampaignSurface.HYBRID, {}).get("spend", 0.0)
        return {
            "by_surface": by_surface,
            "business_pct": round((business_spend / total_spend) * 100, 1) if total_spend else 0.0,
            "paypal_pct": round((paypal_spend / total_spend) * 100, 1) if total_spend else 0.0,
            "hybrid_pct": round((hybrid_spend / total_spend) * 100, 1) if total_spend else 0.0,
            "total_spend": round(total_spend, 2),
            "total_incremental_revenue": round(
                sum(v["incremental_revenue"] for v in by_surface.values()), 2
            ),
            "has_data": total_spend > 0,
        }
