"""Reorder quantity and vendor selection.

Both decisions live here, in the backend, rather than in an n8n JavaScript node.
n8n orchestrates - it calls this through the API and acts on the answer - so the
rules stay testable, versioned and identical whether a workflow, a user or a test
asks the question.

Neither function writes anything. They answer "what would we order, and from
whom", and the caller decides what to do with that.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.inventory import InventoryItem
from app.db.models.procurement import (
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    Vendor,
    VendorProduct,
)


class ReorderStrategy:
    """How much to buy when stock runs down.

    The two implemented strategies are deterministic and explainable, which is
    what a merchant needs to trust an automatic order. The named-but-unbuilt ones
    are here so the abstraction does not have to change when demand forecasting
    arrives - they are rejected explicitly rather than silently falling through.
    """

    FIXED_QUANTITY = "FIXED_QUANTITY"
    TARGET_MAX_STOCK = "TARGET_MAX_STOCK"

    #: Planned, not implemented. Selecting one raises rather than guessing.
    SALES_VELOCITY = "SALES_VELOCITY"
    FORECAST_BASED = "FORECAST_BASED"

    IMPLEMENTED = (FIXED_QUANTITY, TARGET_MAX_STOCK)
    ALL = (FIXED_QUANTITY, TARGET_MAX_STOCK, SALES_VELOCITY, FORECAST_BASED)


@dataclass(slots=True)
class ReorderDecision:
    """Why we are ordering this much - the fields the UI shows verbatim."""

    should_reorder: bool
    quantity: float
    strategy: str
    available: float
    reorder_point: float
    reason: str
    blockers: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "should_reorder": self.should_reorder,
            "quantity": self.quantity,
            "strategy": self.strategy,
            "available": self.available,
            "reorder_point": self.reorder_point,
            "reason": self.reason,
            "blockers": self.blockers,
        }


def decide_reorder(item: InventoryItem, *, strategy: str | None = None) -> ReorderDecision:
    """Whether to reorder, and how much.

    Uses ``available_quantity`` - stock already promised to open orders must not
    count toward the decision, or a shop with 100 units all reserved looks
    healthy while it has nothing to sell.
    """
    chosen = strategy or item.reorder_strategy or ReorderStrategy.FIXED_QUANTITY
    available = item.available_quantity
    reorder_point = float(item.reorder_point)

    if chosen not in ReorderStrategy.IMPLEMENTED:
        return ReorderDecision(
            should_reorder=False,
            quantity=0.0,
            strategy=chosen,
            available=available,
            reorder_point=reorder_point,
            reason=f"Strategy {chosen} is not implemented.",
            blockers=[f"unsupported_strategy:{chosen}"],
        )

    if available > reorder_point:
        return ReorderDecision(
            should_reorder=False,
            quantity=0.0,
            strategy=chosen,
            available=available,
            reorder_point=reorder_point,
            reason=(
                f"Available stock {available:g} is above the reorder point "
                f"{reorder_point:g}."
            ),
        )

    if chosen == ReorderStrategy.TARGET_MAX_STOCK:
        target = float(item.maximum_stock or 0)
        if target <= 0:
            return ReorderDecision(
                should_reorder=False,
                quantity=0.0,
                strategy=chosen,
                available=available,
                reorder_point=reorder_point,
                reason="TARGET_MAX_STOCK needs a maximum_stock above zero.",
                blockers=["maximum_stock_not_set"],
            )
        quantity = max(target - available, 0.0)
        reason = (
            f"Available {available:g} is at or below the reorder point "
            f"{reorder_point:g}. Topping up to the maximum of {target:g}."
        )
    else:
        quantity = float(item.reorder_quantity or 0)
        reason = (
            f"Available {available:g} is at or below the reorder point "
            f"{reorder_point:g}. Ordering the fixed quantity of {quantity:g}."
        )

    if quantity <= 0:
        return ReorderDecision(
            should_reorder=False,
            quantity=0.0,
            strategy=chosen,
            available=available,
            reorder_point=reorder_point,
            reason="Calculated quantity is zero.",
            blockers=["zero_quantity"],
        )

    return ReorderDecision(
        should_reorder=True,
        quantity=quantity,
        strategy=chosen,
        available=available,
        reorder_point=reorder_point,
        reason=reason,
    )


@dataclass(slots=True)
class VendorChoice:
    vendor: Vendor
    supply: VendorProduct | None
    unit_price: float
    reason: str


async def select_vendor(
    session: AsyncSession,
    *,
    item: InventoryItem,
    quantity: float,
) -> VendorChoice | None:
    """Pick the supplier, deterministically.

    Order of preference, and nothing else:

    1. the item's configured default vendor, if it is active and can supply it
    2. the supply link flagged ``is_preferred``
    3. the cheapest active supplier whose minimum order quantity is satisfiable

    Ties break on vendor name so repeated runs choose the same vendor. A vendor
    is never invented from the legacy free-text ``supplier`` string.
    """
    stmt = (
        select(VendorProduct)
        .join(Vendor, Vendor.id == VendorProduct.vendor_id)
        .where(
            VendorProduct.merchant_id == item.merchant_id,
            VendorProduct.inventory_item_id == item.id,
            VendorProduct.automatic_ordering_enabled.is_(True),
            Vendor.is_active.is_(True),
        )
    )
    supplies = list((await session.execute(stmt)).scalars().all())
    if not supplies:
        return None

    def satisfiable(supply: VendorProduct) -> bool:
        return quantity >= float(supply.minimum_order_quantity or 0)

    eligible = [s for s in supplies if satisfiable(s)]
    if not eligible:
        return None

    if item.default_vendor_id:
        for supply in eligible:
            if supply.vendor_id == item.default_vendor_id:
                return VendorChoice(
                    vendor=supply.vendor,
                    supply=supply,
                    unit_price=float(supply.unit_price or item.unit_cost or 0),
                    reason="Item's configured default vendor.",
                )

    preferred = [s for s in eligible if s.is_preferred]
    if preferred:
        pick = min(preferred, key=lambda s: (float(s.unit_price or 0), s.vendor.name))
        return VendorChoice(
            vendor=pick.vendor,
            supply=pick,
            unit_price=float(pick.unit_price or item.unit_cost or 0),
            reason="Preferred supplier for this item.",
        )

    pick = min(eligible, key=lambda s: (float(s.unit_price or 0), s.vendor.name))
    return VendorChoice(
        vendor=pick.vendor,
        supply=pick,
        unit_price=float(pick.unit_price or item.unit_cost or 0),
        reason="Cheapest active supplier able to meet the quantity.",
    )


async def open_order_for_item(
    session: AsyncSession, *, item: InventoryItem
) -> PurchaseOrder | None:
    """An order already in flight for this item, if any.

    This is the second line of defence against duplicate reordering. Idempotency
    keys stop the *same* event ordering twice; this stops three separate sales
    each raising their own order while the first delivery is still in transit.
    """
    stmt = (
        select(PurchaseOrder)
        .join(PurchaseOrderLine, PurchaseOrderLine.purchase_order_id == PurchaseOrder.id)
        .where(
            PurchaseOrder.merchant_id == item.merchant_id,
            PurchaseOrderLine.inventory_item_id == item.id,
            PurchaseOrder.status.in_(PurchaseOrderStatus.OPEN),
        )
        .order_by(PurchaseOrder.created_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


async def next_reference(session: AsyncSession, merchant_id: uuid.UUID) -> str:
    """Sequential, human-quotable order reference, per merchant."""
    from sqlalchemy import func

    count = (
        await session.execute(
            select(func.count())
            .select_from(PurchaseOrder)
            .where(PurchaseOrder.merchant_id == merchant_id)
        )
    ).scalar_one()
    return f"PO-{int(count) + 1:05d}"
