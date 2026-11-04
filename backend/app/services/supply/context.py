"""Shared plumbing for the supply services: scoping, references, messaging, tracing."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models.agent import AgentName, AgentRun, AgentRunStatus, AgentStep, AgentWorkflow
from app.db.models.governance import AgentMessage
from app.db.models.inventory import InventoryItem
from app.db.models.procurement import PurchaseOrder, Vendor, VendorProduct
from app.db.models.supply import (
    NegotiationOffer,
    NegotiationSession,
    ProcurementRequest,
    SupplierAgent,
    SupplierInvoice,
)
from app.repositories.agent import AgentRunRepository
from app.repositories.merchant import AuditLogRepository
from app.services.supply.protocol import (
    AgentIdentity,
    MessageBus,
    buyer_identity,
    supplier_identity,
    system_identity,
)


class SupplyContext:
    """Base for the negotiation and lifecycle services. One merchant, one session."""

    def __init__(
        self,
        session: AsyncSession,
        merchant_id: uuid.UUID,
        *,
        actor_id: uuid.UUID | None = None,
        actor_label: str = "",
        request_id: str | None = None,
    ) -> None:
        self.session = session
        self.merchant_id = merchant_id
        self.actor_id = actor_id
        self.actor_label = actor_label or "system"
        self.request_id = request_id
        self.bus = MessageBus(session, merchant_id)
        self.audit = AuditLogRepository(session)
        self.buyer: AgentIdentity = buyer_identity(merchant_id)
        self.system: AgentIdentity = system_identity()

    # ------------------------------------------------------------------ references
    async def next_reference(self, model: Any, prefix: str, column: str = "reference") -> str:
        count = (
            await self.session.execute(
                select(func.count()).select_from(model).where(model.merchant_id == self.merchant_id)
            )
        ).scalar_one()
        return f"{prefix}-{int(count) + 1:05d}"

    # ------------------------------------------------------------------ loaders (all tenant scoped)
    async def _scoped(self, model: Any, entity_id: uuid.UUID, label: str) -> Any:
        row = (
            await self.session.execute(
                select(model).where(model.id == entity_id, model.merchant_id == self.merchant_id)
            )
        ).scalars().first()
        if row is None:
            raise NotFoundError(f"{label} not found.")
        return row

    async def request(self, request_id: uuid.UUID) -> ProcurementRequest:
        return await self._scoped(ProcurementRequest, request_id, "Procurement request")

    async def item(self, item_id: uuid.UUID) -> InventoryItem:
        return await self._scoped(InventoryItem, item_id, "Inventory item")

    async def supplier_agent(self, agent_id: uuid.UUID) -> SupplierAgent:
        return await self._scoped(SupplierAgent, agent_id, "Supplier agent")

    async def offer(self, offer_id: uuid.UUID) -> NegotiationOffer:
        return await self._scoped(NegotiationOffer, offer_id, "Offer")

    async def purchase_order(self, order_id: uuid.UUID) -> PurchaseOrder:
        return await self._scoped(PurchaseOrder, order_id, "Purchase order")

    async def invoice(self, invoice_id: uuid.UUID) -> SupplierInvoice:
        return await self._scoped(SupplierInvoice, invoice_id, "Supplier invoice")

    async def sessions_for(self, request_id: uuid.UUID) -> list[NegotiationSession]:
        return list(
            (
                await self.session.execute(
                    select(NegotiationSession)
                    .where(
                        NegotiationSession.merchant_id == self.merchant_id,
                        NegotiationSession.procurement_request_id == request_id,
                    )
                    .order_by(NegotiationSession.created_at)
                )
            ).scalars().all()
        )

    async def offers_for(self, session_id: uuid.UUID) -> list[NegotiationOffer]:
        return list(
            (
                await self.session.execute(
                    select(NegotiationOffer)
                    .where(NegotiationOffer.merchant_id == self.merchant_id, NegotiationOffer.session_id == session_id)
                    .order_by(NegotiationOffer.sequence)
                )
            ).scalars().all()
        )

    async def supply_link(self, agent: SupplierAgent, item_id: uuid.UUID) -> VendorProduct | None:
        return (
            await self.session.execute(
                select(VendorProduct).where(
                    VendorProduct.merchant_id == self.merchant_id,
                    VendorProduct.vendor_id == agent.vendor_id,
                    VendorProduct.inventory_item_id == item_id,
                )
            )
        ).scalars().first()

    async def vendor(self, vendor_id: uuid.UUID) -> Vendor:
        return await self._scoped(Vendor, vendor_id, "Vendor")

    async def agent_for_vendor(self, vendor_id: uuid.UUID) -> SupplierAgent | None:
        return (
            await self.session.execute(
                select(SupplierAgent).where(
                    SupplierAgent.merchant_id == self.merchant_id, SupplierAgent.vendor_id == vendor_id
                )
            )
        ).scalars().first()

    def supplier(self, agent: SupplierAgent) -> AgentIdentity:
        return supplier_identity(agent)

    # ------------------------------------------------------------------ messaging
    async def send(
        self,
        *,
        sender: AgentIdentity,
        recipient: AgentIdentity,
        message_type: str,
        payload: dict[str, Any],
        request: ProcurementRequest,
        key: str,
        session_id: uuid.UUID | None = None,
        summary: str = "",
    ) -> AgentMessage:
        return await self.bus.send(
            sender=sender,
            recipient=recipient,
            message_type=message_type,
            payload=payload,
            conversation_id=request.conversation_id,
            correlation_id=request.correlation_id,
            idempotency_key=f"{request.reference}:{key}",
            procurement_request_id=request.id,
            session_id=session_id,
            summary=summary,
        )

    # ------------------------------------------------------------------ agent run trace
    async def run_for(self, request: ProcurementRequest) -> AgentRun:
        repo = AgentRunRepository(self.session, self.merchant_id)
        if request.agent_run_id:
            run = await self.session.get(AgentRun, request.agent_run_id)
            if run is not None and run.merchant_id == self.merchant_id:
                return run
        run = await repo.start(
            agent_name=AgentName.PROCUREMENT_ORCHESTRATOR,
            workflow=AgentWorkflow.PROCUREMENT,
            input_text=f"Procure {request.quantity:f} x {request.product_name} ({request.reference})",
            user_id=self.actor_id,
            metadata={"procurement_request_id": str(request.id), "correlation_id": request.correlation_id},
        )
        request.agent_run_id = run.id
        await self.session.flush()
        return run

    async def step(
        self,
        request: ProcurementRequest,
        *,
        node: str,
        agent_name: str,
        action: str,
        result: str = "",
        decision: str | None = None,
        evidence: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        run = await self.run_for(request)
        repo = AgentRunRepository(self.session, self.merchant_id)
        existing = (
            await self.session.execute(
                select(func.count()).select_from(AgentStep).where(AgentStep.agent_run_id == run.id)
            )
        ).scalar_one()
        await repo.add_step(
            run=run,
            sequence=int(existing) + 1,
            node=node,
            agent_name=agent_name,
            action=action,
            result=result[:4000],
            decision=decision,
            evidence=evidence or [],
            metadata={**(metadata or {}), "at": datetime.now(tz=UTC).isoformat()},
        )

    async def finish_run(
        self, request: ProcurementRequest, *, status: str, summary: str, requires_approval: bool, output: dict
    ) -> None:
        run = await self.run_for(request)
        if run.status in (AgentRunStatus.COMPLETED, AgentRunStatus.AWAITING_APPROVAL) and status == run.status:
            return
        await AgentRunRepository(self.session, self.merchant_id).finish(
            run,
            status=status,
            summary=summary,
            output=output,
            decision=summary,
            requires_approval=requires_approval,
            used_fallback=not bool(output.get("used_llm")),
        )
