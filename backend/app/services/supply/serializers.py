"""Outbound shapes for the supply domain.

``supplier_public`` is the only way a supplier agent leaves the backend. It omits
the agent's private negotiation policy (opening markup, concession rate) and every
``floor_price`` - those exist for the supplier agent alone.
"""

from __future__ import annotations

from typing import Any

from app.db.models.governance import FinancialExecution
from app.db.models.procurement import PurchaseOrder, VendorProduct
from app.db.models.supply import (
    GoodsReceipt,
    InvoiceMatch,
    NegotiationOffer,
    NegotiationSession,
    ProcurementReconciliation,
    ProcurementRequest,
    SupplierAgent,
    SupplierInvoice,
)
from app.services.supply.policy import D


def _s(value: Any) -> str | None:
    return None if value is None else format(D(value), "f")


def _t(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def supplier_public(agent: SupplierAgent, catalog: list[VendorProduct] | None = None) -> dict[str, Any]:
    on_time = agent.on_time_rate
    return {
        "supplier_agent_id": str(agent.id),
        "vendor_id": str(agent.vendor_id),
        "agent_key": agent.agent_key,
        "display_name": agent.display_name,
        "tagline": agent.tagline,
        "strategy": agent.strategy,
        "status": agent.status,
        "is_simulated": agent.is_simulated,
        "region": agent.region,
        "reliability_score": _s(agent.reliability_score),
        "quality_score": _s(agent.quality_score),
        "on_time_rate": _s(on_time),
        "payment_terms": agent.payment_terms,
        "currency": agent.currency,
        "shipping_flat": _s(agent.shipping_flat),
        "shipping_per_unit": _s(agent.shipping_per_unit),
        "free_shipping_threshold": _s(agent.free_shipping_threshold),
        "tax_rate": _s(agent.tax_rate),
        "expedite_available": bool(agent.expedite_days),
        "paypal_payee_configured": bool(agent.paypal_email),
        "key_fingerprint": agent.key_fingerprint,
        "performance": {
            "orders_completed": agent.orders_completed,
            "orders_on_time": agent.orders_on_time,
            "units_ordered": _s(agent.units_ordered),
            "units_received": _s(agent.units_received),
            "invoices_received": agent.invoices_received,
            "invoice_discrepancies": agent.invoice_discrepancies,
            "negotiations_won": agent.negotiations_won,
            "negotiations_total": agent.negotiations_total,
            "total_savings": _s(agent.total_savings),
            "last_performance_at": _t(agent.last_performance_at),
        },
        "catalog": [
            {
                "inventory_item_id": str(s.inventory_item_id),
                "vendor_sku": s.vendor_sku,
                "indicative_unit_price": _s(s.unit_price),
                "minimum_order_quantity": _s(s.minimum_order_quantity),
                "available_quantity": _s(s.available_quantity),
                "lead_time_days": _s(s.lead_time_days),
                "volume_breaks": s.volume_breaks or [],
            }
            for s in (catalog or [])
        ],
    }


def offer_out(offer: NegotiationOffer) -> dict[str, Any]:
    return {
        "offer_id": str(offer.id),
        "session_id": str(offer.session_id),
        "supplier_agent_id": str(offer.supplier_agent_id),
        "round": offer.round,
        "sequence": offer.sequence,
        "direction": offer.direction,
        "kind": offer.kind,
        "currency": offer.currency,
        "unit_price": _s(offer.unit_price),
        "quantity": _s(offer.quantity),
        "subtotal": _s(offer.subtotal),
        "shipping_cost": _s(offer.shipping_cost),
        "tax_amount": _s(offer.tax_amount),
        "landed_total": _s(offer.landed_total),
        "landed_unit_cost": _s(offer.landed_unit_cost),
        "lead_time_days": offer.lead_time_days,
        "payment_terms": offer.payment_terms,
        "valid_until": _t(offer.valid_until),
        "validation_status": offer.validation_status,
        "validation_errors": offer.validation_errors or [],
        "within_policy": offer.within_policy,
        "proposed_by": offer.proposed_by,
        "ai_proposal": offer.ai_proposal or {},
        "rationale": offer.rationale,
        "score": offer.score or {},
        "terms_hash": offer.terms_hash,
        "created_at": _t(offer.created_at),
    }


def session_out(session: NegotiationSession, agent: SupplierAgent | None, offers: list[NegotiationOffer]) -> dict[str, Any]:
    supplier_offers = [o for o in offers if o.direction == "SUPPLIER_TO_BUYER"]
    opening = supplier_offers[0] if supplier_offers else None
    latest = supplier_offers[-1] if supplier_offers else None
    return {
        "session_id": str(session.id),
        "status": session.status,
        "current_round": session.current_round,
        "max_rounds": session.max_rounds,
        "outcome_reason": session.outcome_reason,
        "expires_at": _t(session.expires_at),
        "is_simulated": session.is_simulated,
        "supplier": supplier_public(agent) if agent else None,
        "opening_offer": offer_out(opening) if opening else None,
        "latest_offer": offer_out(latest) if latest else None,
        "best_offer_id": str(session.best_offer_id) if session.best_offer_id else None,
        "offers": [offer_out(o) for o in offers],
    }


def request_out(request: ProcurementRequest) -> dict[str, Any]:
    return {
        "procurement_request_id": str(request.id),
        "reference": request.reference,
        "rfq_reference": request.rfq_reference,
        "inventory_item_id": str(request.inventory_item_id),
        "product_id": str(request.product_id) if request.product_id else None,
        "sku": request.sku,
        "product_name": request.product_name,
        "unit": request.unit,
        "quantity": _s(request.quantity),
        "required_by": request.required_by.isoformat() if request.required_by else None,
        "max_delivery_days": request.max_delivery_days,
        "trigger": request.trigger,
        "status": request.status,
        "source": request.source,
        "currency": request.currency,
        "correlation_id": request.correlation_id,
        "conversation_id": request.conversation_id,
        "policy": {
            "expected_selling_price": _s(request.expected_selling_price),
            "target_margin": _s(request.target_margin),
            "max_unit_cost": _s(request.max_unit_cost),
            "target_unit_cost": _s(request.target_unit_cost),
            "max_budget": _s(request.max_budget),
            "min_reliability": _s(request.min_reliability),
            "max_rounds": request.max_rounds,
            "max_delivery_days": request.max_delivery_days,
            "policy_version": request.policy_version,
            "notes": (request.policy or {}).get("notes", []),
        },
        "demand": request.demand_snapshot or {},
        "recommendation": request.recommendation or {},
        "recommended_session_id": str(request.recommended_session_id) if request.recommended_session_id else None,
        "recommended_offer_id": str(request.recommended_offer_id) if request.recommended_offer_id else None,
        "selected_supplier_agent_id": str(request.selected_supplier_agent_id) if request.selected_supplier_agent_id else None,
        "approval_request_id": str(request.approval_request_id) if request.approval_request_id else None,
        "purchase_order_id": str(request.purchase_order_id) if request.purchase_order_id else None,
        "agent_run_id": str(request.agent_run_id) if request.agent_run_id else None,
        "baseline_landed_total": _s(request.baseline_landed_total),
        "final_landed_total": _s(request.final_landed_total),
        "savings_amount": _s(request.savings_amount),
        "rfq_issued_at": _t(request.rfq_issued_at),
        "rfq_deadline": _t(request.rfq_deadline),
        "closed_at": _t(request.closed_at),
        "failure_reason": request.failure_reason,
        "created_at": _t(request.created_at),
        "updated_at": _t(request.updated_at),
    }


def receipt_out(receipt: GoodsReceipt) -> dict[str, Any]:
    return {
        "goods_receipt_id": str(receipt.id),
        "reference": receipt.reference,
        "purchase_order_id": str(receipt.purchase_order_id),
        "procurement_request_id": str(receipt.procurement_request_id) if receipt.procurement_request_id else None,
        "received_at": _t(receipt.received_at),
        "lines": receipt.lines or [],
        "total_quantity": _s(receipt.total_quantity),
        "received_value": _s(receipt.received_value),
        "is_partial": receipt.is_partial,
        "on_time": receipt.on_time,
        "notes": receipt.notes,
    }


def match_out(match: InvoiceMatch | None) -> dict[str, Any] | None:
    if match is None:
        return None
    return {
        "match_id": str(match.id),
        "status": match.status,
        "line_results": match.line_results or [],
        "discrepancies": match.discrepancies or [],
        "po_total": _s(match.po_total),
        "received_value": _s(match.received_value),
        "invoice_total": _s(match.invoice_total),
        "variance_amount": _s(match.variance_amount),
        "tolerance": match.tolerance or {},
        "matched_at": _t(match.matched_at),
    }


def execution_out(execution: FinancialExecution | None) -> dict[str, Any] | None:
    if execution is None:
        return None
    return {
        "execution_id": str(execution.id),
        "approval_request_id": str(execution.approval_request_id),
        "kind": execution.kind,
        "resource_type": execution.resource_type,
        "resource_id": str(execution.resource_id),
        "amount": _s(execution.amount),
        "currency": execution.currency,
        "provider": execution.provider,
        "mode": execution.mode,
        "method": execution.method,
        "status": execution.status,
        "idempotency_key": execution.idempotency_key,
        "payee_email": execution.payee_email,
        "paypal_order_id": execution.paypal_order_id,
        "paypal_authorization_id": execution.paypal_authorization_id,
        "paypal_capture_id": execution.paypal_capture_id,
        "paypal_payout_batch_id": execution.paypal_payout_batch_id,
        "approve_url": execution.approve_url,
        "debug_id": execution.debug_id,
        "error": execution.error,
        "executed_at": _t(execution.executed_at),
        "completed_at": _t(execution.completed_at),
        "reconciled_at": _t(execution.reconciled_at),
        "correlation_id": execution.correlation_id,
    }


def invoice_out(
    invoice: SupplierInvoice,
    *,
    supplier_name: str = "",
    purchase_order_reference: str = "",
    match: InvoiceMatch | None = None,
    execution: FinancialExecution | None = None,
) -> dict[str, Any]:
    return {
        "supplier_invoice_id": str(invoice.id),
        "invoice_number": invoice.invoice_number,
        "status": invoice.status,
        "purchase_order_id": str(invoice.purchase_order_id),
        "purchase_order_reference": purchase_order_reference,
        "procurement_request_id": str(invoice.procurement_request_id) if invoice.procurement_request_id else None,
        "supplier_agent_id": str(invoice.supplier_agent_id) if invoice.supplier_agent_id else None,
        "supplier_name": supplier_name,
        "currency": invoice.currency,
        "subtotal": _s(invoice.subtotal),
        "shipping_amount": _s(invoice.shipping_amount),
        "tax_amount": _s(invoice.tax_amount),
        "total": _s(invoice.total),
        "issued_at": _t(invoice.issued_at),
        "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
        "payment_terms": invoice.payment_terms,
        "lines": invoice.lines or [],
        "paypal_invoice_id": invoice.paypal_invoice_id,
        "is_simulated": invoice.is_simulated,
        "approval_request_id": str(invoice.approval_request_id) if invoice.approval_request_id else None,
        "paid_amount": _s(invoice.paid_amount),
        "paid_at": _t(invoice.paid_at),
        "match": match_out(match),
        "execution": execution_out(execution),
    }


def reconciliation_out(rec: ProcurementReconciliation) -> dict[str, Any]:
    return {
        "reconciliation_id": str(rec.id),
        "status": rec.status,
        "procurement_request_id": str(rec.procurement_request_id) if rec.procurement_request_id else None,
        "purchase_order_id": str(rec.purchase_order_id),
        "supplier_invoice_id": str(rec.supplier_invoice_id),
        "execution_id": str(rec.execution_id) if rec.execution_id else None,
        "po_total": _s(rec.po_total),
        "received_value": _s(rec.received_value),
        "invoice_total": _s(rec.invoice_total),
        "paid_amount": _s(rec.paid_amount),
        "variance_amount": _s(rec.variance_amount),
        "payment_reference": rec.payment_reference,
        "previous_unit_cost": _s(rec.previous_unit_cost),
        "new_unit_cost": _s(rec.new_unit_cost),
        "previous_margin_pct": _s(rec.previous_margin_pct),
        "new_margin_pct": _s(rec.new_margin_pct),
        "summary": rec.summary or {},
        "reconciled_at": _t(rec.reconciled_at),
    }


def order_brief(order: PurchaseOrder | None) -> dict[str, Any] | None:
    if order is None:
        return None
    return {
        "purchase_order_id": str(order.id),
        "reference": order.reference,
        "status": order.status,
        "total_value": _s(order.total_value),
        "currency": order.currency,
        "shipping_amount": _s(order.shipping_amount),
        "tax_amount": _s(order.tax_amount),
        "payment_terms": order.payment_terms,
        "expected_at": order.expected_at.isoformat() if order.expected_at else None,
        "sent_at": _t(order.sent_at),
        "received_at": _t(order.received_at),
        "lines": [
            {
                "line_id": str(line.id),
                "sku": line.sku,
                "product_name": line.product_name,
                "quantity_ordered": _s(line.quantity_ordered),
                "quantity_received": _s(line.quantity_received),
                "unit_price": _s(line.unit_price),
                "line_total": _s(line.line_total),
            }
            for line in (order.lines or [])
        ],
    }
