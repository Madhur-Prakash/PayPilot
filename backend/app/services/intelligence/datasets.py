"""Datasets for AG Studio: PayPilot's own computed tables, as plain rows.

AG Studio lets a merchant build dashboards by dragging fields onto a canvas (or
asking its agent to). What it needs is tidy tables. This module is that boundary:

  * every number in a row was **computed by the backend** (Decimal / SQL) -
    Studio only groups, filters and charts them; it never derives a financial figure
    PayPilot did not already compute;
  * rows are merchant-scoped by construction and respect the caller's permissions
    (a dataset the user may not read is simply absent);
  * amounts are JSON numbers rounded to cents, for charting. The authoritative,
    exact ``Decimal`` values stay in the database and the finance screens.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.paypal import PayPalTransactionRecord
from app.db.models.supply import NegotiationOffer, ProcurementRequest, SupplierAgent
from app.services.supply.demand import InventoryIntelligence
from app.services.supply.policy import money

DATASET_PERMISSION: dict[str, str] = {
    "paypal_transactions": "paypal:read",
    "procurements": "procurement:read",
    "negotiation_offers": "procurement:read",
    "suppliers": "vendor:read",
    "inventory_cover": "inventory:read",
}
DATASET_LABEL: dict[str, str] = {
    "paypal_transactions": "PayPal transactions (last 120 days)",
    "procurements": "Procurements",
    "negotiation_offers": "Negotiation offers",
    "suppliers": "Supplier agents",
    "inventory_cover": "Inventory cover and reorder need",
}


def _num(value: Any) -> float | None:
    if value is None:
        return None
    return float(money(value))


def _date(value: datetime | None) -> str | None:
    return value.date().isoformat() if value else None


async def build_datasets(session: AsyncSession, merchant_id: uuid.UUID, permissions: Iterable[str]) -> dict[str, Any]:
    granted = set(permissions)
    allowed = [name for name, perm in DATASET_PERMISSION.items() if perm in granted]
    out: dict[str, list[dict[str, Any]]] = {}
    since = datetime.now(UTC) - timedelta(days=120)

    suppliers = {s.id: s for s in (await session.execute(
        select(SupplierAgent).where(SupplierAgent.merchant_id == merchant_id)
    )).scalars().all()} if {"procurements", "negotiation_offers", "suppliers"} & set(allowed) else {}
    requests = {r.id: r for r in (await session.execute(
        select(ProcurementRequest).where(ProcurementRequest.merchant_id == merchant_id)
    )).scalars().all()} if {"procurements", "negotiation_offers"} & set(allowed) else {}

    if "paypal_transactions" in allowed:
        rows = (await session.execute(
            select(PayPalTransactionRecord).where(PayPalTransactionRecord.merchant_id == merchant_id,
                                                  PayPalTransactionRecord.initiated_at >= since)
            .order_by(PayPalTransactionRecord.initiated_at)
        )).scalars().all()
        out["paypal_transactions"] = [{
            "date": _date(r.initiated_at), "category": r.category, "status": r.status_code or "S",
            "currency": r.currency, "gross": _num(r.gross_amount), "fee": _num(r.fee_amount),
            "net": _num(r.net_amount), "source": r.mode.title(),
        } for r in rows]

    if "procurements" in allowed:
        out["procurements"] = [{
            "reference": r.reference, "product": r.product_name, "status": r.status.replace("_", " ").title(),
            "quantity": _num(r.quantity), "created": _date(r.created_at),
            "supplier": suppliers[r.selected_supplier_agent_id].display_name
            if r.selected_supplier_agent_id in suppliers else "(none)",
            "max_budget": _num(r.max_budget), "baseline_landed_total": _num(r.baseline_landed_total),
            "final_landed_total": _num(r.final_landed_total), "savings": _num(r.savings_amount),
            "target_margin_pct": float((Decimal(r.target_margin) * 100).quantize(Decimal("0.1"))),
        } for r in requests.values()]

    if "negotiation_offers" in allowed:
        offers = (await session.execute(
            select(NegotiationOffer).where(NegotiationOffer.merchant_id == merchant_id)
            .order_by(NegotiationOffer.created_at)
        )).scalars().all()
        out["negotiation_offers"] = [{
            "procurement": requests[o.procurement_request_id].reference if o.procurement_request_id in requests else "",
            "supplier": suppliers[o.supplier_agent_id].display_name if o.supplier_agent_id in suppliers else "",
            "round": o.round, "direction": o.direction.title(), "kind": o.kind.title(),
            "unit_price": float(Decimal(o.unit_price).quantize(Decimal("0.0001"))),
            "landed_total": _num(o.landed_total), "lead_time_days": o.lead_time_days,
            "validation": o.validation_status.title(), "within_policy": bool(o.within_policy),
        } for o in offers]

    if "suppliers" in allowed:
        out["suppliers"] = [{
            "supplier": s.display_name, "strategy": s.strategy.title(), "region": s.region,
            "reliability": float(Decimal(s.reliability_score).quantize(Decimal("0.01"))),
            "on_time_rate": float(Decimal(s.on_time_rate).quantize(Decimal("0.01"))),
            "orders_completed": s.orders_completed, "negotiations_won": s.negotiations_won,
            "total_savings": _num(s.total_savings), "simulated": bool(s.is_simulated),
        } for s in suppliers.values()]

    if "inventory_cover" in allowed:
        assessments = await InventoryIntelligence(session, merchant_id).scan()
        out["inventory_cover"] = [{
            "sku": a.sku, "product": a.product_name, "on_hand": _num(a.on_hand), "on_order": _num(a.on_order),
            "days_of_cover": _num(a.days_of_cover), "daily_velocity": _num(a.velocity_recent),
            "demand_change_pct": _num(a.demand_change_pct), "risk": a.risk_level.title(),
            "suggested_reorder_qty": _num(a.suggested_quantity), "revenue_at_risk": _num(a.revenue_at_risk),
            "unit_cost": _num(a.unit_cost), "selling_price": _num(a.selling_price),
        } for a in assessments]

    return {
        "datasets": out,
        "labels": {name: DATASET_LABEL[name] for name in out},
        "note": "Computed by PayPilot's backend. Studio groups and charts these rows; it does not derive financial figures.",
        "generated_at": datetime.now(UTC).isoformat(),
    }
