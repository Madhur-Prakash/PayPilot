"""Procurement evaluation: deterministic supplier scoring and the recommendation.

Only offers that passed ``validate_offer`` inside policy are eligible. Each is
scored on six normalised criteria with fixed weights; ties break on landed total,
then on agent key, so the same inputs always produce the same winner. The
explanation is generated from the same numbers - it can be rephrased, never
re-derived, by a language model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.db.models.supply import PaymentTerms
from app.services.supply.policy import (
    ONE,
    ZERO,
    D,
    ProcurementConstraints,
    money,
    pct,
    serialisable,
)

#: Fixed, documented weights. They sum to 1.
WEIGHTS: dict[str, Decimal] = {
    "landed_cost": Decimal("0.40"),
    "lead_time": Decimal("0.20"),
    "reliability": Decimal("0.20"),
    "quality": Decimal("0.10"),
    "payment_terms": Decimal("0.05"),
    "availability": Decimal("0.05"),
}
SCORE = Decimal("0.0001")


@dataclass(frozen=True)
class Candidate:
    session_id: str
    offer_id: str
    supplier_agent_id: str
    agent_key: str
    supplier_name: str
    unit_price: Decimal
    quantity: Decimal
    shipping: Decimal
    tax: Decimal
    landed_total: Decimal
    landed_unit_cost: Decimal
    lead_time_days: int
    payment_terms: str
    reliability: Decimal
    quality: Decimal
    within_policy: bool
    violations: tuple[str, ...] = ()
    opening_landed_total: Decimal | None = None


@dataclass
class Evaluation:
    winner: Candidate | None
    ranking: list[dict[str, Any]] = field(default_factory=list)
    ineligible: list[dict[str, Any]] = field(default_factory=list)
    explanation: str = ""
    reasons: list[str] = field(default_factory=list)
    weights: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return serialisable(
            {
                "winner": self.winner.__dict__ if self.winner else None,
                "ranking": self.ranking,
                "ineligible": self.ineligible,
                "explanation": self.explanation,
                "reasons": self.reasons,
                "weights": self.weights,
            }
        )


def _q(value: Decimal) -> Decimal:
    return value.quantize(SCORE)


def evaluate(candidates: list[Candidate], constraints: ProcurementConstraints) -> Evaluation:
    eligible = [c for c in candidates if c.within_policy]
    ineligible = [
        {
            "session_id": c.session_id,
            "supplier_name": c.supplier_name,
            "agent_key": c.agent_key,
            "landed_total": c.landed_total,
            "lead_time_days": c.lead_time_days,
            "violations": list(c.violations),
        }
        for c in candidates
        if not c.within_policy
    ]
    weights = {k: str(v) for k, v in WEIGHTS.items()}
    if not eligible:
        return Evaluation(
            winner=None,
            ineligible=serialisable(ineligible),
            explanation="No supplier offer met the merchant's policy. Nothing can be recommended.",
            weights=weights,
        )

    cheapest = min(c.landed_total for c in eligible)
    fastest = min(max(c.lead_time_days, 1) for c in eligible)
    rows: list[tuple[Decimal, Candidate, dict[str, Decimal]]] = []
    for c in eligible:
        criteria = {
            "landed_cost": _q(cheapest / c.landed_total) if c.landed_total > 0 else ZERO,
            "lead_time": _q(Decimal(fastest) / Decimal(max(c.lead_time_days, 1))),
            "reliability": _q(min(c.reliability, ONE)),
            "quality": _q(min(c.quality, ONE)),
            "payment_terms": _q(Decimal(PaymentTerms.DAYS.get(c.payment_terms, 0)) / Decimal(30)),
            "availability": _q(min(c.quantity / constraints.quantity, ONE)) if constraints.quantity else ONE,
        }
        total = _q(sum((WEIGHTS[k] * v for k, v in criteria.items()), ZERO))
        rows.append((total, c, criteria))

    rows.sort(key=lambda r: (-r[0], r[1].landed_total, r[1].agent_key))
    winner_total, winner, _criteria = rows[0]

    ranking = [
        {
            "rank": i + 1,
            "session_id": c.session_id,
            "offer_id": c.offer_id,
            "supplier_agent_id": c.supplier_agent_id,
            "agent_key": c.agent_key,
            "supplier_name": c.supplier_name,
            "score": total,
            "criteria": criteria,
            "unit_price": c.unit_price,
            "quantity": c.quantity,
            "shipping": c.shipping,
            "tax": c.tax,
            "landed_total": c.landed_total,
            "landed_unit_cost": c.landed_unit_cost,
            "lead_time_days": c.lead_time_days,
            "payment_terms": c.payment_terms,
            "reliability": c.reliability,
            "quality": c.quality,
            "budget_utilisation_pct": pct(c.landed_total, constraints.max_budget),
            "expected_margin_pct": pct(
                constraints.expected_selling_price - c.landed_unit_cost, constraints.expected_selling_price
            ),
        }
        for i, (total, c, criteria) in enumerate(rows)
    ]

    reasons: list[str] = []
    if winner.landed_total == cheapest:
        runner = next((r[1] for r in rows[1:]), None)
        if runner is not None:
            reasons.append(
                f"Lowest landed cost: {money(winner.landed_total):,.2f} "
                f"({money(runner.landed_total - winner.landed_total):,.2f} below {runner.supplier_name})."
            )
        else:
            reasons.append(f"Only offer inside policy, landed at {money(winner.landed_total):,.2f}.")
    else:
        reasons.append(
            f"Landed at {money(winner.landed_total):,.2f}, "
            f"{money(winner.landed_total - cheapest):,.2f} above the cheapest eligible offer, but stronger overall."
        )
    reasons.append(
        f"Delivers in {winner.lead_time_days} days (requirement: {constraints.max_delivery_days})."
    )
    reasons.append(f"Reliability {winner.reliability:.0%}, quality {winner.quality:.0%}.")
    margin = pct(constraints.expected_selling_price - winner.landed_unit_cost, constraints.expected_selling_price)
    reasons.append(
        f"Keeps a {margin}% gross margin against the {constraints.target_margin * 100:.0f}% target."
    )
    if winner.opening_landed_total and winner.opening_landed_total > winner.landed_total:
        reasons.append(
            f"Negotiated down {money(winner.opening_landed_total - winner.landed_total):,.2f} "
            f"from its opening quote."
        )
    for row in ineligible:
        first = (row["violations"] or ["outside policy"])[0]
        reasons.append(f"{row['supplier_name']} was not eligible: {first}")

    explanation = (
        f"Recommend {winner.supplier_name}: score {winner_total:.3f} of 1.000. " + " ".join(reasons[:3])
    )
    return Evaluation(
        winner=winner,
        ranking=serialisable(ranking),
        ineligible=serialisable(ineligible),
        explanation=explanation,
        reasons=reasons,
        weights=weights,
    )


__all__ = ["WEIGHTS", "Candidate", "D", "Evaluation", "evaluate"]
