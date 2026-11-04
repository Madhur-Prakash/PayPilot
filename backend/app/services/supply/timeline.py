"""Procurement timeline: the data behind the Bryntum Gantt.

Every procurement becomes a parent task whose children are the real stages it went
through - negotiation, human approval, purchase order and delivery, supplier
invoice, PayPal payment - each with the dates the system actually recorded, chained
finish-to-start. Goods receipts appear as milestones, so a partial delivery is
visible as two diamonds and a half-filled delivery bar.

Nothing here schedules anything: tasks are ``manuallyScheduled`` and the chart is
read-only. The Gantt is a *view of what happened and what is due*, not a planner
that could move a date and imply a commitment the backend never made.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.governance import ApprovalRequest, FinancialExecution
from app.db.models.procurement import PurchaseOrder
from app.db.models.supply import (
    GoodsReceipt,
    NegotiationOffer,
    ProcurementRequest,
    SupplierAgent,
    SupplierInvoice,
)
from app.services.supply.policy import ZERO, D

MIN_SPAN = timedelta(hours=2)
FINISH_TO_START = 2  # Bryntum dependency type: End-to-Start


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _from_date(value: date | None) -> datetime | None:
    return datetime.combine(value, time(17, 0), tzinfo=UTC) if value else None


def _span(start: datetime | None, end: datetime | None, fallback: datetime) -> tuple[datetime, datetime]:
    start = start or fallback
    end = end or start + MIN_SPAN
    if end < start + MIN_SPAN:
        end = start + MIN_SPAN
    return start, end


def _task(task_id: str, name: str, start: datetime, end: datetime, *, state: str, percent: int = 0,
          milestone: bool = False, detail: str = "") -> dict[str, Any]:
    return {
        "id": task_id,
        "name": name,
        "startDate": start.isoformat(),
        "endDate": start.isoformat() if milestone else end.isoformat(),
        "percentDone": max(0, min(percent, 100)),
        "milestone": milestone,
        "manuallyScheduled": True,
        "state": state,       # done | active | pending | blocked  (drives the colour)
        "detail": detail,
    }


async def build_timeline(session: AsyncSession, merchant_id: uuid.UUID, *, limit: int = 12) -> dict[str, Any]:
    now = datetime.now(UTC)
    requests = (await session.execute(
        select(ProcurementRequest).where(ProcurementRequest.merchant_id == merchant_id)
        .order_by(ProcurementRequest.created_at.desc()).limit(limit)
    )).scalars().all()
    if not requests:
        return {"tasks": [], "dependencies": [], "generated_at": now.isoformat(), "count": 0}

    ids = [r.id for r in requests]
    po_ids = [r.purchase_order_id for r in requests if r.purchase_order_id]
    approval_ids = [r.approval_request_id for r in requests if r.approval_request_id]
    supplier_ids = [r.selected_supplier_agent_id for r in requests if r.selected_supplier_agent_id]

    offers = (await session.execute(
        select(NegotiationOffer).where(NegotiationOffer.merchant_id == merchant_id,
                                       NegotiationOffer.procurement_request_id.in_(ids))
    )).scalars().all()
    approvals = {a.id: a for a in (await session.execute(
        select(ApprovalRequest).where(ApprovalRequest.merchant_id == merchant_id, ApprovalRequest.id.in_(approval_ids))
    )).scalars().all()} if approval_ids else {}
    pos = {p.id: p for p in (await session.execute(
        select(PurchaseOrder).where(PurchaseOrder.merchant_id == merchant_id, PurchaseOrder.id.in_(po_ids))
    )).scalars().all()} if po_ids else {}
    receipts = (await session.execute(
        select(GoodsReceipt).where(GoodsReceipt.merchant_id == merchant_id, GoodsReceipt.purchase_order_id.in_(po_ids))
        .order_by(GoodsReceipt.received_at)
    )).scalars().all() if po_ids else []
    invoices = {i.purchase_order_id: i for i in (await session.execute(
        select(SupplierInvoice).where(SupplierInvoice.merchant_id == merchant_id, SupplierInvoice.purchase_order_id.in_(po_ids))
    )).scalars().all()} if po_ids else {}
    exec_ids = [i.execution_id for i in invoices.values() if i.execution_id]
    executions = {e.id: e for e in (await session.execute(
        select(FinancialExecution).where(FinancialExecution.merchant_id == merchant_id, FinancialExecution.id.in_(exec_ids))
    )).scalars().all()} if exec_ids else {}
    suppliers = {s.id: s for s in (await session.execute(
        select(SupplierAgent).where(SupplierAgent.merchant_id == merchant_id, SupplierAgent.id.in_(supplier_ids))
    )).scalars().all()} if supplier_ids else {}

    offers_by_request: dict[uuid.UUID, list[NegotiationOffer]] = {}
    for offer in offers:
        offers_by_request.setdefault(offer.procurement_request_id, []).append(offer)
    receipts_by_po: dict[uuid.UUID, list[GoodsReceipt]] = {}
    for receipt in receipts:
        receipts_by_po.setdefault(receipt.purchase_order_id, []).append(receipt)

    tasks: list[dict[str, Any]] = []
    dependencies: list[dict[str, Any]] = []

    for request in reversed(requests):  # oldest first reads naturally top to bottom
        created = _aware(request.created_at) or now
        pid = str(request.id)
        children: list[dict[str, Any]] = []

        # 1. RFQ and negotiation
        mine = offers_by_request.get(request.id, [])
        negotiation_end = max((_aware(o.created_at) for o in mine if o.created_at), default=None) \
            or _aware(request.rfq_deadline)
        start, end = _span(_aware(request.rfq_issued_at) or created, negotiation_end, created)
        negotiated = request.status not in ("DRAFT", "SOURCING", "NEGOTIATING")
        rounds = max((o.round for o in mine), default=0)
        children.append(_task(f"{pid}:nego", "RFQ & negotiation", start, end,
                              state="done" if negotiated else "active", percent=100 if negotiated else 50,
                              detail=f"{len(mine)} offers across {rounds} rounds"))
        last_id = f"{pid}:nego"

        # 2. Human approval
        approval = approvals.get(request.approval_request_id) if request.approval_request_id else None
        if approval is not None:
            decided = _aware(approval.decided_at)
            a_start, a_end = _span(_aware(approval.created_at), decided or now, end)
            state = {"APPROVED": "done", "EXECUTED": "done", "PENDING": "active", "REJECTED": "blocked",
                     "INVALIDATED": "blocked", "EXPIRED": "blocked"}.get(approval.status, "pending")
            children.append(_task(f"{pid}:approval", "Human approval", a_start, a_end, state=state,
                                  percent=100 if decided else 40,
                                  detail=f"{approval.status.title()} - {approval.decided_by_label or 'awaiting a human'}"))
            dependencies.append({"id": f"{pid}:d1", "from": last_id, "to": f"{pid}:approval", "type": FINISH_TO_START})
            last_id, end = f"{pid}:approval", a_end

        # 3. Purchase order and delivery
        po = pos.get(request.purchase_order_id) if request.purchase_order_id else None
        if po is not None:
            received = sum((D(r.total_quantity) for r in receipts_by_po.get(po.id, [])), ZERO)
            ordered = D(request.quantity)
            done_pct = int(min(Decimal(100), (received / ordered * 100) if ordered else ZERO))
            d_start = _aware(po.sent_at) or _aware(po.approved_at) or _aware(po.created_at) or end
            expected = _from_date(po.expected_at)
            last_receipt = max((_aware(r.received_at) for r in receipts_by_po.get(po.id, [])), default=None)
            d_end = (last_receipt if done_pct >= 100 else expected) or last_receipt or expected
            d_start, d_end = _span(d_start, d_end, end)
            overdue = done_pct < 100 and expected is not None and expected < now
            children.append(_task(f"{pid}:po", f"PO {po.reference} & delivery", d_start, d_end,
                                  state="done" if done_pct >= 100 else ("blocked" if overdue else "active"),
                                  percent=done_pct,
                                  detail=f"{received:f} of {ordered:f} {request.unit} received"
                                         + (" - overdue" if overdue else "")))
            dependencies.append({"id": f"{pid}:d2", "from": last_id, "to": f"{pid}:po", "type": FINISH_TO_START})
            last_id, end = f"{pid}:po", d_end
            for index, receipt in enumerate(receipts_by_po.get(po.id, []), start=1):
                at = _aware(receipt.received_at) or d_end
                children.append(_task(f"{pid}:rcpt{index}", f"Receipt {receipt.reference}", at, at, state="done",
                                      milestone=True,
                                      detail=f"{D(receipt.total_quantity):f} {request.unit}"
                                             + (" (partial)" if receipt.is_partial else "")))

            # 4. Supplier invoice
            invoice = invoices.get(po.id)
            if invoice is not None:
                i_start = _aware(invoice.issued_at) or end
                i_end = _from_date(invoice.due_date) or _aware(invoice.paid_at)
                i_start, i_end = _span(i_start, i_end if (i_end and i_end > i_start) else None, end)
                paid = invoice.status == "PAID"
                children.append(_task(f"{pid}:invoice", f"Invoice {invoice.invoice_number}", i_start, i_end,
                                      state="done" if paid else ("blocked" if invoice.status == "DISCREPANCY" else "active"),
                                      percent=100 if paid else 30,
                                      detail=f"{invoice.status.title()} - {invoice.total} {invoice.currency}"))
                dependencies.append({"id": f"{pid}:d3", "from": last_id, "to": f"{pid}:invoice", "type": FINISH_TO_START})
                last_id, end = f"{pid}:invoice", i_end

                # 5. PayPal payment
                execution = executions.get(invoice.execution_id) if invoice.execution_id else None
                if execution is not None:
                    p_start = _aware(execution.executed_at) or _aware(execution.created_at) or end
                    p_end = _aware(execution.reconciled_at) or _aware(execution.completed_at)
                    p_start, p_end = _span(p_start, p_end, end)
                    complete = bool(execution.completed_at) or execution.status in ("CAPTURED", "COMPLETED")
                    children.append(_task(f"{pid}:pay", f"PayPal payment ({execution.mode.title()})", p_start, p_end,
                                          state="done" if complete else "active", percent=100 if complete else 50,
                                          detail=f"{execution.status.replace('_', ' ').title()} - {execution.amount} {execution.currency}"))
                    dependencies.append({"id": f"{pid}:d4", "from": last_id, "to": f"{pid}:pay", "type": FINISH_TO_START})

        supplier = suppliers.get(request.selected_supplier_agent_id) if request.selected_supplier_agent_id else None
        starts = [c["startDate"] for c in children]
        ends = [c["endDate"] for c in children]
        weights = [c["percentDone"] for c in children if not c["milestone"]]
        tasks.append({
            "id": pid,
            "name": f"{request.reference} - {request.product_name}",
            "startDate": min(starts),
            "endDate": max(ends),
            "percentDone": int(sum(weights) / len(weights)) if weights else 0,
            "manuallyScheduled": True,
            "expanded": True,
            "state": "blocked" if request.status in ("REJECTED", "CANCELLED", "NO_ELIGIBLE_OFFER")
            else ("done" if request.status in ("PAID", "RECONCILED") else "active"),
            "detail": f"{request.status.replace('_', ' ').title()}"
                      + (f" - {supplier.display_name}" if supplier else "")
                      + f" - {D(request.quantity):f} {request.unit}",
            "children": children,
        })

    return {"tasks": tasks, "dependencies": dependencies, "generated_at": now.isoformat(), "count": len(tasks)}
