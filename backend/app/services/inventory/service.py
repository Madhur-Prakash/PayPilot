"""Inventory intelligence.

Recommends, never purchases. The only writes a user can make are records of a
decision *they* took (acknowledging a reorder, recording a restock, adjusting a
count) - there is no autonomous purchasing path anywhere in the system.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.db.models.audit import AuditAction
from app.db.models.inventory import InventoryItem, MovementType, StockStatus
from app.repositories.merchant import AuditLogRepository
from app.repositories.product import InventoryRepository, ProductRepository
from app.schemas.analytics import InventoryItemOut, InventoryOverview

log = get_logger(__name__)

#: Days of cover at or below which each status applies.
STATUS_THRESHOLDS: tuple[tuple[float, str], ...] = (
    (0.0, StockStatus.OUT_OF_STOCK),
    (1.5, StockStatus.CRITICAL),
    (3.0, StockStatus.LOW),
    (6.0, StockStatus.WATCH),
)


def _status_for(days_of_cover: float | None, quantity: float) -> str:
    if quantity <= 0:
        return StockStatus.OUT_OF_STOCK
    if days_of_cover is None:
        return StockStatus.HEALTHY
    for threshold, status in STATUS_THRESHOLDS:
        if days_of_cover <= threshold:
            return status
    return StockStatus.HEALTHY


class InventoryService:
    def __init__(self, session: AsyncSession, merchant_id: uuid.UUID) -> None:
        self.session = session
        self.merchant_id = merchant_id
        self.repo = InventoryRepository(session, merchant_id)
        self.products = ProductRepository(session, merchant_id)
        self.audit = AuditLogRepository(session)

    async def refresh(self, *, demand_days: int = 14, today=None) -> list[InventoryItem]:
        """Recompute demand, cover, risk and the recommendation for every item."""
        demand = await self.repo.daily_demand(days=demand_days, today=today)
        products = await self.products.by_id_map()
        items = await self.repo.list_items()

        for item in items:
            daily = demand.get(item.product_id, 0.0)
            item.avg_daily_demand = daily
            quantity = float(item.quantity_on_hand or 0)
            cover = round(quantity / daily, 2) if daily > 0 else None
            item.days_of_cover = cover
            item.status = _status_for(cover, quantity)

            lead_time = float(item.lead_time_days or 0)
            # Risk is the chance of running dry before a reorder could arrive.
            if cover is None:
                risk = 0.0
            elif cover <= 0:
                risk = 1.0
            elif lead_time <= 0:
                risk = 0.0
            else:
                risk = max(0.0, min(1.0, (lead_time - cover) / lead_time + 0.15))
            item.stockout_risk = round(risk, 3)

            product = products.get(item.product_id)
            unit_price = float(product.price) if product else 0.0
            # Revenue exposed if the item is unavailable for the rest of the lead time.
            days_short = max(lead_time - (cover or 0), 0)
            item.revenue_at_risk = round(daily * days_short * unit_price, 2)
            item.recommendation = self._recommend(item, cover, lead_time)

        await self.session.flush()
        log.info("inventory_refreshed", items=len(items))
        return items

    @staticmethod
    def _recommend(item: InventoryItem, cover: float | None, lead_time: float) -> str:
        name = item.product_name
        if item.status == StockStatus.OUT_OF_STOCK:
            return f"{name} is out of stock. Reorder today to stop losing sales."
        if cover is None:
            return f"No recent demand recorded for {name}. No reorder needed yet."
        if item.status == StockStatus.CRITICAL:
            return (
                f"About {cover:.1f} days of cover left against a {lead_time:.0f}-day lead time. "
                f"Reorder {item.reorder_quantity:.0f} {item.unit} today."
            )
        if item.status == StockStatus.LOW:
            return (
                f"Roughly {cover:.1f} days of stock remaining. Place an order for "
                f"{item.reorder_quantity:.0f} {item.unit} within the next day."
            )
        if item.status == StockStatus.WATCH:
            return f"{cover:.1f} days of cover. Fine for now - review before the weekend."
        return f"Healthy: about {cover:.1f} days of cover."

    async def overview(self) -> InventoryOverview:
        items = await self.refresh()
        out = [InventoryItemOut.model_validate(item) for item in items]
        at_risk = [
            i
            for i in out
            if i.status in (StockStatus.LOW, StockStatus.CRITICAL, StockStatus.OUT_OF_STOCK)
        ]
        return InventoryOverview(
            items=sorted(out, key=lambda i: (i.days_of_cover is None, i.days_of_cover or 0)),
            total_items=len(out),
            at_risk_items=len(at_risk),
            total_revenue_at_risk=round(sum(i.revenue_at_risk for i in out), 2),
            total_stock_value=round(sum(i.quantity_on_hand * i.unit_cost for i in out), 2),
            critical=sorted(at_risk, key=lambda i: i.days_of_cover or 0)[:5],
        )

    async def record_action(
        self,
        item_id: uuid.UUID,
        *,
        action: str,
        quantity: float,
        note: str,
        user_id: uuid.UUID,
        actor_label: str = "",
    ) -> InventoryItem:
        """Record a human decision. Never places an order with a supplier."""
        item = await self.repo.get(item_id)
        if item is None:
            raise NotFoundError("Inventory item not found.")

        if action == "RECORD_RESTOCK":
            item.quantity_on_hand = float(item.quantity_on_hand or 0) + quantity
            item.last_restocked_at = datetime.now(tz=UTC)
            movement_type = MovementType.RESTOCK
            description = f"Restock of {quantity:.0f} {item.unit} recorded."
        elif action == "ADJUST":
            item.quantity_on_hand = max(quantity, 0)
            item.last_counted_at = datetime.now(tz=UTC)
            movement_type = MovementType.ADJUSTMENT
            description = f"Stock count adjusted to {quantity:.0f} {item.unit}."
        else:
            movement_type = MovementType.REORDER_ACKNOWLEDGED
            description = (
                f"Reorder recommendation acknowledged for {item.product_name}. "
                "No purchase order was placed by the system."
            )

        await self.session.flush()
        await self.repo.record_movement(
            item=item,
            movement_type=movement_type,
            quantity=quantity,
            note=note or description,
            actor_type="USER",
            actor_id=user_id,
        )
        await self.refresh()
        await self.audit.record(
            action=AuditAction.INVENTORY_ACTION,
            merchant_id=self.merchant_id,
            actor_id=user_id,
            actor_label=actor_label,
            resource="inventory_item",
            resource_id=str(item.id),
            description=description,
            metadata={"action": action, "quantity": quantity, "note": note},
        )
        log.info("inventory_action", item_id=str(item.id), action=action, quantity=quantity)
        return item

    async def summary_for_agent(self) -> dict:
        overview = await self.overview()
        return {
            "items_tracked": overview.total_items,
            "items_at_risk": overview.at_risk_items,
            "total_revenue_at_risk": overview.total_revenue_at_risk,
            "critical_items": [
                {
                    "product": i.product_name,
                    "stock": i.quantity_on_hand,
                    "days_of_cover": i.days_of_cover,
                    "revenue_at_risk": i.revenue_at_risk,
                    "recommendation": i.recommendation,
                }
                for i in overview.critical
            ],
        }
