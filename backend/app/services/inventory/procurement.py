"""Purchase orders: raising, approving, sending and receiving.

The approval gate is the important part. An automatic order below the configured
threshold is sent without a human; at or above it, the workflow stops and waits.
Either way the order exists and is visible - automation never quietly spends
money, and it never quietly fails to.

Receiving supports partial delivery, because suppliers ship what they have.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.logging import get_logger
from app.db.models.automation import EventType
from app.db.models.inventory import InventoryBatch, InventoryItem, MovementType
from app.db.models.procurement import (
    OrderingMethod,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
)
from app.services.inventory import events as event_bus
from app.services.inventory.replenishment import (
    ReorderDecision,
    VendorChoice,
    next_reference,
)
from app.services.inventory.stock import StockEngine

log = get_logger(__name__)


@dataclass(slots=True)
class OrderOutcome:
    order: PurchaseOrder
    created: bool
    reason: str


class ProcurementService:
    def __init__(self, session: AsyncSession, merchant_id: uuid.UUID) -> None:
        self.session = session
        self.merchant_id = merchant_id
        self.stock = StockEngine(session, merchant_id)

    # ------------------------------------------------------------------ create
    async def create_order(
        self,
        *,
        item: InventoryItem,
        choice: VendorChoice,
        decision: ReorderDecision,
        correlation_id: str,
        idempotency_key: str | None = None,
        source: str = "AUTOMATION",
        actor_id: uuid.UUID | None = None,
        dry_run: bool | None = None,
    ) -> OrderOutcome:
        """Raise one order for one item.

        ``idempotency_key`` is checked before anything is written, so a webhook
        delivered three times yields one order and two no-ops. The unique index
        on ``(merchant_id, idempotency_key)`` is the real guarantee; this lookup
        just avoids the exception in the common case.
        """
        if idempotency_key:
            existing = (
                await self.session.execute(
                    select(PurchaseOrder).where(
                        PurchaseOrder.merchant_id == self.merchant_id,
                        PurchaseOrder.idempotency_key == idempotency_key,
                    )
                )
            ).scalars().first()
            if existing is not None:
                return OrderOutcome(
                    order=existing,
                    created=False,
                    reason="An order already exists for this event.",
                )

        is_dry_run = settings.inventory_dry_run if dry_run is None else dry_run
        unit_price = float(choice.unit_price or item.unit_cost or 0)
        total = round(unit_price * decision.quantity, 2)

        # 0 means "approve nothing automatically", which is why this is >= not >.
        threshold = float(settings.inventory_approval_threshold)
        requires_approval = source == "AUTOMATION" and total >= threshold

        lead_days = float(
            (choice.supply.lead_time_days if choice.supply else None)
            or choice.vendor.lead_time_days
            or item.lead_time_days
            or 3
        )

        order = PurchaseOrder(
            merchant_id=self.merchant_id,
            vendor_id=choice.vendor.id,
            reference=await next_reference(self.session, self.merchant_id),
            status=(
                PurchaseOrderStatus.PENDING_APPROVAL
                if requires_approval
                else PurchaseOrderStatus.APPROVED
            ),
            source=source,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            total_value=total,
            requires_approval=requires_approval,
            expected_at=date.today() + timedelta(days=int(lead_days)),
            is_dry_run=is_dry_run,
            notes=decision.reason,
            metadata_json={
                "strategy": decision.strategy,
                "available_at_trigger": decision.available,
                "reorder_point": decision.reorder_point,
                "vendor_reason": choice.reason,
            },
        )
        self.session.add(order)
        await self.session.flush()

        line = PurchaseOrderLine(
            merchant_id=self.merchant_id,
            purchase_order_id=order.id,
            inventory_item_id=item.id,
            sku=item.sku,
            product_name=item.product_name,
            quantity_ordered=decision.quantity,
            unit_price=unit_price,
            line_total=total,
        )
        self.session.add(line)

        # Incoming stock is committed the moment the order is raised, so a second
        # reorder decision sees it and does not order the same units twice.
        await self.session.flush()
        await self.hydrate(order)

        await event_bus.emit(
            self.session,
            merchant_id=self.merchant_id,
            event_type=EventType.PO_CREATED,
            correlation_id=correlation_id,
            entity_type="purchase_order",
            entity_id=order.id,
            payload=self.describe(order),
        )

        log.info(
            "purchase_order_created",
            reference=order.reference,
            sku=item.sku,
            quantity=decision.quantity,
            vendor=choice.vendor.name,
            requires_approval=requires_approval,
            dry_run=is_dry_run,
            correlation_id=correlation_id,
        )
        return OrderOutcome(order=order, created=True, reason=decision.reason)

    # ------------------------------------------------------------------ approve
    async def approve(
        self,
        *,
        order_id: uuid.UUID,
        approve: bool,
        actor_id: uuid.UUID,
        note: str = "",
    ) -> PurchaseOrder:
        order = await self.get(order_id)
        if order.status not in (
            PurchaseOrderStatus.PENDING_APPROVAL,
            PurchaseOrderStatus.DRAFT,
        ):
            raise BadRequestError(
                f"{order.reference} is {order.status.lower().replace('_', ' ')} "
                "and cannot be approved."
            )

        order.status = (
            PurchaseOrderStatus.APPROVED if approve else PurchaseOrderStatus.REJECTED
        )
        order.approved_by_id = actor_id
        order.approved_at = datetime.now(tz=UTC)
        order.approval_note = note
        await self.session.flush()
        await self.hydrate(order)

        await event_bus.emit(
            self.session,
            merchant_id=self.merchant_id,
            event_type=EventType.PO_APPROVED,
            correlation_id=order.correlation_id or event_bus.new_correlation_id(),
            entity_type="purchase_order",
            entity_id=order.id,
            payload={**self.describe(order), "approved": approve},
        )
        return order

    # ------------------------------------------------------------------ send
    async def mark_sent(
        self, *, order_id: uuid.UUID, channel: str = "", detail: str = ""
    ) -> PurchaseOrder:
        """Record that the vendor was actually contacted.

        A dry run stops here with the order intact and clearly labelled, which is
        the whole point: everything is exercised except the irreversible step.
        """
        order = await self.get(order_id)
        if order.status != PurchaseOrderStatus.APPROVED:
            raise BadRequestError(
                f"{order.reference} must be approved before it can be sent."
            )

        if order.is_dry_run:
            order.notes = (order.notes + "\nDRY RUN - no order was sent.").strip()
            order.status = PurchaseOrderStatus.ORDERED
            order.sent_at = datetime.now(tz=UTC)
        else:
            order.status = PurchaseOrderStatus.ORDERED
            order.sent_at = datetime.now(tz=UTC)

        order.metadata_json = {
            **(order.metadata_json or {}),
            "sent_channel": channel or order.vendor.ordering_method,
            "sent_detail": detail,
        }
        await self.session.flush()
        await self.hydrate(order)

        await event_bus.emit(
            self.session,
            merchant_id=self.merchant_id,
            event_type=EventType.PO_SENT,
            correlation_id=order.correlation_id or event_bus.new_correlation_id(),
            entity_type="purchase_order",
            entity_id=order.id,
            payload={**self.describe(order), "channel": channel, "dry_run": order.is_dry_run},
        )
        return order

    # ------------------------------------------------------------------ receive
    async def receive(
        self,
        *,
        order_id: uuid.UUID,
        lines: list[dict[str, Any]],
        actor_id: uuid.UUID | None = None,
        expiry_date: date | None = None,
    ) -> PurchaseOrder:
        """Book in goods. Partial receipts are normal, not an error.

        Each receipt creates a batch so expiry and landed cost stay attached to
        the units that actually arrived.
        """
        order = await self.get(order_id)
        if order.status in (
            PurchaseOrderStatus.CANCELLED,
            PurchaseOrderStatus.REJECTED,
        ):
            raise BadRequestError(f"{order.reference} is {order.status.lower()}.")

        by_id = {str(line.id): line for line in order.lines}
        correlation_id = order.correlation_id or event_bus.new_correlation_id()

        for entry in lines:
            line = by_id.get(str(entry.get("line_id")))
            if line is None:
                raise BadRequestError("Unknown purchase order line.")
            quantity = float(entry.get("quantity") or 0)
            if quantity <= 0:
                continue
            if quantity > line.quantity_outstanding:
                raise BadRequestError(
                    f"{line.sku}: receiving {quantity:g} exceeds the "
                    f"{line.quantity_outstanding:g} still outstanding."
                )

            item = (
                await self.session.execute(
                    select(InventoryItem).where(InventoryItem.id == line.inventory_item_id)
                )
            ).scalars().first()
            if item is None:
                raise NotFoundError("Inventory item no longer exists.")

            batch = InventoryBatch(
                merchant_id=self.merchant_id,
                inventory_item_id=item.id,
                batch_code=f"{order.reference}-{line.sku}",
                quantity=quantity,
                quantity_received=quantity,
                unit_cost=float(line.unit_price or 0),
                received_at=datetime.now(tz=UTC),
                expiry_date=expiry_date,
                vendor_id=order.vendor_id,
                purchase_order_id=order.id,
            )
            self.session.add(batch)
            await self.session.flush()

            await self.stock.apply(
                item_id=item.id,
                movement_type=MovementType.PURCHASE_RECEIPT,
                quantity=quantity,
                correlation_id=correlation_id,
                note=f"Received against {order.reference}",
                reference_type="PURCHASE_ORDER",
                reference_id=str(order.id),
                batch_id=batch.id,
                unit_cost=float(line.unit_price or 0),
                actor_type="USER" if actor_id else "SYSTEM",
                actor_id=actor_id,
            )

            line.quantity_received = float(line.quantity_received) + quantity

        outstanding = sum(line.quantity_outstanding for line in order.lines)
        order.status = (
            PurchaseOrderStatus.RECEIVED
            if outstanding <= 0
            else PurchaseOrderStatus.PARTIALLY_RECEIVED
        )
        if outstanding <= 0:
            order.received_at = datetime.now(tz=UTC)
        await self.session.flush()
        await self.hydrate(order)

        await event_bus.emit(
            self.session,
            merchant_id=self.merchant_id,
            event_type=EventType.PURCHASE_RECEIVED,
            correlation_id=correlation_id,
            entity_type="purchase_order",
            entity_id=order.id,
            payload={**self.describe(order), "outstanding": outstanding},
        )
        return order

    # ------------------------------------------------------------------ helpers
    async def hydrate(self, order: PurchaseOrder) -> PurchaseOrder:
        """Load the relationships ``describe`` reads.

        A freshly constructed order has no loaded ``vendor`` or ``lines``, and
        touching them would fire lazy IO from async context - which SQLAlchemy
        refuses with MissingGreenlet rather than blocking the loop.
        """
        await self.session.refresh(order, ["vendor", "lines"])
        return order

    async def get(self, order_id: uuid.UUID) -> PurchaseOrder:
        order = (
            await self.session.execute(
                select(PurchaseOrder).where(
                    PurchaseOrder.id == order_id,
                    PurchaseOrder.merchant_id == self.merchant_id,
                )
            )
        ).scalars().first()
        if order is None:
            raise NotFoundError("Purchase order not found.")
        return order

    @staticmethod
    def describe(order: PurchaseOrder) -> dict[str, Any]:
        return {
            "purchase_order_id": str(order.id),
            "reference": order.reference,
            "status": order.status,
            "vendor_id": str(order.vendor_id),
            "vendor_name": order.vendor.name if order.vendor else "",
            "total_value": float(order.total_value or 0),
            "requires_approval": bool(order.requires_approval),
            "is_dry_run": bool(order.is_dry_run),
            "correlation_id": order.correlation_id,
            "lines": [
                {
                    "line_id": str(line.id),
                    "sku": line.sku,
                    "product_name": line.product_name,
                    "quantity_ordered": float(line.quantity_ordered),
                    "quantity_received": float(line.quantity_received),
                    "unit_price": float(line.unit_price or 0),
                }
                for line in order.lines
            ],
        }


async def notify_vendor(order: PurchaseOrder) -> tuple[bool, str]:
    """Contact the supplier over their configured channel.

    Returns ``(sent, detail)`` and never raises: a vendor's mail server being
    down must not roll back an order that is otherwise valid. The caller records
    the failure and the operator can retry.
    """
    if order.is_dry_run:
        return False, "Dry run - no vendor was contacted."

    vendor = order.vendor
    method = (vendor.ordering_method or OrderingMethod.MANUAL).upper()

    if method == OrderingMethod.MANUAL:
        return False, "Vendor is set to manual ordering."

    if method == OrderingMethod.EMAIL:
        if not vendor.email:
            return False, "Vendor has no email address on file."
        from app.integrations.email import send_email

        lines = "\n".join(
            f"  {line.sku}  {line.product_name}  x{float(line.quantity_ordered):g} "
            f"@ {float(line.unit_price or 0):,.2f}"
            for line in order.lines
        )
        text = (
            f"Purchase order {order.reference}\n\n{lines}\n\n"
            f"Total: {float(order.total_value or 0):,.2f} {order.currency}\n"
            f"Expected: {order.expected_at or 'as soon as possible'}\n"
        )
        html = (
            f"<h2>Purchase order {order.reference}</h2><pre>{lines}</pre>"
            f"<p><strong>Total: {float(order.total_value or 0):,.2f} "
            f"{order.currency}</strong></p>"
        )
        ok = await send_email(
            to=vendor.email,
            subject=f"Purchase order {order.reference}",
            html=html,
            text=text,
            category="purchase_order",
        )
        return ok, "Emailed" if ok else "Email transport declined or failed."

    if method in (OrderingMethod.WEBHOOK, OrderingMethod.API):
        if not vendor.webhook_url:
            return False, "Vendor has no webhook URL on file."
        import httpx

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
                response = await client.post(
                    vendor.webhook_url, json=ProcurementService.describe(order)
                )
                response.raise_for_status()
            return True, f"Posted to vendor webhook ({response.status_code})."
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"[:200]

    return False, f"Unknown ordering method {method}."
