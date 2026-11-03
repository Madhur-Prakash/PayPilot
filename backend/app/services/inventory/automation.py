"""What n8n actually calls, and the scheduled sweeps.

n8n orchestrates; this module holds the rules it orchestrates. A workflow node
posts "this low-stock event happened" and gets back a decision it did not have to
make - which keeps the business logic testable here rather than scattered across
JavaScript nodes in a tool with no test suite.

Every entry point is idempotent and records an :class:`AutomationRun` so the UI
can show what happened, step by step, under this platform's own RBAC.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.automation import (
    AutomationRun,
    AutomationStatus,
    EventType,
)
from app.db.models.inventory import (
    BatchStatus,
    InventoryBatch,
    InventoryItem,
    MovementType,
)
from app.services.inventory import events as event_bus
from app.services.inventory.procurement import ProcurementService, notify_vendor
from app.services.inventory.replenishment import (
    decide_reorder,
    open_order_for_item,
    select_vendor,
)
from app.services.inventory.stock import StockEngine

log = get_logger(__name__)


@dataclass(slots=True)
class ReplenishmentResult:
    status: str
    reason: str
    run_id: uuid.UUID | None = None
    purchase_order_id: uuid.UUID | None = None
    reference: str = ""
    quantity: float = 0.0
    vendor: str = ""
    requires_approval: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "run_id": str(self.run_id) if self.run_id else None,
            "purchase_order_id": (
                str(self.purchase_order_id) if self.purchase_order_id else None
            ),
            "reference": self.reference,
            "quantity": self.quantity,
            "vendor": self.vendor,
            "requires_approval": self.requires_approval,
        }


class InventoryAutomation:
    def __init__(self, session: AsyncSession, merchant_id: uuid.UUID) -> None:
        self.session = session
        self.merchant_id = merchant_id

    # ------------------------------------------------------------------ runs
    async def start_run(
        self,
        *,
        workflow_name: str,
        correlation_id: str,
        trigger_event_id: uuid.UUID | None = None,
        trigger_event_type: str = "",
        entity_type: str = "",
        entity_id: uuid.UUID | None = None,
        n8n_execution_id: str = "",
    ) -> AutomationRun:
        run = AutomationRun(
            merchant_id=self.merchant_id,
            correlation_id=correlation_id,
            workflow_name=workflow_name,
            n8n_execution_id=n8n_execution_id,
            trigger_event_id=trigger_event_id,
            trigger_event_type=trigger_event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            status=AutomationStatus.RUNNING,
            started_at=datetime.now(tz=UTC),
            steps=[],
            is_dry_run=settings.inventory_dry_run,
        )
        self.session.add(run)
        await self.session.flush()
        return run

    @staticmethod
    def step(run: AutomationRun, name: str, detail: str, status: str = "ok") -> None:
        """Append one human-readable step. This is what the trace UI renders."""
        run.steps = [
            *(run.steps or []),
            {
                "at": datetime.now(tz=UTC).isoformat(),
                "step": name,
                "detail": detail,
                "status": status,
            },
        ]

    @staticmethod
    def finish(run: AutomationRun, status: str, error: str = "") -> None:
        run.status = status
        run.error = error
        run.completed_at = datetime.now(tz=UTC)

    # ------------------------------------------------------------------ reorder
    async def replenish(
        self,
        *,
        inventory_item_id: uuid.UUID,
        event_id: uuid.UUID | None = None,
        correlation_id: str | None = None,
        n8n_execution_id: str = "",
        force: bool = False,
    ) -> ReplenishmentResult:
        """Decide and, if warranted, raise a purchase order.

        Every early return is a real business outcome, not a failure: automation
        turned off, an order already in flight, no supplier configured. Each one
        is recorded so the merchant can see *why* nothing was ordered.
        """
        correlation_id = correlation_id or event_bus.new_correlation_id()
        run = await self.start_run(
            workflow_name="low-stock-replenishment",
            correlation_id=correlation_id,
            trigger_event_id=event_id,
            trigger_event_type=EventType.LOW_STOCK,
            entity_type="inventory_item",
            entity_id=inventory_item_id,
            n8n_execution_id=n8n_execution_id,
        )

        item = (
            await self.session.execute(
                select(InventoryItem).where(
                    InventoryItem.id == inventory_item_id,
                    InventoryItem.merchant_id == self.merchant_id,
                )
            )
        ).scalars().first()
        if item is None:
            self.step(run, "Fetch inventory", "Item not found for this merchant.", "error")
            self.finish(run, AutomationStatus.FAILED, "Inventory item not found.")
            return ReplenishmentResult("FAILED", "Inventory item not found.", run.id)

        self.step(
            run,
            "Fetch inventory",
            f"{item.sku}: {item.available_quantity:g} available, "
            f"reorder point {float(item.reorder_point):g}.",
        )

        if not settings.inventory_automation_enabled:
            self.step(run, "Check policy", "Inventory automation is off.", "skipped")
            self.finish(run, AutomationStatus.SKIPPED)
            return ReplenishmentResult("SKIPPED", "Inventory automation is disabled.", run.id)

        if not item.automatic_ordering_enabled and not force:
            self.step(
                run, "Check policy", f"Automatic ordering is off for {item.sku}.", "skipped"
            )
            self.finish(run, AutomationStatus.SKIPPED)
            return ReplenishmentResult(
                "SKIPPED", f"Automatic ordering is disabled for {item.sku}.", run.id
            )

        existing = await open_order_for_item(self.session, item=item)
        if existing is not None:
            self.step(
                run,
                "Check open orders",
                f"{existing.reference} is already {existing.status.lower()}.",
                "skipped",
            )
            self.finish(run, AutomationStatus.SKIPPED)
            return ReplenishmentResult(
                "SKIPPED",
                f"{existing.reference} is already open for this item.",
                run.id,
                purchase_order_id=existing.id,
                reference=existing.reference,
            )

        decision = decide_reorder(item)
        if not decision.should_reorder and not force:
            self.step(run, "Calculate quantity", decision.reason, "skipped")
            self.finish(run, AutomationStatus.SKIPPED)
            return ReplenishmentResult("SKIPPED", decision.reason, run.id)

        self.step(
            run,
            "Calculate quantity",
            f"{decision.strategy}: order {decision.quantity:g}. {decision.reason}",
        )

        choice = await select_vendor(self.session, item=item, quantity=decision.quantity)
        if choice is None:
            reason = f"No active supplier can supply {decision.quantity:g} of {item.sku}."
            self.step(run, "Select vendor", reason, "error")
            self.finish(run, AutomationStatus.FAILED, reason)
            await event_bus.emit(
                self.session,
                merchant_id=self.merchant_id,
                event_type=EventType.PO_FAILED,
                correlation_id=correlation_id,
                entity_type="inventory_item",
                entity_id=item.id,
                payload={"sku": item.sku, "reason": reason},
            )
            return ReplenishmentResult("FAILED", reason, run.id)

        self.step(run, "Select vendor", f"{choice.vendor.name}. {choice.reason}")

        procurement = ProcurementService(self.session, self.merchant_id)
        outcome = await procurement.create_order(
            item=item,
            choice=choice,
            decision=decision,
            correlation_id=correlation_id,
            # Derived from the event, so a redelivery maps to the same order.
            idempotency_key=f"reorder:{event_id or item.id}",
        )
        order = outcome.order

        if not outcome.created:
            self.step(run, "Create order", f"{order.reference} already existed.", "skipped")
            self.finish(run, AutomationStatus.SKIPPED)
            return ReplenishmentResult(
                "SKIPPED",
                outcome.reason,
                run.id,
                purchase_order_id=order.id,
                reference=order.reference,
            )

        self.step(
            run,
            "Create order",
            f"{order.reference} for {decision.quantity:g} at "
            f"{float(order.total_value):,.2f}.",
        )

        if order.requires_approval:
            self.step(
                run,
                "Approval",
                f"{float(order.total_value):,.2f} is at or above the "
                f"{settings.inventory_approval_threshold:,.0f} threshold. Waiting for a human.",
                "pending",
            )
            self.finish(run, AutomationStatus.AWAITING_APPROVAL)
            return ReplenishmentResult(
                "AWAITING_APPROVAL",
                "Order created and waiting for approval.",
                run.id,
                purchase_order_id=order.id,
                reference=order.reference,
                quantity=decision.quantity,
                vendor=choice.vendor.name,
                requires_approval=True,
            )

        sent, detail = await notify_vendor(order)
        await procurement.mark_sent(
            order_id=order.id, channel=choice.vendor.ordering_method, detail=detail
        )
        self.step(
            run,
            "Notify vendor",
            detail or ("Sent" if sent else "Not sent"),
            "ok" if sent else "warning",
        )

        self.finish(run, AutomationStatus.COMPLETED)
        return ReplenishmentResult(
            "COMPLETED",
            f"{order.reference} raised with {choice.vendor.name}.",
            run.id,
            purchase_order_id=order.id,
            reference=order.reference,
            quantity=decision.quantity,
            vendor=choice.vendor.name,
        )

    # ------------------------------------------------------------------ aging
    async def sweep_aging(
        self, *, today: date | None = None, n8n_execution_id: str = ""
    ) -> dict[str, Any]:
        """Move batches through AGING -> EXPIRING_SOON -> EXPIRED.

        Expired stock is written off with a WASTAGE movement rather than deleted,
        so the ledger still explains where the units went.
        """
        today = today or date.today()
        correlation_id = event_bus.new_correlation_id("AGE")
        run = await self.start_run(
            workflow_name="inventory-aging",
            correlation_id=correlation_id,
            n8n_execution_id=n8n_execution_id,
        )

        horizon = today + timedelta(days=settings.inventory_expiry_window_days)
        stmt = select(InventoryBatch).where(
            InventoryBatch.merchant_id == self.merchant_id,
            InventoryBatch.status.notin_([BatchStatus.EXPIRED, BatchStatus.DEPLETED]),
            InventoryBatch.expiry_date.is_not(None),
            InventoryBatch.expiry_date <= horizon,
        )
        batches = list((await self.session.execute(stmt)).scalars().all())

        engine = StockEngine(self.session, self.merchant_id)
        expiring = expired = 0

        for batch in batches:
            if batch.expiry_date and batch.expiry_date <= today:
                quantity = float(batch.quantity or 0)
                batch.status = BatchStatus.EXPIRED
                if quantity > 0:
                    await engine.apply(
                        item_id=batch.inventory_item_id,
                        movement_type=MovementType.EXPIRY,
                        quantity=quantity,
                        correlation_id=correlation_id,
                        note=f"Batch {batch.batch_code} expired on {batch.expiry_date}.",
                        reference_type="BATCH",
                        reference_id=str(batch.id),
                        batch_id=batch.id,
                        unit_cost=float(batch.unit_cost or 0),
                        source="system",
                    )
                    batch.quantity = 0
                expired += 1
                await event_bus.emit(
                    self.session,
                    merchant_id=self.merchant_id,
                    event_type=EventType.STOCK_EXPIRED,
                    correlation_id=correlation_id,
                    entity_type="inventory_batch",
                    entity_id=batch.id,
                    payload={
                        "batch_code": batch.batch_code,
                        "quantity": quantity,
                        "expiry_date": str(batch.expiry_date),
                    },
                )
            else:
                batch.status = BatchStatus.EXPIRING_SOON
                expiring += 1
                await event_bus.emit(
                    self.session,
                    merchant_id=self.merchant_id,
                    event_type=EventType.STOCK_EXPIRING,
                    correlation_id=correlation_id,
                    entity_type="inventory_batch",
                    entity_id=batch.id,
                    payload={
                        "batch_code": batch.batch_code,
                        "quantity": float(batch.quantity or 0),
                        "expiry_date": str(batch.expiry_date),
                        "days_left": (batch.expiry_date - today).days,
                    },
                )

        self.step(
            run,
            "Sweep batches",
            f"{len(batches)} within the {settings.inventory_expiry_window_days}-day window: "
            f"{expiring} expiring soon, {expired} expired.",
        )
        self.finish(run, AutomationStatus.COMPLETED)
        await self.session.flush()

        return {
            "scanned": len(batches),
            "expiring_soon": expiring,
            "expired": expired,
            "run_id": str(run.id),
            "correlation_id": correlation_id,
        }

    # ------------------------------------------------------------------ recon
    async def reconcile(self, *, n8n_execution_id: str = "") -> dict[str, Any]:
        """Compare stored balances against the ledger. Never auto-corrects.

        A discrepancy means something wrote stock outside the engine, which is a
        bug worth a human looking at - silently "fixing" it would hide the cause.
        """

        from app.db.models.inventory import InventoryMovement

        correlation_id = event_bus.new_correlation_id("RECON")
        run = await self.start_run(
            workflow_name="daily-reconciliation",
            correlation_id=correlation_id,
            n8n_execution_id=n8n_execution_id,
        )

        items = list(
            (
                await self.session.execute(
                    select(InventoryItem).where(
                        InventoryItem.merchant_id == self.merchant_id
                    )
                )
            ).scalars().all()
        )

        discrepancies: list[dict[str, Any]] = []
        for item in items:
            latest = (
                await self.session.execute(
                    select(InventoryMovement.balance_after)
                    .where(InventoryMovement.inventory_item_id == item.id)
                    .order_by(InventoryMovement.created_at.desc())
                    .limit(1)
                )
            ).scalars().first()
            if latest is None:
                continue
            expected = float(latest)
            actual = float(item.quantity_on_hand)
            if abs(expected - actual) > 0.001:
                discrepancies.append(
                    {
                        "sku": item.sku,
                        "inventory_item_id": str(item.id),
                        "expected": expected,
                        "actual": actual,
                        "difference": round(actual - expected, 2),
                    }
                )

        if discrepancies:
            await event_bus.emit(
                self.session,
                merchant_id=self.merchant_id,
                event_type=EventType.RECONCILIATION_DISCREPANCY,
                correlation_id=correlation_id,
                entity_type="merchant",
                entity_id=self.merchant_id,
                payload={"count": len(discrepancies), "items": discrepancies[:50]},
            )

        self.step(
            run,
            "Reconcile",
            f"{len(items)} items checked, {len(discrepancies)} discrepancies.",
            "warning" if discrepancies else "ok",
        )
        self.finish(run, AutomationStatus.COMPLETED)
        await self.session.flush()

        return {
            "checked": len(items),
            "discrepancies": discrepancies,
            "run_id": str(run.id),
            "correlation_id": correlation_id,
        }
