"""A deterministic, offline stand-in for the PayPal REST API.

Used when no PayPal credentials are configured, so the whole product - payments,
invoices, payouts, transaction sync, webhooks - can be demonstrated and tested
without a PayPal account. Everything it returns is unmistakably simulated:

* every identifier starts with ``SIM-``;
* the gateway reports ``mode == "SIMULATED"`` and services persist that mode on
  every row, which the UI renders as a badge;
* it never makes a network call.

Determinism: identifiers are derived from a hash of the caller's ``request_id``,
so a retried call returns the same object (the same idempotency PayPal gives via
``PayPal-Request-Id``). Synthetic transactions are a pure function of the date.

Simplification, documented: a simulated order is treated as already approved by
the payer, so ``capture_order`` / ``authorize_order`` succeed immediately. Against
the real sandbox the payer must approve at the order's ``approve_url`` first.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from app.core.config import settings
from app.integrations.paypal.client import split_windows
from app.integrations.paypal.errors import PayPalAPIError
from app.integrations.paypal.models import (
    InvoiceDraft,
    Money,
    OrderItem,
    PayoutBatchRequest,
    PayPalCapture,
    PayPalInvoice,
    PayPalOrder,
    PayPalPayoutBatch,
    PayPalPayoutItemStatus,
    PayPalPlan,
    PayPalSubscription,
    PayPalTransaction,
    TransactionSearchPage,
    money_str,
)

SIMULATED_ALGO = "SIMULATED-HMAC-SHA256"

#: Synthetic catalogue for simulated checkout payments (USD).
_BASKETS = (
    Decimal("6.25"), Decimal("9.50"), Decimal("12.75"), Decimal("18.00"),
    Decimal("21.40"), Decimal("24.00"), Decimal("33.90"), Decimal("46.50"),
)
_PAYERS = (
    "Avery Collins", "Jordan Reyes", "Taylor Brooks", "Morgan Patel", "Casey Nguyen",
    "Riley Thompson", "Jamie Foster", "Quinn Ramirez", "Drew Sullivan", "Parker Hayes",
    "Hayden Ortiz", "Rowan Mitchell",
)


def _digest(*parts: Any) -> str:
    return hashlib.sha256("::".join(str(p) for p in parts).encode()).hexdigest()


def sim_id(kind: str, *parts: Any) -> str:
    return f"SIM-{kind}-{_digest(kind, *parts)[:14].upper()}"


def _webhook_key() -> bytes:
    if settings.paypal_simulator_webhook_secret:
        return settings.paypal_simulator_webhook_secret.encode()
    return hashlib.sha256(f"paypal-simulator::{settings.jwt_secret}".encode()).digest()


def sign_simulated_webhook(body: bytes) -> dict[str, str]:
    """Headers that make ``body`` verifiable by the simulator (and only the simulator)."""
    transmission_id = str(uuid.uuid4())
    transmission_time = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    signature = hmac.new(
        _webhook_key(),
        f"{transmission_id}|{transmission_time}|".encode() + body,
        hashlib.sha256,
    ).hexdigest()
    return {
        "paypal-transmission-id": transmission_id,
        "paypal-transmission-time": transmission_time,
        "paypal-transmission-sig": signature,
        "paypal-cert-url": "simulated://paypilot/paypal-simulator",
        "paypal-auth-algo": SIMULATED_ALGO,
    }


class SimulatedPayPal:
    """Implements the PayPal gateway interface with no network access."""

    mode: Literal["SIMULATED"] = "SIMULATED"
    base_url = "simulated://paypal"

    def __init__(self) -> None:
        self._orders: dict[str, dict[str, Any]] = {}
        self._authorizations: dict[str, dict[str, Any]] = {}
        self._invoices: dict[str, dict[str, Any]] = {}
        self._payouts: dict[str, PayPalPayoutBatch] = {}
        self._plans: dict[str, PayPalPlan] = {}
        self._subscriptions: dict[str, dict[str, Any]] = {}

    def __repr__(self) -> str:
        return "SimulatedPayPal()"

    async def aclose(self) -> None:
        return None

    # ------------------------------------------------------------------ transactions
    @staticmethod
    def _transactions_for_day(day: date) -> list[PayPalTransaction]:
        seed = int(_digest("day", day.isoformat())[:8], 16)
        count = 6 + seed % 6
        txns: list[PayPalTransaction] = []
        for index in range(count):
            h = int(_digest("txn", day.isoformat(), index)[:12], 16)
            amount = _BASKETS[h % len(_BASKETS)]
            refund = h % 29 == 0
            minute = (h // 7) % (14 * 60)
            initiated = datetime(day.year, day.month, day.day, 7, 0, tzinfo=UTC) + timedelta(minutes=minute)
            gross = -amount if refund else amount
            fee = Decimal("0") if refund else -(amount * Decimal("0.0349") + Decimal("0.49")).quantize(Decimal("0.01"))
            payer = _PAYERS[(h // 13) % len(_PAYERS)]
            txn_id = sim_id("TXN", day.isoformat(), index)
            txns.append(
                PayPalTransaction(
                    transaction_id=txn_id,
                    event_code="T1107" if refund else "T0006",
                    status="S",
                    initiated_at=initiated,
                    updated_at=initiated,
                    gross=Money(currency_code="USD", value=gross),
                    fee=Money(currency_code="USD", value=fee),
                    invoice_id="",
                    custom_field="",
                    payer_email=f"{payer.split()[0].lower()}.{(h % 97):02d}@simulated.example",
                    payer_name=payer,
                    item_count=1 + h % 3,
                    raw={"simulated": True, "transaction_info": {"transaction_id": txn_id}},
                )
            )
        return sorted(txns, key=lambda t: t.initiated_at)

    async def search_transactions(
        self, *, start: datetime, end: datetime, page: int = 1, page_size: int = 100
    ) -> TransactionSearchPage:
        if end - start > timedelta(days=31):
            raise ValueError("Transaction Search windows are limited to 31 days per call.")
        start = start if start.tzinfo else start.replace(tzinfo=UTC)
        end = end if end.tzinfo else end.replace(tzinfo=UTC)
        rows: list[PayPalTransaction] = []
        day = start.date()
        while day <= end.date():
            rows.extend(t for t in self._transactions_for_day(day) if start <= t.initiated_at <= end)
            day += timedelta(days=1)
        page_size = max(1, min(page_size, 500))
        total_pages = max(1, -(-len(rows) // page_size))
        page = max(1, page)
        chunk = rows[(page - 1) * page_size : page * page_size]
        return TransactionSearchPage(
            transactions=chunk,
            page=page,
            total_pages=total_pages,
            total_items=len(rows),
            last_refreshed_at=datetime.now(tz=UTC),
        )

    async def iter_transactions(
        self, *, start: datetime, end: datetime, page_size: int = 100
    ) -> AsyncIterator[PayPalTransaction]:
        for lower, upper in split_windows(start, end):
            page = 1
            while True:
                result = await self.search_transactions(start=lower, end=upper, page=page, page_size=page_size)
                for txn in result.transactions:
                    yield txn
                if page >= result.total_pages:
                    break
                page += 1

    # ------------------------------------------------------------------ orders
    def _order_view(self, order_id: str) -> PayPalOrder:
        state = self._orders.get(order_id)
        if state is None:
            raise PayPalAPIError(
                "The specified resource does not exist.", http_status=404, name="RESOURCE_NOT_FOUND",
                debug_id="SIM-DEBUG",
            )
        unit: dict[str, Any] = {
            "reference_id": state["reference_id"],
            "amount": Money(currency_code=state["currency"], value=state["amount"]).wire(),
            "payee": {"email_address": state["payee_email"]} if state["payee_email"] else {},
            "payments": {
                "captures": [{"id": c, "status": "COMPLETED"} for c in state["captures"]],
                "authorizations": [{"id": a, "status": self._authorizations[a]["status"]} for a in state["authorizations"]],
            },
        }
        body = {"id": order_id, "status": state["status"], "intent": state["intent"], "purchase_units": [unit], "links": [], "simulated": True}
        return PayPalOrder.from_api(body, debug_id="SIM-DEBUG")

    async def create_order(
        self,
        *,
        intent: Literal["CAPTURE", "AUTHORIZE"],
        amount: Decimal,
        currency: str,
        reference_id: str,
        description: str,
        request_id: str,
        invoice_id: str | None = None,
        custom_id: str | None = None,
        payee_email: str | None = None,
        items: list[OrderItem] | None = None,
        return_url: str | None = None,
        cancel_url: str | None = None,
    ) -> PayPalOrder:
        if amount <= 0:
            raise PayPalAPIError("Amount must be positive.", http_status=422, name="UNPROCESSABLE_ENTITY", debug_id="SIM-DEBUG")
        order_id = sim_id("ORDER", request_id)
        if order_id not in self._orders:
            self._orders[order_id] = {
                "intent": intent,
                "amount": Decimal(money_str(amount, currency)),
                "currency": currency,
                "reference_id": reference_id,
                "description": description,
                "invoice_id": invoice_id or "",
                "custom_id": custom_id or "",
                "payee_email": payee_email or "",
                # Simulated payers approve instantly - see the module docstring.
                "status": "APPROVED",
                "captures": [],
                "authorizations": [],
            }
        return self._order_view(order_id)

    async def get_order(self, order_id: str) -> PayPalOrder:
        return self._order_view(order_id)

    async def capture_order(self, order_id: str, *, request_id: str) -> PayPalOrder:
        state = self._orders.get(order_id)
        if state is None:
            return self._order_view(order_id)
        if state["intent"] != "CAPTURE":
            raise PayPalAPIError("Order intent is AUTHORIZE.", http_status=422, name="ACTION_DOES_NOT_MATCH_INTENT", debug_id="SIM-DEBUG")
        if not state["captures"]:
            state["captures"].append(sim_id("CAPTURE", order_id, request_id))
            state["status"] = "COMPLETED"
        return self._order_view(order_id)

    async def authorize_order(self, order_id: str, *, request_id: str) -> PayPalOrder:
        state = self._orders.get(order_id)
        if state is None:
            return self._order_view(order_id)
        if state["intent"] != "AUTHORIZE":
            raise PayPalAPIError("Order intent is CAPTURE.", http_status=422, name="ACTION_DOES_NOT_MATCH_INTENT", debug_id="SIM-DEBUG")
        if not state["authorizations"]:
            auth_id = sim_id("AUTH", order_id, request_id)
            state["authorizations"].append(auth_id)
            self._authorizations[auth_id] = {
                "order_id": order_id,
                "status": "CREATED",
                "amount": state["amount"],
                "currency": state["currency"],
                "capture": None,
            }
            state["status"] = "COMPLETED"
        return self._order_view(order_id)

    async def capture_authorization(
        self,
        authorization_id: str,
        *,
        request_id: str,
        amount: Decimal | None = None,
        currency: str | None = None,
        final_capture: bool = True,
        invoice_id: str | None = None,
    ) -> PayPalCapture:
        auth = self._authorizations.get(authorization_id)
        if auth is None:
            raise PayPalAPIError("Authorization not found.", http_status=404, name="RESOURCE_NOT_FOUND", debug_id="SIM-DEBUG")
        if auth["status"] == "VOIDED":
            raise PayPalAPIError("Authorization has been voided.", http_status=422, name="AUTHORIZATION_VOIDED", debug_id="SIM-DEBUG")
        value = amount if amount is not None else auth["amount"]
        if value > auth["amount"]:
            raise PayPalAPIError("Capture exceeds the authorized amount.", http_status=422, name="MAX_CAPTURE_AMOUNT_EXCEEDED", debug_id="SIM-DEBUG")
        if auth["capture"] is None:
            auth["capture"] = sim_id("CAPTURE", authorization_id, request_id)
            auth["status"] = "CAPTURED"
            auth["captured_amount"] = value
        return PayPalCapture(
            id=auth["capture"],
            status="COMPLETED",
            amount=Money(currency_code=currency or auth["currency"], value=auth.get("captured_amount", value)),
            final_capture=final_capture,
            debug_id="SIM-DEBUG",
            raw={"simulated": True},
        )

    async def void_authorization(self, authorization_id: str, *, request_id: str) -> None:
        auth = self._authorizations.get(authorization_id)
        if auth is None:
            raise PayPalAPIError("Authorization not found.", http_status=404, name="RESOURCE_NOT_FOUND", debug_id="SIM-DEBUG")
        if auth["status"] == "CAPTURED":
            raise PayPalAPIError("Authorization already captured.", http_status=422, name="PREVIOUSLY_CAPTURED", debug_id="SIM-DEBUG")
        auth["status"] = "VOIDED"

    # ------------------------------------------------------------------ invoicing
    def _invoice_view(self, invoice_id: str) -> PayPalInvoice:
        state = self._invoices.get(invoice_id)
        if state is None:
            raise PayPalAPIError("Invoice not found.", http_status=404, name="RESOURCE_NOT_FOUND", debug_id="SIM-DEBUG")
        draft: InvoiceDraft = state["draft"]
        return PayPalInvoice(
            id=invoice_id,
            status=state["status"],
            invoice_number=state["number"],
            amount=Money(currency_code=draft.currency, value=draft.total),
            recipient_email=draft.recipient_email,
            payer_view_url=f"simulated://paypal/invoice/p/{invoice_id}",
            due_date=draft.due_date,
            debug_id="SIM-DEBUG",
            raw={"simulated": True, "reminders": state["reminders"]},
        )

    async def generate_invoice_number(self) -> str:
        return f"SIM-{len(self._invoices) + 1:05d}"

    async def create_invoice(self, draft: InvoiceDraft, *, request_id: str) -> PayPalInvoice:
        invoice_id = sim_id("INV", request_id)
        if invoice_id not in self._invoices:
            self._invoices[invoice_id] = {
                "draft": draft,
                "status": "DRAFT",
                "number": draft.invoice_number or f"SIM-{len(self._invoices) + 1:05d}",
                "reminders": 0,
            }
        return self._invoice_view(invoice_id)

    async def get_invoice(self, invoice_id: str) -> PayPalInvoice:
        return self._invoice_view(invoice_id)

    async def list_invoices(self, *, page: int = 1, page_size: int = 20) -> list[PayPalInvoice]:
        ids = list(self._invoices)[(page - 1) * page_size : page * page_size]
        return [self._invoice_view(i) for i in ids]

    async def send_invoice(
        self, invoice_id: str, *, subject: str | None = None, note: str | None = None, request_id: str | None = None
    ) -> PayPalInvoice:
        state = self._invoices.get(invoice_id)
        if state is not None and state["status"] == "DRAFT":
            state["status"] = "SENT"
        return self._invoice_view(invoice_id)

    async def remind_invoice(self, invoice_id: str, *, subject: str | None = None, note: str | None = None) -> None:
        state = self._invoices.get(invoice_id)
        if state is None:
            self._invoice_view(invoice_id)
            return
        if state["status"] not in ("SENT", "UNPAID", "PARTIALLY_PAID"):
            raise PayPalAPIError("Only a sent invoice can be reminded.", http_status=422, name="INVALID_INVOICE_STATUS", debug_id="SIM-DEBUG")
        state["reminders"] += 1

    async def cancel_invoice(self, invoice_id: str, *, subject: str | None = None, note: str | None = None) -> None:
        state = self._invoices.get(invoice_id)
        if state is None:
            self._invoice_view(invoice_id)
            return
        if state["status"] == "PAID":
            raise PayPalAPIError("A paid invoice cannot be cancelled.", http_status=422, name="INVALID_INVOICE_STATUS", debug_id="SIM-DEBUG")
        state["status"] = "CANCELLED"

    # ------------------------------------------------------------------ payouts
    async def create_payout(self, batch: PayoutBatchRequest) -> PayPalPayoutBatch:
        batch_id = sim_id("PAYOUT", batch.sender_batch_id)
        existing = self._payouts.get(batch_id)
        if existing is not None:
            return existing
        result = PayPalPayoutBatch(
            payout_batch_id=batch_id,
            batch_status="SUCCESS",
            sender_batch_id=batch.sender_batch_id,
            items=[
                PayPalPayoutItemStatus(
                    payout_item_id=sim_id("PAYOUTITEM", batch_id, index),
                    transaction_status="SUCCESS",
                    receiver=item.receiver,
                    amount=item.amount,
                    sender_item_id=item.sender_item_id,
                )
                for index, item in enumerate(batch.items)
            ],
            debug_id="SIM-DEBUG",
            raw={"simulated": True},
        )
        self._payouts[batch_id] = result
        return result

    async def get_payout_batch(self, payout_batch_id: str) -> PayPalPayoutBatch:
        batch = self._payouts.get(payout_batch_id)
        if batch is None:
            raise PayPalAPIError("Payout batch not found.", http_status=404, name="RESOURCE_NOT_FOUND", debug_id="SIM-DEBUG")
        return batch

    # ------------------------------------------------------------------ subscriptions
    async def create_product(
        self, *, name: str, description: str, product_type: str = "SERVICE", request_id: str
    ) -> dict[str, Any]:
        return {"id": sim_id("PROD", request_id), "name": name, "description": description, "type": product_type, "simulated": True}

    async def create_plan(
        self,
        *,
        product_id: str,
        name: str,
        amount: Decimal,
        currency: str,
        interval_unit: str = "MONTH",
        interval_count: int = 1,
        trial_days: int = 0,
        request_id: str,
    ) -> PayPalPlan:
        plan_id = sim_id("PLAN", request_id)
        plan = self._plans.get(plan_id) or PayPalPlan(
            id=plan_id,
            product_id=product_id,
            name=name,
            status="ACTIVE",
            amount=Decimal(money_str(amount, currency)),
            currency=currency,
            interval_unit=interval_unit,
            interval_count=interval_count,
            trial_days=trial_days,
            raw={"simulated": True},
        )
        self._plans[plan_id] = plan
        return plan

    async def list_plans(self, *, page: int = 1, page_size: int = 20) -> list[PayPalPlan]:
        return list(self._plans.values())[(page - 1) * page_size : page * page_size]

    def _subscription(self, subscription_id: str) -> dict[str, Any]:
        state = self._subscriptions.get(subscription_id)
        if state is None:
            # Unknown simulated subscriptions materialise as ACTIVE so lifecycle
            # actions can be demonstrated against seeded records.
            state = {"status": "ACTIVE", "plan_id": "", "failed": 0}
            self._subscriptions[subscription_id] = state
        return state

    async def get_subscription(self, subscription_id: str) -> PayPalSubscription:
        state = self._subscription(subscription_id)
        return PayPalSubscription(
            id=subscription_id,
            status=state["status"],
            plan_id=state["plan_id"],
            failed_payments=state["failed"],
            raw={"simulated": True},
        )

    async def suspend_subscription(self, subscription_id: str, *, reason: str) -> None:
        self._subscription(subscription_id)["status"] = "SUSPENDED"

    async def activate_subscription(self, subscription_id: str, *, reason: str) -> None:
        state = self._subscription(subscription_id)
        state["status"] = "ACTIVE"
        state["failed"] = 0

    async def cancel_subscription(self, subscription_id: str, *, reason: str) -> None:
        self._subscription(subscription_id)["status"] = "CANCELLED"

    async def revise_subscription(self, subscription_id: str, *, plan_id: str) -> dict[str, Any]:
        state = self._subscription(subscription_id)
        state["plan_id"] = plan_id
        return {"plan_id": plan_id, "simulated": True, "links": []}

    # ------------------------------------------------------------------ webhooks
    async def verify_webhook_signature(self, *, headers: Mapping[str, str], body: bytes) -> bool:
        lowered = {k.lower(): v for k, v in headers.items()}
        if lowered.get("paypal-auth-algo", "") != SIMULATED_ALGO:
            return False
        transmission_id = lowered.get("paypal-transmission-id", "")
        transmission_time = lowered.get("paypal-transmission-time", "")
        signature = lowered.get("paypal-transmission-sig", "")
        if not (transmission_id and transmission_time and signature):
            return False
        expected = hmac.new(
            _webhook_key(),
            f"{transmission_id}|{transmission_time}|".encode() + body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)
