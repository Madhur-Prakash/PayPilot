"""The unified approval inbox and the financial execution ledger.

One inbox for every money-moving decision. Deciding here dispatches to the domain
service that owns the action, which re-derives the live terms and refuses if they
no longer match what the approver is looking at. The permission required is the
one stored on the approval itself (``procurement:approve`` / ``payment:approve``),
re-checked server side - holding ``approval:read`` only lets you *see* the inbox.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy import select

from app.api.deps import DbSession, Principal, require_permission
from app.core.exceptions import BadRequestError, PermissionDeniedError
from app.core.permissions import Permission
from app.db.models.governance import ApprovalAction, FinancialExecution
from app.schemas.common import APIResponse, SchemaBase
from app.services.paypal.finance import PayPalFinanceService
from app.services.supply.approvals import ApprovalService, describe_approval
from app.services.supply.lifecycle import ProcurementLifecycle
from app.services.supply.serializers import execution_out

router = APIRouter(tags=["governance"])


class ApprovalDecision(SchemaBase):
    approve: bool
    note: str = Field(default="", max_length=1000)


@router.get("/approvals", summary="Approval inbox")
async def list_approvals(
    session: DbSession,
    approval_status: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    principal: Principal = Depends(require_permission(Permission.APPROVAL_READ)),
) -> APIResponse[list[dict[str, Any]]]:
    rows, total, counts = await ApprovalService(session, principal.merchant_id).list(status=approval_status, limit=limit)
    items = []
    for row in rows:
        item = describe_approval(row)
        item["can_decide"] = principal.has(row.required_permission)
        items.append(item)
    return APIResponse(data=items, meta={"total": total, "status_counts": counts})


@router.get("/approvals/{approval_id}", summary="Approval detail")
async def get_approval(
    approval_id: uuid.UUID,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.APPROVAL_READ)),
) -> APIResponse[dict[str, Any]]:
    approval = await ApprovalService(session, principal.merchant_id).get(approval_id)
    data = describe_approval(approval)
    data["can_decide"] = principal.has(approval.required_permission)
    executions = (await session.execute(
        select(FinancialExecution).where(FinancialExecution.approval_request_id == approval.id)
    )).scalars().all()
    data["executions"] = [execution_out(e) for e in executions]
    return APIResponse(data=data)


@router.post("/approvals/{approval_id}/decide", summary="Approve or reject (dispatches to the owning service)")
async def decide_approval(
    approval_id: uuid.UUID,
    payload: ApprovalDecision,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.APPROVAL_READ)),
) -> APIResponse[dict[str, Any]]:
    service = ApprovalService(session, principal.merchant_id)
    approval = await service.get(approval_id)
    if not principal.has(approval.required_permission):
        from app.db.models.audit import AuditAction
        from app.services.auth.security_events import record_security_event

        await record_security_event(
            action=AuditAction.PERMISSION_DENIED,
            merchant_id=principal.merchant_id,
            actor_id=principal.user_id,
            actor_label=principal.user.email,
            resource="approval",
            resource_id=str(approval.id),
            description=f"Denied: role {principal.membership.role} cannot decide {approval.reference} "
            f"(requires {approval.required_permission}).",
            request_id=principal.request_id,
            metadata={"required": approval.required_permission, "role": principal.membership.role},
        )
        raise PermissionDeniedError(
            f"Your role ({principal.membership.role}) cannot approve this action.",
            details={"required_permission": approval.required_permission, "role": principal.membership.role},
        )

    ctx = {"actor_id": principal.user_id, "actor_label": principal.label, "request_id": principal.request_id}
    if approval.action == ApprovalAction.PROCUREMENT_PURCHASE:
        await ProcurementLifecycle(session, principal.merchant_id, **ctx).decide_purchase(
            approval.resource_id, approve=payload.approve, permissions=principal.permissions, note=payload.note
        )
    elif approval.action == ApprovalAction.SUPPLIER_PAYMENT:
        await ProcurementLifecycle(session, principal.merchant_id, **ctx).decide_payment(
            approval.resource_id, approve=payload.approve, permissions=principal.permissions, note=payload.note
        )
    elif approval.action == ApprovalAction.CASHBACK_PAYOUT:
        await service.decide(
            approval.id, approve=payload.approve, user_id=principal.user_id, user_label=principal.label,
            permissions=principal.permissions, live_details=approval.details, note=payload.note,
            request_id=principal.request_id,
        )
    else:
        raise BadRequestError(f"Unsupported approval action {approval.action}.")
    refreshed = await service.get(approval_id)
    data = describe_approval(refreshed)
    data["can_decide"] = principal.has(refreshed.required_permission)
    return APIResponse(data=data)


@router.post("/approvals/{approval_id}/execute", summary="Execute an approved cashback payout")
async def execute_approval(
    approval_id: uuid.UUID,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PAYMENT_EXECUTE)),
) -> APIResponse[dict[str, Any] | None]:
    approval = await ApprovalService(session, principal.merchant_id).get(approval_id)
    if approval.action != ApprovalAction.CASHBACK_PAYOUT:
        raise BadRequestError("Execute purchases and supplier payments from their own screens.")
    execution = await PayPalFinanceService(
        session, principal.merchant_id, actor_id=principal.user_id, actor_label=principal.label,
        merchant_name=principal.merchant.name,
    ).execute_cashback(approval_id)
    return APIResponse(data=execution_out(execution))


@router.get("/payments", summary="Financial executions (every PayPal money movement)")
async def list_payments(
    session: DbSession,
    kind: Annotated[str | None, Query()] = None,
    principal: Principal = Depends(require_permission(Permission.PAYPAL_READ)),
) -> APIResponse[list[dict[str, Any] | None]]:
    stmt = select(FinancialExecution).where(FinancialExecution.merchant_id == principal.merchant_id)
    if kind:
        stmt = stmt.where(FinancialExecution.kind == kind)
    rows = (await session.execute(stmt.order_by(FinancialExecution.created_at.desc()).limit(200))).scalars().all()
    return APIResponse(data=[execution_out(r) for r in rows])
