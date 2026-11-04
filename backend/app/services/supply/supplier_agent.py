"""Independent supplier agents.

Each supplier agent is a policy engine built from *its own* private state - its
list price, its floor, its stock, its concession style - and nothing else. It is
handed the public RFQ and the buyer's counters (the two message payloads it would
receive over the wire) and returns its next move. It is never given the
merchant's budget, the merchant's ceiling, or any other supplier's terms, so it
cannot condition on them even by accident: the type it is constructed from simply
does not contain them.

The three demo strategies:

``PREMIUM_RELIABLE``   moderate price, fast delivery, high reliability, small
                       concessions, waives shipping only above its threshold,
                       includes expediting.
``LOW_PRICE_LIMITED``  opens low, slow, limited stock, barely concedes, never
                       waives shipping, cannot expedite.
``FLEXIBLE_VOLUME``    competitive, concedes generously, rewards volume, will
                       waive shipping to close, charges a fee to expedite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.db.models.supply import OfferKind, SupplierStrategy
from app.services.supply.policy import (
    ONE,
    ZERO,
    D,
    landed_cost,
    money,
    shipping_charge,
    unit_amount,
)


@dataclass(frozen=True)
class SupplierPrivatePolicy:
    """Everything a supplier agent knows about itself. Never leaves the agent."""

    agent_key: str
    display_name: str
    strategy: str
    currency: str
    list_price: Decimal
    floor_price: Decimal
    available_quantity: Decimal | None
    min_order_quantity: Decimal
    lead_time_days: int
    shipping_flat: Decimal
    shipping_per_unit: Decimal
    free_shipping_threshold: Decimal
    tax_rate: Decimal
    expedite_fee: Decimal
    expedite_days: int
    payment_terms: str
    opening_markup: Decimal
    concession_rate: Decimal
    max_rounds: int
    volume_breaks: tuple[tuple[Decimal, Decimal], ...] = field(default_factory=tuple)

    def volume_discount(self, quantity: Decimal) -> Decimal:
        best = ZERO
        for min_qty, discount in self.volume_breaks:
            if quantity >= min_qty and discount > best:
                best = discount
        return best


@dataclass(frozen=True)
class RFQView:
    """The public RFQ, as received over the protocol."""

    rfq_reference: str
    sku: str
    product_name: str
    quantity: Decimal
    unit: str
    required_within_days: int | None


@dataclass(frozen=True)
class CounterView:
    """A buyer counter, as received over the protocol."""

    round: int
    unit_price: Decimal
    quantity: Decimal
    request_free_shipping: bool = False
    request_expedite: bool = False
    competitive_pressure: bool = False


@dataclass
class SupplierMove:
    kind: str
    unit_price: Decimal = ZERO
    quantity: Decimal = ZERO
    shipping: Decimal = ZERO
    lead_time_days: int = 0
    payment_terms: str = ""
    expedited: bool = False
    shipping_waived: bool = False
    concessions: list[str] = field(default_factory=list)
    rationale: str = ""

    def landed(self, tax_rate: Decimal) -> Any:
        return landed_cost(
            unit_price=self.unit_price, quantity=self.quantity, shipping=self.shipping, tax_rate=tax_rate
        )


class SupplierAgentEngine:
    def __init__(self, policy: SupplierPrivatePolicy) -> None:
        self.p = policy

    # ------------------------------------------------------------------ helpers
    def _quantity_for(self, requested: Decimal) -> tuple[Decimal, list[str]]:
        notes: list[str] = []
        qty = requested
        if self.p.available_quantity is not None and qty > self.p.available_quantity:
            qty = self.p.available_quantity
            notes.append(f"Can ship {qty:f} of {requested:f} from current stock.")
        if qty < self.p.min_order_quantity:
            qty = self.p.min_order_quantity
            notes.append(f"Minimum order is {self.p.min_order_quantity:f}.")
        return qty, notes

    def _shipping(self, unit_price: Decimal, quantity: Decimal) -> Decimal:
        return shipping_charge(
            flat=self.p.shipping_flat,
            per_unit=self.p.shipping_per_unit,
            free_threshold=self.p.free_shipping_threshold,
            subtotal=money(unit_price * quantity),
            quantity=quantity,
        )

    def _respects_floor(self, price: Decimal) -> Decimal:
        return max(unit_amount(price), self.p.floor_price)

    # ------------------------------------------------------------------ RFQ
    def respond_to_rfq(self, rfq: RFQView) -> SupplierMove:
        if self.p.available_quantity is not None and self.p.available_quantity <= 0:
            return SupplierMove(kind=OfferKind.DECLINE, rationale="Out of stock for this SKU right now.")

        quantity, notes = self._quantity_for(rfq.quantity)
        if quantity <= 0:
            return SupplierMove(kind=OfferKind.DECLINE, rationale="Cannot supply this SKU.")

        price = self.p.list_price * (ONE + self.p.opening_markup) * (ONE - self.p.volume_discount(quantity))
        price = self._respects_floor(price)
        shipping = self._shipping(price, quantity)
        move = SupplierMove(
            kind=OfferKind.QUOTE,
            unit_price=price,
            quantity=quantity,
            shipping=shipping,
            lead_time_days=self.p.lead_time_days,
            payment_terms=self.p.payment_terms,
            concessions=notes,
        )
        move.rationale = self._quote_rationale(move, rfq)
        return move

    # ------------------------------------------------------------------ counters
    def respond_to_counter(self, counter: CounterView, last: SupplierMove) -> SupplierMove:
        """Concede toward the buyer, never below the floor, never past the buyer's ask."""
        final_round = counter.round >= self.p.max_rounds
        concessions: list[str] = []

        quantity, qty_notes = self._quantity_for(counter.quantity)
        concessions += qty_notes

        # Price: move a strategy-defined share of the gap, more under competitive pressure.
        rate = self.p.concession_rate
        if counter.competitive_pressure and self.p.strategy == SupplierStrategy.FLEXIBLE_VOLUME:
            rate = min(rate + Decimal("0.15"), Decimal("0.90"))
        gap = last.unit_price - counter.unit_price
        proposed = last.unit_price - gap * rate if gap > 0 else last.unit_price
        if final_round and self.p.strategy == SupplierStrategy.FLEXIBLE_VOLUME:
            # Flexible suppliers close the deal on the last round if they can.
            proposed = max(counter.unit_price, self.p.floor_price)
        price = self._respects_floor(proposed)
        if price < counter.unit_price:
            price = unit_amount(counter.unit_price)

        lead = last.lead_time_days
        expedited = last.expedited
        shipping = self._shipping(price, quantity)
        waived = last.shipping_waived

        if counter.request_expedite and not expedited:
            if self.p.expedite_days > 0 and self.p.strategy != SupplierStrategy.LOW_PRICE_LIMITED:
                lead = max(1, lead - self.p.expedite_days)
                expedited = True
                if self.p.strategy == SupplierStrategy.PREMIUM_RELIABLE:
                    concessions.append(f"Expedited to {lead} days at no extra charge.")
                else:
                    concessions.append(f"Expedited to {lead} days for a {self.p.expedite_fee:.2f} fee.")
            else:
                concessions.append("Cannot expedite.")
        expedite_fee = self.p.expedite_fee if expedited and self.p.strategy != SupplierStrategy.PREMIUM_RELIABLE else ZERO

        if counter.request_free_shipping and shipping > 0 and not waived:
            near_threshold = (
                self.p.free_shipping_threshold > 0
                and money(price * quantity) >= self.p.free_shipping_threshold * Decimal("0.80")
            )
            if self.p.strategy == SupplierStrategy.FLEXIBLE_VOLUME or (
                self.p.strategy == SupplierStrategy.PREMIUM_RELIABLE and near_threshold
            ):
                waived = True
                concessions.append("Shipping waived.")
            elif self.p.strategy == SupplierStrategy.LOW_PRICE_LIMITED:
                concessions.append("Shipping is not negotiable.")
        if waived:
            shipping = ZERO
        shipping = money(shipping + expedite_fee)

        accepted = price <= counter.unit_price and quantity >= counter.quantity
        kind = OfferKind.ACCEPT if accepted else (OfferKind.FINAL if final_round else OfferKind.COUNTER)
        if accepted:
            price = unit_amount(counter.unit_price)

        move = SupplierMove(
            kind=kind,
            unit_price=price,
            quantity=quantity,
            shipping=shipping,
            lead_time_days=lead,
            payment_terms=self.p.payment_terms,
            expedited=expedited,
            shipping_waived=waived,
            concessions=concessions,
        )
        move.rationale = self._counter_rationale(move, last, counter)
        return move

    # ------------------------------------------------------------------ language (deterministic)
    def _quote_rationale(self, move: SupplierMove, rfq: RFQView) -> str:
        style = {
            SupplierStrategy.PREMIUM_RELIABLE: "We prioritise reliability: roasted to order and dispatched fast.",
            SupplierStrategy.LOW_PRICE_LIMITED: "Our best price on the market, while stock lasts.",
            SupplierStrategy.FLEXIBLE_VOLUME: "Happy to work with you on volume and terms.",
        }.get(self.p.strategy, "")
        extra = f" {' '.join(move.concessions)}" if move.concessions else ""
        shipping = "free shipping" if move.shipping == 0 else f"{move.shipping:.2f} shipping"
        return (
            f"{style} Quote for {move.quantity:f} x {rfq.product_name} at {move.unit_price:.2f} each, "
            f"{shipping}, delivery in {move.lead_time_days} days, {move.payment_terms.replace('_', ' ').lower()}."
            f"{extra}"
        ).strip()

    def _counter_rationale(self, move: SupplierMove, last: SupplierMove, counter: CounterView) -> str:
        if move.kind == OfferKind.ACCEPT:
            return f"Agreed - {move.unit_price:.2f} per unit works for us."
        moved = last.unit_price - move.unit_price
        if move.unit_price == self.p.floor_price:
            stance = "This is as low as we can go."
        elif moved <= 0:
            stance = "We can't move on price."
        else:
            stance = f"We can come down {moved:.2f} to {move.unit_price:.2f}."
        if move.kind == OfferKind.FINAL:
            stance = f"Final offer: {move.unit_price:.2f} per unit."
        extra = f" {' '.join(move.concessions)}" if move.concessions else ""
        return f"{stance}{extra}".strip()


def policy_from_rows(agent: Any, supply: Any) -> SupplierPrivatePolicy:
    """Build a supplier's private policy from its own two rows - nothing else."""
    breaks: list[tuple[Decimal, Decimal]] = []
    for entry in (supply.volume_breaks or []):
        try:
            breaks.append((D(entry.get("min_quantity")), D(entry.get("discount_pct"))))
        except (AttributeError, ValueError):
            continue
    list_price = D(supply.unit_price)
    floor = D(supply.floor_price) if supply.floor_price is not None else unit_amount(list_price * Decimal("0.85"))
    lead = supply.lead_time_days if supply.lead_time_days is not None else agent_lead(agent)
    return SupplierPrivatePolicy(
        agent_key=agent.agent_key,
        display_name=agent.display_name,
        strategy=agent.strategy,
        currency=agent.currency,
        list_price=list_price,
        floor_price=floor,
        available_quantity=D(supply.available_quantity) if supply.available_quantity is not None else None,
        min_order_quantity=D(supply.minimum_order_quantity or 0),
        lead_time_days=int(D(lead)),
        shipping_flat=D(agent.shipping_flat),
        shipping_per_unit=D(agent.shipping_per_unit),
        free_shipping_threshold=D(agent.free_shipping_threshold),
        tax_rate=D(agent.tax_rate),
        expedite_fee=D(agent.expedite_fee),
        expedite_days=int(agent.expedite_days or 0),
        payment_terms=agent.payment_terms,
        opening_markup=D(agent.opening_markup),
        concession_rate=D(agent.concession_rate),
        max_rounds=int(agent.max_rounds or 3),
        volume_breaks=tuple(sorted(breaks)),
    )


def agent_lead(agent: Any) -> Decimal:
    vendor = getattr(agent, "vendor", None)
    return D(getattr(vendor, "lead_time_days", 3) or 3)
