"""Typed PayPal objects. Money is ``Decimal`` end to end - never float."""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Currencies PayPal requires without a fractional part.
ZERO_DECIMAL_CURRENCIES = frozenset({"JPY", "HUF", "TWD"})


def money_str(value: Decimal | int | str, currency: str) -> str:
    """PayPal's wire format for an amount: a string, 2 dp (0 dp for JPY/HUF/TWD)."""
    amount = Decimal(str(value))
    exponent = Decimal("1") if currency.upper() in ZERO_DECIMAL_CURRENCIES else Decimal("0.01")
    return str(amount.quantize(exponent, rounding=ROUND_HALF_UP))


def to_decimal(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    return Decimal(str(value))


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class Money(_Model):
    currency_code: str = "USD"
    value: Decimal = Decimal("0")

    @field_validator("value", mode="before")
    @classmethod
    def _decimal(cls, value: Any) -> Decimal:
        return to_decimal(value)

    def wire(self) -> dict[str, str]:
        return {"currency_code": self.currency_code, "value": money_str(self.value, self.currency_code)}


Mode = Literal["LIVE", "SANDBOX", "SIMULATED"]


# --------------------------------------------------------------------------- #
# Transaction Search
# --------------------------------------------------------------------------- #
class PayPalTransaction(_Model):
    transaction_id: str
    event_code: str = ""
    status: str = ""
    initiated_at: datetime
    updated_at: datetime | None = None
    gross: Money
    fee: Money | None = None
    invoice_id: str = ""
    custom_field: str = ""
    payer_email: str = ""
    payer_name: str = ""
    item_count: int = 0
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def net(self) -> Decimal:
        fee = self.fee.value if self.fee else Decimal("0")
        return self.gross.value + fee  # PayPal reports fees as negative amounts

    @property
    def category(self) -> str:
        code = self.event_code or ""
        if code.startswith("T11"):
            return "REFUND"
        if code.startswith("T00"):
            return "PAYMENT"
        if code.startswith("T01"):
            return "FEE"
        if code.startswith("T04") or code.startswith("T05"):
            return "PAYOUT"
        if code.startswith("T02") or code.startswith("T03"):
            return "TRANSFER"
        return "OTHER"


class TransactionSearchPage(_Model):
    transactions: list[PayPalTransaction] = Field(default_factory=list)
    page: int = 1
    total_pages: int = 1
    total_items: int = 0
    last_refreshed_at: datetime | None = None


# --------------------------------------------------------------------------- #
# Orders v2
# --------------------------------------------------------------------------- #
class OrderItem(_Model):
    name: str
    quantity: int = 1
    unit_amount: Decimal
    sku: str = ""
    description: str = ""


class PayPalOrder(_Model):
    id: str
    status: str
    intent: str = "CAPTURE"
    approve_url: str = ""
    capture_ids: list[str] = Field(default_factory=list)
    authorization_ids: list[str] = Field(default_factory=list)
    amount: Money | None = None
    payee_email: str = ""
    debug_id: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_api(cls, body: dict[str, Any], *, debug_id: str = "") -> PayPalOrder:
        approve = ""
        for link in body.get("links", []) or []:
            if link.get("rel") in ("approve", "payer-action"):
                approve = link.get("href", "")
        captures: list[str] = []
        auths: list[str] = []
        amount: Money | None = None
        payee = ""
        for unit in body.get("purchase_units", []) or []:
            if unit.get("amount") and amount is None:
                amount = Money.model_validate(unit["amount"])
            payee = payee or (unit.get("payee") or {}).get("email_address", "")
            payments = unit.get("payments") or {}
            captures += [c.get("id", "") for c in payments.get("captures", []) or []]
            auths += [a.get("id", "") for a in payments.get("authorizations", []) or []]
        return cls(
            id=body.get("id", ""),
            status=body.get("status", ""),
            intent=body.get("intent", "CAPTURE"),
            approve_url=approve,
            capture_ids=[c for c in captures if c],
            authorization_ids=[a for a in auths if a],
            amount=amount,
            payee_email=payee,
            debug_id=debug_id,
            raw=body,
        )


class PayPalCapture(_Model):
    id: str
    status: str
    amount: Money | None = None
    final_capture: bool = True
    debug_id: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Invoicing v2
# --------------------------------------------------------------------------- #
class InvoiceLine(_Model):
    name: str
    quantity: Decimal = Decimal("1")
    unit_amount: Decimal
    description: str = ""


class InvoiceDraft(_Model):
    currency: str = "USD"
    invoice_number: str = ""
    recipient_email: str
    recipient_given_name: str = ""
    recipient_surname: str = ""
    invoicer_business_name: str = ""
    note: str = ""
    terms: str = ""
    due_date: date | None = None
    items: list[InvoiceLine]

    def wire(self) -> dict[str, Any]:
        detail: dict[str, Any] = {"currency_code": self.currency}
        if self.invoice_number:
            detail["invoice_number"] = self.invoice_number
        if self.note:
            detail["note"] = self.note
        if self.terms:
            detail["terms_and_conditions"] = self.terms
        if self.due_date:
            detail["payment_term"] = {"term_type": "DUE_ON_DATE_SPECIFIED", "due_date": self.due_date.isoformat()}
        body: dict[str, Any] = {
            "detail": detail,
            "primary_recipients": [
                {
                    "billing_info": {
                        "email_address": self.recipient_email,
                        "name": {
                            "given_name": self.recipient_given_name or "Customer",
                            "surname": self.recipient_surname or "",
                        },
                    }
                }
            ],
            "items": [
                {
                    "name": line.name[:200],
                    "description": line.description[:1000],
                    "quantity": str(line.quantity),
                    "unit_amount": {"currency_code": self.currency, "value": money_str(line.unit_amount, self.currency)},
                    "unit_of_measure": "QUANTITY",
                }
                for line in self.items
            ],
        }
        if self.invoicer_business_name:
            body["invoicer"] = {"business_name": self.invoicer_business_name}
        return body

    @property
    def total(self) -> Decimal:
        return sum((line.quantity * line.unit_amount for line in self.items), Decimal("0"))


class PayPalInvoice(_Model):
    id: str
    status: str = "DRAFT"
    invoice_number: str = ""
    amount: Money | None = None
    recipient_email: str = ""
    payer_view_url: str = ""
    due_date: date | None = None
    debug_id: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_api(cls, body: dict[str, Any], *, debug_id: str = "") -> PayPalInvoice:
        detail = body.get("detail") or {}
        metadata = detail.get("metadata") or {}
        recipients = body.get("primary_recipients") or []
        email = ""
        if recipients:
            email = ((recipients[0] or {}).get("billing_info") or {}).get("email_address", "")
        due = (detail.get("payment_term") or {}).get("due_date")
        amount = body.get("amount")
        return cls(
            id=body.get("id", ""),
            status=body.get("status", "DRAFT"),
            invoice_number=detail.get("invoice_number", ""),
            amount=Money.model_validate(amount) if amount else None,
            recipient_email=email,
            payer_view_url=metadata.get("recipient_view_url", ""),
            due_date=date.fromisoformat(due) if due else None,
            debug_id=debug_id,
            raw=body,
        )


# --------------------------------------------------------------------------- #
# Payouts
# --------------------------------------------------------------------------- #
class PayoutItem(_Model):
    receiver: str
    amount: Decimal
    currency: str = "USD"
    note: str = ""
    sender_item_id: str = ""
    recipient_type: Literal["EMAIL", "PHONE", "PAYPAL_ID"] = "EMAIL"

    def wire(self) -> dict[str, Any]:
        item: dict[str, Any] = {
            "recipient_type": self.recipient_type,
            "amount": {"value": money_str(self.amount, self.currency), "currency": self.currency},
            "receiver": self.receiver,
        }
        if self.note:
            item["note"] = self.note[:4000]
        if self.sender_item_id:
            item["sender_item_id"] = self.sender_item_id[:63]
        return item


class PayoutBatchRequest(_Model):
    #: PayPal rejects a reused sender_batch_id - this is the idempotency key.
    sender_batch_id: str
    email_subject: str = "You have a reward"
    email_message: str = ""
    items: list[PayoutItem]

    def wire(self) -> dict[str, Any]:
        header: dict[str, Any] = {
            "sender_batch_id": self.sender_batch_id[:256],
            "email_subject": self.email_subject[:255],
        }
        if self.email_message:
            header["email_message"] = self.email_message[:1000]
        return {"sender_batch_header": header, "items": [i.wire() for i in self.items]}

    @property
    def total(self) -> Decimal:
        return sum((i.amount for i in self.items), Decimal("0"))


class PayPalPayoutItemStatus(_Model):
    payout_item_id: str = ""
    transaction_status: str = ""
    receiver: str = ""
    amount: Decimal = Decimal("0")
    sender_item_id: str = ""


class PayPalPayoutBatch(_Model):
    payout_batch_id: str
    batch_status: str
    sender_batch_id: str = ""
    items: list[PayPalPayoutItemStatus] = Field(default_factory=list)
    debug_id: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_api(cls, body: dict[str, Any], *, debug_id: str = "") -> PayPalPayoutBatch:
        header = body.get("batch_header") or {}
        items = []
        for item in body.get("items", []) or []:
            payout_item = item.get("payout_item") or {}
            items.append(
                PayPalPayoutItemStatus(
                    payout_item_id=item.get("payout_item_id", ""),
                    transaction_status=item.get("transaction_status", ""),
                    receiver=payout_item.get("receiver", ""),
                    amount=to_decimal((payout_item.get("amount") or {}).get("value")),
                    sender_item_id=payout_item.get("sender_item_id", ""),
                )
            )
        return cls(
            payout_batch_id=header.get("payout_batch_id", ""),
            batch_status=header.get("batch_status", ""),
            sender_batch_id=(header.get("sender_batch_header") or {}).get("sender_batch_id", ""),
            items=items,
            debug_id=debug_id,
            raw=body,
        )


# --------------------------------------------------------------------------- #
# Subscriptions
# --------------------------------------------------------------------------- #
class PayPalPlan(_Model):
    id: str
    product_id: str = ""
    name: str = ""
    status: str = ""
    amount: Decimal = Decimal("0")
    currency: str = "USD"
    interval_unit: str = "MONTH"
    interval_count: int = 1
    trial_days: int = 0
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_api(cls, body: dict[str, Any]) -> PayPalPlan:
        amount = Decimal("0")
        currency = "USD"
        unit, count, trial = "MONTH", 1, 0
        for cycle in body.get("billing_cycles", []) or []:
            freq = cycle.get("frequency") or {}
            if cycle.get("tenure_type") == "TRIAL":
                if freq.get("interval_unit") == "DAY":
                    trial = int(freq.get("interval_count", 0)) * int(cycle.get("total_cycles", 1) or 1)
                continue
            price = ((cycle.get("pricing_scheme") or {}).get("fixed_price")) or {}
            amount = to_decimal(price.get("value"))
            currency = price.get("currency_code", currency)
            unit = freq.get("interval_unit", unit)
            count = int(freq.get("interval_count", count))
        return cls(
            id=body.get("id", ""),
            product_id=body.get("product_id", ""),
            name=body.get("name", ""),
            status=body.get("status", ""),
            amount=amount,
            currency=currency,
            interval_unit=unit,
            interval_count=count,
            trial_days=trial,
            raw=body,
        )


class PayPalSubscription(_Model):
    id: str
    status: str
    plan_id: str = ""
    subscriber_name: str = ""
    subscriber_email: str = ""
    failed_payments: int = 0
    last_payment_at: datetime | None = None
    last_payment_amount: Decimal | None = None
    next_billing_at: datetime | None = None
    started_at: datetime | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_api(cls, body: dict[str, Any]) -> PayPalSubscription:
        subscriber = body.get("subscriber") or {}
        name = subscriber.get("name") or {}
        billing = body.get("billing_info") or {}
        last = billing.get("last_payment") or {}
        return cls(
            id=body.get("id", ""),
            status=body.get("status", ""),
            plan_id=body.get("plan_id", ""),
            subscriber_name=" ".join(p for p in (name.get("given_name"), name.get("surname")) if p),
            subscriber_email=subscriber.get("email_address", ""),
            failed_payments=int(billing.get("failed_payments_count", 0) or 0),
            last_payment_at=_dt(last.get("time")),
            last_payment_amount=to_decimal((last.get("amount") or {}).get("value")) if last else None,
            next_billing_at=_dt(billing.get("next_billing_time")),
            started_at=_dt(body.get("start_time")),
            raw=body,
        )


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    # PayPal sometimes emits "+0000" without the colon.
    if len(text) > 5 and text[-5] in "+-" and text[-3] != ":":
        text = f"{text[:-2]}:{text[-2:]}"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


parse_paypal_datetime = _dt
