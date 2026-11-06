"""Supply Agents API: suppliers, demand, procurement, negotiation, receiving,
invoices, payment and reconciliation.

Every money-moving step is two things at once: an endpoint gated by a permission,
and a service that refuses to act without a recorded human approval bound to the
exact terms. ANALYST can source and negotiate; only roles with
``procurement:approve`` / ``payment:approve`` can say yes - and an Owner still has
to say it explicitly.
"""

from __future__ import annotations

import contextlib
import uuid
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import Field
from sqlalchemy import func, select

from app.api.deps import DbSession, Principal, require_permission
from app.core.exceptions import NotFoundError
from app.core.permissions import Permission
from app.db.models.governance import AgentMessage, FinancialExecution
from app.db.models.procurement import PurchaseOrder, VendorProduct
from app.db.models.supply import (
    GoodsReceipt,
    InvoiceMatch,
    NegotiationSession,
    ProcurementReconciliation,
    ProcurementRequest,
    SupplierAgent,
    SupplierInvoice,
)
from app.schemas.common import APIResponse, PageMeta, Paginated, SchemaBase
from app.services.supply.demand import InventoryIntelligence
from app.services.supply.lifecycle import ProcurementLifecycle
from app.services.supply.negotiation import NegotiationService
from app.services.supply.protocol import MessageBus, describe_message
from app.services.supply.serializers import (
    execution_out,
    invoice_out,
    match_out,
    order_brief,
    receipt_out,
    reconciliation_out,
    request_out,
    session_out,
    supplier_public,
)

router = APIRouter(tags=["supply-agents"])


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class ProcurementCreate(SchemaBase):
    inventory_item_id: uuid.UUID
    quantity: Decimal | None = Field(default=None, gt=0)
    target_margin: Decimal | None = Field(default=None, ge=0, lt=1)
    max_delivery_days: int | None = Field(default=None, ge=1, le=60)
    min_reliability: Decimal | None = Field(default=None, ge=0, le=1)
    max_rounds: int | None = Field(default=None, ge=1, le=6)
    budget_cap: Decimal | None = Field(default=None, gt=0)
    auto_negotiate: bool = False
    note: str = Field(default="", max_length=1000)


class Decision(SchemaBase):
    approve: bool
    note: str = Field(default="", max_length=1000)


class ReceiveLine(SchemaBase):
    line_id: uuid.UUID
    quantity: Decimal = Field(gt=0)


class ReceiveRequest(SchemaBase):
    lines: list[ReceiveLine] = Field(min_length=1)
    notes: str = Field(default="", max_length=1000)


class DeliveryDelayRequest(SchemaBase):
    days: int = Field(default=3, ge=1, le=30)
    reason: str = Field(default="", max_length=240)


def _ctx(principal: Principal, request: Request | None = None) -> dict[str, Any]:
    return {
        "actor_id": principal.user_id,
        "actor_label": principal.label,
        "request_id": principal.request_id,
    }


# --------------------------------------------------------------------------- #
# Supplier network
# --------------------------------------------------------------------------- #
@router.get("/suppliers", summary="Supplier agent network")
async def list_suppliers(
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.VENDOR_READ)),
) -> APIResponse[list[dict[str, Any]]]:
    agents = (await session.execute(
        select(SupplierAgent).where(SupplierAgent.merchant_id == principal.merchant_id).order_by(SupplierAgent.display_name)
    )).scalars().all()
    out = []
    for agent in agents:
        catalog = (await session.execute(
            select(VendorProduct).where(VendorProduct.merchant_id == principal.merchant_id, VendorProduct.vendor_id == agent.vendor_id)
        )).scalars().all()
        out.append(supplier_public(agent, list(catalog)))
    return APIResponse(data=out, meta={"count": len(out)})


@router.get("/suppliers/{supplier_agent_id}", summary="Supplier agent profile")
async def get_supplier(
    supplier_agent_id: uuid.UUID,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.VENDOR_READ)),
) -> APIResponse[dict[str, Any]]:
    agent = (await session.execute(
        select(SupplierAgent).where(SupplierAgent.id == supplier_agent_id, SupplierAgent.merchant_id == principal.merchant_id)
    )).scalars().first()
    if agent is None:
        raise NotFoundError("Supplier agent not found.")
    catalog = (await session.execute(
        select(VendorProduct).where(VendorProduct.merchant_id == principal.merchant_id, VendorProduct.vendor_id == agent.vendor_id)
    )).scalars().all()
    sessions = (await session.execute(
        select(NegotiationSession).where(NegotiationSession.supplier_agent_id == agent.id)
        .order_by(NegotiationSession.created_at.desc()).limit(20)
    )).scalars().all()
    history = []
    for s in sessions:
        req = await session.get(ProcurementRequest, s.procurement_request_id)
        history.append({"session_id": str(s.id), "status": s.status, "rounds": s.current_round,
                        "procurement_reference": req.reference if req else "",
                        "product_name": req.product_name if req else "",
                        "outcome_reason": s.outcome_reason,
                        "created_at": s.created_at.isoformat() if s.created_at else None})
    data = supplier_public(agent, list(catalog))
    data["negotiation_history"] = history
    return APIResponse(data=data)


# --------------------------------------------------------------------------- #
# Inventory intelligence
# --------------------------------------------------------------------------- #
@router.get("/supply/demand", summary="Demand, stockout risk and reorder recommendations")
async def demand_scan(
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.INVENTORY_READ)),
) -> APIResponse[list[dict[str, Any]]]:
    results = await InventoryIntelligence(session, principal.merchant_id).scan()
    return APIResponse(
        data=[r.as_dict() for r in results],
        meta={"at_risk": sum(1 for r in results if r.stockout_risk),
              "demand_increases": sum(1 for r in results if r.demand_increased),
              "method": "deterministic: 14-day velocity vs prior 14 days; cover = available / velocity"},
    )


@router.get("/supply/timeline", summary="Procurement timeline for the Gantt (tasks + dependencies)")
async def procurement_timeline(
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=30)] = 12,
    principal: Principal = Depends(require_permission(Permission.PROCUREMENT_READ)),
) -> APIResponse[dict[str, Any]]:
    from app.services.supply.timeline import build_timeline

    return APIResponse(data=await build_timeline(session, principal.merchant_id, limit=limit))


@router.get("/supply/overview", summary="Supply command center")
async def supply_overview(
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PROCUREMENT_READ)),
) -> APIResponse[dict[str, Any]]:
    from app.services.intelligence.unified import command_center

    data = await command_center(session, principal.merchant_id, days=30)
    demand = await InventoryIntelligence(session, principal.merchant_id).scan()
    receipts = (await session.execute(
        select(GoodsReceipt).where(GoodsReceipt.merchant_id == principal.merchant_id)
        .order_by(GoodsReceipt.received_at.desc()).limit(5)
    )).scalars().all()
    return APIResponse(data={
        "inventory": data["inventory"],
        "procurement": data["procurement"],
        "suppliers": data["suppliers"],
        "approvals": data["approvals"],
        "events": [e for e in data["events"] if e["module"] in ("supply", "finance", "governance")],
        "reorder": [d.as_dict() for d in demand if d.stockout_risk or d.suggested_quantity > 0][:10],
        "recent_receipts": [receipt_out(r) for r in receipts],
        "currency": data["currency"],
    })


# --------------------------------------------------------------------------- #
# Procurement requests
# --------------------------------------------------------------------------- #
@router.get("/procurement", summary="Procurement requests and RFQs")
async def list_procurement(
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    request_status: Annotated[str | None, Query(alias="status")] = None,
    principal: Principal = Depends(require_permission(Permission.PROCUREMENT_READ)),
) -> APIResponse[Paginated[dict[str, Any]]]:
    conditions = [ProcurementRequest.merchant_id == principal.merchant_id]
    if request_status:
        conditions.append(ProcurementRequest.status == request_status)
    rows = (await session.execute(
        select(ProcurementRequest).where(*conditions).order_by(ProcurementRequest.created_at.desc())
        .limit(page_size).offset((page - 1) * page_size)
    )).scalars().all()
    total = (await session.execute(select(func.count()).select_from(ProcurementRequest).where(*conditions))).scalar_one()
    items = []
    for row in rows:
        item = request_out(row)
        sessions = (await session.execute(
            select(NegotiationSession).where(NegotiationSession.procurement_request_id == row.id)
        )).scalars().all()
        item["session_count"] = len(sessions)
        item["max_round"] = max((s.current_round for s in sessions), default=0)
        items.append(item)
    return APIResponse(data=Paginated(items=items, pagination=PageMeta.build(page=page, page_size=page_size, total=int(total))))


@router.post("/procurement", status_code=status.HTTP_201_CREATED, summary="Raise a procurement request (and RFQ)")
async def create_procurement(
    payload: ProcurementCreate,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PROCUREMENT_CREATE)),
) -> APIResponse[dict[str, Any]]:
    service = NegotiationService(session, principal.merchant_id, **_ctx(principal))
    request = await service.create_request(
        inventory_item_id=payload.inventory_item_id,
        quantity=payload.quantity,
        target_margin=payload.target_margin,
        max_delivery_days=payload.max_delivery_days,
        min_reliability=payload.min_reliability,
        max_rounds=payload.max_rounds,
        budget_cap=payload.budget_cap,
        source="USER",
        note=payload.note,
    )
    if payload.auto_negotiate:
        principal.require(Permission.PROCUREMENT_NEGOTIATE)
        request = await service.run_to_recommendation(request.id)
    return APIResponse(data=await _procurement_detail(session, principal, request))


class AutopilotRequest(SchemaBase):
    inventory_item_id: uuid.UUID | None = None
    quantity: Decimal | None = Field(default=None, gt=0)


@router.post("/procurement/autopilot", summary="Run the LangGraph procurement workflow to the approval gate",
             description="Inventory Intelligence picks the item most at risk (or the one given), the Buyer "
             "Agent sources and negotiates, Procurement Evaluation recommends, and the graph stops at a "
             "human approval request. Nothing is purchased.")
async def procurement_autopilot(
    payload: AutopilotRequest,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PROCUREMENT_CREATE, Permission.PROCUREMENT_NEGOTIATE)),
) -> APIResponse[dict[str, Any] | None]:
    from app.agents.procurement_graph import run_procurement_autopilot

    service = NegotiationService(session, principal.merchant_id, **_ctx(principal))
    state = await run_procurement_autopilot(service, inventory_item_id=payload.inventory_item_id, quantity=payload.quantity)
    if not state.get("request_id"):
        return APIResponse(data=None, meta={"outcome": "no_action", "message": "No item is at stockout risk."})
    request = await service.request(state["request_id"])
    return APIResponse(data=await _procurement_detail(session, principal, request),
                       meta={"stages": state.get("stages", []), "outcome": state.get("outcome")})


@router.get("/procurement/{request_id}", summary="Procurement detail: policy, sessions, offers, lifecycle")
async def get_procurement(
    request_id: uuid.UUID,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PROCUREMENT_READ)),
) -> APIResponse[dict[str, Any]]:
    service = NegotiationService(session, principal.merchant_id, **_ctx(principal))
    request = await service.request(request_id)
    return APIResponse(data=await _procurement_detail(session, principal, request))


@router.post("/procurement/{request_id}/advance", summary="Advance the negotiation by one stage")
async def advance_procurement(
    request_id: uuid.UUID,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PROCUREMENT_NEGOTIATE)),
) -> APIResponse[dict[str, Any]]:
    service = NegotiationService(session, principal.merchant_id, **_ctx(principal))
    step = await service.advance(request_id)
    request = await service.request(request_id)
    detail = await _procurement_detail(session, principal, request)
    return APIResponse(data=detail, meta={"stage": step["stage"]})


@router.post("/procurement/{request_id}/negotiate", summary="Run the negotiation to a recommendation")
async def run_procurement(
    request_id: uuid.UUID,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PROCUREMENT_NEGOTIATE)),
) -> APIResponse[dict[str, Any]]:
    service = NegotiationService(session, principal.merchant_id, **_ctx(principal))
    request = await service.run_to_recommendation(request_id)
    return APIResponse(data=await _procurement_detail(session, principal, request))


@router.post("/procurement/{request_id}/approve", summary="Approve or reject the recommended purchase")
async def decide_procurement(
    request_id: uuid.UUID,
    payload: Decision,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PROCUREMENT_APPROVE)),
) -> APIResponse[dict[str, Any]]:
    lifecycle = ProcurementLifecycle(session, principal.merchant_id, **_ctx(principal))
    request = await lifecycle.decide_purchase(
        request_id, approve=payload.approve, permissions=principal.permissions, note=payload.note
    )
    return APIResponse(data=await _procurement_detail(session, principal, request))


@router.get("/procurement/{request_id}/messages", summary="Agent-to-agent conversation (verified envelopes)")
async def procurement_messages(
    request_id: uuid.UUID,
    session: DbSession,
    after: Annotated[str | None, Query(description="Only messages sent after this ISO timestamp")] = None,
    principal: Principal = Depends(require_permission(Permission.PROCUREMENT_READ)),
) -> APIResponse[list[dict[str, Any]]]:
    stmt = select(AgentMessage).where(
        AgentMessage.merchant_id == principal.merchant_id, AgentMessage.procurement_request_id == request_id
    )
    if after:
        from datetime import datetime

        with contextlib.suppress(ValueError):
            stmt = stmt.where(AgentMessage.sent_at > datetime.fromisoformat(after.replace("Z", "+00:00")))
    rows = (await session.execute(stmt.order_by(AgentMessage.sent_at, AgentMessage.created_at))).scalars().all()
    return APIResponse(data=[describe_message(m) for m in rows], meta={"count": len(rows)})


async def _procurement_detail(session: Any, principal: Principal, request: ProcurementRequest) -> dict[str, Any]:
    service = NegotiationService(session, principal.merchant_id)
    data = request_out(request)
    sessions_out = []
    for s in await service.sessions_for(request.id):
        agent = await session.get(SupplierAgent, s.supplier_agent_id)
        sessions_out.append(session_out(s, agent, await service.offers_for(s.id)))
    data["sessions"] = sessions_out
    data["message_count"] = (await session.execute(
        select(func.count()).select_from(AgentMessage).where(AgentMessage.procurement_request_id == request.id)
    )).scalar_one()
    order = await session.get(PurchaseOrder, request.purchase_order_id) if request.purchase_order_id else None
    if order is not None:
        await session.refresh(order, ["lines"])
    data["purchase_order"] = order_brief(order)
    data["receipts"] = []
    data["invoices"] = []
    data["reconciliation"] = None
    if order is not None:
        receipts = (await session.execute(
            select(GoodsReceipt).where(GoodsReceipt.purchase_order_id == order.id).order_by(GoodsReceipt.received_at)
        )).scalars().all()
        data["receipts"] = [receipt_out(r) for r in receipts]
        invoices = (await session.execute(
            select(SupplierInvoice).where(SupplierInvoice.purchase_order_id == order.id)
        )).scalars().all()
        for inv in invoices:
            match = await session.get(InvoiceMatch, inv.latest_match_id) if inv.latest_match_id else None
            execution = await session.get(FinancialExecution, inv.execution_id) if inv.execution_id else None
            agent = await session.get(SupplierAgent, inv.supplier_agent_id) if inv.supplier_agent_id else None
            data["invoices"].append(invoice_out(inv, supplier_name=agent.display_name if agent else "",
                                                purchase_order_reference=order.reference, match=match, execution=execution))
        rec = (await session.execute(
            select(ProcurementReconciliation).where(ProcurementReconciliation.purchase_order_id == order.id)
        )).scalars().first()
        data["reconciliation"] = reconciliation_out(rec) if rec else None
        data["readiness"] = await ProcurementLifecycle(session, principal.merchant_id).readiness(order.id)
    if request.approval_request_id:
        from app.services.supply.approvals import ApprovalService, describe_approval

        approval = await ApprovalService(session, principal.merchant_id).get(request.approval_request_id)
        data["approval"] = describe_approval(approval)
    else:
        data["approval"] = None
    data["can"] = {
        "negotiate": principal.has(Permission.PROCUREMENT_NEGOTIATE),
        "approve": principal.has(Permission.PROCUREMENT_APPROVE),
        "receive": principal.has(Permission.PURCHASE_ORDER_RECEIVE),
        "match": principal.has(Permission.SUPPLIER_INVOICE_MATCH),
        "approve_payment": principal.has(Permission.PAYMENT_APPROVE),
        "execute_payment": principal.has(Permission.PAYMENT_EXECUTE),
    }
    return data


# --------------------------------------------------------------------------- #
# Receiving
# --------------------------------------------------------------------------- #
@router.post("/purchase-orders/{order_id}/goods-receipts", status_code=status.HTTP_201_CREATED,
             summary="Book a (partial) goods receipt and re-run matching")
async def create_goods_receipt(
    order_id: uuid.UUID,
    payload: ReceiveRequest,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PURCHASE_ORDER_RECEIVE)),
) -> APIResponse[dict[str, Any]]:
    lifecycle = ProcurementLifecycle(session, principal.merchant_id, **_ctx(principal))
    receipt = await lifecycle.receive(order_id, lines=[line.model_dump() for line in payload.lines], notes=payload.notes)
    return APIResponse(data=receipt_out(receipt))


@router.post("/purchase-orders/{order_id}/delivery-delay",
             summary="Supplier agent reports a delivery delay (signed DELIVERY_UPDATE; reschedules the timeline)")
async def report_delivery_delay(
    order_id: uuid.UUID,
    payload: DeliveryDelayRequest,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PROCUREMENT_NEGOTIATE)),
) -> APIResponse[dict[str, Any]]:
    """Plays the supplier's side of the protocol: its agent sends a signed DELIVERY_UPDATE
    (status DELAYED), the PO's expected date moves, and the Gantt redraws the delivery and
    the PayPal payment that waits on it - in red, with the original plan underneath."""
    lifecycle = ProcurementLifecycle(session, principal.merchant_id, **_ctx(principal))
    return APIResponse(data=await lifecycle.report_delivery_delay(order_id, days=payload.days, reason=payload.reason))


@router.get("/goods-receipts", summary="Goods receipts")
async def list_goods_receipts(
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PURCHASE_ORDER_READ)),
) -> APIResponse[list[dict[str, Any]]]:
    rows = (await session.execute(
        select(GoodsReceipt).where(GoodsReceipt.merchant_id == principal.merchant_id)
        .order_by(GoodsReceipt.received_at.desc()).limit(100)
    )).scalars().all()
    out = []
    for r in rows:
        item = receipt_out(r)
        order = await session.get(PurchaseOrder, r.purchase_order_id)
        item["purchase_order_reference"] = order.reference if order else ""
        out.append(item)
    return APIResponse(data=out)


@router.get("/purchase-orders/{order_id}/lifecycle", summary="Purchase order lifecycle")
async def purchase_order_lifecycle(
    order_id: uuid.UUID,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PURCHASE_ORDER_READ)),
) -> APIResponse[dict[str, Any]]:
    order = (await session.execute(
        select(PurchaseOrder).where(PurchaseOrder.id == order_id, PurchaseOrder.merchant_id == principal.merchant_id)
    )).scalars().first()
    if order is None:
        raise NotFoundError("Purchase order not found.")
    if order.procurement_request_id:
        request = await session.get(ProcurementRequest, order.procurement_request_id)
        if request is not None:
            return APIResponse(data=await _procurement_detail(session, principal, request))
    await session.refresh(order, ["lines"])
    return APIResponse(data={"purchase_order": order_brief(order), "readiness":
                             await ProcurementLifecycle(session, principal.merchant_id).readiness(order.id)})


# --------------------------------------------------------------------------- #
# Supplier invoices, matching, payment
# --------------------------------------------------------------------------- #
@router.get("/supplier-invoices", summary="Supplier invoices")
async def list_supplier_invoices(
    session: DbSession,
    invoice_status: Annotated[str | None, Query(alias="status")] = None,
    principal: Principal = Depends(require_permission(Permission.SUPPLIER_INVOICE_READ)),
) -> APIResponse[list[dict[str, Any]]]:
    conditions = [SupplierInvoice.merchant_id == principal.merchant_id]
    if invoice_status:
        conditions.append(SupplierInvoice.status == invoice_status)
    rows = (await session.execute(
        select(SupplierInvoice).where(*conditions).order_by(SupplierInvoice.issued_at.desc()).limit(100)
    )).scalars().all()
    out = []
    for inv in rows:
        order = await session.get(PurchaseOrder, inv.purchase_order_id)
        agent = await session.get(SupplierAgent, inv.supplier_agent_id) if inv.supplier_agent_id else None
        match = await session.get(InvoiceMatch, inv.latest_match_id) if inv.latest_match_id else None
        execution = await session.get(FinancialExecution, inv.execution_id) if inv.execution_id else None
        out.append(invoice_out(inv, supplier_name=agent.display_name if agent else "",
                               purchase_order_reference=order.reference if order else "",
                               match=match, execution=execution))
    return APIResponse(data=out)


@router.post("/supplier-invoices/{invoice_id}/match", summary="Run three-way matching")
async def match_supplier_invoice(
    invoice_id: uuid.UUID,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.SUPPLIER_INVOICE_MATCH)),
) -> APIResponse[dict[str, Any] | None]:
    lifecycle = ProcurementLifecycle(session, principal.merchant_id, **_ctx(principal))
    match = await lifecycle.match_invoice(invoice_id)
    return APIResponse(data=match_out(match))


@router.post("/supplier-invoices/{invoice_id}/approve-payment", summary="Approve or reject paying an invoice")
async def approve_supplier_payment(
    invoice_id: uuid.UUID,
    payload: Decision,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PAYMENT_APPROVE)),
) -> APIResponse[dict[str, Any]]:
    lifecycle = ProcurementLifecycle(session, principal.merchant_id, **_ctx(principal))
    invoice = await lifecycle.decide_payment(invoice_id, approve=payload.approve,
                                             permissions=principal.permissions, note=payload.note)
    return APIResponse(data=invoice_out(invoice))


@router.post("/supplier-invoices/{invoice_id}/pay", summary="Execute the approved PayPal payment")
async def pay_supplier_invoice(
    invoice_id: uuid.UUID,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PAYMENT_EXECUTE)),
) -> APIResponse[dict[str, Any] | None]:
    lifecycle = ProcurementLifecycle(session, principal.merchant_id, **_ctx(principal))
    execution = await lifecycle.execute_payment(invoice_id)
    return APIResponse(data=execution_out(execution))


@router.post("/payments/{execution_id}/capture", summary="Capture a payer-approved PayPal order")
async def capture_payment(
    execution_id: uuid.UUID,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PAYMENT_EXECUTE)),
) -> APIResponse[dict[str, Any] | None]:
    lifecycle = ProcurementLifecycle(session, principal.merchant_id, **_ctx(principal))
    execution = await lifecycle.capture_payment(execution_id)
    return APIResponse(data=execution_out(execution))


# --------------------------------------------------------------------------- #
# Reconciliation
# --------------------------------------------------------------------------- #
@router.get("/reconciliations", summary="Procurement reconciliations")
async def list_reconciliations(
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.SUPPLIER_INVOICE_READ)),
) -> APIResponse[list[dict[str, Any]]]:
    rows = (await session.execute(
        select(ProcurementReconciliation).where(ProcurementReconciliation.merchant_id == principal.merchant_id)
        .order_by(ProcurementReconciliation.reconciled_at.desc()).limit(100)
    )).scalars().all()
    out = []
    for rec in rows:
        item = reconciliation_out(rec)
        order = await session.get(PurchaseOrder, rec.purchase_order_id)
        item["purchase_order_reference"] = order.reference if order else ""
        out.append(item)
    return APIResponse(data=out)


@router.post("/purchase-orders/{order_id}/reconcile", summary="Reconcile PO, receipt, invoice and payment")
async def reconcile_order(
    order_id: uuid.UUID,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.SUPPLIER_INVOICE_MATCH)),
) -> APIResponse[dict[str, Any]]:
    lifecycle = ProcurementLifecycle(session, principal.merchant_id, **_ctx(principal))
    rec = await lifecycle.reconcile(order_id)
    return APIResponse(data=reconciliation_out(rec))


# --------------------------------------------------------------------------- #
# Agent communication
# --------------------------------------------------------------------------- #
@router.get("/agent-messages", summary="All agent-to-agent messages")
async def list_agent_messages(
    session: DbSession,
    message_type: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    principal: Principal = Depends(require_permission(Permission.AGENTS_VIEW)),
) -> APIResponse[list[dict[str, Any]]]:
    stmt = select(AgentMessage).where(AgentMessage.merchant_id == principal.merchant_id)
    if message_type:
        stmt = stmt.where(AgentMessage.message_type == message_type)
    rows = (await session.execute(stmt.order_by(AgentMessage.sent_at.desc()).limit(limit))).scalars().all()
    counts = dict((await session.execute(
        select(AgentMessage.message_type, func.count()).where(AgentMessage.merchant_id == principal.merchant_id)
        .group_by(AgentMessage.message_type)
    )).all())
    return APIResponse(data=[describe_message(m) for m in rows], meta={"type_counts": {k: int(v) for k, v in counts.items()}})


@router.post("/agent-messages/inbound", summary="Deliver a signed envelope from an external agent",
             description="The same verification boundary the in-process agents use: tenant, identity, "
             "signature, freshness, schema and replay checks. Rejections return 401/403/409/422.")
async def inbound_agent_message(
    envelope: dict[str, Any],
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PROCUREMENT_NEGOTIATE)),
) -> APIResponse[dict[str, Any]]:
    message = await MessageBus(session, principal.merchant_id).deliver(envelope)
    return APIResponse(data=describe_message(message))
