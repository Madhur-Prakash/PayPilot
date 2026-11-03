"""The stock engine: the only code allowed to change a quantity.

Every path that moves stock - a sale, a receipt, a return, a manual adjustment,
an expiry write-off - goes through :meth:`StockEngine.apply`. That is what keeps
three invariants true:

1. **The ledger is complete.** A quantity change and its movement row are written
   in the same transaction, so there is no such thing as stock that moved without
   a reason on record.
2. **Concurrent sales cannot both win.** The item row is locked ``FOR UPDATE``
   before it is read, so two simultaneous sales serialise instead of both reading
   10 and both writing 9.
3. **Low stock is noticed exactly once per crossing.** The event is emitted only
   when the balance *crosses* the reorder point, not on every subsequent sale
   below it, so a busy afternoon does not raise twenty reorder events.

Nothing here talks to n8n. It writes events to the outbox; delivery is somebody
else's job.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.automation import EventType
from app.db.models.inventory import (
    InventoryItem,
    InventoryMovement,
    MovementType,
    StockStatus,
)
from app.services.inventory import events as event_bus
from app.services.inventory.replenishment import decide_reorder

log = get_logger(__name__)

#: Movements that add stock. Everything else subtracts, except the two that only
#: shuffle the reserved bucket.
_INBOUND = frozenset(
    {
        MovementType.RESTOCK,
        MovementType.PURCHASE_RECEIPT,
        MovementType.CUSTOMER_RETURN,
        MovementType.TRANSFER_IN,
    }
)


@dataclass(slots=True)
class StockChange:
    """What one movement did, and what it triggered."""

    item: InventoryItem
    movement: InventoryMovement
    balance_before: float
    balance_after: float
    status_before: str
    status_after: str
    crossed_reorder_point: bool
    correlation_id: str
    events: list[str]


class InsufficientStock(ValueError):
    """Raised rather than letting a balance go negative."""


class StockEngine:
    """Applies movements to one merchant's inventory."""

    def __init__(self, session: AsyncSession, merchant_id: uuid.UUID) -> None:
        self.session = session
        self.merchant_id = merchant_id

    # ------------------------------------------------------------------ status
    @staticmethod
    def derive_status(item: InventoryItem) -> str:
        """The authoritative stock state.

        Computed here and stored, never recomputed in the browser, so every
        surface agrees on what "low" means.
        """
        available = item.available_quantity
        reorder_point = float(item.reorder_point or 0)
        maximum = float(item.maximum_stock or 0)

        if available <= 0:
            return StockStatus.OUT_OF_STOCK
        if available <= reorder_point:
            # REORDER_REQUIRED is the actionable state; CRITICAL is kept for the
            # steeper case so existing dashboards keep their meaning.
            return (
                StockStatus.CRITICAL
                if reorder_point > 0 and available <= reorder_point / 2
                else StockStatus.REORDER_REQUIRED
            )
        if maximum > 0 and available > maximum:
            return StockStatus.OVERSTOCKED
        if reorder_point > 0 and available <= reorder_point * 1.25:
            return StockStatus.WATCH
        return StockStatus.HEALTHY

    # ------------------------------------------------------------------ apply
    async def apply(
        self,
        *,
        item_id: uuid.UUID,
        movement_type: str,
        quantity: float,
        correlation_id: str | None = None,
        note: str = "",
        reference_type: str = "",
        reference_id: str = "",
        batch_id: uuid.UUID | None = None,
        unit_cost: float | None = None,
        actor_type: str = "SYSTEM",
        actor_id: uuid.UUID | None = None,
        source: str = "backend",
        metadata: dict[str, Any] | None = None,
        allow_negative: bool = False,
    ) -> StockChange:
        """Move stock, write the ledger row, and record any resulting events.

        ``quantity`` is always positive; direction comes from ``movement_type``.
        The caller owns the transaction - nothing here commits, so a sale that
        fails later rolls the stock change back with it.
        """
        correlation_id = correlation_id or event_bus.new_correlation_id()
        magnitude = abs(float(quantity))

        # Lock first, read second. Doing it the other way round is the classic
        # lost-update bug: both sales read the same balance and the second
        # overwrites the first.
        stmt = (
            select(InventoryItem)
            .where(
                InventoryItem.id == item_id,
                InventoryItem.merchant_id == self.merchant_id,
            )
            .with_for_update()
        )
        item = (await self.session.execute(stmt)).scalars().first()
        if item is None:
            raise ValueError("Inventory item not found for this merchant.")

        balance_before = float(item.quantity_on_hand)
        status_before = item.status
        available_before = item.available_quantity

        if movement_type in MovementType.NON_STOCK_CHANGING:
            delta = 0.0
            if movement_type == MovementType.RESERVATION:
                if not allow_negative and magnitude > item.available_quantity:
                    raise InsufficientStock(
                        f"Cannot reserve {magnitude:g}: only "
                        f"{item.available_quantity:g} available."
                    )
                item.reserved_quantity = float(item.reserved_quantity) + magnitude
            else:  # RELEASE
                item.reserved_quantity = max(float(item.reserved_quantity) - magnitude, 0.0)
        else:
            delta = magnitude if movement_type in _INBOUND else -magnitude
            new_balance = balance_before + delta
            if new_balance < 0 and not allow_negative:
                raise InsufficientStock(
                    f"{item.sku}: cannot remove {magnitude:g} from {balance_before:g}."
                )
            item.quantity_on_hand = new_balance
            if movement_type in _INBOUND:
                item.last_restocked_at = datetime.now(tz=UTC)

        balance_after = float(item.quantity_on_hand)
        cost = float(unit_cost if unit_cost is not None else item.unit_cost or 0)

        movement = InventoryMovement(
            merchant_id=self.merchant_id,
            inventory_item_id=item.id,
            movement_type=movement_type,
            quantity=delta if delta else magnitude,
            balance_before=balance_before,
            balance_after=balance_after,
            unit_cost=cost,
            total_value=round(cost * magnitude, 2),
            note=note,
            actor_type=actor_type,
            actor_id=actor_id,
            quantity_units=int(magnitude),
            reference_type=reference_type,
            reference_id=str(reference_id or ""),
            batch_id=batch_id,
            source=source,
            correlation_id=correlation_id,
            metadata_json=metadata or {},
        )
        self.session.add(movement)

        item.status = self.derive_status(item)
        item.version = int(item.version or 0) + 1
        await self.session.flush()

        emitted: list[str] = []
        if settings.inventory_automation_enabled:
            emitted = await self._emit_for(
                item=item,
                movement=movement,
                correlation_id=correlation_id,
                available_before=available_before,
                balance_before=balance_before,
                balance_after=balance_after,
            )

        crossed = (
            available_before > float(item.reorder_point)
            >= item.available_quantity
        )

        log.info(
            "stock_applied",
            sku=item.sku,
            movement=movement_type,
            before=balance_before,
            after=balance_after,
            status=item.status,
            correlation_id=correlation_id,
            events=emitted,
        )

        return StockChange(
            item=item,
            movement=movement,
            balance_before=balance_before,
            balance_after=balance_after,
            status_before=status_before,
            status_after=item.status,
            crossed_reorder_point=crossed,
            correlation_id=correlation_id,
            events=emitted,
        )

    # ------------------------------------------------------------------ events
    async def _emit_for(
        self,
        *,
        item: InventoryItem,
        movement: InventoryMovement,
        correlation_id: str,
        available_before: float,
        balance_before: float,
        balance_after: float,
    ) -> list[str]:
        """Record the events this movement caused.

        The low-stock event fires on the *crossing* only. Re-emitting it on every
        subsequent sale below the line would hand n8n a storm of duplicate work
        that idempotency would then have to absorb - cheaper not to create it.
        """
        emitted: list[str] = []
        base = {
            "sku": item.sku,
            "product_name": item.product_name,
            "inventory_item_id": str(item.id),
            "quantity_on_hand": float(item.quantity_on_hand),
            "reserved_quantity": float(item.reserved_quantity),
            "available_quantity": item.available_quantity,
            "reorder_point": float(item.reorder_point),
            "status": item.status,
            "movement_type": movement.movement_type,
        }

        await event_bus.emit(
            self.session,
            merchant_id=self.merchant_id,
            event_type=EventType.STOCK_CHANGED,
            correlation_id=correlation_id,
            entity_type="inventory_item",
            entity_id=item.id,
            payload={**base, "balance_before": balance_before, "balance_after": balance_after},
        )
        emitted.append(EventType.STOCK_CHANGED)

        reorder_point = float(item.reorder_point or 0)
        crossed = available_before > reorder_point >= item.available_quantity
        if not crossed:
            return emitted

        decision = decide_reorder(item)
        await event_bus.emit(
            self.session,
            merchant_id=self.merchant_id,
            event_type=EventType.LOW_STOCK,
            correlation_id=correlation_id,
            entity_type="inventory_item",
            entity_id=item.id,
            payload={
                **base,
                "decision": decision.as_dict(),
                "automatic_ordering_enabled": bool(item.automatic_ordering_enabled),
            },
        )
        emitted.append(EventType.LOW_STOCK)
        return emitted
