"""Unified Business Intelligence: one view across growth, supply and finance.

This is where the two halves of the product meet:

* ``inventory_signals`` tells Growth which products are about to run out (don't
  promote them) and which are overstocked (promote them) - so an inventory
  shortage changes campaign recommendations.
* ``margin_signals`` exposes the procurement-driven cost changes, so a cheaper
  negotiated purchase shows up as a better product margin in growth analytics.
* ``command_center`` assembles the merchant's whole operating picture.

All figures come from the database and deterministic services.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.agent import AgentRun
from app.db.models.commerce import Product
from app.db.models.governance import ApprovalRequest, ApprovalStatus, FinancialExecution
from app.db.models.growth import GrowthOpportunity, OpportunityStatus
from app.db.models.inventory import InventoryItem
from app.db.models.procurement import PurchaseOrder, PurchaseOrderStatus
from app.db.models.supply import (
    NegotiationSession,
    NegotiationStatus,
    ProcurementReconciliation,
    ProcurementRequest,
    ProcurementStatus,
    SupplierAgent,
    SupplierInvoice,
    SupplierInvoiceStatus,
)
from app.integrations.paypal import paypal_status
from app.services.analytics.service import AnalyticsService
from app.services.intelligence.events import describe_event, recent_events
from app.services.paypal.sync import transaction_intelligence
from app.services.supply.approvals import describe_approval
from app.services.supply.demand import InventoryIntelligence
from app.services.supply.policy import ZERO, D, margin_pct, money


async def inventory_signals(session: AsyncSession, merchant_id: uuid.UUID) -> dict[str, Any]:
    """Products growth should avoid promoting, and products it could promote."""
    assessments = await InventoryIntelligence(session, merchant_id).scan()
    at_risk = [a for a in assessments if a.stockout_risk]
    overstocked = [a for a in assessments if a.overstocked]
    return {
        "do_not_promote": [
            {"product_id": a.product_id, "sku": a.sku, "product_name": a.product_name,
             "days_of_cover": str(a.days_of_cover) if a.days_of_cover is not None else None,
             "reason": f"Only {a.days_of_cover} days of cover against a {a.lead_time_days}-day lead time."}
            for a in at_risk
        ],
        "promotable_overstock": [
            {"product_id": a.product_id, "sku": a.sku, "product_name": a.product_name,
             "days_of_cover": str(a.days_of_cover) if a.days_of_cover is not None else None,
             "reason": f"{a.days_of_cover} days of cover - a promotion would release working capital."}
            for a in overstocked
        ],
        "demand_increases": [
            {"product_id": a.product_id, "sku": a.sku, "product_name": a.product_name,
             "demand_change_pct": str(a.demand_change_pct), "velocity": str(a.velocity_recent)}
            for a in assessments if a.demand_increased
        ],
    }


async def margin_signals(session: AsyncSession, merchant_id: uuid.UUID, *, limit: int = 10) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(ProcurementReconciliation)
            .where(ProcurementReconciliation.merchant_id == merchant_id)
            .order_by(ProcurementReconciliation.reconciled_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    out = []
    for rec in rows:
        out.append({
            "purchase_order_id": str(rec.purchase_order_id),
            "previous_unit_cost": format(D(rec.previous_unit_cost or 0), "f"),
            "new_unit_cost": format(D(rec.new_unit_cost or 0), "f"),
            "previous_margin_pct": format(D(rec.previous_margin_pct or 0), "f"),
            "new_margin_pct": format(D(rec.new_margin_pct or 0), "f"),
            "reconciled_at": rec.reconciled_at.isoformat() if rec.reconciled_at else None,
            "summary": rec.summary or {},
        })
    return out


async def command_center(session: AsyncSession, merchant_id: uuid.UUID, *, days: int = 30) -> dict[str, Any]:
    analytics = AnalyticsService(session, merchant_id)
    period = await analytics.resolve_period(days=days)
    kpis, current, _previous = await analytics.kpis(period)

    # ---- growth
    opp_rows = (
        await session.execute(
            select(func.count(), func.coalesce(func.sum(GrowthOpportunity.estimated_value_monthly), 0))
            .where(
                GrowthOpportunity.merchant_id == merchant_id,
                GrowthOpportunity.status.in_(OpportunityStatus.OPEN),
            )
        )
    ).first()

    # ---- inventory
    status_counts = dict(
        (await session.execute(
            select(InventoryItem.status, func.count()).where(InventoryItem.merchant_id == merchant_id).group_by(InventoryItem.status)
        )).all()
    )
    assessments = await InventoryIntelligence(session, merchant_id).scan()
    at_risk = [a for a in assessments if a.stockout_risk][:5]
    stock_value = (await session.execute(
        select(func.coalesce(func.sum(InventoryItem.quantity_on_hand * InventoryItem.unit_cost), 0))
        .where(InventoryItem.merchant_id == merchant_id)
    )).scalar_one()

    # ---- procurement
    open_requests = dict(
        (await session.execute(
            select(ProcurementRequest.status, func.count())
            .where(ProcurementRequest.merchant_id == merchant_id)
            .group_by(ProcurementRequest.status)
        )).all()
    )
    active_negotiations = (await session.execute(
        select(func.count()).select_from(NegotiationSession).where(
            NegotiationSession.merchant_id == merchant_id,
            NegotiationSession.status.in_((NegotiationStatus.INVITED, NegotiationStatus.QUOTED, NegotiationStatus.COUNTERED)),
        )
    )).scalar_one()
    since = datetime.now(tz=UTC) - timedelta(days=days)
    spend = (await session.execute(
        select(func.coalesce(func.sum(PurchaseOrder.total_value), 0)).where(
            PurchaseOrder.merchant_id == merchant_id,
            PurchaseOrder.status.notin_((PurchaseOrderStatus.CANCELLED, PurchaseOrderStatus.REJECTED, PurchaseOrderStatus.FAILED)),
            PurchaseOrder.created_at >= since,
        )
    )).scalar_one()
    savings = (await session.execute(
        select(func.coalesce(func.sum(ProcurementRequest.savings_amount), 0)).where(
            ProcurementRequest.merchant_id == merchant_id,
            ProcurementRequest.purchase_order_id.isnot(None),
        )
    )).scalar_one()
    outstanding = (await session.execute(
        select(func.count(), func.coalesce(func.sum(SupplierInvoice.total), 0)).where(
            SupplierInvoice.merchant_id == merchant_id,
            SupplierInvoice.status.notin_((SupplierInvoiceStatus.PAID, SupplierInvoiceStatus.VOID)),
        )
    )).first()
    deliveries = (await session.execute(
        select(PurchaseOrder).where(
            PurchaseOrder.merchant_id == merchant_id,
            PurchaseOrder.status.in_((PurchaseOrderStatus.ORDERED, PurchaseOrderStatus.ACKNOWLEDGED, PurchaseOrderStatus.PARTIALLY_RECEIVED)),
        ).order_by(PurchaseOrder.expected_at).limit(5)
    )).scalars().all()
    active_requests = (await session.execute(
        select(ProcurementRequest).where(
            ProcurementRequest.merchant_id == merchant_id,
            ProcurementRequest.status.in_(ProcurementStatus.OPEN),
        ).order_by(ProcurementRequest.created_at.desc()).limit(5)
    )).scalars().all()

    # ---- approvals
    pending = (await session.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.merchant_id == merchant_id, ApprovalRequest.status == ApprovalStatus.PENDING
        ).order_by(ApprovalRequest.created_at.desc()).limit(5)
    )).scalars().all()
    pending_count = (await session.execute(
        select(func.count()).select_from(ApprovalRequest).where(
            ApprovalRequest.merchant_id == merchant_id, ApprovalRequest.status == ApprovalStatus.PENDING
        )
    )).scalar_one()

    # ---- agents + finance
    runs = (await session.execute(
        select(AgentRun).where(AgentRun.merchant_id == merchant_id).order_by(AgentRun.created_at.desc()).limit(6)
    )).scalars().all()
    executions = (await session.execute(
        select(FinancialExecution).where(FinancialExecution.merchant_id == merchant_id)
        .order_by(FinancialExecution.created_at.desc()).limit(5)
    )).scalars().all()
    events = await recent_events(session, merchant_id, limit=12, prefix="business.")
    suppliers = (await session.execute(
        select(SupplierAgent).where(SupplierAgent.merchant_id == merchant_id).order_by(SupplierAgent.reliability_score.desc())
    )).scalars().all()

    revenue = D(current.revenue)
    gross_profit = D(current.gross_margin)
    return {
        "period": {"days": days, "start": period.current.start.isoformat(), "end": period.current.end.isoformat()},
        "currency": settings.default_currency,
        "kpis": [k.model_dump() for k in kpis],
        "financials": {
            "revenue": str(money(revenue)),
            "net_sales": str(money(revenue - D(current.discount_total))),
            "gross_profit": str(money(gross_profit)),
            "gross_margin_pct": str(money(current.gross_margin_pct)),
            "orders": current.orders,
            "discounts": str(money(current.discount_total)),
        },
        "growth": {
            "open_opportunities": int(opp_rows[0] or 0) if opp_rows else 0,
            "opportunity_value": str(money(opp_rows[1] or 0)) if opp_rows else "0.00",
        },
        "inventory": {
            "status_counts": {k: int(v) for k, v in status_counts.items()},
            "stock_value": str(money(stock_value or 0)),
            "at_risk": [a.as_dict() for a in at_risk],
            "tracked_items": len(assessments),
        },
        "procurement": {
            "requests_by_status": {k: int(v) for k, v in open_requests.items()},
            "active_negotiations": int(active_negotiations or 0),
            "spend": str(money(spend or 0)),
            "savings": str(money(savings or 0)),
            "outstanding_invoices": int(outstanding[0] or 0) if outstanding else 0,
            "outstanding_amount": str(money(outstanding[1] or 0)) if outstanding else "0.00",
            "active_requests": [
                {"procurement_request_id": str(r.id), "reference": r.reference, "status": r.status,
                 "product_name": r.product_name, "quantity": format(D(r.quantity), "f"),
                 "max_budget": format(D(r.max_budget), "f"),
                 "final_landed_total": format(D(r.final_landed_total), "f") if r.final_landed_total is not None else None}
                for r in active_requests
            ],
            "upcoming_deliveries": [
                {"purchase_order_id": str(o.id), "reference": o.reference, "status": o.status,
                 "expected_at": o.expected_at.isoformat() if o.expected_at else None,
                 "total_value": format(D(o.total_value), "f")}
                for o in deliveries
            ],
        },
        "suppliers": [
            {"supplier_agent_id": str(s.id), "display_name": s.display_name, "reliability_score": format(D(s.reliability_score), "f"),
             "on_time_rate": format(D(s.on_time_rate), "f"), "status": s.status, "is_simulated": s.is_simulated}
            for s in suppliers
        ],
        "approvals": {"pending": int(pending_count or 0), "items": [describe_approval(a) for a in pending]},
        "agents": [
            {"run_id": str(r.id), "agent_name": r.agent_name, "workflow": r.workflow, "status": r.status,
             "summary": (r.summary or r.input_text or "")[:200], "used_fallback": r.used_fallback,
             "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in runs
        ],
        "financial_events": [
            {"execution_id": str(e.id), "kind": e.kind, "status": e.status, "mode": e.mode, "method": e.method,
             "amount": format(D(e.amount), "f"), "currency": e.currency,
             "reference": e.paypal_capture_id or e.paypal_order_id or e.paypal_payout_batch_id,
             "created_at": e.created_at.isoformat() if e.created_at else None}
            for e in executions
        ],
        "events": [describe_event(e) for e in events],
        "paypal": {**paypal_status(), "intelligence": await transaction_intelligence(session, merchant_id, days=days)},
        "margins": await margin_signals(session, merchant_id, limit=5),
    }


async def product_margin(session: AsyncSession, product: Product) -> dict[str, Any]:
    price = D(product.price)
    cost = D(product.cost_price)
    return {"product_id": str(product.id), "price": str(money(price)), "unit_cost": str(money(cost)),
            "margin_pct": str(margin_pct(price=price, unit_cost=cost)) if price else "0.00"}


__all__ = ["ZERO", "Decimal", "command_center", "inventory_signals", "margin_signals", "product_margin"]
