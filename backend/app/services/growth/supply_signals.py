"""Supply-aware growth opportunities - where Growth and Procurement meet.

Four deterministic detectors, each with an explicit formula:

* **Capture rising demand** (demand up AND stockout risk):
  value = extra units/day x 30 x selling price - the revenue the merchant keeps
  only if stock lands in time. Action: restock through the Supply Agents and hold
  promotions on that SKU until it does.
* **Inventory-aware promotion** (overstock):
  value = excess units x unit margin x sell-through assumption.
* **Procurement margin improvement** (a supplier agent's indicative price is
  below the current unit cost): value = (cost - best price) x units/day x 30.
* **Subscription recovery** (failed PayPal subscription payments):
  value = at-risk monthly revenue x recovery assumption.

``apply_inventory_constraints`` then edits *other* opportunities: anything that
would promote a product about to run out is down-weighted and annotated, because
a campaign that sells stock you cannot replenish destroys trust, not just margin.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.growth import OpportunityKind
from app.db.models.inventory import InventoryItem
from app.db.models.paypal import PayPalSubscriptionRecord
from app.db.models.procurement import VendorProduct
from app.db.models.supply import SupplierAgent, SupplierAgentStatus
from app.services.supply.demand import InventoryIntelligence
from app.services.supply.policy import D, money

#: Share of overstock a promotion realistically sells through in a month.
OVERSTOCK_SELL_THROUGH = Decimal("0.30")
#: Share of failed-payment subscriptions a recovery flow realistically saves.
SUBSCRIPTION_RECOVERY_RATE = Decimal("0.50")


def _impact(value: Decimal) -> str:
    if value >= 400:
        return "HIGH"
    if value >= 150:
        return "MEDIUM"
    return "LOW"


async def supply_aware_opportunities(session: AsyncSession, merchant_id: uuid.UUID) -> list[Any]:
    from app.services.growth.detector import DetectedOpportunity

    found: list[DetectedOpportunity] = []
    assessments = await InventoryIntelligence(session, merchant_id).scan()

    for a in assessments:
        if a.demand_increased and a.stockout_risk and a.selling_price > 0:
            extra_per_day = max(a.velocity_recent - a.velocity_prior, Decimal("0"))
            value = money(extra_per_day * 30 * a.selling_price)
            found.append(DetectedOpportunity(
                key=f"supply-demand-{a.sku.lower()}",
                title=f"Capture rising demand for {a.product_name}",
                summary=(f"Demand is up {a.demand_change_pct}% ({a.velocity_prior}/day -> {a.velocity_recent}/day) "
                         f"but only {a.days_of_cover} days of cover remain against a {a.lead_time_days}-day lead time."),
                kind=OpportunityKind.INVENTORY,
                estimated_value_monthly=float(value),
                confidence=0.82,
                impact=_impact(value),
                effort="LOW",
                risk="low",
                evidence=[
                    {"metric": "Sales velocity", "value": f"{a.velocity_recent}/day", "change": f"{a.demand_change_pct:+}%", "source": "transactions"},
                    {"metric": "Days of cover", "value": str(a.days_of_cover), "source": "inventory"},
                    {"metric": "Suggested reorder", "value": f"{a.suggested_quantity:f} {a.unit}", "source": "inventory intelligence"},
                ],
                hypothesis=("Rising demand and falling cover are observed together; if stock runs out before the "
                            "next delivery, the extra demand is lost. This is a supply constraint, not a demand problem."),
                recommended_action=(f"Restock {a.suggested_quantity:f} {a.unit} through the Supply Agents within "
                                    f"{a.required_within_days} days, and hold promotions on {a.product_name} until it lands."),
                reasoning=f"Value = extra {extra_per_day}/day x 30 days x ${a.selling_price} selling price.",
                graph_path=["revenue", "product_demand", "inventory_cover"],
                target_segment={"sku": a.sku, "inventory_item_id": a.inventory_item_id},
                tags=["supply", "procurement", a.sku.lower()],
                requires_approval=True,
            ))
        if a.overstocked and a.unit_cost > 0 and a.selling_price > a.unit_cost:
            excess = max(a.available - a.velocity_recent * a.target_cover_days, Decimal("0"))
            value = money(excess * (a.selling_price - a.unit_cost) * OVERSTOCK_SELL_THROUGH)
            if value > 0:
                found.append(DetectedOpportunity(
                    key=f"supply-overstock-{a.sku.lower()}",
                    title=f"Promote overstocked {a.product_name}",
                    summary=f"{a.days_of_cover} days of cover - well above the {a.target_cover_days}-day target.",
                    kind=OpportunityKind.INVENTORY,
                    estimated_value_monthly=float(value),
                    confidence=0.6,
                    impact=_impact(value),
                    effort="LOW",
                    risk="low",
                    evidence=[{"metric": "Days of cover", "value": str(a.days_of_cover), "source": "inventory"},
                              {"metric": "Excess units", "value": f"{excess:f}", "source": "inventory intelligence"}],
                    hypothesis="Stock is tied up beyond what demand needs; a targeted promotion converts it to cash.",
                    recommended_action=f"Bundle or feature {a.product_name} in the next campaign.",
                    reasoning=f"Value = {excess:f} excess x unit margin x {OVERSTOCK_SELL_THROUGH:.0%} sell-through.",
                    graph_path=["gross_margin", "inventory_cover"],
                    target_segment={"sku": a.sku},
                    tags=["supply", "promotion", a.sku.lower()],
                ))

    # Procurement margin improvement: is a supplier agent cheaper than our current cost?
    items = {i.id: i for i in (await session.execute(
        select(InventoryItem).where(InventoryItem.merchant_id == merchant_id)
    )).scalars().all()}
    velocity = {a.inventory_item_id: a for a in assessments}
    supplies = (await session.execute(
        select(VendorProduct, SupplierAgent)
        .join(SupplierAgent, SupplierAgent.vendor_id == VendorProduct.vendor_id)
        .where(VendorProduct.merchant_id == merchant_id, SupplierAgent.status == SupplierAgentStatus.ONLINE)
    )).all()
    best: dict[uuid.UUID, tuple[Decimal, str]] = {}
    for supply, agent in supplies:
        price = D(supply.unit_price)
        current = best.get(supply.inventory_item_id)
        if current is None or price < current[0]:
            best[supply.inventory_item_id] = (price, agent.display_name)
    for item_id, (price, supplier) in best.items():
        item = items.get(item_id)
        a = velocity.get(str(item_id))
        if item is None or a is None or a.velocity_recent <= 0:
            continue
        gap = D(item.unit_cost) - price
        if gap <= 0:
            continue
        value = money(gap * a.velocity_recent * 30)
        found.append(DetectedOpportunity(
            key=f"supply-savings-{item.sku.lower()}",
            title=f"Lower the unit cost of {item.product_name}",
            summary=f"{supplier} lists it at ${price:.2f} against a current cost of ${D(item.unit_cost):.2f}.",
            kind=OpportunityKind.PRICING,
            estimated_value_monthly=float(value),
            confidence=0.55,
            impact=_impact(value),
            effort="MEDIUM",
            risk="low",
            evidence=[{"metric": "Current unit cost", "value": f"${D(item.unit_cost):.2f}", "source": "inventory"},
                      {"metric": "Best indicative price", "value": f"${price:.2f}", "source": supplier}],
            hypothesis="An indicative list price is not a landed cost; negotiation decides whether the saving is real.",
            recommended_action="Run an RFQ through the Supply Agents and let the buyer agent negotiate landed cost.",
            reasoning=f"Value = ${gap:.2f} per unit x {a.velocity_recent}/day x 30 days (before shipping and tax).",
            graph_path=["gross_margin", "unit_cost"],
            target_segment={"sku": item.sku},
            tags=["supply", "margin", item.sku.lower()],
        ))

    # Subscription recovery from PayPal subscription failures.
    subs = (await session.execute(
        select(PayPalSubscriptionRecord).where(
            PayPalSubscriptionRecord.merchant_id == merchant_id, PayPalSubscriptionRecord.failed_payments > 0
        )
    )).scalars().all()
    if subs:
        at_risk = sum((D(s.amount) for s in subs), Decimal("0"))
        value = money(at_risk * SUBSCRIPTION_RECOVERY_RATE)
        found.append(DetectedOpportunity(
            key="paypal-subscription-recovery",
            title="Recover failed subscription payments",
            summary=f"{len(subs)} PayPal subscription(s) have failed payments worth ${at_risk:.2f}/month.",
            kind=OpportunityKind.RETENTION,
            estimated_value_monthly=float(value),
            confidence=0.65,
            impact=_impact(value),
            effort="LOW",
            risk="low",
            evidence=[{"metric": "Subscriptions with failed payments", "value": str(len(subs)), "source": "PayPal webhooks"},
                      {"metric": "Monthly revenue at risk", "value": f"${at_risk:.2f}", "source": "PayPal subscriptions"}],
            hypothesis="Most failed recurring payments are card or balance issues, not cancellations.",
            recommended_action="Send a recovery reminder and reactivate after the payer updates their funding source.",
            reasoning=f"Value = ${at_risk:.2f} at risk x {SUBSCRIPTION_RECOVERY_RATE:.0%} recovery.",
            graph_path=["revenue", "subscriptions"],
            tags=["paypal", "subscriptions"],
        ))
    return found


async def apply_inventory_constraints(session: AsyncSession, merchant_id: uuid.UUID, found: list[Any]) -> list[Any]:
    """Down-weight growth opportunities that would promote a product about to run out."""
    assessments = await InventoryIntelligence(session, merchant_id).scan()
    at_risk = {a.product_name.lower(): a for a in assessments if a.stockout_risk}
    if not at_risk:
        return found
    for opp in found:
        if "supply" in (opp.tags or []):
            continue
        text = f"{opp.title} {opp.summary} {opp.recommended_action}".lower()
        hits = [a for name, a in at_risk.items() if name in text]
        if not hits:
            continue
        a = hits[0]
        opp.confidence = round(opp.confidence * 0.6, 3)
        opp.evidence = [*opp.evidence, {
            "metric": "Inventory constraint", "value": f"{a.days_of_cover} days of cover",
            "source": "inventory intelligence",
            "detail": f"{a.product_name} may stock out before a campaign completes - restock first.",
        }]
        opp.recommended_action = f"{opp.recommended_action} (Hold until {a.product_name} is restocked.)"
        opp.tags = [*(opp.tags or []), "inventory-constrained"]
    return found
