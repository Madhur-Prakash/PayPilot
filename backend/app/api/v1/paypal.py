"""PayPal endpoints.

The webhook receiver is the only unauthenticated route here, and it trusts
nothing it has not verified with PayPal (or, in simulation, with the simulator's
own signature). Everything else is merchant-scoped and permission-gated; nothing
returns a credential or token.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field
from sqlalchemy import func, select

from app.api.deps import DbSession, Principal, require_permission
from app.core.exceptions import BadRequestError, ConflictError
from app.core.permissions import Permission
from app.db.models.governance import ExecutionStatus, FinancialExecution
from app.db.models.paypal import (
    PayPalInvoiceRecord,
    PayPalSubscriptionRecord,
    PayPalTransactionRecord,
    PayPalWebhookEvent,
)
from app.integrations.paypal import get_paypal_gateway, paypal_status, sign_simulated_webhook
from app.schemas.common import APIResponse, PageMeta, Paginated, SchemaBase
from app.services.paypal.finance import PayPalFinanceService, invoice_record_out, subscription_out
from app.services.paypal.radar import build_radar
from app.services.paypal.sync import TransactionSyncService, transaction_intelligence
from app.services.paypal.webhooks import WebhookService, describe_webhook
from app.services.supply.approvals import describe_approval

router = APIRouter(prefix="/paypal", tags=["paypal"])


class SyncRequest(SchemaBase):
    days: int | None = Field(default=None, ge=1, le=1095)


class InvoiceLineIn(SchemaBase):
    name: str = Field(min_length=1, max_length=200)
    quantity: Decimal = Field(default=Decimal("1"), gt=0)
    unit_amount: Decimal = Field(gt=0)
    description: str = Field(default="", max_length=1000)


class InvoiceCreate(SchemaBase):
    recipient_email: str = Field(min_length=3, max_length=255)
    recipient_name: str = Field(default="", max_length=160)
    items: list[InvoiceLineIn] = Field(min_length=1, max_length=50)
    note: str = Field(default="", max_length=2000)
    due_date: date | None = None
    send: bool = True
    campaign_id: uuid.UUID | None = None


class InvoiceAction(SchemaBase):
    action: str = Field(pattern="^(remind|cancel|refresh)$")
    note: str = Field(default="", max_length=1000)


class CashbackRecipient(SchemaBase):
    email: str = Field(min_length=3, max_length=255)
    amount: Decimal = Field(gt=0, le=Decimal("100"))


class CashbackRequest(SchemaBase):
    recipients: list[CashbackRecipient] = Field(min_length=1, max_length=500)
    note: str = Field(default="Thanks for coming back!", max_length=500)
    campaign_id: uuid.UUID | None = None


class PlanCreate(SchemaBase):
    name: str = Field(min_length=2, max_length=120)
    amount: Decimal = Field(gt=0)
    interval_unit: str = Field(default="MONTH", pattern="^(DAY|WEEK|MONTH|YEAR)$")
    trial_days: int = Field(default=0, ge=0, le=90)


class SubscriptionAction(SchemaBase):
    action: str = Field(pattern="^(suspend|activate|cancel|recover)$")
    reason: str = Field(default="", max_length=128)


class SimulatedWebhook(SchemaBase):
    event_type: str = Field(default="PAYMENT.CAPTURE.COMPLETED", max_length=64)
    execution_id: uuid.UUID | None = None
    subscription_record_id: uuid.UUID | None = None


# --------------------------------------------------------------------------- #
# Status + sync
# --------------------------------------------------------------------------- #
@router.get("/status", summary="PayPal connection status (no secrets)")
async def status_(
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PAYPAL_READ)),
) -> APIResponse[dict[str, Any]]:
    checkpoint = await TransactionSyncService(session, principal.merchant_id).checkpoint()
    return APIResponse(data={
        **paypal_status(),
        "sync": {
            "synced_until": checkpoint.synced_until.isoformat() if checkpoint.synced_until else None,
            "last_run_at": checkpoint.last_run_at.isoformat() if checkpoint.last_run_at else None,
            "last_status": checkpoint.last_status,
            "last_error": checkpoint.last_error,
            "items_total": checkpoint.items_total,
            "mode": checkpoint.mode,
        },
        "apis": [
            {"name": "OAuth 2.0 client credentials", "path": "/v1/oauth2/token"},
            {"name": "Transaction Search", "path": "/v1/reporting/transactions"},
            {"name": "Orders v2", "path": "/v2/checkout/orders"},
            {"name": "Payments v2 (authorizations)", "path": "/v2/payments/authorizations"},
            {"name": "Invoicing v2", "path": "/v2/invoicing/invoices"},
            {"name": "Payouts", "path": "/v1/payments/payouts"},
            {"name": "Subscriptions", "path": "/v1/billing/subscriptions"},
            {"name": "Webhook verification", "path": "/v1/notifications/verify-webhook-signature"},
        ],
    })


@router.post("/sync", summary="Synchronise transactions from PayPal (incremental)")
async def sync(
    payload: SyncRequest,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PAYPAL_SYNC)),
) -> APIResponse[dict[str, Any]]:
    result = await TransactionSyncService(session, principal.merchant_id).sync(
        days=payload.days, actor_id=principal.user_id, actor_label=principal.label
    )
    return APIResponse(data=result)


@router.get("/transactions", summary="Synced PayPal transactions")
async def transactions(
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 100,
    category: Annotated[str | None, Query()] = None,
    principal: Principal = Depends(require_permission(Permission.PAYPAL_READ)),
) -> APIResponse[Paginated[dict[str, Any]]]:
    conditions = [PayPalTransactionRecord.merchant_id == principal.merchant_id]
    if category:
        conditions.append(PayPalTransactionRecord.category == category)
    rows = (await session.execute(
        select(PayPalTransactionRecord).where(*conditions)
        .order_by(PayPalTransactionRecord.initiated_at.desc())
        .limit(page_size).offset((page - 1) * page_size)
    )).scalars().all()
    total = (await session.execute(select(func.count()).select_from(PayPalTransactionRecord).where(*conditions))).scalar_one()
    items = [
        {
            "id": str(r.id),
            "paypal_transaction_id": r.paypal_transaction_id,
            "event_code": r.event_code,
            "status_code": r.status_code,
            "category": r.category,
            "currency": r.currency,
            "gross_amount": format(r.gross_amount, "f"),
            "fee_amount": format(r.fee_amount, "f"),
            "net_amount": format(r.net_amount, "f"),
            "initiated_at": r.initiated_at.isoformat() if r.initiated_at else None,
            "invoice_id": r.invoice_id,
            "payer_name": r.payer_name,
            "repeat_key": r.payer_hash[:10],
            "item_count": r.item_count,
            "mode": r.mode,
        }
        for r in rows
    ]
    return APIResponse(data=Paginated(items=items, pagination=PageMeta.build(page=page, page_size=page_size, total=int(total))))


@router.get("/intelligence", summary="Transaction intelligence over synced PayPal data")
async def intelligence(
    session: DbSession,
    days: Annotated[int, Query(ge=7, le=365)] = 30,
    principal: Principal = Depends(require_permission(Permission.PAYPAL_READ)),
) -> APIResponse[dict[str, Any]]:
    return APIResponse(data=await transaction_intelligence(session, principal.merchant_id, days=days))


# --------------------------------------------------------------------------- #
# Webhooks
# --------------------------------------------------------------------------- #
@router.post("/webhooks", summary="PayPal webhook receiver (verified, idempotent)", include_in_schema=True)
async def receive_webhook(request: Request, session: DbSession) -> APIResponse[dict[str, Any]]:
    body = await request.body()
    event, outcome = await WebhookService(session).ingest(headers=dict(request.headers), body=body)
    if outcome == "invalid":
        raise BadRequestError("Malformed webhook body.")
    if outcome == "rejected":
        # Persisted for forensics (committed by the session), but never acted on.
        from fastapi.responses import JSONResponse

        await session.commit()
        return JSONResponse(status_code=401, content={"success": False, "error": {
            "code": "PAYPAL_WEBHOOK_REJECTED", "message": "Webhook signature could not be verified."}})  # type: ignore[return-value]
    return APIResponse(data={"outcome": outcome, "event_id": event.event_id if event else None})


@router.get("/webhooks/events", summary="Received webhook events")
async def webhook_events(
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PAYPAL_READ)),
) -> APIResponse[list[dict[str, Any]]]:
    rows = (await session.execute(
        select(PayPalWebhookEvent).where(
            (PayPalWebhookEvent.merchant_id == principal.merchant_id) | (PayPalWebhookEvent.merchant_id.is_(None))
        ).order_by(PayPalWebhookEvent.received_at.desc()).limit(100)
    )).scalars().all()
    return APIResponse(data=[describe_webhook(r) for r in rows])


@router.post("/webhooks/simulate", summary="Send a signed simulated webhook through the real pipeline")
async def simulate_webhook(
    payload: SimulatedWebhook,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PAYPAL_MANAGE)),
) -> APIResponse[dict[str, Any]]:
    gateway = get_paypal_gateway()
    if gateway.mode != "SIMULATED":
        raise ConflictError("Simulated webhooks are only accepted when PayPal runs in simulation mode.")
    resource: dict[str, Any] = {}
    resource_type = "capture"
    if payload.execution_id:
        execution = (await session.execute(
            select(FinancialExecution).where(
                FinancialExecution.id == payload.execution_id, FinancialExecution.merchant_id == principal.merchant_id
            )
        )).scalars().first()
        if execution is None:
            raise BadRequestError("Unknown payment.")
        resource = {
            "id": execution.paypal_capture_id or f"SIM-CAPTURE-{execution.id.hex[:12].upper()}",
            "status": "COMPLETED",
            "amount": {"currency_code": execution.currency, "value": format(execution.amount, "f")},
            "custom_id": f"{principal.merchant_id}|{execution.resource_id}",
            "supplementary_data": {"related_ids": {"order_id": execution.paypal_order_id}},
        }
    elif payload.subscription_record_id:
        record = (await session.execute(
            select(PayPalSubscriptionRecord).where(
                PayPalSubscriptionRecord.id == payload.subscription_record_id,
                PayPalSubscriptionRecord.merchant_id == principal.merchant_id,
            )
        )).scalars().first()
        if record is None:
            raise BadRequestError("Unknown subscription.")
        resource = {"id": record.paypal_subscription_id, "status": record.status}
        resource_type = "subscription"
    else:
        raise BadRequestError("Pass an execution_id or a subscription_record_id.")
    event = {
        "id": f"SIM-WH-{uuid.uuid4().hex[:16].upper()}",
        "event_type": payload.event_type,
        "resource_type": resource_type,
        "summary": f"Simulated {payload.event_type}",
        "resource": resource,
        "create_time": None,
    }
    body = json.dumps(event).encode()
    row, outcome = await WebhookService(session).ingest(headers=sign_simulated_webhook(body), body=body)
    return APIResponse(data={"outcome": outcome, "event": describe_webhook(row) if row else None})


@router.post("/webhooks/{webhook_event_id}/reprocess", summary="Re-run a failed webhook handler")
async def reprocess_webhook(
    webhook_event_id: uuid.UUID,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PAYPAL_MANAGE)),
) -> APIResponse[dict[str, Any]]:
    row = (await session.execute(
        select(PayPalWebhookEvent).where(
            PayPalWebhookEvent.id == webhook_event_id, PayPalWebhookEvent.merchant_id == principal.merchant_id
        )
    )).scalars().first()
    if row is None:
        raise BadRequestError("Unknown webhook event.")
    if row.verification_status == "REJECTED":
        raise ConflictError("An unverified webhook is never processed.")
    await WebhookService(session).process(row)
    return APIResponse(data=describe_webhook(row))


# --------------------------------------------------------------------------- #
# Invoices (merchant -> customer)
# --------------------------------------------------------------------------- #
def _finance(session: Any, principal: Principal) -> PayPalFinanceService:
    return PayPalFinanceService(session, principal.merchant_id, actor_id=principal.user_id,
                                actor_label=principal.label, merchant_name=principal.merchant.name)


@router.get("/invoices", summary="PayPal invoices sent to customers")
async def list_invoices(
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PAYPAL_READ)),
) -> APIResponse[list[dict[str, Any]]]:
    rows = (await session.execute(
        select(PayPalInvoiceRecord).where(PayPalInvoiceRecord.merchant_id == principal.merchant_id)
        .order_by(PayPalInvoiceRecord.created_at.desc()).limit(200)
    )).scalars().all()
    return APIResponse(data=[invoice_record_out(r) for r in rows])


@router.post("/invoices", summary="Create (and send) a PayPal invoice")
async def create_invoice(
    payload: InvoiceCreate,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PAYPAL_MANAGE)),
) -> APIResponse[dict[str, Any]]:
    record = await _finance(session, principal).create_invoice(
        recipient_email=payload.recipient_email,
        recipient_name=payload.recipient_name,
        items=[i.model_dump() for i in payload.items],
        note=payload.note,
        due_date=payload.due_date,
        send=payload.send,
        campaign_id=payload.campaign_id,
    )
    return APIResponse(data=invoice_record_out(record))


@router.post("/invoices/{record_id}/action", summary="Remind, cancel or refresh an invoice")
async def invoice_action(
    record_id: uuid.UUID,
    payload: InvoiceAction,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PAYPAL_MANAGE)),
) -> APIResponse[dict[str, Any]]:
    record = await _finance(session, principal).invoice_action(record_id, payload.action, payload.note)
    return APIResponse(data=invoice_record_out(record))


# --------------------------------------------------------------------------- #
# Cashback payouts
# --------------------------------------------------------------------------- #
@router.post("/payouts/cashback", summary="Request a cashback payout batch (creates an approval)")
async def request_cashback(
    payload: CashbackRequest,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PAYPAL_MANAGE)),
) -> APIResponse[dict[str, Any]]:
    approval = await _finance(session, principal).request_cashback(
        recipients=[r.model_dump() for r in payload.recipients], note=payload.note, campaign_id=payload.campaign_id
    )
    return APIResponse(data=describe_approval(approval))


@router.get("/payouts", summary="Payout executions")
async def list_payouts(
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PAYPAL_READ)),
) -> APIResponse[list[dict[str, Any] | None]]:
    from app.services.supply.serializers import execution_out

    rows = (await session.execute(
        select(FinancialExecution).where(
            FinancialExecution.merchant_id == principal.merchant_id, FinancialExecution.method == "PAYOUTS"
        ).order_by(FinancialExecution.created_at.desc()).limit(100)
    )).scalars().all()
    return APIResponse(data=[execution_out(r) for r in rows])


@router.post("/payouts/{execution_id}/refresh", summary="Refresh a payout batch status from PayPal")
async def refresh_payout(
    execution_id: uuid.UUID,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PAYPAL_MANAGE)),
) -> APIResponse[dict[str, Any] | None]:
    from app.services.supply.serializers import execution_out

    execution = await _finance(session, principal).refresh_payout(execution_id)
    return APIResponse(data=execution_out(execution))


# --------------------------------------------------------------------------- #
# Subscriptions
# --------------------------------------------------------------------------- #
@router.get("/subscriptions", summary="Subscriptions and failed-payment recovery")
async def list_subscriptions(
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PAYPAL_READ)),
) -> APIResponse[list[dict[str, Any]]]:
    rows = (await session.execute(
        select(PayPalSubscriptionRecord).where(PayPalSubscriptionRecord.merchant_id == principal.merchant_id)
        .order_by(PayPalSubscriptionRecord.failed_payments.desc(), PayPalSubscriptionRecord.started_at.desc())
    )).scalars().all()
    data = [subscription_out(r) for r in rows]
    active = [r for r in rows if r.status == "ACTIVE"]
    mrr = sum((r.amount for r in active), Decimal("0"))
    return APIResponse(data=data, meta={
        "active": len(active), "monthly_recurring_revenue": format(mrr, "f"),
        "at_risk": sum(1 for r in rows if r.failed_payments > 0 or r.status == "SUSPENDED"),
        "at_risk_revenue": format(sum((r.amount for r in rows if r.failed_payments > 0), Decimal("0")), "f"),
    })


@router.get("/subscriptions/radar", summary="Subscription revenue radar (billing periods, retries, recovery)")
async def subscription_radar(
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PAYPAL_READ)),
    days_back: Annotated[int, Query(ge=14, le=365)] = 120,
    days_ahead: Annotated[int, Query(ge=7, le=180)] = 60,
) -> APIResponse[dict[str, Any]]:
    """One row per PayPal subscriber, one bar per billing period - drawn with Bryntum Scheduler."""
    rows = (await session.execute(
        select(PayPalSubscriptionRecord).where(PayPalSubscriptionRecord.merchant_id == principal.merchant_id)
    )).scalars().all()
    return APIResponse(data=build_radar(rows, days_back=days_back, days_ahead=days_ahead))


@router.get("/plans", summary="Subscription plans")
async def list_plans(
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PAYPAL_READ)),
) -> APIResponse[dict[str, Any]]:
    return APIResponse(data=await _finance(session, principal).list_plans())


@router.post("/plans", summary="Create a subscription plan")
async def create_plan(
    payload: PlanCreate,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PAYPAL_MANAGE)),
) -> APIResponse[dict[str, Any]]:
    return APIResponse(data=await _finance(session, principal).create_plan(
        name=payload.name, amount=payload.amount, interval_unit=payload.interval_unit, trial_days=payload.trial_days
    ))


@router.post("/subscriptions/{record_id}/action", summary="Suspend, activate, recover or cancel")
async def subscription_action(
    record_id: uuid.UUID,
    payload: SubscriptionAction,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PAYPAL_MANAGE)),
) -> APIResponse[dict[str, Any]]:
    record = await _finance(session, principal).subscription_action(record_id, payload.action, payload.reason)
    return APIResponse(data=subscription_out(record))


__all__ = ["ExecutionStatus", "router"]
