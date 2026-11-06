"""PayPal finance operations for the growth side: invoices, cashback, subscriptions.

* **Customer invoices** (Invoicing v2) - e.g. a win-back offer invoiced to a lapsed
  B2B customer. Requesting payment does not move the merchant's money, so it is
  gated by ``paypal:manage`` rather than an approval.
* **Cashback payouts** (Payouts) - money *leaves* the merchant, so a batch is an
  approval request first; execution consumes the approval and uses the approval id
  as PayPal's ``sender_batch_id`` (PayPal rejects a reused id - idempotency).
  Payouts are used for rewards only, never to settle supplier invoices.
* **Subscriptions** - plans, lifecycle actions and failed-payment recovery.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.permissions import Permission
from app.db.models.audit import ActorType, AuditAction
from app.db.models.governance import (
    ApprovalAction,
    ExecutionKind,
    ExecutionMethod,
    ExecutionStatus,
    FinancialExecution,
)
from app.db.models.paypal import PayPalInvoiceRecord, PayPalSubscriptionRecord
from app.integrations.paypal import (
    InvoiceDraft,
    InvoiceLine,
    PayoutBatchRequest,
    PayoutItem,
    PayPalAPIError,
    get_paypal_gateway,
)
from app.integrations.paypal.simulator import SimulatedPayPal
from app.repositories.merchant import AuditLogRepository
from app.services.supply.approvals import ApprovalService
from app.services.supply.policy import D, money, serialisable

#: Seeded demo subscriptions carry simulator ids; they stay on the simulator even
#: when real credentials are configured, so a sandbox call never sees a SIM- id.
_SEEDED_SIMULATOR = SimulatedPayPal()

#: Hard ceiling on one cashback batch, whatever an approver is shown.
MAX_PAYOUT_ITEMS = 500
MAX_PAYOUT_ITEM_AMOUNT = Decimal("100.00")


class PayPalFinanceService:
    def __init__(
        self,
        session: AsyncSession,
        merchant_id: uuid.UUID,
        *,
        actor_id: uuid.UUID | None = None,
        actor_label: str = "system",
        merchant_name: str = "",
    ) -> None:
        self.session = session
        self.merchant_id = merchant_id
        self.actor_id = actor_id
        self.actor_label = actor_label
        self.merchant_name = merchant_name
        self.audit = AuditLogRepository(session)

    # ================================================================== invoices
    async def create_invoice(
        self,
        *,
        recipient_email: str,
        recipient_name: str,
        items: list[dict[str, Any]],
        note: str = "",
        due_date: date | None = None,
        send: bool = True,
        customer_id: uuid.UUID | None = None,
        campaign_id: uuid.UUID | None = None,
    ) -> PayPalInvoiceRecord:
        if not items:
            raise BadRequestError("An invoice needs at least one line.")
        lines = [
            InvoiceLine(name=str(i["name"])[:200], quantity=D(i.get("quantity", 1)), unit_amount=money(i["unit_amount"]),
                        description=str(i.get("description", ""))[:1000])
            for i in items
        ]
        if any(line.quantity <= 0 or line.unit_amount <= 0 for line in lines):
            raise BadRequestError("Invoice lines need a positive quantity and amount.")
        given, _, surname = recipient_name.partition(" ")
        draft = InvoiceDraft(
            currency=settings.default_currency,
            recipient_email=recipient_email,
            recipient_given_name=given,
            recipient_surname=surname,
            invoicer_business_name=self.merchant_name[:100],
            note=note[:4000],
            due_date=due_date,
            items=lines,
        )
        gateway = get_paypal_gateway()
        request_id = f"invoice:{self.merchant_id}:{uuid.uuid4().hex}"
        invoice = await gateway.create_invoice(draft, request_id=request_id)
        if send:
            invoice = await gateway.send_invoice(invoice.id, subject=f"Invoice from {self.merchant_name}", note=note or None,
                                                 request_id=f"{request_id}:send")
        record = PayPalInvoiceRecord(
            merchant_id=self.merchant_id,
            paypal_invoice_id=invoice.id,
            invoice_number=invoice.invoice_number,
            status=invoice.status,
            recipient_email=recipient_email,
            recipient_name=recipient_name[:160],
            customer_id=customer_id,
            campaign_id=campaign_id,
            currency=draft.currency,
            amount=money(draft.total),
            due_date=due_date,
            payer_view_url=invoice.payer_view_url,
            note=note,
            mode=gateway.mode,
            sent_at=datetime.now(tz=UTC) if send else None,
            created_by_id=self.actor_id,
            raw=serialisable({k: v for k, v in (invoice.raw or {}).items() if k in ("id", "status", "detail", "amount", "simulated")}),
        )
        self.session.add(record)
        await self.session.flush()
        await self.audit.record(
            action=AuditAction.PAYPAL_INVOICE_SENT, merchant_id=self.merchant_id, actor_id=self.actor_id,
            actor_type=ActorType.USER, actor_label=self.actor_label, resource="paypal_invoice",
            resource_id=str(record.id),
            description=f"Invoice {invoice.invoice_number or invoice.id} for {draft.currency} {money(draft.total):,.2f} "
            f"to {recipient_email} ({gateway.mode})",
        )
        return record

    async def invoice(self, record_id: uuid.UUID) -> PayPalInvoiceRecord:
        row = (await self.session.execute(
            select(PayPalInvoiceRecord).where(PayPalInvoiceRecord.id == record_id, PayPalInvoiceRecord.merchant_id == self.merchant_id)
        )).scalars().first()
        if row is None:
            raise NotFoundError("Invoice not found.")
        return row

    async def invoice_action(self, record_id: uuid.UUID, action: str, note: str = "") -> PayPalInvoiceRecord:
        record = await self.invoice(record_id)
        gateway = get_paypal_gateway()
        if action == "remind":
            await gateway.remind_invoice(record.paypal_invoice_id, note=note or None)
            record.raw = {**(record.raw or {}), "last_reminder_at": datetime.now(tz=UTC).isoformat()}
        elif action == "cancel":
            await gateway.cancel_invoice(record.paypal_invoice_id, note=note or None)
            record.status = "CANCELLED"
        elif action == "refresh":
            fresh = await gateway.get_invoice(record.paypal_invoice_id)
            record.status = fresh.status
            record.payer_view_url = fresh.payer_view_url or record.payer_view_url
        else:
            raise BadRequestError("Unknown invoice action.")
        await self.session.flush()
        return record

    # ================================================================== cashback payouts
    async def request_cashback(
        self,
        *,
        recipients: list[dict[str, Any]],
        note: str,
        campaign_id: uuid.UUID | None = None,
        email_subject: str = "",
    ) -> Any:
        if not recipients:
            raise BadRequestError("Add at least one recipient.")
        if len(recipients) > MAX_PAYOUT_ITEMS:
            raise BadRequestError(f"A batch is limited to {MAX_PAYOUT_ITEMS} recipients.")
        items = []
        for index, r in enumerate(recipients):
            amount = money(r["amount"])
            if amount <= 0 or amount > MAX_PAYOUT_ITEM_AMOUNT:
                raise BadRequestError(f"Each cashback must be between 0.01 and {MAX_PAYOUT_ITEM_AMOUNT}.")
            items.append({"receiver": str(r["email"]).strip().lower(), "amount": amount,
                          "sender_item_id": f"cb-{index + 1}"})
        total = money(sum((i["amount"] for i in items), Decimal("0")))
        batch_id = uuid.uuid4()
        details = {
            "kind": "CASHBACK",
            "batch_id": str(batch_id),
            "campaign_id": str(campaign_id) if campaign_id else "",
            "currency": settings.default_currency,
            "total": total,
            "recipients": items,
            "note": note[:500],
            "email_subject": email_subject[:200] or f"A thank-you from {self.merchant_name}",
            "method": ExecutionMethod.PAYOUTS,
        }
        return await ApprovalService(self.session, self.merchant_id).request(
            action=ApprovalAction.CASHBACK_PAYOUT,
            resource_type="cashback_batch",
            resource_id=batch_id,
            title=f"Send {len(items)} cashback reward(s) via PayPal Payouts",
            summary=f"{settings.default_currency} {total:,.2f} in total. {note[:300]}",
            amount=total,
            currency=settings.default_currency,
            details=details,
            policy_version="payouts-1",
            required_permission=str(Permission.PAYMENT_APPROVE),
            risk_flags=[f"Mode: {settings.paypal_mode}"] + (["Large batch"] if len(items) > 50 else []),
            requested_by_type=ActorType.USER,
            requested_by_id=self.actor_id,
            requested_by_label=self.actor_label,
            correlation_id=f"CASHBACK-{batch_id.hex[:10]}",
        )

    async def execute_cashback(self, approval_id: uuid.UUID) -> FinancialExecution:
        approvals = ApprovalService(self.session, self.merchant_id)
        approval = await approvals.get(approval_id)
        if approval.action != ApprovalAction.CASHBACK_PAYOUT:
            raise BadRequestError("Not a cashback approval.")
        existing = (await self.session.execute(
            select(FinancialExecution).where(
                FinancialExecution.merchant_id == self.merchant_id,
                FinancialExecution.approval_request_id == approval.id,
                FinancialExecution.status != ExecutionStatus.FAILED,
            )
        )).scalars().first()
        if existing is not None:
            return existing
        # The batch terms live only in the approval, so they are their own live state.
        await approvals.consume(approval.id, live_details=approval.details, actor_id=self.actor_id)
        details = approval.details
        gateway = get_paypal_gateway()
        execution = FinancialExecution(
            merchant_id=self.merchant_id,
            approval_request_id=approval.id,
            kind=ExecutionKind.CASHBACK_PAYOUT,
            resource_type="cashback_batch",
            resource_id=approval.resource_id,
            amount=money(details["total"]),
            currency=details["currency"],
            mode=gateway.mode,
            method=ExecutionMethod.PAYOUTS,
            status=ExecutionStatus.CREATED,
            idempotency_key=f"payout:{approval.id}",
            requested_by_id=self.actor_id,
            executed_at=datetime.now(tz=UTC),
            correlation_id=approval.correlation_id,
        )
        self.session.add(execution)
        await self.session.flush()
        try:
            batch = await gateway.create_payout(
                PayoutBatchRequest(
                    sender_batch_id=f"pp-{approval.id.hex}",
                    email_subject=details.get("email_subject") or "A reward for you",
                    email_message=details.get("note") or "",
                    items=[PayoutItem(receiver=r["receiver"], amount=D(r["amount"]), currency=details["currency"],
                                      note=details.get("note", ""), sender_item_id=r["sender_item_id"])
                           for r in details["recipients"]],
                )
            )
            execution.paypal_payout_batch_id = batch.payout_batch_id
            execution.debug_id = batch.debug_id
            execution.status = ExecutionStatus.COMPLETED if batch.batch_status == "SUCCESS" else ExecutionStatus.PENDING
            if execution.status == ExecutionStatus.COMPLETED:
                execution.completed_at = datetime.now(tz=UTC)
            execution.response = serialisable({"batch_status": batch.batch_status,
                                               "items": [i.model_dump() for i in batch.items[:50]]})
            await self.audit.record(
                action=AuditAction.PAYMENT_EXECUTED, merchant_id=self.merchant_id, actor_id=self.actor_id,
                actor_type=ActorType.USER, actor_label=self.actor_label, resource="financial_execution",
                resource_id=str(execution.id),
                description=f"Cashback batch {batch.payout_batch_id}: {details['currency']} {D(details['total']):,.2f} ({gateway.mode})",
            )
        except PayPalAPIError as exc:
            execution.status = ExecutionStatus.FAILED
            execution.error = exc.message
            execution.debug_id = exc.debug_id
            approval.status = "APPROVED"
            approval.executed_at = None
        await self.session.flush()
        return execution

    async def refresh_payout(self, execution_id: uuid.UUID) -> FinancialExecution:
        execution = (await self.session.execute(
            select(FinancialExecution).where(FinancialExecution.id == execution_id, FinancialExecution.merchant_id == self.merchant_id)
        )).scalars().first()
        if execution is None or not execution.paypal_payout_batch_id:
            raise NotFoundError("Payout not found.")
        batch = await get_paypal_gateway().get_payout_batch(execution.paypal_payout_batch_id)
        execution.status = (
            ExecutionStatus.COMPLETED if batch.batch_status == "SUCCESS"
            else ExecutionStatus.FAILED if batch.batch_status in ("DENIED", "CANCELED")
            else ExecutionStatus.PENDING
        )
        await self.session.flush()
        return execution

    # ================================================================== subscriptions
    async def create_plan(self, *, name: str, amount: Decimal, interval_unit: str = "MONTH", trial_days: int = 0) -> dict[str, Any]:
        if money(amount) <= 0:
            raise BadRequestError("Plan price must be positive.")
        gateway = get_paypal_gateway()
        key = uuid.uuid4().hex
        product = await gateway.create_product(name=f"{self.merchant_name} {name}"[:127],
                                               description=f"{name} subscription", request_id=f"product:{key}")
        plan = await gateway.create_plan(product_id=product["id"], name=name, amount=money(amount),
                                         currency=settings.default_currency, interval_unit=interval_unit,
                                         trial_days=trial_days, request_id=f"plan:{key}")
        return {"plan": serialisable(plan.model_dump(exclude={"raw"})), "mode": gateway.mode}

    async def list_plans(self) -> dict[str, Any]:
        gateway = get_paypal_gateway()
        plans = await gateway.list_plans()
        return {"plans": [serialisable(p.model_dump(exclude={"raw"})) for p in plans], "mode": gateway.mode}

    async def subscription_action(self, record_id: uuid.UUID, action: str, reason: str) -> PayPalSubscriptionRecord:
        record = (await self.session.execute(
            select(PayPalSubscriptionRecord).where(
                PayPalSubscriptionRecord.id == record_id, PayPalSubscriptionRecord.merchant_id == self.merchant_id
            )
        )).scalars().first()
        if record is None:
            raise NotFoundError("Subscription not found.")
        gateway = (
            _SEEDED_SIMULATOR if record.mode == "SIMULATED" and get_paypal_gateway().mode != "SIMULATED"
            else get_paypal_gateway()
        )
        reason = reason or f"{action} requested by {self.actor_label}"
        if action == "suspend":
            await gateway.suspend_subscription(record.paypal_subscription_id, reason=reason)
            record.status = "SUSPENDED"
        elif action in ("activate", "recover"):
            await gateway.activate_subscription(record.paypal_subscription_id, reason=reason)
            record.status = "ACTIVE"
            record.failed_payments = 0
        elif action == "cancel":
            await gateway.cancel_subscription(record.paypal_subscription_id, reason=reason)
            record.status = "CANCELLED"
        else:
            raise ConflictError("Unknown subscription action.")
        # Lifecycle history for the revenue radar. A new dict, so the JSON column is
        # seen as changed.
        history = [e for e in (record.raw or {}).get("events", []) if isinstance(e, dict)][-19:]
        history.append({"type": action, "at": datetime.now(tz=UTC).isoformat(), "by": self.actor_label})
        record.raw = {**(record.raw or {}), "events": history}
        await self.session.flush()
        return record


def invoice_record_out(row: PayPalInvoiceRecord) -> dict[str, Any]:
    return {
        "invoice_record_id": str(row.id),
        "paypal_invoice_id": row.paypal_invoice_id,
        "invoice_number": row.invoice_number,
        "status": row.status,
        "recipient_email": row.recipient_email,
        "recipient_name": row.recipient_name,
        "currency": row.currency,
        "amount": format(D(row.amount), "f"),
        "due_date": row.due_date.isoformat() if row.due_date else None,
        "payer_view_url": row.payer_view_url,
        "note": row.note,
        "mode": row.mode,
        "campaign_id": str(row.campaign_id) if row.campaign_id else None,
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
        "paid_at": row.paid_at.isoformat() if row.paid_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def subscription_out(row: PayPalSubscriptionRecord) -> dict[str, Any]:
    return {
        "subscription_record_id": str(row.id),
        "paypal_subscription_id": row.paypal_subscription_id,
        "plan_id": row.plan_id,
        "plan_name": row.plan_name,
        "status": row.status,
        "subscriber_name": row.subscriber_name,
        "currency": row.currency,
        "amount": format(D(row.amount), "f"),
        "interval": row.interval,
        "failed_payments": row.failed_payments,
        "last_payment_at": row.last_payment_at.isoformat() if row.last_payment_at else None,
        "next_billing_at": row.next_billing_at.isoformat() if row.next_billing_at else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "mode": row.mode,
        "needs_recovery": row.failed_payments > 0 or row.status == "SUSPENDED",
    }
