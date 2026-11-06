"""PayPal REST client (sandbox / live).

* OAuth2 client credentials, cached until shortly before expiry, refreshed under a
  lock so concurrent requests never stampede the token endpoint, and invalidated
  and retried once if an API call comes back 401.
* ``PayPal-Request-Id`` on every POST that supports it - PayPal's idempotency key.
  Callers derive it from the business action, so a retried request can never
  move money twice.
* Bounded retries with backoff on 429 / 5xx / transport errors.
* ``paypal-debug-id`` captured into every result and error.
* Secrets never logged: not the client secret, the Basic header, or a token.

Endpoints implemented follow the PayPal REST API reference (developer.paypal.com):
OAuth ``/v1/oauth2/token``; Transaction Search ``/v1/reporting/transactions``;
Orders ``/v2/checkout/orders``; Payments ``/v2/payments/authorizations``;
Invoicing ``/v2/invoicing/invoices``; Payouts ``/v1/payments/payouts``;
Catalog products ``/v1/catalogs/products``; Plans ``/v1/billing/plans``;
Subscriptions ``/v1/billing/subscriptions``; webhook verification
``/v1/notifications/verify-webhook-signature``. See docs/PAYPAL.md.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.paypal.errors import (
    PayPalAPIError,
    PayPalAuthError,
    PayPalNotConfiguredError,
)
from app.integrations.paypal.models import (
    InvoiceDraft,
    Money,
    OrderItem,
    PayoutBatchRequest,
    PayPalCapture,
    PayPalInvoice,
    PayPalOrder,
    PayPalPayoutBatch,
    PayPalPlan,
    PayPalSubscription,
    PayPalTransaction,
    TransactionSearchPage,
    money_str,
    parse_paypal_datetime,
)

log = get_logger(__name__)

#: Transaction Search refuses a window longer than 31 days.
MAX_SEARCH_WINDOW = timedelta(days=31)
#: Re-fetch a token this long before PayPal says it expires.
TOKEN_SAFETY_MARGIN = 60
#: PayPal's own REST hosts. A base URL outside these (a proxy, a mock) keeps Orders on
#: the REST client, because the Server SDK can only target PayPal's environments.
PAYPAL_HOSTS: dict[str, tuple[str, ...]] = {
    "sandbox": ("https://api-m.sandbox.paypal.com", "https://api.sandbox.paypal.com"),
    "live": ("https://api-m.paypal.com", "https://api.paypal.com"),
}

WEBHOOK_HEADERS = (
    "paypal-transmission-id",
    "paypal-transmission-time",
    "paypal-transmission-sig",
    "paypal-cert-url",
    "paypal-auth-algo",
)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def split_windows(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Split ``[start, end]`` into consecutive windows of at most 31 days."""
    if end <= start:
        return []
    windows: list[tuple[datetime, datetime]] = []
    cursor = start
    while cursor < end:
        upper = min(cursor + MAX_SEARCH_WINDOW, end)
        windows.append((cursor, upper))
        cursor = upper
    return windows


def parse_transaction(detail: dict[str, Any]) -> PayPalTransaction:
    info = detail.get("transaction_info") or {}
    payer = detail.get("payer_info") or {}
    name = payer.get("payer_name") or {}
    cart = detail.get("cart_info") or {}
    fee = info.get("fee_amount")
    return PayPalTransaction(
        transaction_id=info.get("transaction_id", ""),
        event_code=info.get("transaction_event_code", ""),
        status=info.get("transaction_status", ""),
        initiated_at=parse_paypal_datetime(info.get("transaction_initiation_date"))
        or datetime.now(tz=UTC),
        updated_at=parse_paypal_datetime(info.get("transaction_updated_date")),
        gross=Money.model_validate(info.get("transaction_amount") or {"currency_code": "USD", "value": "0"}),
        fee=Money.model_validate(fee) if fee else None,
        invoice_id=info.get("invoice_id", "") or "",
        custom_field=info.get("custom_field", "") or "",
        payer_email=payer.get("email_address", "") or "",
        payer_name=name.get("alternate_full_name")
        or " ".join(p for p in (name.get("given_name"), name.get("surname")) if p),
        item_count=len(cart.get("item_details") or []),
        raw=detail,
    )


class PayPalClient:
    """Async PayPal REST client. One instance per process is enough."""

    mode: Literal["LIVE", "SANDBOX"]

    def __init__(
        self,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        base_url: str | None = None,
        webhook_id: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        environment: str | None = None,
    ) -> None:
        self._client_id = client_id if client_id is not None else settings.paypal_client_id
        self._client_secret = (
            client_secret if client_secret is not None else settings.paypal_client_secret
        )
        if not (self._client_id and self._client_secret):
            raise PayPalNotConfiguredError()
        self.base_url = (base_url or settings.paypal_base_url).rstrip("/")
        self.webhook_id = webhook_id if webhook_id is not None else settings.paypal_webhook_id
        env = environment or settings.paypal_environment
        self.mode = "LIVE" if env == "live" else "SANDBOX"
        self._max_retries = settings.paypal_max_retries if max_retries is None else max_retries
        self._sleep = sleep or asyncio.sleep
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout or settings.paypal_timeout_seconds),
            transport=transport,
        )
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._token_lock = asyncio.Lock()
        self._orders_sdk = self._build_orders_sdk(
            env=env,
            custom_base=self.base_url not in PAYPAL_HOSTS.get(env, ()),
            custom_transport=transport is not None,
            timeout=timeout,
        )

    def _build_orders_sdk(
        self, *, env: str, custom_base: bool, custom_transport: bool, timeout: float | None
    ) -> Any:
        """Orders v2 on the official PayPal Server SDK, when it can reach the target.

        A custom base URL or an injected transport means a test or a proxy the SDK
        cannot be pointed at, so those keep the REST path.
        """
        if not settings.paypal_orders_via_sdk or custom_base or custom_transport:
            return None
        try:
            from app.integrations.paypal.server_sdk import PayPalServerSDKOrders
        except ImportError:  # pragma: no cover - package missing from an old image
            log.warning("paypal_server_sdk_unavailable")
            return None
        return PayPalServerSDKOrders(
            client_id=self._client_id,
            client_secret=self._client_secret,
            environment=env,
            timeout=timeout,
            max_retries=self._max_retries,
        )

    @property
    def orders_transport(self) -> str:
        """Which code path moves money: the official SDK or the REST client."""
        return "paypal-server-sdk" if self._orders_sdk is not None else "rest"

    def __repr__(self) -> str:
        return f"PayPalClient(mode={self.mode}, base_url={self.base_url!r}, orders={self.orders_transport})"

    async def aclose(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------ auth
    async def _access_token(self, *, force: bool = False) -> str:
        if not force and self._token and time.monotonic() < self._token_expires_at:
            return self._token
        async with self._token_lock:
            # Another coroutine may have refreshed while we waited.
            if not force and self._token and time.monotonic() < self._token_expires_at:
                return self._token
            try:
                response = await self._http.post(
                    "/v1/oauth2/token",
                    data={"grant_type": "client_credentials"},
                    auth=(self._client_id, self._client_secret),
                    headers={"Accept": "application/json"},
                )
            except httpx.HTTPError as exc:
                raise PayPalAuthError(f"Could not reach PayPal OAuth: {type(exc).__name__}") from None
            if response.status_code != 200:
                body = _json(response)
                raise PayPalAuthError(
                    "PayPal rejected the client credentials.",
                    details={
                        "http_status": response.status_code,
                        "paypal_error": body.get("error", ""),
                        "debug_id": response.headers.get("paypal-debug-id", ""),
                    },
                )
            body = response.json()
            self._token = body["access_token"]
            expires_in = int(body.get("expires_in", 32400))
            self._token_expires_at = time.monotonic() + max(expires_in - TOKEN_SAFETY_MARGIN, 30)
            log.info("paypal_token_acquired", expires_in=expires_in, mode=self.mode)
            return self._token

    async def access_token(self) -> str:
        """A valid bearer token for server-side callers (the MCP bridge).

        Never returned to a browser; the cache and refresh logic is the same one
        every REST call uses.
        """
        return await self._access_token()

    def invalidate_token(self) -> None:
        self._token = None
        self._token_expires_at = 0.0

    # ------------------------------------------------------------------ transport
    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        content: bytes | None = None,
        params: dict[str, Any] | None = None,
        request_id: str | None = None,
        prefer_representation: bool = True,
        expected: tuple[int, ...] = (200, 201, 202, 204),
    ) -> tuple[dict[str, Any], str]:
        """Send one API call. Returns ``(json_body, debug_id)``."""
        attempt = 0
        refreshed = False
        while True:
            token = await self._access_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            }
            if method in ("POST", "PATCH", "PUT"):
                headers["Content-Type"] = "application/json"
            if prefer_representation:
                headers["Prefer"] = "return=representation"
            if request_id:
                headers["PayPal-Request-Id"] = request_id[:108]

            started = time.perf_counter()
            try:
                response = await self._http.request(
                    method,
                    path,
                    json=json_body if content is None else None,
                    content=content,
                    params=params,
                    headers=headers,
                )
            except httpx.TransportError as exc:
                if attempt < self._max_retries:
                    attempt += 1
                    await self._sleep(_backoff(attempt))
                    continue
                raise PayPalAPIError(
                    f"PayPal unreachable: {type(exc).__name__}", http_status=503, name="TRANSPORT_ERROR"
                ) from None

            debug_id = response.headers.get("paypal-debug-id", "")
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            log.info(
                "paypal_api_call",
                method=method,
                path=path.split("?")[0],
                status=response.status_code,
                debug_id=debug_id,
                duration_ms=elapsed,
                mode=self.mode,
            )

            if response.status_code == 401 and not refreshed:
                self.invalidate_token()
                refreshed = True
                continue
            if response.status_code in expected:
                return (_json(response) if response.content else {}), debug_id

            error = _api_error(response, debug_id)
            if error.retryable and attempt < self._max_retries:
                attempt += 1
                retry_after = response.headers.get("retry-after")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else _backoff(attempt)
                await self._sleep(delay)
                continue
            raise error

    # ------------------------------------------------------------------ transaction search
    async def search_transactions(
        self, *, start: datetime, end: datetime, page: int = 1, page_size: int = 100
    ) -> TransactionSearchPage:
        if end - start > MAX_SEARCH_WINDOW:
            raise ValueError("Transaction Search windows are limited to 31 days per call.")
        body, _ = await self._request(
            "GET",
            "/v1/reporting/transactions",
            params={
                "start_date": _iso(start),
                "end_date": _iso(end),
                "fields": "transaction_info,payer_info,cart_info",
                "page_size": max(1, min(page_size, 500)),
                "page": max(1, page),
            },
            prefer_representation=False,
        )
        return TransactionSearchPage(
            transactions=[parse_transaction(d) for d in body.get("transaction_details", []) or []],
            page=int(body.get("page", page) or page),
            total_pages=int(body.get("total_pages", 1) or 1),
            total_items=int(body.get("total_items", 0) or 0),
            last_refreshed_at=parse_paypal_datetime(body.get("last_refreshed_datetime")),
        )

    async def iter_transactions(
        self, *, start: datetime, end: datetime, page_size: int = 100
    ) -> AsyncIterator[PayPalTransaction]:
        for lower, upper in split_windows(start, end):
            page = 1
            while True:
                result = await self.search_transactions(
                    start=lower, end=upper, page=page, page_size=page_size
                )
                for txn in result.transactions:
                    yield txn
                if page >= result.total_pages:
                    break
                page += 1

    # ------------------------------------------------------------------ orders v2
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
        if self._orders_sdk is not None:
            return await self._orders_sdk.create_order(
                intent=intent,
                amount=amount,
                currency=currency,
                reference_id=reference_id,
                description=description,
                request_id=request_id,
                invoice_id=invoice_id,
                custom_id=custom_id,
                payee_email=payee_email,
                items=items,
                return_url=return_url,
                cancel_url=cancel_url,
            )
        unit: dict[str, Any] = {
            "reference_id": reference_id[:256],
            "description": description[:127],
            "amount": {"currency_code": currency, "value": money_str(amount, currency)},
        }
        if items:
            item_total = sum((Decimal(i.quantity) * i.unit_amount for i in items), Decimal("0"))
            unit["amount"]["breakdown"] = {
                "item_total": {"currency_code": currency, "value": money_str(item_total, currency)}
            }
            if item_total != amount:
                # Anything above the item total (shipping, tax) goes in its own bucket so
                # the breakdown always sums - PayPal rejects it otherwise.
                diff = amount - item_total
                if diff > 0:
                    unit["amount"]["breakdown"]["handling"] = {
                        "currency_code": currency,
                        "value": money_str(diff, currency),
                    }
                else:
                    unit["amount"]["breakdown"]["discount"] = {
                        "currency_code": currency,
                        "value": money_str(-diff, currency),
                    }
            unit["items"] = [
                {
                    "name": i.name[:127],
                    "quantity": str(i.quantity),
                    "unit_amount": {"currency_code": currency, "value": money_str(i.unit_amount, currency)},
                    **({"sku": i.sku[:127]} if i.sku else {}),
                    **({"description": i.description[:127]} if i.description else {}),
                }
                for i in items
            ]
        if invoice_id:
            unit["invoice_id"] = invoice_id[:127]
        if custom_id:
            unit["custom_id"] = custom_id[:127]
        if payee_email:
            unit["payee"] = {"email_address": payee_email}

        body: dict[str, Any] = {"intent": intent, "purchase_units": [unit]}
        if return_url or cancel_url:
            body["payment_source"] = {
                "paypal": {
                    "experience_context": {
                        "brand_name": settings.paypal_brand_name[:127],
                        "user_action": "PAY_NOW",
                        "shipping_preference": "NO_SHIPPING",
                        **({"return_url": return_url} if return_url else {}),
                        **({"cancel_url": cancel_url} if cancel_url else {}),
                    }
                }
            }
        data, debug_id = await self._request(
            "POST", "/v2/checkout/orders", json_body=body, request_id=request_id
        )
        return PayPalOrder.from_api(data, debug_id=debug_id)

    async def get_order(self, order_id: str) -> PayPalOrder:
        if self._orders_sdk is not None:
            return await self._orders_sdk.get_order(order_id)
        data, debug_id = await self._request(
            "GET", f"/v2/checkout/orders/{order_id}", prefer_representation=False
        )
        return PayPalOrder.from_api(data, debug_id=debug_id)

    async def capture_order(self, order_id: str, *, request_id: str) -> PayPalOrder:
        if self._orders_sdk is not None:
            return await self._orders_sdk.capture_order(order_id, request_id=request_id)
        data, debug_id = await self._request(
            "POST", f"/v2/checkout/orders/{order_id}/capture", json_body={}, request_id=request_id
        )
        return PayPalOrder.from_api(data, debug_id=debug_id)

    async def authorize_order(self, order_id: str, *, request_id: str) -> PayPalOrder:
        data, debug_id = await self._request(
            "POST", f"/v2/checkout/orders/{order_id}/authorize", json_body={}, request_id=request_id
        )
        return PayPalOrder.from_api(data, debug_id=debug_id)

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
        body: dict[str, Any] = {"final_capture": final_capture}
        if amount is not None and currency:
            body["amount"] = {"currency_code": currency, "value": money_str(amount, currency)}
        if invoice_id:
            body["invoice_id"] = invoice_id[:127]
        data, debug_id = await self._request(
            "POST",
            f"/v2/payments/authorizations/{authorization_id}/capture",
            json_body=body,
            request_id=request_id,
        )
        return PayPalCapture(
            id=data.get("id", ""),
            status=data.get("status", ""),
            amount=Money.model_validate(data["amount"]) if data.get("amount") else None,
            final_capture=bool(data.get("final_capture", final_capture)),
            debug_id=debug_id,
            raw=data,
        )

    async def void_authorization(self, authorization_id: str, *, request_id: str) -> None:
        await self._request(
            "POST",
            f"/v2/payments/authorizations/{authorization_id}/void",
            json_body={},
            request_id=request_id,
        )

    # ------------------------------------------------------------------ invoicing v2
    async def generate_invoice_number(self) -> str:
        data, _ = await self._request(
            "POST", "/v2/invoicing/generate-next-invoice-number", json_body={},
            prefer_representation=False,
        )
        return str(data.get("invoice_number", ""))

    async def create_invoice(self, draft: InvoiceDraft, *, request_id: str) -> PayPalInvoice:
        data, debug_id = await self._request(
            "POST", "/v2/invoicing/invoices", json_body=draft.wire(), request_id=request_id
        )
        if not data.get("id"):
            # Without return=representation PayPal answers with only a self link.
            href = next((link.get("href", "") for link in data.get("links", []) if link.get("rel") == "self"), "")
            invoice_id = href.rstrip("/").rsplit("/", 1)[-1] if href else ""
            return await self.get_invoice(invoice_id)
        return PayPalInvoice.from_api(data, debug_id=debug_id)

    async def get_invoice(self, invoice_id: str) -> PayPalInvoice:
        data, debug_id = await self._request(
            "GET", f"/v2/invoicing/invoices/{invoice_id}", prefer_representation=False
        )
        return PayPalInvoice.from_api(data, debug_id=debug_id)

    async def list_invoices(self, *, page: int = 1, page_size: int = 20) -> list[PayPalInvoice]:
        data, _ = await self._request(
            "GET",
            "/v2/invoicing/invoices",
            params={"page": page, "page_size": min(page_size, 100), "total_required": "true"},
            prefer_representation=False,
        )
        return [PayPalInvoice.from_api(item) for item in data.get("items", []) or []]

    async def send_invoice(
        self,
        invoice_id: str,
        *,
        subject: str | None = None,
        note: str | None = None,
        request_id: str | None = None,
    ) -> PayPalInvoice:
        body: dict[str, Any] = {"send_to_invoicer": True, "send_to_recipient": True}
        if subject:
            body["subject"] = subject[:4000]
        if note:
            body["note"] = note[:4000]
        await self._request(
            "POST",
            f"/v2/invoicing/invoices/{invoice_id}/send",
            json_body=body,
            request_id=request_id,
            prefer_representation=False,
        )
        return await self.get_invoice(invoice_id)

    async def remind_invoice(
        self, invoice_id: str, *, subject: str | None = None, note: str | None = None
    ) -> None:
        body: dict[str, Any] = {"send_to_invoicer": True}
        if subject:
            body["subject"] = subject[:4000]
        if note:
            body["note"] = note[:4000]
        await self._request(
            "POST", f"/v2/invoicing/invoices/{invoice_id}/remind", json_body=body,
            prefer_representation=False,
        )

    async def cancel_invoice(
        self, invoice_id: str, *, subject: str | None = None, note: str | None = None
    ) -> None:
        body: dict[str, Any] = {"send_to_invoicer": True, "send_to_recipient": True}
        if subject:
            body["subject"] = subject[:4000]
        if note:
            body["note"] = note[:4000]
        await self._request(
            "POST", f"/v2/invoicing/invoices/{invoice_id}/cancel", json_body=body,
            prefer_representation=False,
        )

    # ------------------------------------------------------------------ payouts
    async def create_payout(self, batch: PayoutBatchRequest) -> PayPalPayoutBatch:
        data, debug_id = await self._request(
            "POST", "/v1/payments/payouts", json_body=batch.wire(), prefer_representation=False
        )
        return PayPalPayoutBatch.from_api(data, debug_id=debug_id)

    async def get_payout_batch(self, payout_batch_id: str) -> PayPalPayoutBatch:
        data, debug_id = await self._request(
            "GET", f"/v1/payments/payouts/{payout_batch_id}", prefer_representation=False
        )
        return PayPalPayoutBatch.from_api(data, debug_id=debug_id)

    # ------------------------------------------------------------------ subscriptions
    async def create_product(
        self, *, name: str, description: str, product_type: str = "SERVICE", request_id: str
    ) -> dict[str, Any]:
        data, _ = await self._request(
            "POST",
            "/v1/catalogs/products",
            json_body={"name": name[:127], "description": description[:256], "type": product_type},
            request_id=request_id,
        )
        return data

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
        cycles: list[dict[str, Any]] = []
        sequence = 1
        if trial_days > 0:
            cycles.append(
                {
                    "frequency": {"interval_unit": "DAY", "interval_count": trial_days},
                    "tenure_type": "TRIAL",
                    "sequence": sequence,
                    "total_cycles": 1,
                }
            )
            sequence += 1
        cycles.append(
            {
                "frequency": {"interval_unit": interval_unit, "interval_count": interval_count},
                "tenure_type": "REGULAR",
                "sequence": sequence,
                "total_cycles": 0,
                "pricing_scheme": {
                    "fixed_price": {"currency_code": currency, "value": money_str(amount, currency)}
                },
            }
        )
        data, _ = await self._request(
            "POST",
            "/v1/billing/plans",
            json_body={
                "product_id": product_id,
                "name": name[:127],
                "status": "ACTIVE",
                "billing_cycles": cycles,
                "payment_preferences": {
                    "auto_bill_outstanding": True,
                    "setup_fee_failure_action": "CONTINUE",
                    "payment_failure_threshold": 3,
                },
            },
            request_id=request_id,
        )
        return PayPalPlan.from_api(data)

    async def list_plans(self, *, page: int = 1, page_size: int = 20) -> list[PayPalPlan]:
        data, _ = await self._request(
            "GET",
            "/v1/billing/plans",
            params={"page": page, "page_size": min(page_size, 20), "total_required": "true"},
            prefer_representation=True,
        )
        return [PayPalPlan.from_api(p) for p in data.get("plans", []) or []]

    async def get_subscription(self, subscription_id: str) -> PayPalSubscription:
        data, _ = await self._request(
            "GET", f"/v1/billing/subscriptions/{subscription_id}", prefer_representation=False
        )
        return PayPalSubscription.from_api(data)

    async def _subscription_action(self, subscription_id: str, action: str, reason: str) -> None:
        await self._request(
            "POST",
            f"/v1/billing/subscriptions/{subscription_id}/{action}",
            json_body={"reason": reason[:128]},
            prefer_representation=False,
        )

    async def suspend_subscription(self, subscription_id: str, *, reason: str) -> None:
        await self._subscription_action(subscription_id, "suspend", reason)

    async def activate_subscription(self, subscription_id: str, *, reason: str) -> None:
        await self._subscription_action(subscription_id, "activate", reason)

    async def cancel_subscription(self, subscription_id: str, *, reason: str) -> None:
        await self._subscription_action(subscription_id, "cancel", reason)

    async def revise_subscription(self, subscription_id: str, *, plan_id: str) -> dict[str, Any]:
        data, _ = await self._request(
            "POST",
            f"/v1/billing/subscriptions/{subscription_id}/revise",
            json_body={"plan_id": plan_id},
            prefer_representation=False,
        )
        return data

    # ------------------------------------------------------------------ webhooks
    async def verify_webhook_signature(self, *, headers: Mapping[str, str], body: bytes) -> bool:
        """Ask PayPal whether this delivery is genuine. Fails closed.

        The event is embedded byte-for-byte: re-serialising a parsed copy can
        reorder keys or reformat numbers, and PayPal then reports FAILURE for a
        genuine event.
        """
        lowered = {k.lower(): v for k, v in headers.items()}
        if not self.webhook_id:
            log.warning("paypal_webhook_rejected", reason="webhook_id_not_configured")
            return False
        if any(not lowered.get(name) for name in WEBHOOK_HEADERS):
            return False
        if lowered.get("paypal-auth-algo", "").upper().startswith("SIMULATED"):
            # A simulator signature is never acceptable against a real account.
            return False
        try:
            json.loads(body)
        except (ValueError, TypeError):
            return False

        envelope = (
            "{"
            f'"auth_algo":{json.dumps(lowered["paypal-auth-algo"])},'
            f'"cert_url":{json.dumps(lowered["paypal-cert-url"])},'
            f'"transmission_id":{json.dumps(lowered["paypal-transmission-id"])},'
            f'"transmission_sig":{json.dumps(lowered["paypal-transmission-sig"])},'
            f'"transmission_time":{json.dumps(lowered["paypal-transmission-time"])},'
            f'"webhook_id":{json.dumps(self.webhook_id)},'
            '"webhook_event":'
        ).encode() + body + b"}"
        try:
            data, _ = await self._request(
                "POST",
                "/v1/notifications/verify-webhook-signature",
                content=envelope,
                prefer_representation=False,
            )
        except PayPalAPIError as exc:
            log.warning("paypal_webhook_verify_error", status=exc.http_status, debug_id=exc.debug_id)
            return False
        return str(data.get("verification_status", "")).upper() == "SUCCESS"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {"items": data}


def _api_error(response: httpx.Response, debug_id: str) -> PayPalAPIError:
    body = _json(response)
    name = str(body.get("name") or body.get("error") or "")
    message = str(body.get("message") or body.get("error_description") or f"PayPal returned {response.status_code}")
    issues = [i for i in (body.get("details") or []) if isinstance(i, dict)]
    # The top-level message is generic ("failed business validation"); the first
    # issue code says what actually went wrong (e.g. CURRENCY_NOT_SUPPORTED).
    if issues and issues[0].get("issue"):
        first = issues[0]
        message = f"{first['issue']}: {first.get('description') or message}"
    log.warning(
        "paypal_api_error", http_status=response.status_code, name=name,
        issues=[i.get("issue") for i in issues][:5], debug_id=debug_id or body.get("debug_id"),
    )
    return PayPalAPIError(
        message,
        http_status=response.status_code,
        name=name,
        debug_id=debug_id or str(body.get("debug_id") or ""),
        issues=issues,
    )


def _backoff(attempt: int) -> float:
    return min(0.5 * (2 ** (attempt - 1)), 8.0)


__all__ = [
    "MAX_SEARCH_WINDOW",
    "WEBHOOK_HEADERS",
    "PayPalClient",
    "parse_transaction",
    "split_windows",
]
