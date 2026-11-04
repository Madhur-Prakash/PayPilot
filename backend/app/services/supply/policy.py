"""The deterministic financial and negotiation engine.

This module is a security boundary. Every amount in the procurement workflow -
the most the merchant may pay per unit, the total budget, a landed cost, a
saving, an invoice variance, a new inventory valuation - is computed here, in
``Decimal``, from stored data. A language model may *propose* a negotiating move
and may phrase one; it never produces a number that is enforced or persisted
without passing through ``validate_offer``.

Worked example (the one in the product brief)::

    expected selling price  $25.00
    target gross margin      40%
    max landed unit cost     $25.00 x (1 - 0.40) = $15.00
    quantity                 100
    max procurement budget   $1,500.00
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from app.core.config import settings

CENT = Decimal("0.01")
UNIT = Decimal("0.0001")
RATIO = Decimal("0.0001")
ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")

#: Bumped whenever the rules below change meaning. Frozen into every policy
#: snapshot, so an approval always records which rulebook it was granted under.
POLICY_ENGINE_VERSION = "2026.11-1"


# --------------------------------------------------------------------------- #
# Decimal helpers
# --------------------------------------------------------------------------- #
def D(value: Any) -> Decimal:
    """Coerce to Decimal without ever passing through binary float."""
    if isinstance(value, Decimal):
        return value
    if value is None or value == "":
        return ZERO
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Not a valid amount: {value!r}") from exc


def money(value: Any) -> Decimal:
    return D(value).quantize(CENT, rounding=ROUND_HALF_UP)


def unit_amount(value: Any) -> Decimal:
    return D(value).quantize(UNIT, rounding=ROUND_HALF_UP)


def ratio(value: Any) -> Decimal:
    return D(value).quantize(RATIO, rounding=ROUND_HALF_UP)


def pct(numerator: Any, denominator: Any) -> Decimal:
    """Percentage, 2 dp. Zero denominator gives zero, never an exception."""
    denominator = D(denominator)
    if denominator == 0:
        return ZERO
    return (D(numerator) / denominator * HUNDRED).quantize(CENT, rounding=ROUND_HALF_UP)


def canonical(payload: Any) -> str:
    """Stable JSON for hashing: sorted keys, Decimals as strings."""

    def default(value: Any) -> Any:
        if isinstance(value, Decimal):
            return format(value, "f")
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=default)


def sha256(payload: Any) -> str:
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


def serialisable(payload: Any) -> Any:
    """Decimals -> strings, recursively, for JSON columns."""
    return json.loads(canonical(payload))


# --------------------------------------------------------------------------- #
# Policy
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ProcurementConstraints:
    """The merchant's limits for one purchase, computed before any agent speaks."""

    currency: str
    quantity: Decimal
    expected_selling_price: Decimal
    target_margin: Decimal
    #: Most the merchant may pay per unit, landed (price + shipping + tax).
    max_unit_cost: Decimal
    #: What the buyer agent aims for.
    target_unit_cost: Decimal
    max_budget: Decimal
    max_delivery_days: int
    min_reliability: Decimal
    max_rounds: int
    engine_version: str = POLICY_ENGINE_VERSION
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def version(self) -> str:
        """A content hash: two identical policies share a version, any change makes a new one."""
        return f"pol-{sha256(self.as_dict(include_version=False))[:16]}"

    def as_dict(self, *, include_version: bool = True) -> dict[str, Any]:
        data = asdict(self)
        data["notes"] = list(self.notes)
        if include_version:
            data["policy_version"] = self.version
        return serialisable(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProcurementConstraints:
        return cls(
            currency=str(data["currency"]),
            quantity=D(data["quantity"]),
            expected_selling_price=D(data["expected_selling_price"]),
            target_margin=D(data["target_margin"]),
            max_unit_cost=D(data["max_unit_cost"]),
            target_unit_cost=D(data["target_unit_cost"]),
            max_budget=D(data["max_budget"]),
            max_delivery_days=int(data["max_delivery_days"]),
            min_reliability=D(data["min_reliability"]),
            max_rounds=int(data["max_rounds"]),
            engine_version=str(data.get("engine_version", POLICY_ENGINE_VERSION)),
            notes=tuple(data.get("notes") or ()),
        )


def compute_constraints(
    *,
    expected_selling_price: Any,
    quantity: Any,
    target_margin: Any | None = None,
    max_delivery_days: int = 7,
    min_reliability: Any = "0.80",
    max_rounds: int | None = None,
    budget_cap: Any | None = None,
    aspiration_discount: Any = "0.12",
    currency: str | None = None,
) -> ProcurementConstraints:
    """Derive the purchase limits. Pure function of its inputs."""
    price = money(expected_selling_price)
    qty = D(quantity)
    margin = ratio(target_margin if target_margin is not None else settings.procurement_default_target_margin)
    if price <= 0:
        raise ValueError("Expected selling price must be positive.")
    if qty <= 0:
        raise ValueError("Quantity must be positive.")
    if not (ZERO <= margin < ONE):
        raise ValueError("Target margin must be between 0 and 1.")

    notes: list[str] = []
    max_unit = unit_amount(price * (ONE - margin))
    budget = money(max_unit * qty)
    if budget_cap is not None and money(budget_cap) < budget:
        budget = money(budget_cap)
        # A tighter budget tightens the per-unit ceiling too.
        max_unit = min(max_unit, unit_amount(budget / qty))
        notes.append("Budget cap is tighter than the margin target and governs.")

    target = unit_amount(max_unit * (ONE - D(aspiration_discount)))
    rounds = min(
        max_rounds if max_rounds is not None else settings.procurement_max_negotiation_rounds,
        settings.procurement_max_negotiation_rounds,
    )
    return ProcurementConstraints(
        currency=currency or settings.default_currency,
        quantity=qty,
        expected_selling_price=price,
        target_margin=margin,
        max_unit_cost=max_unit,
        target_unit_cost=target,
        max_budget=budget,
        max_delivery_days=int(max_delivery_days),
        min_reliability=ratio(min_reliability),
        max_rounds=max(1, int(rounds)),
        notes=tuple(notes),
    )


# --------------------------------------------------------------------------- #
# Landed cost
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class LandedCost:
    subtotal: Decimal
    shipping: Decimal
    tax: Decimal
    total: Decimal
    unit_cost: Decimal

    def as_dict(self) -> dict[str, str]:
        return serialisable(asdict(self))


def landed_cost(*, unit_price: Any, quantity: Any, shipping: Any, tax_rate: Any) -> LandedCost:
    qty = D(quantity)
    subtotal = money(D(unit_price) * qty)
    shipping_amount = money(shipping)
    tax = money(subtotal * D(tax_rate))
    total = money(subtotal + shipping_amount + tax)
    per_unit = unit_amount(total / qty) if qty > 0 else ZERO
    return LandedCost(subtotal=subtotal, shipping=shipping_amount, tax=tax, total=total, unit_cost=per_unit)


def shipping_charge(
    *, flat: Any, per_unit: Any, free_threshold: Any, subtotal: Any, quantity: Any
) -> Decimal:
    threshold = D(free_threshold)
    if threshold > 0 and D(subtotal) >= threshold:
        return ZERO
    return money(D(flat) + D(per_unit) * D(quantity))


def max_unit_price_for(
    *, constraints: ProcurementConstraints, shipping: Any, tax_rate: Any, quantity: Any | None = None
) -> Decimal:
    """Highest unit price whose landed cost still fits the per-unit ceiling and budget."""
    qty = D(quantity) if quantity is not None else constraints.quantity
    if qty <= 0:
        return ZERO
    ceiling_total = min(constraints.max_unit_cost * qty, constraints.max_budget)
    price = (ceiling_total - D(shipping)) / (qty * (ONE + D(tax_rate)))
    return max(ZERO, price.quantize(UNIT, rounding=ROUND_HALF_UP))


def unit_price_for_landed_target(
    *, target_unit_cost: Any, quantity: Any, shipping: Any, tax_rate: Any
) -> Decimal:
    qty = D(quantity)
    if qty <= 0:
        return ZERO
    price = (D(target_unit_cost) * qty - D(shipping)) / (qty * (ONE + D(tax_rate)))
    return max(ZERO, price.quantize(UNIT, rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------- #
# Offer validation
# --------------------------------------------------------------------------- #
@dataclass
class OfferCheck:
    status: str  # VALID | OUT_OF_POLICY | INVALID
    errors: list[dict[str, str]]
    landed: LandedCost | None

    @property
    def within_policy(self) -> bool:
        return self.status == "VALID"


def validate_offer(
    *,
    constraints: ProcurementConstraints,
    unit_price: Any,
    quantity: Any,
    shipping: Any,
    tax_rate: Any,
    lead_time_days: int,
    reliability: Any,
    claimed_total: Any | None = None,
    available_quantity: Any | None = None,
    min_order_quantity: Any | None = None,
) -> OfferCheck:
    """Check one offer against arithmetic and the merchant's policy.

    ``claimed_total`` is whatever the proposer said the total was. It is never
    used - the landed cost is always recomputed - but a mismatch marks the offer
    INVALID, which is how a hallucinated or tampered total is caught.
    """
    errors: list[dict[str, str]] = []
    price, qty = D(unit_price), D(quantity)

    if price <= 0:
        errors.append({"code": "NON_POSITIVE_PRICE", "message": "Unit price must be positive."})
    if qty <= 0:
        errors.append({"code": "NON_POSITIVE_QUANTITY", "message": "Quantity must be positive."})
    if lead_time_days < 0:
        errors.append({"code": "NEGATIVE_LEAD_TIME", "message": "Lead time cannot be negative."})
    if D(shipping) < 0:
        errors.append({"code": "NEGATIVE_SHIPPING", "message": "Shipping cannot be negative."})
    if errors:
        return OfferCheck(status="INVALID", errors=errors, landed=None)

    landed = landed_cost(unit_price=price, quantity=qty, shipping=shipping, tax_rate=tax_rate)

    if claimed_total is not None and money(claimed_total) != landed.total:
        return OfferCheck(
            status="INVALID",
            errors=[
                {
                    "code": "TOTAL_MISMATCH",
                    "message": f"Claimed total {money(claimed_total)} does not equal the recomputed "
                    f"landed total {landed.total}.",
                }
            ],
            landed=landed,
        )
    if available_quantity is not None and qty > D(available_quantity):
        return OfferCheck(
            status="INVALID",
            errors=[{"code": "EXCEEDS_STOCK", "message": "Offer exceeds the supplier's available stock."}],
            landed=landed,
        )

    if landed.unit_cost > constraints.max_unit_cost:
        errors.append(
            {
                "code": "OVER_MAX_UNIT_COST",
                "message": f"Landed unit cost {landed.unit_cost:.2f} exceeds the "
                f"{constraints.max_unit_cost:.2f} ceiling.",
            }
        )
    if landed.total > constraints.max_budget and qty <= constraints.quantity:
        errors.append(
            {
                "code": "OVER_BUDGET",
                "message": f"Landed total {landed.total} exceeds the {constraints.max_budget} budget.",
            }
        )
    if qty > constraints.quantity and landed.total > money(constraints.max_unit_cost * qty):
        errors.append({"code": "OVER_BUDGET", "message": "Upsized quantity breaks the per-unit ceiling."})
    if lead_time_days > constraints.max_delivery_days:
        errors.append(
            {
                "code": "TOO_SLOW",
                "message": f"Delivers in {lead_time_days} days; the requirement is "
                f"{constraints.max_delivery_days}.",
            }
        )
    if D(reliability) < constraints.min_reliability:
        errors.append(
            {
                "code": "BELOW_MIN_RELIABILITY",
                "message": f"Reliability {D(reliability):.0%} is below the "
                f"{constraints.min_reliability:.0%} minimum.",
            }
        )
    if qty < constraints.quantity:
        errors.append(
            {
                "code": "PARTIAL_QUANTITY",
                "message": f"Covers {qty:f} of the {constraints.quantity:f} required.",
            }
        )
    if min_order_quantity is not None and qty < D(min_order_quantity):
        errors.append({"code": "BELOW_MOQ", "message": "Below the supplier's minimum order quantity."})

    return OfferCheck(status="OUT_OF_POLICY" if errors else "VALID", errors=errors, landed=landed)


def validate_buyer_counter(
    *,
    proposed_unit_price: Any,
    supplier_unit_price: Any,
    ceiling_unit_price: Any,
) -> tuple[Decimal | None, str]:
    """Bound a proposed counter (from a model or a person).

    Returns ``(accepted_price, reason)``. A counter must be positive, strictly
    below what the supplier is asking (otherwise it is an acceptance), and never
    above the merchant's ceiling. Out-of-range proposals are refused, not clamped,
    so a model cannot nudge the buyer above its own limits.
    """
    try:
        proposed = unit_amount(proposed_unit_price)
    except ValueError:
        return None, "Proposed price is not a number."
    supplier = D(supplier_unit_price)
    ceiling = D(ceiling_unit_price)
    if proposed <= 0:
        return None, "Proposed price must be positive."
    if proposed > ceiling:
        return None, f"Proposed {proposed:.2f} is above the merchant's ceiling of {ceiling:.2f}."
    if proposed >= supplier:
        return None, "Proposed price is not below the supplier's ask."
    return proposed, "Within policy."


# --------------------------------------------------------------------------- #
# Outcomes
# --------------------------------------------------------------------------- #
def gross_profit(*, selling_price: Any, unit_cost: Any, quantity: Any) -> tuple[Decimal, Decimal]:
    """(expected gross profit, gross margin %) for selling ``quantity`` units."""
    revenue = money(D(selling_price) * D(quantity))
    cost = money(D(unit_cost) * D(quantity))
    profit = money(revenue - cost)
    return profit, pct(profit, revenue)


def margin_pct(*, price: Any, unit_cost: Any) -> Decimal:
    return pct(D(price) - D(unit_cost), price)


def savings(*, baseline_total: Any, final_total: Any) -> tuple[Decimal, Decimal]:
    baseline = money(baseline_total)
    saved = money(baseline - money(final_total))
    return saved, pct(saved, baseline)


def budget_utilisation(*, total: Any, budget: Any) -> Decimal:
    return pct(total, budget)


def weighted_average_cost(
    *, on_hand_before: Any, cost_before: Any, received_quantity: Any, received_unit_cost: Any
) -> Decimal:
    """Moving weighted-average inventory cost after a receipt."""
    qty_before = max(D(on_hand_before), ZERO)
    qty_in = D(received_quantity)
    total_qty = qty_before + qty_in
    if total_qty <= 0:
        return unit_amount(received_unit_cost)
    value = qty_before * D(cost_before) + qty_in * D(received_unit_cost)
    return unit_amount(value / total_qty)


def round_up_to(value: Any, step: Any) -> Decimal:
    """Ceil ``value`` to a multiple of ``step`` (pack sizes, MOQs)."""
    step = D(step)
    if step <= 0:
        return D(value)
    return (D(value) / step).to_integral_value(rounding=ROUND_CEILING) * step


__all__ = [
    "CENT",
    "ONE",
    "POLICY_ENGINE_VERSION",
    "UNIT",
    "ZERO",
    "D",
    "LandedCost",
    "OfferCheck",
    "ProcurementConstraints",
    "budget_utilisation",
    "canonical",
    "compute_constraints",
    "gross_profit",
    "landed_cost",
    "margin_pct",
    "max_unit_price_for",
    "money",
    "pct",
    "ratio",
    "round_up_to",
    "savings",
    "serialisable",
    "sha256",
    "shipping_charge",
    "unit_amount",
    "unit_price_for_landed_target",
    "validate_buyer_counter",
    "validate_offer",
    "weighted_average_cost",
]
