"""The procurement lifecycle after the recommendation.

    approve -> purchase order -> supplier invoice -> delivery -> (partial) receiving
            -> three-way match -> payment approval -> PayPal payment -> reconciliation
            -> inventory valuation + product margin -> supplier learning -> memory

Two human gates, each bound to exact terms: one to *buy*, one to *pay*. Neither
can be passed by an agent, and both re-verify their terms against live state
when they are used.

Payment uses PayPal Orders v2 with the supplier as payee: the buyer agent prepares
the order, a person approves it, and - against the real sandbox - the approver
completes PayPal's payer approval before the capture. Payouts are deliberately
*not* used for supplier settlement; they are reserved for cashback rewards.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.exceptions import BadRequestError, ConflictError
from app.core.logging import get_logger
from app.core.permissions import Permission
from app.db.models.agent import AgentName, AgentRunStatus
from app.db.models.audit import ActorType, AuditAction
from app.db.models.automation import EventType
from app.db.models.commerce import Product
from app.db.models.governance import (
    AgentMessageType,
    ApprovalAction,
    ApprovalStatus,
    ExecutionKind,
    ExecutionMethod,
    ExecutionStatus,
    FinancialExecution,
)
from app.db.models.inventory import InventoryItem
from app.db.models.procurement import PurchaseOrder, PurchaseOrderLine, PurchaseOrderStatus
from app.db.models.supply import (
    GoodsReceipt,
    InvoiceMatch,
    MatchStatus,
    NegotiationStatus,
    PaymentTerms,
    ProcurementReconciliation,
    ProcurementRequest,
    ProcurementStatus,
    ReconciliationStatus,
    SupplierAgent,
    SupplierInvoice,
    SupplierInvoiceStatus,
)
from app.integrations.paypal import OrderItem, PayPalAPIError, get_paypal_gateway
from app.services.intelligence.events import BusinessEvent, emit_business_event
from app.services.inventory import events as inventory_events
from app.services.inventory.procurement import ProcurementService
from app.services.inventory.replenishment import next_reference
from app.services.supply.approvals import ApprovalService, hash_details
from app.services.supply.context import SupplyContext
from app.services.supply.negotiation import NegotiationService
from app.services.supply.policy import (
    ONE,
    ZERO,
    D,
    margin_pct,
    money,
    ratio,
    serialisable,
    unit_amount,
    weighted_average_cost,
)

log = get_logger(__name__)


class ProcurementLifecycle(SupplyContext):
    # ================================================================== purchase approval
    async def decide_purchase(
        self,
        request_id: uuid.UUID,
        *,
        approve: bool,
        permissions: frozenset[str],
        note: str = "",
    ) -> ProcurementRequest:
        if self.actor_id is None:
            raise BadRequestError("Only a signed-in person can decide a purchase.")
        request = await self.request(request_id)
        if request.status != ProcurementStatus.AWAITING_APPROVAL or request.approval_request_id is None:
            raise ConflictError(
                f"{request.reference} is {request.status.lower().replace('_', ' ')} - nothing awaits approval."
            )
        negotiation = NegotiationService(
            self.session, self.merchant_id, actor_id=self.actor_id, actor_label=self.actor_label,
            request_id=self.request_id,
        )
        live = await negotiation.purchase_details(request)
        approvals = ApprovalService(self.session, self.merchant_id)
        approval = await approvals.decide(
            request.approval_request_id,
            approve=approve,
            user_id=self.actor_id,
            user_label=self.actor_label,
            permissions=permissions,
            live_details=live,
            note=note,
            request_id=self.request_id,
        )

        sessions = await self.sessions_for(request.id)
        if not approve:
            request.status = ProcurementStatus.REJECTED
            request.closed_at = datetime.now(tz=UTC)
            request.failure_reason = note or "Purchase rejected by a human approver."
            for session in sessions:
                if session.status not in NegotiationStatus.TERMINAL:
                    session.status = NegotiationStatus.REJECTED
                    agent = await self.supplier_agent(session.supplier_agent_id)
                    await self.send(
                        sender=self.buyer, recipient=self.supplier(agent),
                        message_type=AgentMessageType.OFFER_REJECTED,
                        payload={"rfq_reference": request.rfq_reference, "reason": "The merchant decided not to proceed."},
                        request=request, key=f"reject:{agent.agent_key}", session_id=session.id,
                        summary=f"Buyer Agent declined {agent.display_name}'s offer - the merchant rejected the purchase.",
                    )
            await self.step(request, node="approval", agent_name=AgentName.PROCUREMENT_ORCHESTRATOR,
                            action="Human rejected the purchase", result=note or "No reason given.",
                            decision="REJECTED")
            await self.finish_run(request, status=AgentRunStatus.COMPLETED, summary="Purchase rejected by a human.",
                                  requires_approval=False, output={"approved": False})
            return request

        # The approval is consumed by exactly one purchase order.
        await approvals.consume(approval.id, live_details=live, actor_id=self.actor_id)
        order = await self._create_purchase_order(request, live, approval.reference)
        request.status = ProcurementStatus.ORDERED
        request.purchase_order_id = order.id

        winner_agent: SupplierAgent | None = None
        for session in sessions:
            agent = await self.supplier_agent(session.supplier_agent_id)
            if request.recommended_session_id and session.id == request.recommended_session_id:
                session.status = NegotiationStatus.ACCEPTED
                winner_agent = agent
                await self.send(
                    sender=self.buyer, recipient=self.supplier(agent),
                    message_type=AgentMessageType.OFFER_ACCEPTED,
                    payload={"rfq_reference": request.rfq_reference, "offer_id": live["offer_id"],
                             "reason": f"Approved by {self.actor_label} ({approval.reference}).",
                             "conditional_on_approval": False},
                    request=request, key=f"accept:{agent.agent_key}", session_id=session.id,
                    summary=f"Buyer Agent accepted {agent.display_name}'s offer after human approval {approval.reference}.",
                )
            elif session.status not in NegotiationStatus.TERMINAL:
                session.status = NegotiationStatus.REJECTED
                await self.send(
                    sender=self.buyer, recipient=self.supplier(agent),
                    message_type=AgentMessageType.OFFER_REJECTED,
                    payload={"rfq_reference": request.rfq_reference, "reason": "Another offer was selected."},
                    request=request, key=f"reject:{agent.agent_key}", session_id=session.id,
                    summary=f"Buyer Agent thanked {agent.display_name} and declined - another offer was selected.",
                )
        if winner_agent is None:
            raise BadRequestError("Recommended supplier session no longer exists.")

        winner_agent.negotiations_won = (winner_agent.negotiations_won or 0) + 1
        winner_agent.total_savings = money(D(winner_agent.total_savings) + D(request.savings_amount or 0))

        await self.send(
            sender=self.buyer, recipient=self.supplier(winner_agent),
            message_type=AgentMessageType.PURCHASE_ORDER_CREATED,
            payload={
                "purchase_order_reference": order.reference,
                "rfq_reference": request.rfq_reference,
                "unit_price": live["unit_price"],
                "quantity": live["quantity"],
                "total": live["landed_total"],
                "currency": request.currency,
                "expected_delivery": order.expected_at,
                "approval_reference": approval.reference,
            },
            request=request, key="purchase-order",
            summary=f"Purchase order {order.reference} issued to {winner_agent.display_name} for "
            f"{request.currency} {D(live['landed_total']):,.2f}.",
        )
        await self.send(
            sender=self.supplier(winner_agent), recipient=self.buyer,
            message_type=AgentMessageType.DELIVERY_UPDATE,
            payload={"purchase_order_reference": order.reference, "status": "CONFIRMED",
                     "expected_delivery": order.expected_at,
                     "tracking_reference": f"TRK-{order.reference}",
                     "note": "Order confirmed and scheduled for dispatch."},
            request=request, key="delivery:confirmed",
            summary=f"{winner_agent.display_name} confirmed {order.reference}; expected {order.expected_at}.",
        )
        invoice = await self._supplier_issues_invoice(request, order, winner_agent)

        await emit_business_event(
            self.session, merchant_id=self.merchant_id, event_type=BusinessEvent.PURCHASE_APPROVED,
            correlation_id=request.correlation_id, entity_type="purchase_order", entity_id=order.id,
            payload={"reference": order.reference, "approval": approval.reference,
                     "supplier": winner_agent.display_name, "total": live["landed_total"],
                     "approved_by": self.actor_label},
        )
        await self.audit.record(
            action=AuditAction.PURCHASE_ORDER_CREATED, merchant_id=self.merchant_id,
            actor_id=self.actor_id, actor_type=ActorType.USER, actor_label=self.actor_label,
            resource="purchase_order", resource_id=str(order.id),
            description=f"{order.reference} created under {approval.reference} for {request.currency} {D(live['landed_total']):,.2f}",
            request_id=self.request_id, metadata={"procurement_request": request.reference},
        )
        await self.step(request, node="purchase_order", agent_name=AgentName.BUYER,
                        action="Issued purchase order", result=f"{order.reference} to {winner_agent.display_name}",
                        decision=f"Approved by {self.actor_label}")
        await self.step(request, node="invoice", agent_name=AgentName.SUPPLIER_NETWORK,
                        action="Supplier issued invoice",
                        result=f"{invoice.invoice_number}: {invoice.currency} {D(invoice.total):,.2f}, due {invoice.due_date}")
        await self.finish_run(request, status=AgentRunStatus.COMPLETED,
                              summary=f"Purchase approved; {order.reference} issued.", requires_approval=False,
                              output={"purchase_order": order.reference, "approval": approval.reference})
        return request

    async def _create_purchase_order(
        self, request: ProcurementRequest, details: dict[str, Any], approval_reference: str
    ) -> PurchaseOrder:
        now = datetime.now(tz=UTC)
        quantity = D(details["quantity"])
        unit_price = D(details["unit_price"])
        order = PurchaseOrder(
            merchant_id=self.merchant_id,
            vendor_id=uuid.UUID(details["vendor_id"]),
            reference=await next_reference(self.session, self.merchant_id),
            status=PurchaseOrderStatus.ORDERED,
            source="AGENT",
            idempotency_key=f"procurement:{request.id}",
            correlation_id=request.correlation_id,
            total_value=D(details["landed_total"]),
            currency=request.currency,
            requires_approval=True,
            approved_by_id=self.actor_id,
            approved_at=now,
            approval_note=f"Approved via {approval_reference}",
            sent_at=now,
            expected_at=(now + timedelta(days=int(details["lead_time_days"]))).date(),
            procurement_request_id=request.id,
            approval_request_id=request.approval_request_id,
            shipping_amount=D(details["shipping"]),
            tax_amount=D(details["tax"]),
            payment_terms=details["payment_terms"],
            notes=f"Negotiated by the Buyer Agent ({request.reference}).",
            metadata_json={"procurement_reference": request.reference, "terms_hash": details["terms_hash"],
                           "policy_version": details["policy_version"]},
        )
        self.session.add(order)
        await self.session.flush()
        self.session.add(
            PurchaseOrderLine(
                merchant_id=self.merchant_id,
                purchase_order_id=order.id,
                inventory_item_id=request.inventory_item_id,
                sku=request.sku,
                product_name=request.product_name,
                quantity_ordered=quantity,
                quantity_received=ZERO,
                unit_price=unit_price,
                line_total=money(quantity * unit_price),
            )
        )
        await self.session.flush()
        await self.session.refresh(order, ["vendor", "lines"])
        await inventory_events.emit(
            self.session, merchant_id=self.merchant_id, event_type=EventType.PO_CREATED,
            correlation_id=request.correlation_id, entity_type="purchase_order", entity_id=order.id,
            payload={**ProcurementService.describe(order), "procurement_reference": request.reference},
        )
        return order

    async def _supplier_issues_invoice(
        self, request: ProcurementRequest, order: PurchaseOrder, agent: SupplierAgent
    ) -> SupplierInvoice:
        """The supplier agent invoices the full order on dispatch, at the agreed terms."""
        line = order.lines[0]
        subtotal = money(D(line.quantity_ordered) * D(line.unit_price))
        shipping = money(order.shipping_amount)
        tax = money(order.tax_amount)
        days = PaymentTerms.DAYS.get(order.payment_terms or agent.payment_terms, 30)
        prefix = agent.agent_key.split(".")[-1][:6].upper()
        invoice = SupplierInvoice(
            merchant_id=self.merchant_id,
            purchase_order_id=order.id,
            procurement_request_id=request.id,
            supplier_agent_id=agent.id,
            vendor_id=agent.vendor_id,
            invoice_number=f"{prefix}-{order.reference}",
            status=SupplierInvoiceStatus.RECEIVED,
            currency=order.currency,
            subtotal=subtotal,
            shipping_amount=shipping,
            tax_amount=tax,
            total=money(subtotal + shipping + tax),
            issued_at=datetime.now(tz=UTC),
            due_date=date.today() + timedelta(days=days),
            payment_terms=order.payment_terms,
            lines=serialisable([{
                "sku": line.sku, "description": line.product_name, "quantity": D(line.quantity_ordered),
                "unit_price": D(line.unit_price), "line_total": subtotal,
            }]),
            is_simulated=agent.is_simulated,
        )
        self.session.add(invoice)
        await self.session.flush()
        message = await self.send(
            sender=self.supplier(agent), recipient=self.buyer,
            message_type=AgentMessageType.INVOICE_ISSUED,
            payload={
                "invoice_number": invoice.invoice_number,
                "purchase_order_reference": order.reference,
                "currency": invoice.currency,
                "subtotal": subtotal, "shipping": shipping, "tax": tax, "total": invoice.total,
                "due_date": invoice.due_date,
                "lines": invoice.lines,
            },
            request=request, key="invoice",
            summary=f"{agent.display_name} issued invoice {invoice.invoice_number} for {invoice.currency} {D(invoice.total):,.2f}.",
        )
        invoice.message_id = message.id
        agent.invoices_received = (agent.invoices_received or 0) + 1
        await emit_business_event(
            self.session, merchant_id=self.merchant_id, event_type=BusinessEvent.INVOICE_RECEIVED,
            correlation_id=request.correlation_id, entity_type="supplier_invoice", entity_id=invoice.id,
            payload={"invoice_number": invoice.invoice_number, "total": invoice.total, "supplier": agent.display_name},
        )
        return invoice

    # ================================================================== receiving
    async def receive(
        self, purchase_order_id: uuid.UUID, *, lines: list[dict[str, Any]], notes: str = ""
    ) -> GoodsReceipt:
        order = await self.purchase_order(purchase_order_id)
        await self.session.refresh(order, ["lines"])
        before = {str(line.id): D(line.quantity_received) for line in order.lines}
        order = await ProcurementService(self.session, self.merchant_id).receive(
            order_id=order.id,
            lines=[{"line_id": str(e["line_id"]), "quantity": float(D(e["quantity"]))} for e in lines],
            actor_id=self.actor_id,
        )
        received_lines: list[dict[str, Any]] = []
        total_qty = ZERO
        value = ZERO
        for line in order.lines:
            delta = D(line.quantity_received) - before.get(str(line.id), ZERO)
            if delta <= 0:
                continue
            total_qty += delta
            value += money(delta * D(line.unit_price))
            received_lines.append({"line_id": str(line.id), "sku": line.sku, "quantity_received": delta,
                                   "quantity_rejected": ZERO, "unit_price": D(line.unit_price)})
        if total_qty <= 0:
            raise BadRequestError("Nothing was received.")

        outstanding = sum((D(line.quantity_ordered) - D(line.quantity_received) for line in order.lines), ZERO)
        today = datetime.now(tz=UTC).date()
        on_time = order.expected_at is None or today <= order.expected_at
        receipt = GoodsReceipt(
            merchant_id=self.merchant_id,
            reference=await self.next_reference(GoodsReceipt, "GRN"),
            purchase_order_id=order.id,
            procurement_request_id=order.procurement_request_id,
            received_by_id=self.actor_id,
            received_at=datetime.now(tz=UTC),
            lines=serialisable(received_lines),
            total_quantity=total_qty,
            received_value=money(value),
            is_partial=outstanding > 0,
            on_time=on_time,
            notes=notes,
            correlation_id=order.correlation_id or "",
        )
        self.session.add(receipt)
        await self.session.flush()

        request = await self._request_for_order(order)
        if request is not None:
            request.status = ProcurementStatus.PARTIALLY_RECEIVED if outstanding > 0 else ProcurementStatus.RECEIVED
            agent = await self.agent_for_vendor(order.vendor_id)
            if agent is not None:
                await self.send(
                    sender=self.buyer, recipient=self.supplier(agent),
                    message_type=AgentMessageType.GOODS_RECEIVED,
                    payload={"purchase_order_reference": order.reference, "receipt_reference": receipt.reference,
                             "quantity_received": total_qty, "outstanding": outstanding, "on_time": on_time},
                    request=request, key=f"received:{receipt.reference}",
                    summary=f"{receipt.reference}: received {total_qty:f} against {order.reference}"
                    + (f", {outstanding:f} still outstanding." if outstanding > 0 else " - order complete."),
                )
            await self.step(request, node="receiving", agent_name=AgentName.RECONCILIATION,
                            action="Goods received", result=f"{receipt.reference}: {total_qty:f} received, {outstanding:f} outstanding",
                            decision="PARTIAL" if outstanding > 0 else "COMPLETE")
        await emit_business_event(
            self.session, merchant_id=self.merchant_id, event_type=BusinessEvent.GOODS_RECEIVED,
            correlation_id=order.correlation_id or receipt.reference, entity_type="purchase_order", entity_id=order.id,
            payload={"receipt": receipt.reference, "purchase_order": order.reference, "quantity": total_qty,
                     "outstanding": outstanding, "on_time": on_time},
        )
        await self.audit.record(
            action=AuditAction.GOODS_RECEIVED, merchant_id=self.merchant_id, actor_id=self.actor_id,
            actor_type=ActorType.USER if self.actor_id else ActorType.SYSTEM, actor_label=self.actor_label,
            resource="purchase_order", resource_id=str(order.id),
            description=f"{receipt.reference}: {total_qty:f} received against {order.reference}",
            request_id=self.request_id,
        )

        # A receipt can resolve a discrepancy - re-match any open invoice.
        for invoice in await self._open_invoices(order.id):
            await self.match_invoice(invoice.id)
        return receipt

    async def _request_for_order(self, order: PurchaseOrder) -> ProcurementRequest | None:
        if order.procurement_request_id is None:
            return None
        return await self.session.get(ProcurementRequest, order.procurement_request_id)

    async def _open_invoices(self, order_id: uuid.UUID) -> list[SupplierInvoice]:
        return list(
            (
                await self.session.execute(
                    select(SupplierInvoice).where(
                        SupplierInvoice.merchant_id == self.merchant_id,
                        SupplierInvoice.purchase_order_id == order_id,
                        SupplierInvoice.status.in_(
                            (SupplierInvoiceStatus.RECEIVED, SupplierInvoiceStatus.DISCREPANCY, SupplierInvoiceStatus.MATCHED)
                        ),
                    )
                )
            ).scalars().all()
        )

    # ================================================================== three-way match
    async def match_invoice(self, invoice_id: uuid.UUID) -> InvoiceMatch:
        invoice = await self.invoice(invoice_id)
        if invoice.status in (SupplierInvoiceStatus.PAID, SupplierInvoiceStatus.VOID):
            raise ConflictError(f"Invoice {invoice.invoice_number} is {invoice.status.lower()}.")
        order = await self.purchase_order(invoice.purchase_order_id)
        await self.session.refresh(order, ["lines"])
        price_tol = ratio(settings.procurement_price_tolerance_pct)
        total_tol = money(settings.procurement_total_tolerance_amount)

        invoice_lines = {str(entry.get("sku")): entry for entry in (invoice.lines or [])}
        results: list[dict[str, Any]] = []
        discrepancies: list[dict[str, Any]] = []
        received_value = ZERO
        ordered_value = ZERO
        within_tolerance = False

        for line in order.lines:
            ordered, received = D(line.quantity_ordered), D(line.quantity_received)
            po_price = D(line.unit_price)
            billed = invoice_lines.pop(line.sku, None)
            billed_qty = D(billed.get("quantity")) if billed else ZERO
            billed_price = D(billed.get("unit_price")) if billed else ZERO
            received_value += money(received * po_price)
            ordered_value += money(ordered * po_price)
            verdict = "MATCHED"
            if billed is None:
                verdict = "NOT_INVOICED"
            if billed_qty > received:
                verdict = "DISCREPANCY"
                discrepancies.append({
                    "code": "BILLED_NOT_RECEIVED", "sku": line.sku,
                    "message": f"Billed {billed_qty:f} but only {received:f} received.",
                    "amount": money((billed_qty - received) * billed_price),
                })
            if billed_qty > ordered:
                verdict = "DISCREPANCY"
                discrepancies.append({
                    "code": "BILLED_OVER_ORDER", "sku": line.sku,
                    "message": f"Billed {billed_qty:f} against {ordered:f} ordered.",
                    "amount": money((billed_qty - ordered) * billed_price),
                })
            if billed is not None and po_price > 0 and billed_price != po_price:
                variance = abs(billed_price - po_price) / po_price
                if variance > price_tol:
                    verdict = "DISCREPANCY"
                    discrepancies.append({
                        "code": "PRICE_VARIANCE", "sku": line.sku,
                        "message": f"Billed {billed_price:.2f}/unit against the agreed {po_price:.2f}.",
                        "amount": money((billed_price - po_price) * billed_qty),
                    })
                else:
                    within_tolerance = True
            results.append({
                "line_id": str(line.id), "sku": line.sku, "ordered": ordered, "received": received,
                "invoiced": billed_qty, "po_unit_price": po_price, "invoice_unit_price": billed_price,
                "verdict": verdict,
            })
        for sku, extra in invoice_lines.items():
            discrepancies.append({"code": "UNKNOWN_LINE", "sku": sku,
                                  "message": "Invoice line is not on the purchase order.",
                                  "amount": money(extra.get("line_total", 0))})

        expected_shipping = money(order.shipping_amount)
        if abs(money(invoice.shipping_amount) - expected_shipping) > total_tol:
            discrepancies.append({"code": "SHIPPING_VARIANCE", "sku": "",
                                  "message": f"Shipping billed {D(invoice.shipping_amount):.2f}, agreed {expected_shipping:.2f}.",
                                  "amount": money(D(invoice.shipping_amount) - expected_shipping)})
        po_subtotal = ordered_value
        tax_rate = (D(order.tax_amount) / po_subtotal) if po_subtotal > 0 else ZERO
        expected_payable = money(received_value + expected_shipping + money(received_value * tax_rate))
        variance = money(D(invoice.total) - expected_payable)
        if not discrepancies and variance != 0:
            if abs(variance) <= total_tol:
                within_tolerance = True
            else:
                discrepancies.append({"code": "TOTAL_VARIANCE", "sku": "",
                                      "message": f"Invoice total {D(invoice.total):,.2f} vs {expected_payable:,.2f} payable on goods received.",
                                      "amount": variance})

        status = (
            MatchStatus.DISCREPANCY if discrepancies
            else MatchStatus.WITHIN_TOLERANCE if within_tolerance
            else MatchStatus.MATCHED
        )
        match = InvoiceMatch(
            merchant_id=self.merchant_id,
            supplier_invoice_id=invoice.id,
            purchase_order_id=order.id,
            status=status,
            line_results=serialisable(results),
            discrepancies=serialisable(discrepancies),
            po_total=money(order.total_value),
            received_value=money(received_value),
            invoice_total=money(invoice.total),
            variance_amount=variance,
            tolerance=serialisable({"price_pct": price_tol, "total_amount": total_tol}),
            matched_by_id=self.actor_id,
            matched_at=datetime.now(tz=UTC),
        )
        self.session.add(match)
        await self.session.flush()
        invoice.latest_match_id = match.id
        invoice.status = SupplierInvoiceStatus.DISCREPANCY if status == MatchStatus.DISCREPANCY else SupplierInvoiceStatus.MATCHED

        agent = await self.session.get(SupplierAgent, invoice.supplier_agent_id) if invoice.supplier_agent_id else None
        meta = dict(invoice.metadata_json or {})
        # Billing ahead of delivery is the supplier's discrepancy only if it persists
        # past full receipt; price and line errors count immediately.
        if (
            status == MatchStatus.DISCREPANCY
            and agent is not None
            and not meta.get("discrepancy_counted")
            and any(d["code"] != "BILLED_NOT_RECEIVED" for d in discrepancies)
        ):
            agent.invoice_discrepancies = (agent.invoice_discrepancies or 0) + 1
            meta["discrepancy_counted"] = True
        invoice.metadata_json = meta

        request = await self._request_for_order(order)
        if request is not None:
            await self.send(
                sender=self.system, recipient=self.buyer,
                message_type=AgentMessageType.INVOICE_MATCHED,
                payload={"invoice_number": invoice.invoice_number, "status": status, "variance": variance,
                         "discrepancies": serialisable(discrepancies)},
                request=request, key=f"match:{match.id}",
                summary=f"Three-way match on {invoice.invoice_number}: {status.lower().replace('_', ' ')}"
                + (f" - {discrepancies[0]['message']}" if discrepancies else "."),
            )
            await self.step(request, node="matching", agent_name=AgentName.RECONCILIATION,
                            action="Three-way match (PO x receipt x invoice)",
                            result=f"{status}: " + ("; ".join(d["message"] for d in discrepancies) or "all lines agree"),
                            decision="HOLD PAYMENT" if status == MatchStatus.DISCREPANCY else "PAYABLE")
        await self.audit.record(
            action=AuditAction.INVOICE_MATCHED, merchant_id=self.merchant_id, actor_id=self.actor_id,
            actor_type=ActorType.USER if self.actor_id else ActorType.SYSTEM, actor_label=self.actor_label,
            resource="supplier_invoice", resource_id=str(invoice.id),
            description=f"{invoice.invoice_number}: {status}", status="SUCCESS" if status in MatchStatus.PAYABLE else "FAILURE",
            request_id=self.request_id, metadata={"variance": str(variance), "discrepancies": len(discrepancies)},
        )

        if status in MatchStatus.PAYABLE and order.status == PurchaseOrderStatus.RECEIVED:
            await self.request_payment_approval(invoice)
        return match

    # ================================================================== payment
    async def payment_details(self, invoice: SupplierInvoice) -> dict[str, Any]:
        agent = await self.session.get(SupplierAgent, invoice.supplier_agent_id) if invoice.supplier_agent_id else None
        order = await self.purchase_order(invoice.purchase_order_id)
        match = await self.session.get(InvoiceMatch, invoice.latest_match_id) if invoice.latest_match_id else None
        return serialisable({
            "invoice_id": str(invoice.id),
            "invoice_number": invoice.invoice_number,
            "purchase_order": order.reference,
            "supplier_agent": agent.agent_key if agent else "",
            "supplier_name": agent.display_name if agent else "",
            "payee_email": agent.paypal_email if agent else "",
            "amount": money(invoice.total),
            "currency": invoice.currency,
            "match_id": str(match.id) if match else "",
            "match_status": match.status if match else "",
            "method": ExecutionMethod.ORDERS_CAPTURE,
        })

    async def request_payment_approval(self, invoice: SupplierInvoice) -> Any:
        approvals = ApprovalService(self.session, self.merchant_id)
        existing = await approvals.open_for(
            resource_type="supplier_invoice", resource_id=invoice.id, action=ApprovalAction.SUPPLIER_PAYMENT
        )
        details = await self.payment_details(invoice)
        if existing is not None and existing.details_hash == hash_details(details):
            return existing
        order = await self.purchase_order(invoice.purchase_order_id)
        request = await self._request_for_order(order)
        risks = []
        if not details["payee_email"]:
            risks.append("No PayPal payee email on file for this supplier.")
        if invoice.is_simulated:
            risks.append("Invoice was issued by a simulated supplier agent.")
        approval = await approvals.request(
            action=ApprovalAction.SUPPLIER_PAYMENT,
            resource_type="supplier_invoice",
            resource_id=invoice.id,
            title=f"Pay {details['supplier_name']} invoice {invoice.invoice_number}",
            summary=f"Three-way match {details['match_status'].lower()}. Payment via PayPal Orders v2 to "
            f"{details['payee_email'] or 'the supplier'}; mode {settings.paypal_mode}.",
            amount=D(invoice.total),
            currency=invoice.currency,
            details=details,
            policy_version=request.policy_version if request else "",
            required_permission=str(Permission.PAYMENT_APPROVE),
            risk_flags=risks,
            requested_by_type=ActorType.AGENT,
            requested_by_label="Buyer Agent",
            correlation_id=order.correlation_id or "",
            procurement_request_id=request.id if request else None,
        )
        invoice.approval_request_id = approval.id
        invoice.status = SupplierInvoiceStatus.PAYMENT_APPROVAL_PENDING
        if request is not None:
            request.status = ProcurementStatus.PAYMENT_PENDING
            await self.send(
                sender=self.buyer, recipient=self.system,
                message_type=AgentMessageType.PAYMENT_REQUESTED,
                payload={"invoice_number": invoice.invoice_number, "amount": invoice.total,
                         "currency": invoice.currency, "method": ExecutionMethod.ORDERS_CAPTURE,
                         "mode": settings.paypal_mode, "approval_reference": approval.reference},
                request=request, key=f"payment-request:{approval.reference}",
                summary=f"Buyer Agent requested payment of {invoice.currency} {D(invoice.total):,.2f} ({approval.reference}).",
            )
        return approval

    async def decide_payment(
        self, invoice_id: uuid.UUID, *, approve: bool, permissions: frozenset[str], note: str = ""
    ) -> SupplierInvoice:
        if self.actor_id is None:
            raise BadRequestError("Only a signed-in person can approve a payment.")
        invoice = await self.invoice(invoice_id)
        if invoice.approval_request_id is None:
            raise ConflictError("No payment approval is pending for this invoice.")
        approvals = ApprovalService(self.session, self.merchant_id)
        approval = await approvals.decide(
            invoice.approval_request_id, approve=approve, user_id=self.actor_id, user_label=self.actor_label,
            permissions=permissions, live_details=await self.payment_details(invoice), note=note,
            request_id=self.request_id,
        )
        order = await self.purchase_order(invoice.purchase_order_id)
        request = await self._request_for_order(order)
        if not approve:
            invoice.status = SupplierInvoiceStatus.MATCHED
            invoice.metadata_json = {**(invoice.metadata_json or {}), "payment_rejected": note or True}
            return invoice
        if request is not None:
            await self.send(
                sender=self.system, recipient=self.buyer,
                message_type=AgentMessageType.PAYMENT_APPROVED,
                payload={"invoice_number": invoice.invoice_number, "amount": invoice.total,
                         "currency": invoice.currency, "approval_reference": approval.reference},
                request=request, key=f"payment-approved:{approval.reference}",
                summary=f"{self.actor_label} approved payment {approval.reference}.",
            )
        return invoice

    async def execute_payment(self, invoice_id: uuid.UUID) -> FinancialExecution:
        if self.actor_id is None:
            raise BadRequestError("Only a signed-in person can execute a payment.")
        invoice = await self.invoice(invoice_id)

        # Duplicate-execution guard: one live execution per invoice.
        existing = (
            await self.session.execute(
                select(FinancialExecution).where(
                    FinancialExecution.merchant_id == self.merchant_id,
                    FinancialExecution.resource_type == "supplier_invoice",
                    FinancialExecution.resource_id == invoice.id,
                    FinancialExecution.status != ExecutionStatus.FAILED,
                )
            )
        ).scalars().first()
        if existing is not None:
            return existing
        if invoice.approval_request_id is None:
            raise ConflictError("Payment has not been requested for this invoice.")

        approvals = ApprovalService(self.session, self.merchant_id)
        details = await self.payment_details(invoice)
        approval = await approvals.consume(invoice.approval_request_id, live_details=details, actor_id=self.actor_id)
        if not details["payee_email"]:
            raise BadRequestError("The supplier has no PayPal payee email on file.")

        gateway = get_paypal_gateway()
        attempts = (
            await self.session.execute(
                select(FinancialExecution.id).where(
                    FinancialExecution.merchant_id == self.merchant_id,
                    FinancialExecution.resource_id == invoice.id,
                )
            )
        ).all()
        idem = f"supplier-invoice:{invoice.id}:{approval.id}:{len(attempts) + 1}"
        order = await self.purchase_order(invoice.purchase_order_id)
        execution = FinancialExecution(
            merchant_id=self.merchant_id,
            approval_request_id=approval.id,
            kind=ExecutionKind.SUPPLIER_SETTLEMENT,
            resource_type="supplier_invoice",
            resource_id=invoice.id,
            amount=money(invoice.total),
            currency=invoice.currency,
            mode=gateway.mode,
            method=ExecutionMethod.ORDERS_CAPTURE,
            status=ExecutionStatus.CREATED,
            idempotency_key=idem,
            payee_email=details["payee_email"],
            requested_by_id=self.actor_id,
            executed_at=datetime.now(tz=UTC),
            correlation_id=order.correlation_id or "",
        )
        self.session.add(execution)
        await self.session.flush()
        invoice.execution_id = execution.id

        items = None
        line = (invoice.lines or [None])[0]
        if line and D(line.get("quantity")) == D(line.get("quantity")).to_integral_value():
            items = [OrderItem(name=str(line.get("description", "Goods"))[:127], quantity=int(D(line["quantity"])),
                               unit_amount=D(line["unit_price"]), sku=str(line.get("sku", "")))]
        try:
            paypal_order = await gateway.create_order(
                intent="CAPTURE",
                amount=money(invoice.total),
                currency=invoice.currency,
                reference_id=order.reference,
                description=f"{invoice.invoice_number} - {order.reference}",
                request_id=f"{idem}:create",
                invoice_id=invoice.invoice_number,
                custom_id=f"{self.merchant_id}|{invoice.id}",
                payee_email=details["payee_email"],
                items=items,
                return_url=f"{settings.frontend_url}/finance/payments?execution={execution.id}",
                cancel_url=f"{settings.frontend_url}/finance/payments?execution={execution.id}&cancelled=1",
            )
            execution.paypal_order_id = paypal_order.id
            execution.debug_id = paypal_order.debug_id
            execution.response = serialisable({"create": _trim(paypal_order.raw)})
            if gateway.mode == "SIMULATED":
                captured = await gateway.capture_order(paypal_order.id, request_id=f"{idem}:capture")
                await self._settled(execution, invoice, captured.capture_ids[0] if captured.capture_ids else "")
            else:
                execution.status = ExecutionStatus.PAYER_ACTION_REQUIRED
                execution.approve_url = paypal_order.approve_url
                invoice.status = SupplierInvoiceStatus.PAYMENT_PENDING
        except PayPalAPIError as exc:
            await self._payment_failed(execution, invoice, approval.id, exc.message, exc.debug_id)
        return execution

    async def capture_payment(self, execution_id: uuid.UUID) -> FinancialExecution:
        execution = await self._scoped(FinancialExecution, execution_id, "Payment")
        if execution.status in ExecutionStatus.SETTLED:
            return execution
        if execution.status != ExecutionStatus.PAYER_ACTION_REQUIRED or not execution.paypal_order_id:
            raise ConflictError(f"Payment is {execution.status.lower()} and cannot be captured.")
        invoice = await self.invoice(execution.resource_id)
        gateway = get_paypal_gateway()
        try:
            current = await gateway.get_order(execution.paypal_order_id)
            if current.status not in ("APPROVED", "COMPLETED"):
                raise ConflictError(
                    f"PayPal order {execution.paypal_order_id} is {current.status} - the payer must approve it "
                    "in PayPal first.", details={"approve_url": execution.approve_url},
                )
            captured = current if current.capture_ids else await gateway.capture_order(
                execution.paypal_order_id, request_id=f"{execution.idempotency_key}:capture"
            )
            await self._settled(execution, invoice, captured.capture_ids[0] if captured.capture_ids else "")
        except PayPalAPIError as exc:
            await self._payment_failed(execution, invoice, execution.approval_request_id, exc.message, exc.debug_id)
        return execution

    async def _settled(self, execution: FinancialExecution, invoice: SupplierInvoice, capture_id: str) -> None:
        now = datetime.now(tz=UTC)
        execution.status = ExecutionStatus.CAPTURED
        execution.paypal_capture_id = capture_id
        execution.completed_at = now
        invoice.status = SupplierInvoiceStatus.PAID
        invoice.paid_amount = money(execution.amount)
        invoice.paid_at = now
        order = await self.purchase_order(invoice.purchase_order_id)
        request = await self._request_for_order(order)
        if request is not None:
            request.status = ProcurementStatus.PAID
            await self.send(
                sender=self.system, recipient=self.buyer,
                message_type=AgentMessageType.PAYMENT_COMPLETED,
                payload={"invoice_number": invoice.invoice_number, "amount": execution.amount,
                         "currency": execution.currency, "method": execution.method, "mode": execution.mode,
                         "paypal_reference": capture_id},
                request=request, key=f"payment-completed:{execution.id}",
                summary=f"PayPal capture {capture_id} completed for {execution.currency} {D(execution.amount):,.2f}"
                + (" (SIMULATED)" if execution.mode == "SIMULATED" else f" ({execution.mode})") + ".",
            )
            await self.step(request, node="payment", agent_name=AgentName.PROCUREMENT_ORCHESTRATOR,
                            action="PayPal payment captured",
                            result=f"Orders v2 {execution.paypal_order_id} -> capture {capture_id} ({execution.mode})",
                            decision="PAID")
        await self.audit.record(
            action=AuditAction.PAYMENT_EXECUTED, merchant_id=self.merchant_id, actor_id=self.actor_id,
            actor_type=ActorType.USER if self.actor_id else ActorType.SYSTEM, actor_label=self.actor_label,
            resource="financial_execution", resource_id=str(execution.id),
            description=f"Paid {invoice.invoice_number}: {execution.currency} {D(execution.amount):,.2f} via PayPal ({execution.mode})",
            request_id=self.request_id,
            metadata={"paypal_order_id": execution.paypal_order_id, "capture_id": capture_id,
                      "idempotency_key": execution.idempotency_key},
        )
        await self.session.flush()
        if order.status == PurchaseOrderStatus.RECEIVED:
            await self.reconcile(order.id)

    async def _payment_failed(
        self, execution: FinancialExecution, invoice: SupplierInvoice, approval_id: uuid.UUID, error: str, debug_id: str
    ) -> None:
        execution.status = ExecutionStatus.FAILED
        execution.error = error[:2000]
        execution.debug_id = debug_id or execution.debug_id
        invoice.status = SupplierInvoiceStatus.PAYMENT_APPROVAL_PENDING
        # No money moved, so the human approval stays valid for a retry.
        approval = await ApprovalService(self.session, self.merchant_id).get(approval_id)
        if approval.status == ApprovalStatus.EXECUTED:
            approval.status = ApprovalStatus.APPROVED
            approval.executed_at = None
        order = await self.purchase_order(invoice.purchase_order_id)
        request = await self._request_for_order(order)
        if request is not None:
            await self.send(
                sender=self.system, recipient=self.buyer,
                message_type=AgentMessageType.PAYMENT_FAILED,
                payload={"invoice_number": invoice.invoice_number, "amount": execution.amount,
                         "currency": execution.currency, "reason": error[:500], "mode": execution.mode},
                request=request, key=f"payment-failed:{execution.id}",
                summary=f"PayPal payment failed: {error[:160]}",
            )
        await self.audit.record(
            action=AuditAction.PAYMENT_FAILED, merchant_id=self.merchant_id, actor_id=self.actor_id,
            actor_type=ActorType.SYSTEM, actor_label=self.actor_label, resource="financial_execution",
            resource_id=str(execution.id), description=f"Payment failed: {error[:200]}", status="FAILURE",
            metadata={"debug_id": debug_id},
        )

    # ================================================================== reconciliation
    async def readiness(self, purchase_order_id: uuid.UUID) -> dict[str, Any]:
        order = await self.purchase_order(purchase_order_id)
        invoice = (
            await self.session.execute(
                select(SupplierInvoice).where(
                    SupplierInvoice.merchant_id == self.merchant_id, SupplierInvoice.purchase_order_id == order.id
                ).order_by(SupplierInvoice.created_at.desc())
            )
        ).scalars().first()
        match = await self.session.get(InvoiceMatch, invoice.latest_match_id) if invoice and invoice.latest_match_id else None
        execution = await self.session.get(FinancialExecution, invoice.execution_id) if invoice and invoice.execution_id else None
        checks = [
            {"check": "Goods fully received", "ok": order.status == PurchaseOrderStatus.RECEIVED},
            {"check": "Supplier invoice on file", "ok": invoice is not None},
            {"check": "Three-way match payable", "ok": bool(match and match.status in MatchStatus.PAYABLE)},
            {"check": "Payment captured", "ok": bool(execution and execution.status in ExecutionStatus.SETTLED)},
            {"check": "Paid amount equals invoice",
             "ok": bool(invoice and invoice.paid_amount is not None and money(invoice.paid_amount) == money(invoice.total))},
        ]
        return {"ready": all(c["ok"] for c in checks), "checks": checks,
                "invoice_id": str(invoice.id) if invoice else None,
                "execution_id": str(execution.id) if execution else None}

    async def reconcile(self, purchase_order_id: uuid.UUID) -> ProcurementReconciliation:
        existing = (
            await self.session.execute(
                select(ProcurementReconciliation).where(
                    ProcurementReconciliation.merchant_id == self.merchant_id,
                    ProcurementReconciliation.purchase_order_id == purchase_order_id,
                    ProcurementReconciliation.status == ReconciliationStatus.RECONCILED,
                )
            )
        ).scalars().first()
        if existing is not None:
            return existing
        state = await self.readiness(purchase_order_id)
        if not state["ready"]:
            failing = [c["check"] for c in state["checks"] if not c["ok"]]
            raise ConflictError("Not ready to reconcile: " + ", ".join(failing) + ".", details=state)

        order = await self.purchase_order(purchase_order_id)
        await self.session.refresh(order, ["lines"])
        invoice = await self.invoice(uuid.UUID(state["invoice_id"]))
        execution = await self._scoped(FinancialExecution, uuid.UUID(state["execution_id"]), "Payment")
        match = await self.session.get(InvoiceMatch, invoice.latest_match_id)
        line = order.lines[0]
        item = await self.session.get(InventoryItem, line.inventory_item_id)
        product = await self.session.get(Product, item.product_id) if item else None

        received_qty = sum((D(line.quantity_received) for line in order.lines), ZERO)
        landed_unit = unit_amount(D(invoice.total) / received_qty) if received_qty > 0 else ZERO
        previous_cost = D(item.unit_cost) if item else ZERO
        new_cost = previous_cost
        if item is not None:
            # Receipts already added the units; value the pre-receipt stock at the old cost.
            on_hand_before = max(D(item.quantity_on_hand) - received_qty, ZERO)
            new_cost = weighted_average_cost(
                on_hand_before=on_hand_before, cost_before=previous_cost,
                received_quantity=received_qty, received_unit_cost=landed_unit,
            )
            item.unit_cost = money(new_cost)
        price = D(product.price) if product else ZERO
        previous_margin = margin_pct(price=price, unit_cost=D(product.cost_price) if product else previous_cost) if price else None
        if product is not None:
            product.cost_price = money(new_cost)
        new_margin = margin_pct(price=price, unit_cost=new_cost) if price else None

        now = datetime.now(tz=UTC)
        reconciliation = ProcurementReconciliation(
            merchant_id=self.merchant_id,
            procurement_request_id=order.procurement_request_id,
            purchase_order_id=order.id,
            supplier_invoice_id=invoice.id,
            execution_id=execution.id,
            status=ReconciliationStatus.RECONCILED,
            po_total=money(order.total_value),
            received_value=money(match.received_value if match else 0),
            invoice_total=money(invoice.total),
            paid_amount=money(invoice.paid_amount or 0),
            variance_amount=money(D(invoice.paid_amount or 0) - D(invoice.total)),
            payment_reference=execution.paypal_capture_id or execution.paypal_order_id,
            previous_unit_cost=unit_amount(previous_cost),
            new_unit_cost=unit_amount(new_cost),
            previous_margin_pct=previous_margin,
            new_margin_pct=new_margin,
            summary=serialisable({
                "landed_unit_cost": landed_unit, "received_quantity": received_qty,
                "payment_mode": execution.mode, "match_status": match.status if match else "",
                "purchase_order": order.reference, "invoice": invoice.invoice_number,
            }),
            reconciled_by_id=self.actor_id,
            reconciled_at=now,
        )
        self.session.add(reconciliation)
        execution.reconciled_at = now
        execution.status = ExecutionStatus.COMPLETED

        agent = await self.session.get(SupplierAgent, invoice.supplier_agent_id) if invoice.supplier_agent_id else None
        receipts = (
            await self.session.execute(
                select(GoodsReceipt).where(GoodsReceipt.purchase_order_id == order.id).order_by(GoodsReceipt.received_at)
            )
        ).scalars().all()
        on_time = bool(receipts) and all(r.on_time is not False for r in receipts)
        if agent is not None:
            update_supplier_performance(
                agent,
                ordered=sum((D(line.quantity_ordered) for line in order.lines), ZERO),
                received=received_qty,
                on_time=on_time,
            )

        request = await self._request_for_order(order)
        correlation = order.correlation_id or reconciliation.payment_reference
        if request is not None:
            request.status = ProcurementStatus.RECONCILED
            request.closed_at = now
            await self.send(
                sender=self.system, recipient=self.buyer,
                message_type=AgentMessageType.PROCUREMENT_CLOSED,
                payload={"procurement_reference": request.reference, "outcome": "RECONCILED",
                         "final_total": invoice.total, "savings": request.savings_amount or ZERO},
                request=request, key="closed",
                summary=f"{request.reference} reconciled and closed. Inventory revalued to "
                f"{new_cost:.2f}/unit; margin {previous_margin}% -> {new_margin}%.",
            )
            await self.step(request, node="reconciliation", agent_name=AgentName.RECONCILIATION,
                            action="Reconciled PO, receipt, invoice and PayPal capture",
                            result=f"Paid {D(invoice.paid_amount or 0):,.2f} = invoiced {D(invoice.total):,.2f}; "
                            f"capture {reconciliation.payment_reference}", decision="RECONCILED")
            if agent is not None:
                await self.step(request, node="supplier_learning", agent_name=AgentName.PROCUREMENT_EVALUATION,
                                action="Updated supplier performance",
                                result=f"{agent.display_name}: reliability {D(agent.reliability_score):.0%}, "
                                f"on-time {D(agent.on_time_rate):.0%}, {agent.orders_completed} orders")
            _remember(self.merchant_id, request, agent, invoice, new_cost, previous_margin, new_margin, on_time)

        await emit_business_event(
            self.session, merchant_id=self.merchant_id, event_type=BusinessEvent.PAYMENT_RECONCILED,
            correlation_id=correlation, entity_type="purchase_order", entity_id=order.id,
            payload={"purchase_order": order.reference, "invoice": invoice.invoice_number,
                     "paid": invoice.paid_amount, "capture": reconciliation.payment_reference, "mode": execution.mode},
        )
        if product is not None and previous_margin is not None and new_margin is not None:
            await emit_business_event(
                self.session, merchant_id=self.merchant_id, event_type=BusinessEvent.PRODUCT_MARGIN_CHANGED,
                correlation_id=correlation, entity_type="product", entity_id=product.id,
                payload={"sku": product.sku, "product_name": product.name, "price": price,
                         "previous_unit_cost": previous_cost, "new_unit_cost": new_cost,
                         "previous_margin_pct": previous_margin, "new_margin_pct": new_margin},
            )
        await self.audit.record(
            action=AuditAction.PROCUREMENT_RECONCILED, merchant_id=self.merchant_id, actor_id=self.actor_id,
            actor_type=ActorType.USER if self.actor_id else ActorType.SYSTEM, actor_label=self.actor_label,
            resource="purchase_order", resource_id=str(order.id),
            description=f"{order.reference} reconciled against {invoice.invoice_number} and PayPal {reconciliation.payment_reference}",
            request_id=self.request_id,
        )
        await self.session.flush()
        return reconciliation


# --------------------------------------------------------------------------- #
# Supplier learning
# --------------------------------------------------------------------------- #
def update_supplier_performance(agent: SupplierAgent, *, ordered: Decimal, received: Decimal, on_time: bool) -> None:
    """Deterministic reputation update. Future evaluations read these scores."""
    agent.orders_completed = (agent.orders_completed or 0) + 1
    if on_time:
        agent.orders_on_time = (agent.orders_on_time or 0) + 1
    agent.units_ordered = money(D(agent.units_ordered) + ordered)
    agent.units_received = money(D(agent.units_received) + received)

    on_time_rate = D(agent.orders_on_time) / D(agent.orders_completed)
    fill_rate = min(D(agent.units_received) / D(agent.units_ordered), ONE) if D(agent.units_ordered) > 0 else ONE
    invoices = max(int(agent.invoices_received or 0), 1)
    accuracy = max(ONE - D(agent.invoice_discrepancies or 0) / D(invoices), ZERO)

    agent.on_time_rate = ratio(on_time_rate)
    agent.reliability_score = ratio(Decimal("0.5") * on_time_rate + Decimal("0.3") * fill_rate + Decimal("0.2") * accuracy)
    agent.last_performance_at = datetime.now(tz=UTC)


def _remember(
    merchant_id: uuid.UUID,
    request: ProcurementRequest,
    agent: SupplierAgent | None,
    invoice: SupplierInvoice,
    new_cost: Decimal,
    previous_margin: Decimal | None,
    new_margin: Decimal | None,
    on_time: bool,
) -> None:
    """Procurement memory: accepted prices, delivery and margin effect. Never authoritative."""
    try:
        from app.integrations.vector_memory import MemoryKind, memory

        supplier = agent.display_name if agent else "the supplier"
        text = (
            f"Procurement {request.reference} for {request.quantity:f} x {request.product_name} closed on "
            f"{datetime.now(tz=UTC):%d %B %Y}. Supplier {supplier} won the negotiation; final landed total "
            f"{request.currency} {D(invoice.total):,.2f}"
            + (f", saving {request.currency} {D(request.savings_amount):,.2f} versus the best opening quote" if request.savings_amount else "")
            + f". Delivery was {'on time' if on_time else 'late'}. Inventory revalued to {new_cost:.2f} per unit; "
            f"gross margin moved from {previous_margin}% to {new_margin}%.\n"
        )
        memory.remember_later(merchant_id, text, kind=MemoryKind.PROCUREMENT, tags=(request.sku.lower(), "procurement"))
        if agent is not None:
            memory.remember_later(
                merchant_id,
                f"Supplier {agent.display_name} ({agent.agent_key}) reliability is now "
                f"{D(agent.reliability_score):.0%} after {agent.orders_completed} completed orders "
                f"({agent.orders_on_time} on time, {agent.invoice_discrepancies} invoice discrepancies).",
                kind=MemoryKind.SUPPLIER,
                tags=(agent.agent_key,),
            )
    except Exception as exc:  # memory enriches; it never blocks
        log.debug("procurement_memory_skipped", detail=str(exc)[:120])


def _trim(payload: dict[str, Any]) -> dict[str, Any]:
    keep = {"id", "status", "intent", "links", "purchase_units", "simulated"}
    return {k: v for k, v in (payload or {}).items() if k in keep}
