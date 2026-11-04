"""Inventory Intelligence: demand, stockout risk and procurement requirements.

Every figure here is computed from persisted sales and stock - no model is
involved. For one tracked item:

* sales velocity        = units sold per day over the last 14 days;
* demand change         = that velocity against the 14 days before;
* days of cover         = available / velocity;
* stockout risk         = cover <= lead time + safety days;
* suggested quantity    = velocity x (lead time + review period + safety)
                          - available - already on order, rounded up to the
                          pack size and the supplier minimum;
* required by           = today + whole days of cover remaining.

Example (the product brief's): 42 on hand, 12/day -> 3.5 days of cover; with a
3-day lead time, 10-day review period and 3 safety days the target is 16 days of
cover = 192 units, so the suggestion is 192 - 42 = 150, required within 3 days.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.commerce import Product, Transaction, TransactionItem, TransactionStatus
from app.db.models.inventory import InventoryItem
from app.db.models.procurement import PurchaseOrder, PurchaseOrderLine, PurchaseOrderStatus
from app.db.models.supply import ProcurementRequest, ProcurementStatus
from app.services.supply.policy import ZERO, D, money, pct, round_up_to, serialisable

WINDOW_DAYS = 14
REVIEW_PERIOD_DAYS = 10
SAFETY_DAYS = 3
#: A rise at least this large counts as a demand increase worth flagging.
DEMAND_SPIKE_PCT = Decimal("25")
PACK_SIZE = Decimal("10")


@dataclass
class DemandAssessment:
    inventory_item_id: str
    product_id: str
    sku: str
    product_name: str
    unit: str
    on_hand: Decimal
    available: Decimal
    on_order: Decimal
    velocity_recent: Decimal
    velocity_prior: Decimal
    demand_change_pct: Decimal
    days_of_cover: Decimal | None
    lead_time_days: int
    stockout_risk: bool
    risk_level: str
    demand_increased: bool
    overstocked: bool
    suggested_quantity: Decimal
    required_within_days: int | None
    required_by: date | None
    target_cover_days: int
    unit_cost: Decimal
    selling_price: Decimal
    revenue_at_risk: Decimal
    reason: str
    daily_units: list[dict[str, Any]] = field(default_factory=list)
    open_request_reference: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return serialisable(asdict(self))


class InventoryIntelligence:
    def __init__(self, session: AsyncSession, merchant_id: uuid.UUID) -> None:
        self.session = session
        self.merchant_id = merchant_id

    async def _anchor(self) -> date:
        """Assess as of the latest business date with sales (demo data is anchored)."""
        latest = (
            await self.session.execute(
                select(func.max(Transaction.business_date)).where(Transaction.merchant_id == self.merchant_id)
            )
        ).scalar_one_or_none()
        return latest or datetime.now(tz=UTC).date()

    async def _daily_units(self, product_id: uuid.UUID, start: date, end: date) -> dict[date, Decimal]:
        rows = (
            await self.session.execute(
                select(Transaction.business_date, func.sum(TransactionItem.quantity))
                .join(Transaction, Transaction.id == TransactionItem.transaction_id)
                .where(
                    TransactionItem.merchant_id == self.merchant_id,
                    TransactionItem.product_id == product_id,
                    Transaction.business_date >= start,
                    Transaction.business_date <= end,
                    Transaction.status == TransactionStatus.COMPLETED,
                )
                .group_by(Transaction.business_date)
            )
        ).all()
        return {row[0]: D(row[1] or 0) for row in rows}

    async def _on_order(self, item_id: uuid.UUID) -> Decimal:
        rows = (
            await self.session.execute(
                select(PurchaseOrderLine.quantity_ordered, PurchaseOrderLine.quantity_received)
                .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
                .where(
                    PurchaseOrder.merchant_id == self.merchant_id,
                    PurchaseOrderLine.inventory_item_id == item_id,
                    PurchaseOrder.status.in_(
                        (
                            PurchaseOrderStatus.APPROVED,
                            PurchaseOrderStatus.ORDERED,
                            PurchaseOrderStatus.ACKNOWLEDGED,
                            PurchaseOrderStatus.PARTIALLY_RECEIVED,
                        )
                    ),
                )
            )
        ).all()
        return sum((max(D(o) - D(r), ZERO) for o, r in rows), ZERO)

    async def _open_request(self, item_id: uuid.UUID) -> ProcurementRequest | None:
        return (
            await self.session.execute(
                select(ProcurementRequest)
                .where(
                    ProcurementRequest.merchant_id == self.merchant_id,
                    ProcurementRequest.inventory_item_id == item_id,
                    ProcurementRequest.status.in_(ProcurementStatus.OPEN),
                )
                .order_by(ProcurementRequest.created_at.desc())
            )
        ).scalars().first()

    async def assess(self, item: InventoryItem, *, as_of: date | None = None) -> DemandAssessment:
        anchor = as_of or await self._anchor()
        recent_start = anchor - timedelta(days=WINDOW_DAYS - 1)
        prior_end = recent_start - timedelta(days=1)
        prior_start = prior_end - timedelta(days=WINDOW_DAYS - 1)

        daily = await self._daily_units(item.product_id, prior_start, anchor)
        recent_units = sum((v for d, v in daily.items() if d >= recent_start), ZERO)
        prior_units = sum((v for d, v in daily.items() if d <= prior_end), ZERO)
        window = Decimal(WINDOW_DAYS)
        velocity = (recent_units / window).quantize(Decimal("0.01"))
        prior_velocity = (prior_units / window).quantize(Decimal("0.01"))
        change = pct(velocity - prior_velocity, prior_velocity) if prior_velocity > 0 else (
            Decimal("100") if velocity > 0 else ZERO
        )

        on_hand = D(item.quantity_on_hand)
        available = on_hand - D(item.reserved_quantity)
        on_order = await self._on_order(item.id)
        lead = int(D(item.lead_time_days or 3).to_integral_value(rounding=ROUND_FLOOR)) or 3
        cover = (available / velocity).quantize(Decimal("0.1")) if velocity > 0 else None

        stockout = cover is not None and cover <= Decimal(lead + SAFETY_DAYS)
        if cover is None:
            risk = "NONE"
        elif cover <= Decimal(lead):
            risk = "CRITICAL"
        elif stockout:
            risk = "HIGH"
        elif cover <= Decimal(lead + SAFETY_DAYS + REVIEW_PERIOD_DAYS):
            risk = "WATCH"
        else:
            risk = "HEALTHY"

        target_days = lead + REVIEW_PERIOD_DAYS + SAFETY_DAYS
        need = velocity * Decimal(target_days) - available - on_order
        suggested = round_up_to(max(need, ZERO), PACK_SIZE) if need > 0 else ZERO
        overstocked = cover is not None and cover > Decimal(target_days * 3)

        product = await self.session.get(Product, item.product_id)
        price = D(product.price) if product else ZERO
        within = int(cover.to_integral_value(rounding=ROUND_FLOOR)) if cover is not None else None
        required_by = anchor + timedelta(days=within) if within is not None else None
        # Revenue exposed if nothing arrives before stock runs out.
        gap_days = max(Decimal(lead) - (cover or Decimal(lead)), ZERO)
        revenue_at_risk = money(gap_days * velocity * price)

        demand_up = change >= DEMAND_SPIKE_PCT and velocity > 0
        parts = [f"Selling {velocity:f}/day over the last {WINDOW_DAYS} days"]
        if prior_velocity > 0:
            parts.append(f"({'+' if change >= 0 else ''}{change}% vs the prior {WINDOW_DAYS} days)")
        if cover is not None:
            parts.append(f"with {available:f} available - {cover} days of cover against a {lead}-day lead time.")
        else:
            parts.append("with no recent sales.")
        if stockout:
            parts.append(f"Stockout risk: reorder {suggested:f} to restore {target_days} days of cover.")

        request = await self._open_request(item.id)
        return DemandAssessment(
            inventory_item_id=str(item.id),
            product_id=str(item.product_id),
            sku=item.sku,
            product_name=item.product_name,
            unit=item.unit,
            on_hand=on_hand,
            available=available,
            on_order=on_order,
            velocity_recent=velocity,
            velocity_prior=prior_velocity,
            demand_change_pct=change,
            days_of_cover=cover,
            lead_time_days=lead,
            stockout_risk=stockout,
            risk_level=risk,
            demand_increased=demand_up,
            overstocked=overstocked,
            suggested_quantity=suggested,
            required_within_days=within,
            required_by=required_by,
            target_cover_days=target_days,
            unit_cost=D(item.unit_cost),
            selling_price=price,
            revenue_at_risk=revenue_at_risk,
            reason=" ".join(parts),
            daily_units=[
                {"date": (prior_start + timedelta(days=i)).isoformat(),
                 "units": str(daily.get(prior_start + timedelta(days=i), ZERO))}
                for i in range(WINDOW_DAYS * 2)
            ],
            open_request_reference=request.reference if request else None,
        )

    async def scan(self) -> list[DemandAssessment]:
        items = (
            await self.session.execute(
                select(InventoryItem).where(
                    InventoryItem.merchant_id == self.merchant_id, InventoryItem.is_tracked.is_(True)
                )
            )
        ).scalars().all()
        anchor = await self._anchor()
        results = [await self.assess(item, as_of=anchor) for item in items]
        order = {"CRITICAL": 0, "HIGH": 1, "WATCH": 2, "HEALTHY": 3, "NONE": 4}
        return sorted(results, key=lambda a: (order.get(a.risk_level, 9), -(a.demand_change_pct)))
