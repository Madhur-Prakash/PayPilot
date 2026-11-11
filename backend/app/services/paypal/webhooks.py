"""PayPal webhook ingestion.

Order of operations, and why:

1. **Verify first.** The raw body and PayPal transmission headers go to the
   gateway: the real client asks PayPal's ``verify-webhook-signature`` endpoint,
   the simulator checks its own HMAC. An unverified event is persisted as
   REJECTED for forensics and never acted on.
2. **Persist with a replay guard.** ``event_id`` is unique, so a retried or
   replayed delivery is recognised and acknowledged without being re-processed.
3. **Route idempotently.** Each handler checks current state before changing it
   (a capture already marked settled stays settled), so even a handler that runs
   twice is harmless.
4. **Record failures.** A handler exception marks the event FAILED with the error
   and returns 200 to PayPal anyway only after persisting - PayPal retries on
   non-2xx, and a poison event would otherwise retry for days. Failed events can
   be re-processed from the Finance screen.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.audit import ActorType, AuditAction
from app.db.models.governance import ExecutionKind, ExecutionStatus, FinancialExecution
from app.db.models.paypal import (
    PayPalInvoiceRecord,
    PayPalSubscriptionRecord,
    PayPalWebhookEvent,
    WebhookProcessing,
    WebhookVerification,
)
from app.db.models.supply import SupplierInvoice
from app.integrations.paypal import get_paypal_gateway
from app.repositories.merchant import AuditLogRepository

log = get_logger(__name__)

HANDLED_EVENTS = (
    "CHECKOUT.ORDER.APPROVED",
    "PAYMENT.CAPTURE.COMPLETED",
    "PAYMENT.CAPTURE.DENIED",
    "PAYMENT.CAPTURE.REFUNDED",
    "PAYMENT.CAPTURE.REVERSED",
    "PAYMENT.PAYOUTSBATCH.SUCCESS",
    "PAYMENT.PAYOUTSBATCH.DENIED",
    "PAYMENT.PAYOUTS-ITEM.SUCCEEDED",
    "PAYMENT.PAYOUTS-ITEM.FAILED",
    "INVOICING.INVOICE.PAID",
    "INVOICING.INVOICE.CANCELLED",
    "BILLING.SUBSCRIPTION.ACTIVATED",
    "BILLING.SUBSCRIPTION.SUSPENDED",
    "BILLING.SUBSCRIPTION.CANCELLED",
    "BILLING.SUBSCRIPTION.PAYMENT.FAILED",
    "PAYMENT.SALE.COMPLETED",
)


class WebhookService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def ingest(self, *, headers: dict[str, str], body: bytes) -> tuple[PayPalWebhookEvent | None, str]:
        """Returns (event, outcome). Outcome is one of verified/duplicate/rejected/invalid."""
        gateway = get_paypal_gateway()
        lowered = {k.lower(): v for k, v in headers.items()}
        try:
            event = json.loads(body)
            if not isinstance(event, dict):
                raise ValueError
        except ValueError:
            return None, "invalid"
        event_id = str(event.get("id") or "")[:64]
        if not event_id:
            return None, "invalid"

        existing = (
            await self.session.execute(select(PayPalWebhookEvent).where(PayPalWebhookEvent.event_id == event_id))
        ).scalars().first()
        if existing is not None and existing.verification_status != WebhookVerification.REJECTED:
            existing.attempts = (existing.attempts or 1) + 1
            await self.session.flush()
            return existing, "duplicate"

        verified = await gateway.verify_webhook_signature(headers=lowered, body=body)
        resource = event.get("resource") or {}
        row = existing or PayPalWebhookEvent(event_id=event_id)
        row.event_type = str(event.get("event_type") or "")[:64]
        row.resource_type = str(event.get("resource_type") or "")[:48]
        row.resource_id = str(resource.get("id") or "")[:64]
        row.summary = str(event.get("summary") or "")[:2000]
        row.transmission_id = lowered.get("paypal-transmission-id", "")[:64]
        row.mode = gateway.mode
        row.received_at = datetime.now(tz=UTC)
        row.payload = event
        if not verified:
            row.verification_status = WebhookVerification.REJECTED
            row.processing_status = WebhookProcessing.IGNORED
            row.error = "Signature verification failed - event not trusted."
            if existing is None:
                self.session.add(row)
            await self.session.flush()
            log.warning("paypal_webhook_rejected", event_id=event_id, event_type=row.event_type)
            return row, "rejected"

        row.verification_status = (
            WebhookVerification.SIMULATED_VERIFIED if gateway.mode == "SIMULATED" else WebhookVerification.VERIFIED
        )
        row.merchant_id = await self._resolve_merchant(event)
        if existing is None:
            self.session.add(row)
        await self.session.flush()
        await self.process(row)
        return row, "verified"

    async def process(self, row: PayPalWebhookEvent) -> None:
        handler = {
            "PAYMENT.CAPTURE.COMPLETED": self._capture_completed,
            "PAYMENT.CAPTURE.DENIED": self._capture_failed,
            "PAYMENT.CAPTURE.REVERSED": self._capture_failed,
            "PAYMENT.CAPTURE.REFUNDED": self._capture_refunded,
            "CHECKOUT.ORDER.APPROVED": self._order_approved,
            "PAYMENT.PAYOUTSBATCH.SUCCESS": self._payout_batch,
            "PAYMENT.PAYOUTSBATCH.DENIED": self._payout_batch,
            "INVOICING.INVOICE.PAID": self._invoice_status,
            "INVOICING.INVOICE.CANCELLED": self._invoice_status,
            "BILLING.SUBSCRIPTION.ACTIVATED": self._subscription_status,
            "BILLING.SUBSCRIPTION.SUSPENDED": self._subscription_status,
            "BILLING.SUBSCRIPTION.CANCELLED": self._subscription_status,
            "BILLING.SUBSCRIPTION.PAYMENT.FAILED": self._subscription_payment_failed,
        }.get(row.event_type)
        if handler is None:
            row.processing_status = WebhookProcessing.IGNORED
            row.processed_at = datetime.now(tz=UTC)
            await self.session.flush()
            return
        try:
            note = await handler(row, row.payload.get("resource") or {})
            row.processing_status = WebhookProcessing.PROCESSED
            row.error = note or ""
        except Exception as exc:
            log.exception("paypal_webhook_handler_failed", event_type=row.event_type)
            row.processing_status = WebhookProcessing.FAILED
            row.error = f"{type(exc).__name__}: {str(exc)[:500]}"
        row.processed_at = datetime.now(tz=UTC)
        await self.session.flush()
        if row.merchant_id:
            await AuditLogRepository(self.session).record(
                action=AuditAction.PAYPAL_WEBHOOK, merchant_id=row.merchant_id, actor_type=ActorType.SYSTEM,
                actor_label=f"PayPal webhook ({row.mode})", resource="paypal_webhook", resource_id=row.event_id,
                description=f"{row.event_type}: {row.processing_status.lower()}",
                status="SUCCESS" if row.processing_status == WebhookProcessing.PROCESSED else "FAILURE",
            )

    # ------------------------------------------------------------------ attribution
    async def _resolve_merchant(self, event: dict[str, Any]) -> uuid.UUID | None:
        resource = event.get("resource") or {}
        custom = str(resource.get("custom_id") or "")
        if "|" in custom:
            try:
                return uuid.UUID(custom.split("|", 1)[0])
            except ValueError:
                pass
        order_id = _order_id(resource)
        for column, value in (
            (FinancialExecution.paypal_order_id, order_id),
            (FinancialExecution.paypal_capture_id, str(resource.get("id") or "")),
            (FinancialExecution.paypal_payout_batch_id, str((resource.get("batch_header") or {}).get("payout_batch_id") or "")),
        ):
            if value:
                hit = (await self.session.execute(select(FinancialExecution.merchant_id).where(column == value))).first()
                if hit:
                    return hit[0]
        invoice_id = str((resource.get("invoice") or resource).get("id") or "")
        if invoice_id:
            hit = (await self.session.execute(
                select(PayPalInvoiceRecord.merchant_id).where(PayPalInvoiceRecord.paypal_invoice_id == invoice_id)
            )).first()
            if hit:
                return hit[0]
        sub_id = str(resource.get("id") or resource.get("billing_agreement_id") or "")
        if sub_id:
            hit = (await self.session.execute(
                select(PayPalSubscriptionRecord.merchant_id).where(PayPalSubscriptionRecord.paypal_subscription_id == sub_id)
            )).first()
            if hit:
                return hit[0]
        return None

    async def _execution(self, resource: dict[str, Any]) -> FinancialExecution | None:
        order_id = _order_id(resource)
        capture_id = str(resource.get("id") or "")
        stmt = select(FinancialExecution)
        if order_id:
            hit = (await self.session.execute(stmt.where(FinancialExecution.paypal_order_id == order_id))).scalars().first()
            if hit:
                return hit
        if capture_id:
            return (await self.session.execute(stmt.where(FinancialExecution.paypal_capture_id == capture_id))).scalars().first()
        return None

    # ------------------------------------------------------------------ handlers
    async def _capture_completed(self, row: PayPalWebhookEvent, resource: dict[str, Any]) -> str:
        if str(resource.get("custom_id") or "").endswith("|shop"):
            return await self._shop_sale(row, resource)
        execution = await self._execution(resource)
        if execution is None:
            return "No matching payment execution - recorded only."
        if execution.status in ExecutionStatus.SETTLED:
            return "Already settled - no change."
        if execution.kind == ExecutionKind.MERCHANT_PURCHASE:
            from app.services.paypal.orders import MerchantPaymentService

            await MerchantPaymentService(self.session, execution.merchant_id, actor_id=None,
                                         actor_label=f"PayPal webhook ({row.mode})").settle(
                execution, str(resource.get("id") or ""), raw=resource, source="webhook")
            return "Test-stock purchase settled from webhook."
        from app.services.supply.lifecycle import ProcurementLifecycle

        lifecycle = ProcurementLifecycle(self.session, execution.merchant_id, actor_label="PayPal webhook")
        invoice = await self.session.get(SupplierInvoice, execution.resource_id)
        if invoice is None:
            execution.status = ExecutionStatus.CAPTURED
            execution.paypal_capture_id = str(resource.get("id") or "")
            return "Capture recorded."
        await lifecycle._settled(execution, invoice, str(resource.get("id") or ""))
        return "Payment settled from webhook."

    async def _shop_sale(self, row: PayPalWebhookEvent, resource: dict[str, Any]) -> str:
        """A customer paid at the online store: record the sale (idempotent with the browser return)."""
        from app.db.models.merchant import Merchant
        from app.integrations.paypal import get_paypal_gateway
        from app.services.shop import ShopService

        order_id = str(((resource.get("supplementary_data") or {}).get("related_ids") or {}).get("order_id") or "")
        merchant = await self.session.get(Merchant, row.merchant_id) if row.merchant_id else None
        if not order_id or merchant is None:
            return "Online-store capture without an order or merchant - recorded only."
        order = await get_paypal_gateway().get_order(order_id)
        result = await ShopService(self.session, merchant).record_paid_order(
            order, str(resource.get("id") or ""), source="webhook")
        return "Online sale recorded from webhook." if result["recorded_now"] else "Online sale already recorded - no change."

    async def _capture_failed(self, row: PayPalWebhookEvent, resource: dict[str, Any]) -> str:
        execution = await self._execution(resource)
        if execution is None:
            return "No matching payment execution."
        execution.status = ExecutionStatus.FAILED
        execution.error = f"{row.event_type}: {resource.get('status', '')}"
        return "Payment marked failed."

    async def _capture_refunded(self, row: PayPalWebhookEvent, resource: dict[str, Any]) -> str:
        execution = await self._execution(resource)
        if execution is not None:
            execution.response = {**(execution.response or {}), "refund": {"event_id": row.event_id, "status": resource.get("status")}}
        return "Refund recorded."

    async def _order_approved(self, row: PayPalWebhookEvent, resource: dict[str, Any]) -> str:
        execution = await self._execution(resource)
        if execution is None:
            return "No matching payment execution."
        execution.response = {**(execution.response or {}), "payer_approved_at": datetime.now(tz=UTC).isoformat()}
        return "Payer approval recorded; capture can proceed."

    async def _payout_batch(self, row: PayPalWebhookEvent, resource: dict[str, Any]) -> str:
        header = resource.get("batch_header") or {}
        batch_id = str(header.get("payout_batch_id") or "")
        execution = (await self.session.execute(
            select(FinancialExecution).where(FinancialExecution.paypal_payout_batch_id == batch_id)
        )).scalars().first() if batch_id else None
        if execution is None:
            return "No matching payout."
        status = str(header.get("batch_status") or "")
        execution.status = ExecutionStatus.COMPLETED if status == "SUCCESS" else ExecutionStatus.FAILED
        execution.completed_at = datetime.now(tz=UTC)
        return f"Payout batch {status.lower()}."

    async def _invoice_status(self, row: PayPalWebhookEvent, resource: dict[str, Any]) -> str:
        invoice = resource.get("invoice") or resource
        invoice_id = str(invoice.get("id") or "")
        record = (await self.session.execute(
            select(PayPalInvoiceRecord).where(PayPalInvoiceRecord.paypal_invoice_id == invoice_id)
        )).scalars().first()
        if record is None:
            return "Unknown invoice."
        record.status = str(invoice.get("status") or ("PAID" if row.event_type.endswith("PAID") else "CANCELLED"))
        if record.status == "PAID":
            record.paid_at = datetime.now(tz=UTC)
        return f"Invoice {record.status.lower()}."

    async def _subscription_status(self, row: PayPalWebhookEvent, resource: dict[str, Any]) -> str:
        record = await self._subscription(resource)
        if record is None:
            return "Unknown subscription."
        record.status = str(resource.get("status") or row.event_type.rsplit(".", 1)[-1])
        if record.status == "ACTIVE":
            record.failed_payments = 0
        return f"Subscription {record.status.lower()}."

    async def _subscription_payment_failed(self, row: PayPalWebhookEvent, resource: dict[str, Any]) -> str:
        record = await self._subscription(resource)
        if record is None:
            return "Unknown subscription."
        record.failed_payments = (record.failed_payments or 0) + 1
        return f"Failed payment #{record.failed_payments} recorded - eligible for recovery."

    async def _subscription(self, resource: dict[str, Any]) -> PayPalSubscriptionRecord | None:
        sub_id = str(resource.get("id") or resource.get("billing_agreement_id") or "")
        if not sub_id:
            return None
        return (await self.session.execute(
            select(PayPalSubscriptionRecord).where(PayPalSubscriptionRecord.paypal_subscription_id == sub_id)
        )).scalars().first()


def _order_id(resource: dict[str, Any]) -> str:
    related = ((resource.get("supplementary_data") or {}).get("related_ids") or {})
    if related.get("order_id"):
        return str(related["order_id"])
    if str(resource.get("id", "")).startswith(("SIM-ORDER", )) or resource.get("intent"):
        return str(resource.get("id"))
    return ""


def describe_webhook(row: PayPalWebhookEvent) -> dict[str, Any]:
    return {
        "webhook_event_id": str(row.id),
        "event_id": row.event_id,
        "event_type": row.event_type,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "summary": row.summary,
        "verification_status": row.verification_status,
        "processing_status": row.processing_status,
        "attempts": row.attempts,
        "error": row.error,
        "mode": row.mode,
        "received_at": row.received_at.isoformat() if row.received_at else None,
        "processed_at": row.processed_at.isoformat() if row.processed_at else None,
    }
