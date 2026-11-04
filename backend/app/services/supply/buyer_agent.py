"""The Buyer Agent: negotiates for the merchant, inside the merchant's limits.

The buyer's counter is computed deterministically from the frozen policy
(``ProcurementConstraints``) and the supplier's last offer. When an LLM is
configured, a *strategist* may propose a different counter price and the
negotiating language for each open session in a round. That proposal is
recorded verbatim, then checked by ``validate_buyer_counter``: if it is inside
the policy it is used, otherwise it is refused and the deterministic counter
stands. Either way the UI shows which happened.

The buyer never reveals the merchant's ceiling or budget, and never quotes one
supplier's price to another - "competitive pressure" is a boolean.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.integrations.groq import llm_service
from app.services.supply.policy import (
    ZERO,
    D,
    ProcurementConstraints,
    max_unit_price_for,
    unit_amount,
    unit_price_for_landed_target,
    validate_buyer_counter,
)

log = get_logger(__name__)


@dataclass(frozen=True)
class OfferSnapshot:
    """The supplier's latest offer, as the buyer sees it (public terms only)."""

    session_id: str
    supplier_label: str
    unit_price: Decimal
    quantity: Decimal
    shipping: Decimal
    tax_rate: Decimal
    lead_time_days: int
    landed_total: Decimal
    landed_unit_cost: Decimal
    within_policy: bool
    violations: tuple[str, ...] = ()


@dataclass
class BuyerMove:
    kind: str  # COUNTER | HOLD (the buyer is satisfied with this offer)
    unit_price: Decimal = ZERO
    quantity: Decimal = ZERO
    request_free_shipping: bool = False
    request_expedite: bool = False
    competitive_pressure: bool = False
    note: str = ""
    proposed_by: str = "BUYER_STRATEGY"
    ai_proposal: dict[str, Any] = field(default_factory=dict)


class BuyerStrategy:
    def __init__(self, constraints: ProcurementConstraints) -> None:
        self.c = constraints

    def ceiling_price(self, offer: OfferSnapshot) -> Decimal:
        return max_unit_price_for(
            constraints=self.c, shipping=offer.shipping, tax_rate=offer.tax_rate, quantity=self.c.quantity
        )

    def counter(
        self,
        offer: OfferSnapshot,
        *,
        round_number: int,
        best_competing_landed_unit: Decimal | None,
    ) -> BuyerMove:
        """Next move against one supplier. Pure function of policy + public offer."""
        # Satisfied: inside policy and at or under the aspiration target.
        if offer.within_policy and offer.landed_unit_cost <= self.c.target_unit_cost:
            return BuyerMove(kind="HOLD", note="Offer meets our target.")

        # The buyer always asks for shipping to be included, so the aspiration price
        # is computed as if it were.
        target_price = unit_price_for_landed_target(
            target_unit_cost=self.c.target_unit_cost,
            quantity=self.c.quantity,
            shipping=ZERO,
            tax_rate=offer.tax_rate,
        )
        ceiling = self.ceiling_price(offer)
        # Open at the aspiration price; give ground each round, never past the ceiling.
        give = Decimal(max(round_number - 1, 0)) / Decimal(max(self.c.max_rounds, 1)) * Decimal("0.5")
        price = target_price + (offer.unit_price - target_price) * give
        price = unit_amount(min(price, ceiling, offer.unit_price - Decimal("0.01")))
        if price <= 0:
            price = unit_amount(offer.unit_price * Decimal("0.9"))

        pressure = (
            best_competing_landed_unit is not None
            and best_competing_landed_unit < offer.landed_unit_cost
        )
        request_expedite = offer.lead_time_days > self.c.max_delivery_days
        request_free_shipping = offer.shipping > 0
        parts = [f"We can do {price:.2f} per unit for {self.c.quantity:f} units."]
        if request_free_shipping:
            parts.append("We'd need shipping included.")
        if request_expedite:
            parts.append(f"We need delivery within {self.c.max_delivery_days} days.")
        if pressure:
            parts.append("We have a more competitive landed offer on the table.")
        return BuyerMove(
            kind="COUNTER",
            unit_price=price,
            quantity=self.c.quantity,
            request_free_shipping=request_free_shipping,
            request_expedite=request_expedite,
            competitive_pressure=pressure,
            note=" ".join(parts),
        )


# --------------------------------------------------------------------------- #
# Optional LLM strategist
# --------------------------------------------------------------------------- #
class StrategistMove(BaseModel):
    session_id: str
    counter_unit_price: float | None = None
    request_free_shipping: bool | None = None
    request_expedite: bool | None = None
    message: str = Field(default="", max_length=600)


class StrategistPlan(BaseModel):
    moves: list[StrategistMove] = Field(default_factory=list)
    summary: str = Field(default="", max_length=800)


STRATEGIST_SYSTEM = (
    "You are a procurement negotiation strategist for a small US merchant. You see each "
    "supplier's latest public offer and the deterministic counter the buyer agent plans. "
    "For each session you may propose a counter unit price and write a short, professional "
    "negotiating message (no more than two sentences). Rules: never reveal the merchant's "
    "ceiling, budget, margin or another supplier's price; never invent a number the buyer "
    "did not give you except the counter price; your counter price will be checked against "
    "the merchant's limits by the backend and refused if outside them. Respond as JSON: "
    '{"moves":[{"session_id":"...","counter_unit_price":12.34,"request_free_shipping":true,'
    '"request_expedite":false,"message":"..."}],"summary":"..."}'
)


async def strategist_review(
    *,
    product_name: str,
    quantity: Decimal,
    round_number: int,
    offers: list[OfferSnapshot],
    planned: dict[str, BuyerMove],
    trace: Any = None,
) -> tuple[StrategistPlan | None, bool]:
    """Ask the LLM for counter proposals. Returns (plan, used_llm)."""
    if not llm_service.enabled or not planned:
        return None, False
    lines = []
    for offer in offers:
        move = planned.get(offer.session_id)
        if move is None:
            continue
        lines.append(
            {
                "session_id": offer.session_id,
                "supplier": offer.supplier_label,
                "their_unit_price": str(offer.unit_price),
                "their_quantity": str(offer.quantity),
                "their_shipping": str(offer.shipping),
                "their_lead_time_days": offer.lead_time_days,
                "planned_counter_unit_price": str(move.unit_price),
                "planned_requests": {
                    "free_shipping": move.request_free_shipping,
                    "expedite": move.request_expedite,
                },
            }
        )
    import json

    user = (
        f"Product: {product_name}. Quantity needed: {quantity:f}. Round {round_number}.\n"
        f"Open sessions:\n{json.dumps(lines, indent=2)}"
    )
    plan, result = await llm_service.structured(
        system=STRATEGIST_SYSTEM,
        user=user,
        schema=StrategistPlan,
        fallback=StrategistPlan(),
        trace=trace,
        trace_name="buyer_strategist",
    )
    if result.used_fallback or not plan.moves:
        return None, False
    return plan, True


def apply_strategist(
    move: BuyerMove,
    proposal: StrategistMove | None,
    *,
    offer: OfferSnapshot,
    ceiling: Decimal,
) -> BuyerMove:
    """Use the model's proposal only if the backend's bounds accept it."""
    if proposal is None or move.kind != "COUNTER":
        return move
    record: dict[str, Any] = {
        "counter_unit_price": proposal.counter_unit_price,
        "request_free_shipping": proposal.request_free_shipping,
        "request_expedite": proposal.request_expedite,
        "message": proposal.message,
    }
    if proposal.counter_unit_price is not None:
        accepted, reason = validate_buyer_counter(
            proposed_unit_price=D(str(proposal.counter_unit_price)),
            supplier_unit_price=offer.unit_price,
            ceiling_unit_price=ceiling,
        )
        record["validation"] = reason
        if accepted is not None:
            move.unit_price = accepted
            move.proposed_by = "LLM"
            record["accepted"] = True
        else:
            record["accepted"] = False
    if proposal.message:
        move.note = proposal.message.strip()
    if proposal.request_free_shipping is not None and offer.shipping > 0:
        move.request_free_shipping = bool(proposal.request_free_shipping)
    if proposal.request_expedite is not None:
        move.request_expedite = bool(proposal.request_expedite) or move.request_expedite
    move.ai_proposal = record
    return move
