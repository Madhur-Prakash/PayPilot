"""Supply Agents, PayPal and memory tools.

Narrowly scoped, like every tool: each wraps one deterministic service call,
declares the permission it needs, and returns structured facts plus a one-line
summary. Nothing here moves money. ``approve_purchase`` and ``pay_supplier_invoice``
exist precisely so that an agent which *tries* gets a clear refusal pointing at
the human approval endpoint - an agent cannot approve its own financial action.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.exceptions import ApprovalRequiredError, NotFoundError
from app.core.permissions import Permission
from app.db.models.governance import ApprovalRequest, ApprovalStatus
from app.db.models.inventory import InventoryItem
from app.db.models.procurement import VendorProduct
from app.db.models.supply import ProcurementRequest, ProcurementStatus, SupplierAgent
from app.integrations.vector_memory import memory
from app.services.paypal.sync import TransactionSyncService, transaction_intelligence
from app.services.supply.approvals import describe_approval
from app.services.supply.demand import InventoryIntelligence
from app.services.supply.negotiation import NegotiationService
from app.services.supply.serializers import request_out, supplier_public
from app.tools.base import ToolContext, registry


class EmptyArgs(BaseModel):
    pass


class ProcurementStartArgs(BaseModel):
    sku: str = Field(min_length=1, max_length=64, description="Inventory SKU to procure.")
    quantity: float | None = Field(default=None, gt=0, description="Override the suggested quantity.")


class ProcurementRefArgs(BaseModel):
    reference: str = Field(min_length=3, max_length=32, description="Procurement reference, e.g. PR-00001.")


class MemorySearchArgs(BaseModel):
    query: str = Field(min_length=2, max_length=300)
    kind: str | None = Field(default=None, description="Optional memory kind, e.g. supplier or procurement.")
    limit: int = Field(default=5, ge=1, le=15)


class WindowArgs(BaseModel):
    days: int = Field(default=30, ge=7, le=180)


async def _request_by_ref(ctx: ToolContext, reference: str) -> ProcurementRequest:
    row = (await ctx.session.execute(
        select(ProcurementRequest).where(
            ProcurementRequest.merchant_id == ctx.merchant_id, ProcurementRequest.reference == reference.upper()
        )
    )).scalars().first()
    if row is None:
        raise NotFoundError(f"No procurement request {reference}.")
    return row


# --------------------------------------------------------------------------- #
# Inventory intelligence
# --------------------------------------------------------------------------- #
@registry.register(
    "get_stockout_risks",
    description=(
        "Deterministic demand and stockout analysis for every tracked item: 14-day sales "
        "velocity vs the prior 14 days, days of cover, stockout risk and the suggested "
        "reorder quantity. Use it before proposing promotions or purchases."
    ),
    args_model=EmptyArgs,
    permission=Permission.INVENTORY_READ,
)
async def get_stockout_risks(ctx: ToolContext, args: EmptyArgs) -> tuple[dict[str, Any], str]:
    results = await InventoryIntelligence(ctx.session, ctx.merchant_id).scan()
    risky = [r for r in results if r.stockout_risk]
    data = {"at_risk": [r.as_dict() for r in risky[:10]],
            "demand_increases": [r.as_dict() for r in results if r.demand_increased][:10]}
    if risky:
        top = risky[0]
        summary = (f"{len(risky)} item(s) at stockout risk. Worst: {top.product_name} with "
                   f"{top.days_of_cover} days of cover vs {top.lead_time_days}-day lead time; "
                   f"suggest {top.suggested_quantity:f} units.")
    else:
        summary = "No items at stockout risk."
    return data, summary


# --------------------------------------------------------------------------- #
# Supplier network + procurement
# --------------------------------------------------------------------------- #
@registry.register(
    "list_supplier_agents",
    description="The merchant's supplier agents: reliability, terms, indicative prices and stock. "
    "Private negotiation floors are never included.",
    args_model=EmptyArgs,
    permission=Permission.VENDOR_READ,
)
async def list_supplier_agents(ctx: ToolContext, args: EmptyArgs) -> tuple[dict[str, Any], str]:
    agents = (await ctx.session.execute(
        select(SupplierAgent).where(SupplierAgent.merchant_id == ctx.merchant_id)
    )).scalars().all()
    rows = []
    for agent in agents:
        catalog = (await ctx.session.execute(
            select(VendorProduct).where(VendorProduct.vendor_id == agent.vendor_id)
        )).scalars().all()
        rows.append(supplier_public(agent, list(catalog)))
    best = max(agents, key=lambda a: a.reliability_score, default=None)
    summary = f"{len(rows)} supplier agents." + (f" Most reliable: {best.display_name} ({float(best.reliability_score):.0%})." if best else "")
    return {"suppliers": rows}, summary


@registry.register(
    "start_procurement",
    description="Raise a procurement request for a SKU: computes the deterministic purchase "
    "policy (max landed unit cost, budget) and prepares the RFQ. Moves no money.",
    args_model=ProcurementStartArgs,
    permission=Permission.PROCUREMENT_CREATE,
)
async def start_procurement(ctx: ToolContext, args: ProcurementStartArgs) -> tuple[dict[str, Any], str]:
    item = (await ctx.session.execute(
        select(InventoryItem).where(InventoryItem.merchant_id == ctx.merchant_id, InventoryItem.sku == args.sku)
    )).scalars().first()
    if item is None:
        raise NotFoundError(f"No inventory item with SKU {args.sku}.")
    service = NegotiationService(ctx.session, ctx.merchant_id, actor_id=ctx.user_id, actor_label=ctx.agent_name)
    from decimal import Decimal

    request = await service.create_request(
        inventory_item_id=item.id,
        quantity=Decimal(str(args.quantity)) if args.quantity else None,
        source="AGENT",
    )
    return request_out(request), (
        f"{request.reference} raised for {request.quantity:f} x {request.product_name}; "
        f"max landed unit cost {request.max_unit_cost:.2f}, budget {request.max_budget:,.2f}."
    )


@registry.register(
    "run_negotiation",
    description="Run the buyer agent's negotiation with the supplier agents to a recommendation. "
    "Stops at the human approval gate - it cannot purchase.",
    args_model=ProcurementRefArgs,
    permission=Permission.PROCUREMENT_NEGOTIATE,
)
async def run_negotiation(ctx: ToolContext, args: ProcurementRefArgs) -> tuple[dict[str, Any], str]:
    request = await _request_by_ref(ctx, args.reference)
    service = NegotiationService(ctx.session, ctx.merchant_id, actor_id=ctx.user_id, actor_label=ctx.agent_name)
    request = await service.run_to_recommendation(request.id)
    rec = request.recommendation or {}
    return {"request": request_out(request), "recommendation": rec}, (
        rec.get("explanation") or f"{request.reference} is {request.status.lower()}."
    )


@registry.register(
    "get_procurement_status",
    description="Status, policy, recommendation and savings for one procurement request.",
    args_model=ProcurementRefArgs,
    permission=Permission.PROCUREMENT_READ,
)
async def get_procurement_status(ctx: ToolContext, args: ProcurementRefArgs) -> tuple[dict[str, Any], str]:
    request = await _request_by_ref(ctx, args.reference)
    data = request_out(request)
    saving = f", saving {request.savings_amount:,.2f}" if request.savings_amount else ""
    return data, f"{request.reference}: {request.status.lower().replace('_', ' ')}{saving}."


@registry.register(
    "get_procurement_overview",
    description="Open procurement requests, active negotiations, and total negotiated savings.",
    args_model=EmptyArgs,
    permission=Permission.PROCUREMENT_READ,
)
async def get_procurement_overview(ctx: ToolContext, args: EmptyArgs) -> tuple[dict[str, Any], str]:
    rows = (await ctx.session.execute(
        select(ProcurementRequest).where(ProcurementRequest.merchant_id == ctx.merchant_id)
        .order_by(ProcurementRequest.created_at.desc()).limit(10)
    )).scalars().all()
    savings = (await ctx.session.execute(
        select(func.coalesce(func.sum(ProcurementRequest.savings_amount), 0)).where(
            ProcurementRequest.merchant_id == ctx.merchant_id, ProcurementRequest.purchase_order_id.isnot(None)
        )
    )).scalar_one()
    open_rows = [r for r in rows if r.status in ProcurementStatus.OPEN]
    return {"requests": [request_out(r) for r in rows], "total_savings": str(savings)}, (
        f"{len(open_rows)} open procurement request(s); negotiated savings to date {float(savings):,.2f}."
    )


@registry.register(
    "get_pending_approvals",
    description="Financial actions waiting for a human decision, with their exact terms.",
    args_model=EmptyArgs,
    permission=Permission.APPROVAL_READ,
)
async def get_pending_approvals(ctx: ToolContext, args: EmptyArgs) -> tuple[dict[str, Any], str]:
    rows = (await ctx.session.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.merchant_id == ctx.merchant_id, ApprovalRequest.status == ApprovalStatus.PENDING
        ).order_by(ApprovalRequest.created_at.desc()).limit(10)
    )).scalars().all()
    items = [describe_approval(r) for r in rows]
    return {"approvals": items}, (
        f"{len(items)} approval(s) pending." + (f" Latest: {items[0]['title']} ({items[0]['currency']} {items[0]['amount']})." if items else "")
    )


@registry.register(
    "approve_purchase",
    description="Agents cannot approve purchases. Calling this always refuses and explains how a "
    "human approves in the Approval Center.",
    args_model=ProcurementRefArgs,
    permission=Permission.PROCUREMENT_READ,
    requires_approval=True,
)
async def approve_purchase(ctx: ToolContext, args: ProcurementRefArgs) -> tuple[dict[str, Any], str]:
    raise ApprovalRequiredError(
        "An agent cannot approve its own financial action. A person with procurement:approve must "
        f"approve {args.reference} via POST /api/v1/approvals/{{id}}/decide (Approval Center)."
    )


@registry.register(
    "pay_supplier_invoice",
    description="Agents cannot move money. Calling this always refuses and explains the human payment path.",
    args_model=ProcurementRefArgs,
    permission=Permission.SUPPLIER_INVOICE_READ,
    requires_approval=True,
)
async def pay_supplier_invoice(ctx: ToolContext, args: ProcurementRefArgs) -> tuple[dict[str, Any], str]:
    raise ApprovalRequiredError(
        "Supplier payments need a human approval (payment:approve) and a human execution "
        "(payment:execute). The agent may only request payment."
    )


# --------------------------------------------------------------------------- #
# PayPal
# --------------------------------------------------------------------------- #
@registry.register(
    "get_paypal_transaction_insights",
    description="Deterministic analytics over synced PayPal transactions: gross and net revenue, "
    "fees, refund rate, payment failure rate, AOV and repeat payers, per currency.",
    args_model=WindowArgs,
    permission=Permission.PAYPAL_READ,
)
async def get_paypal_transaction_insights(ctx: ToolContext, args: WindowArgs) -> tuple[dict[str, Any], str]:
    data = await transaction_intelligence(ctx.session, ctx.merchant_id, days=args.days)
    if not data.get("has_data"):
        return data, "No PayPal transactions synced yet."
    usd = data["currencies"].get("USD") or next(iter(data["currencies"].values()))
    mode = "simulated" if data.get("is_simulated") else "PayPal"
    return data, (f"{mode} data: {usd['transactions']} payments, gross {usd['gross_revenue']}, "
                  f"refund rate {usd['refund_rate_pct']}%, repeat payers {usd['repeat_payer_rate_pct']}%.")


@registry.register(
    "sync_paypal_transactions",
    description="Pull new transactions from PayPal Transaction Search (incremental, 31-day windows).",
    args_model=EmptyArgs,
    permission=Permission.PAYPAL_SYNC,
)
async def sync_paypal_transactions(ctx: ToolContext, args: EmptyArgs) -> tuple[dict[str, Any], str]:
    result = await TransactionSyncService(ctx.session, ctx.merchant_id).sync(actor_id=ctx.user_id, actor_label=ctx.agent_name)
    return result, f"Synced {result['inserted']} new / {result['updated']} updated transactions ({result['mode']})."


# --------------------------------------------------------------------------- #
# Memory
# --------------------------------------------------------------------------- #
@registry.register(
    "search_memory",
    description="Recall what the agents learned before for this merchant (pgvector semantic search): "
    "past recommendations, approvals, experiment results, negotiation outcomes, supplier reliability. "
    "Context only - never a source of financial figures.",
    args_model=MemorySearchArgs,
    permission=Permission.MEMORY_READ,
)
async def search_memory(ctx: ToolContext, args: MemorySearchArgs) -> tuple[dict[str, Any], str]:
    hits = await memory.recall(ctx.merchant_id, args.query, top_k=args.limit, kinds=(args.kind,) if args.kind else ())
    return {"hits": [h.as_dict() for h in hits]}, f"{len(hits)} relevant memories."


__all__ = ["uuid"]
