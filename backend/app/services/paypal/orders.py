"""Merchant payment orders (PayPal Orders v2) for AI-proposed purchases.

The only path from an AI recommendation to money moving, and every step is a human's:

1. A person (or an agent, on a person's behalf) **requests** a ``MERCHANT_PURCHASE``
   approval - quantity, the supplier's unit cost and PayPal email, bound by SHA-256.
2. Someone holding ``payment:approve`` **decides** it in the approval inbox.
3. Someone holding ``payment:execute`` **creates the PayPal order**. The approval is
   consumed by exactly one live execution; the idempotency key is derived from the
   approval, so a double click or a retried request returns the same order.
4. The payer **approves the order in PayPal** (sandbox buyer login) and is sent back.
5. Someone holding ``payment:execute`` **captures** it. Capture first re-reads the order
   from PayPal and refuses unless PayPal says ``APPROVED``.

PayPal's ``PAYMENT.CAPTURE.COMPLETED`` webhook (signature-verified) settles the same
execution if it arrives first; both paths are idempotent. Without PayPal credentials
the gateway is the labelled simulator and every row says ``SIMULATED``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.logging import get_logger
from app.db.models.audit import ActorType, AuditAction
from app.db.models.discovery import MerchantRecommendation
from app.db.models.governance import (
    ApprovalAction,
    ApprovalRequest,
    ApprovalStatus,
    ExecutionKind,
    ExecutionMethod,
    ExecutionStatus,
    FinancialExecution,
)
from app.integrations.paypal import get_paypal_gateway
from app.integrations.paypal.errors import PayPalAPIError, PayPalError
from app.integrations.paypal.models import OrderItem
from app.repositories.merchant import AuditLogRepository
from app.services.supply.approvals import ApprovalService, describe_approval
from app.services.supply.policy import money, serialisable
from app.services.supply.serializers import execution_out
from app.services.supply_intel.recommendations import (
    RecommendationService,
    live_purchase_details,
    open_purchase_approval,
)

log = get_logger(__name__)

RESOURCE_TYPE = "merchant_recommendation"


def _trim(payload: dict[str, Any]) -> dict[str, Any]:
    keep = ("id", "status", "intent", "create_time", "update_time", "links", "purchase_units", "payer")
    return {k: payload[k] for k in keep if k in payload}


class MerchantPaymentService:
    def __init__(self, session: AsyncSession, merchant_id: uuid.UUID, *, actor_id: uuid.UUID | None,
                 actor_label: str, request_id: str | None = None) -> None:
        self.session = session
        self.merchant_id = merchant_id
        self.actor_id = actor_id
        self.actor_label = actor_label
        self.request_id = request_id
        self.audit = AuditLogRepository(session)

    async def _execution(self, execution_id: uuid.UUID) -> FinancialExecution:
        row = (await self.session.execute(
            select(FinancialExecution).where(FinancialExecution.id == execution_id,
                                             FinancialExecution.merchant_id == self.merchant_id)
        )).scalars().first()
        if row is None:
            raise NotFoundError("Payment not found.")
        return row

    # ------------------------------------------------------------------ create
    async def create_order(self, approval_id: uuid.UUID, *, client_key: str | None = None) -> FinancialExecution:
        if self.actor_id is None:
            raise BadRequestError("Only a signed-in person can create a payment.")
        approvals = ApprovalService(self.session, self.merchant_id)
        approval = await approvals.get(approval_id)
        if approval.action != ApprovalAction.MERCHANT_PURCHASE:
            raise BadRequestError("This endpoint pays approved test-stock purchases. Supplier invoices and payouts "
                                  "are paid from their own screens.")

        # One live execution per approval: a retry or a double click gets the same order back.
        existing = (await self.session.execute(
            select(FinancialExecution).where(FinancialExecution.merchant_id == self.merchant_id,
                                             FinancialExecution.approval_request_id == approval.id,
                                             FinancialExecution.status != ExecutionStatus.FAILED)
        )).scalars().first()
        if existing is not None:
            return existing

        rec = await open_purchase_approval(self.session, approval)
        details = live_purchase_details(rec, approval)
        approval = await approvals.consume(approval.id, live_details=details, actor_id=self.actor_id)
        payee = details["payee_email"] or settings.paypal_sandbox_payee_email
        if not payee:
            raise BadRequestError("The purchase has no supplier PayPal email.")

        attempts = (await self.session.execute(
            select(func.count()).select_from(FinancialExecution).where(
                FinancialExecution.merchant_id == self.merchant_id, FinancialExecution.approval_request_id == approval.id)
        )).scalar_one()
        idem = f"merchant-purchase:{approval.id}:{int(attempts) + 1}"
        gateway = get_paypal_gateway()
        amount = money(Decimal(details["total"]))
        execution = FinancialExecution(
            merchant_id=self.merchant_id, approval_request_id=approval.id, kind=ExecutionKind.MERCHANT_PURCHASE,
            resource_type=RESOURCE_TYPE, resource_id=rec.id, amount=amount, currency=details["currency"],
            mode=gateway.mode, method=ExecutionMethod.ORDERS_CAPTURE, status=ExecutionStatus.CREATED,
            idempotency_key=idem, payee_email=payee, requested_by_id=self.actor_id,
            executed_at=datetime.now(tz=UTC), correlation_id=rec.reference,
            response={"client_idempotency_key": (client_key or "")[:128]} if client_key else {},
        )
        self.session.add(execution)
        await self.session.flush()

        items = [OrderItem(name=str(details["product_title"] or rec.title)[:127], quantity=int(details["quantity"]),
                           unit_amount=Decimal(details["unit_cost"]), sku=str(details["channel3_product_id"] or "")[:127])]
        try:
            order = await gateway.create_order(
                intent="CAPTURE", amount=amount, currency=details["currency"], reference_id=rec.reference,
                description=f"{rec.reference} test stock - {details['product_title'] or rec.title}"[:127],
                request_id=f"{idem}:create", custom_id=f"{self.merchant_id}|{rec.id}", payee_email=payee, items=items,
                return_url=f"{settings.frontend_url}/finance/payment-management?execution={execution.id}",
                cancel_url=f"{settings.frontend_url}/finance/payment-management?execution={execution.id}&cancelled=1",
            )
        except PayPalError as exc:
            await self._failed(execution, approval, exc.message, getattr(exc, "debug_id", ""))
            return execution
        execution.paypal_order_id = order.id
        execution.debug_id = order.debug_id
        execution.approve_url = order.approve_url
        execution.response = serialisable({**(execution.response or {}), "create": _trim(order.raw)})
        # Simulated orders come back already approved (documented simplification); real ones
        # wait for the payer. Either way capture is a separate, explicit human action.
        execution.status = ExecutionStatus.PENDING if order.status == "APPROVED" else ExecutionStatus.PAYER_ACTION_REQUIRED
        rec.execution = {**(rec.execution or {}), "purchase_execution_id": str(execution.id),
                         "purchase_status": execution.status, "paypal_order_id": order.id}
        await self.session.flush()
        await self.audit.record(
            action=AuditAction.PAYMENT_ORDER_CREATED, merchant_id=self.merchant_id, actor_id=self.actor_id,
            actor_type=ActorType.USER, actor_label=self.actor_label, resource="financial_execution",
            resource_id=str(execution.id), request_id=self.request_id,
            description=f"PayPal order {order.id} created for {approval.reference} ({execution.currency} {amount:,.2f}, {gateway.mode}).",
            metadata={"approval": approval.reference, "paypal_order_id": order.id, "idempotency_key": idem,
                      "mode": gateway.mode},
        )
        return execution

    async def _failed(self, execution: FinancialExecution, approval: ApprovalRequest, error: str, debug_id: str) -> None:
        execution.status = ExecutionStatus.FAILED
        execution.error = error[:2000]
        execution.debug_id = debug_id or execution.debug_id
        # No money moved, so the human approval stays valid for a retry.
        if approval.status == ApprovalStatus.EXECUTED:
            approval.status = ApprovalStatus.APPROVED
            approval.executed_at = None
        await self.session.flush()
        await self.audit.record(
            action=AuditAction.PAYMENT_FAILED, merchant_id=self.merchant_id, actor_id=self.actor_id,
            actor_type=ActorType.SYSTEM, actor_label=self.actor_label, resource="financial_execution",
            resource_id=str(execution.id), request_id=self.request_id, status="FAILURE",
            description=f"PayPal order failed for {approval.reference}: {error[:200]}", metadata={"debug_id": debug_id},
        )
        log.warning("merchant_purchase_failed", approval=approval.reference, detail=error[:200])

    # ------------------------------------------------------------------ capture
    async def capture(self, execution_id: uuid.UUID) -> FinancialExecution:
        execution = await self._execution(execution_id)
        if execution.kind != ExecutionKind.MERCHANT_PURCHASE:
            raise BadRequestError("Capture supplier payments from the supplier invoice screen.")
        if execution.status in ExecutionStatus.SETTLED:
            return execution
        if execution.status not in (ExecutionStatus.PAYER_ACTION_REQUIRED, ExecutionStatus.PENDING) or not execution.paypal_order_id:
            raise ConflictError(f"Payment is {execution.status.lower()} and cannot be captured.")
        gateway = get_paypal_gateway()
        try:
            current = await gateway.get_order(execution.paypal_order_id)
            if current.status not in ("APPROVED", "COMPLETED"):
                raise ConflictError(
                    f"PayPal order {execution.paypal_order_id} is {current.status} - the payer must approve it in PayPal "
                    "first.", details={"approve_url": execution.approve_url, "paypal_status": current.status},
                )
            captured = current if current.capture_ids else await gateway.capture_order(
                execution.paypal_order_id, request_id=f"{execution.idempotency_key}:capture")
        except PayPalAPIError as exc:
            execution.error = exc.message[:2000]
            execution.debug_id = exc.debug_id or execution.debug_id
            await self.session.flush()
            raise
        await self.settle(execution, captured.capture_ids[0] if captured.capture_ids else "", raw=captured.raw)
        return execution

    async def settle(self, execution: FinancialExecution, capture_id: str, *, raw: dict[str, Any] | None = None,
                     source: str = "capture") -> None:
        """Mark captured and tell the recommendation. Idempotent - the webhook may call it too."""
        if execution.status in ExecutionStatus.SETTLED and execution.paypal_capture_id == capture_id:
            return
        execution.status = ExecutionStatus.CAPTURED
        execution.paypal_capture_id = capture_id or execution.paypal_capture_id
        execution.completed_at = datetime.now(tz=UTC)
        execution.error = ""
        if raw:
            execution.response = serialisable({**(execution.response or {}), source: _trim(raw)})
        await self.session.flush()
        await RecommendationService(self.session, execution.merchant_id, user_id=self.actor_id,
                                    actor_label=self.actor_label).on_payment_captured(execution.resource_id, execution)
        await self.audit.record(
            action=AuditAction.PAYMENT_CAPTURED, merchant_id=execution.merchant_id, actor_id=self.actor_id,
            actor_type=ActorType.USER if self.actor_id else ActorType.SYSTEM, actor_label=self.actor_label,
            resource="financial_execution", resource_id=str(execution.id), request_id=self.request_id,
            description=f"PayPal capture {execution.paypal_capture_id} completed for {execution.currency} "
                        f"{Decimal(str(execution.amount)):,.2f} ({execution.mode}) via {source}.",
            metadata={"paypal_order_id": execution.paypal_order_id, "mode": execution.mode},
        )

    # ------------------------------------------------------------------ read
    async def order_details(self, execution_id: uuid.UUID) -> dict[str, Any]:
        execution = await self._execution(execution_id)
        out: dict[str, Any] = {"execution": execution_out(execution), "paypal": None, "paypal_error": None}
        if execution.paypal_order_id:
            try:
                order = await get_paypal_gateway().get_order(execution.paypal_order_id)
                out["paypal"] = {
                    "id": order.id, "status": order.status, "intent": order.intent,
                    "amount": order.amount.wire() if order.amount else None, "payee_email": order.payee_email,
                    "capture_ids": order.capture_ids, "approve_url": order.approve_url or execution.approve_url,
                    "payer": (order.raw or {}).get("payer"), "create_time": (order.raw or {}).get("create_time"),
                    "update_time": (order.raw or {}).get("update_time"),
                }
            except PayPalError as exc:
                out["paypal_error"] = exc.message
        approval = await self.session.get(ApprovalRequest, execution.approval_request_id)
        out["approval"] = describe_approval(approval) if approval else None
        if execution.resource_type == RESOURCE_TYPE:
            rec = await self.session.get(MerchantRecommendation, execution.resource_id)
            out["recommendation"] = {"id": str(rec.id), "reference": rec.reference, "title": rec.title,
                                     "status": rec.status} if rec else None
        return out

    async def history(self, *, limit: int = 100, kind: str | None = None) -> dict[str, Any]:
        stmt = select(FinancialExecution).where(FinancialExecution.merchant_id == self.merchant_id)
        if kind:
            stmt = stmt.where(FinancialExecution.kind == kind)
        rows = (await self.session.execute(stmt.order_by(FinancialExecution.created_at.desc()).limit(limit))).scalars().all()
        approvals = {a.id: a for a in (await self.session.execute(
            select(ApprovalRequest).where(ApprovalRequest.id.in_([r.approval_request_id for r in rows]))
        )).scalars().all()} if rows else {}
        items = []
        for row in rows:
            item = execution_out(row) or {}
            approval = approvals.get(row.approval_request_id)
            item["approval_reference"] = approval.reference if approval else None
            item["title"] = approval.title if approval else row.kind
            items.append(item)
        by_status: dict[str, int] = {}
        settled: dict[str, Decimal] = {}
        for row in rows:
            by_status[row.status] = by_status.get(row.status, 0) + 1
            if row.status in ExecutionStatus.SETTLED:
                key = f"{row.currency}:{row.mode}"
                settled[key] = settled.get(key, Decimal(0)) + Decimal(str(row.amount))
        pending = (await self.session.execute(
            select(ApprovalRequest).where(ApprovalRequest.merchant_id == self.merchant_id,
                                          ApprovalRequest.status.in_(ApprovalStatus.OPEN))
            .order_by(ApprovalRequest.created_at.desc()).limit(50)
        )).scalars().all()
        return {
            "items": items,
            "stats": {
                "total": len(rows), "by_status": by_status,
                "settled": [{"currency": k.split(":")[0], "mode": k.split(":")[1], "amount": str(money(v))}
                            for k, v in settled.items()],
                "awaiting_payer": by_status.get(ExecutionStatus.PAYER_ACTION_REQUIRED, 0) + by_status.get(ExecutionStatus.PENDING, 0),
                "failed": by_status.get(ExecutionStatus.FAILED, 0),
            },
            "approvals": [describe_approval(a) for a in pending],
            "mode": get_paypal_gateway().mode,
        }


__all__ = ["MerchantPaymentService"]
