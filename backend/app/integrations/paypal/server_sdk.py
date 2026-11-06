"""Orders v2 through PayPal's official, APIMatic-generated Server SDK.

The money-moving step of procure-to-pay (create the supplier order, read it back,
capture it after buyer approval) runs on ``paypal-server-sdk`` rather than a
hand-rolled HTTP call. The integration was written against the APIMatic Context
Plugin for this SDK, and the choices below follow its guidance:

* **One long-lived client.** ``PaypalServersdkClient`` is built once and reused, so
  the OAuth token and the connection pool survive between calls.
* **Environment chosen explicitly.** ``Environment.SANDBOX`` / ``PRODUCTION`` is
  mapped from ``PAYPAL_ENVIRONMENT``; nothing relies on the SDK's default.
* **Auth failures are not disguised.** The SDK's automatic token fetch swallows the
  provider error and raises a fixed "token is undefined or expired" message. An
  ``o_auth_token_provider`` that calls ``fetch_token()`` itself lets the real 401
  (``OAuthProviderException``) through instead.
* **Retries are deliberate.** The generated default retries only GET/PUT. Orders
  create and capture carry a ``PayPal-Request-Id`` idempotency key, so POST is safe
  to retry on 408/429/5xx too, and a retry can never move money twice.
* **Shape-2 operations.** ``create_order`` / ``get_order`` / ``capture_order`` take a
  single options dict, and every response comes back in an ``ApiResponse``
  envelope.
* **Errors are mapped, not leaked.** Typed ``ErrorException`` fields are read with
  ``getattr`` (they are unassigned when a gateway returns HTML), a transport
  ``ConnectionError`` is reported as "outcome unknown", and an
  ``AuthValidationException``, which is *not* an ``ApiException``, gets its own
  branch.

The SDK uses the synchronous ``requests`` transport, so each call runs in a worker
thread to keep the event loop free. The secret, the Basic header and the bearer
token are never logged.
"""

from __future__ import annotations

import asyncio
import json
import time
from decimal import Decimal
from typing import Any, Literal

import requests
from apimatic_core.exceptions.auth_validation_exception import AuthValidationException
from paypalserversdk.configuration import Environment
from paypalserversdk.exceptions.api_exception import ApiException
from paypalserversdk.exceptions.error_exception import ErrorException
from paypalserversdk.exceptions.o_auth_provider_exception import OAuthProviderException
from paypalserversdk.http.auth.o_auth_2 import ClientCredentialsAuthCredentials
from paypalserversdk.models.amount_breakdown import AmountBreakdown
from paypalserversdk.models.amount_with_breakdown import AmountWithBreakdown
from paypalserversdk.models.checkout_payment_intent import CheckoutPaymentIntent
from paypalserversdk.models.item import Item
from paypalserversdk.models.money import Money as SdkMoney
from paypalserversdk.models.order_request import OrderRequest
from paypalserversdk.models.payee_base import PayeeBase
from paypalserversdk.models.payment_source import PaymentSource
from paypalserversdk.models.paypal_experience_user_action import PaypalExperienceUserAction
from paypalserversdk.models.paypal_wallet import PaypalWallet
from paypalserversdk.models.paypal_wallet_context_shipping_preference import (
    PaypalWalletContextShippingPreference,
)
from paypalserversdk.models.paypal_wallet_experience_context import (
    PaypalWalletExperienceContext,
)
from paypalserversdk.models.purchase_unit_request import PurchaseUnitRequest
from paypalserversdk.paypal_serversdk_client import PaypalServersdkClient

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.paypal.errors import PayPalAPIError, PayPalAuthError
from app.integrations.paypal.models import OrderItem, PayPalOrder, money_str

log = get_logger(__name__)

#: Statuses worth a second attempt. Every write below carries PayPal-Request-Id.
RETRY_STATUSES = [408, 429, 500, 502, 503, 504]
#: Refresh the cached token this many seconds before PayPal says it expires.
TOKEN_CLOCK_SKEW = 60
SDK_NAME = "paypal-server-sdk"


def sdk_environment(environment: str) -> int:
    """Map ``PAYPAL_ENVIRONMENT`` onto the SDK enum. Never fall back to a default."""
    return Environment.PRODUCTION if environment == "live" else Environment.SANDBOX


def _fetch_token(_last_token: Any, auth_manager: Any) -> Any:
    """Token provider: fetch directly so a rejected credential raises its real 401."""
    return auth_manager.fetch_token()


def build_sdk_client(
    *,
    client_id: str,
    client_secret: str,
    environment: str,
    timeout: float,
    max_retries: int,
    http_client_instance: Any = None,
) -> PaypalServersdkClient:
    kwargs: dict[str, Any] = {}
    if http_client_instance is not None:
        # The test seam from the Context Plugin: a stub requests.Session, no network.
        kwargs["http_client_instance"] = http_client_instance
    return PaypalServersdkClient(
        client_credentials_auth_credentials=ClientCredentialsAuthCredentials(
            o_auth_client_id=client_id,
            o_auth_client_secret=client_secret,
            o_auth_token_provider=_fetch_token,
            o_auth_clock_skew=TOKEN_CLOCK_SKEW,
        ),
        environment=sdk_environment(environment),
        timeout=timeout,
        max_retries=max_retries,
        retry_statuses=RETRY_STATUSES,
        retry_methods=["GET", "POST"],
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# request models
# --------------------------------------------------------------------------- #
def _money(value: Decimal, currency: str) -> SdkMoney:
    return SdkMoney(currency_code=currency, value=money_str(value, currency))


def build_order_request(
    *,
    intent: Literal["CAPTURE", "AUTHORIZE"],
    amount: Decimal,
    currency: str,
    reference_id: str,
    description: str,
    invoice_id: str | None = None,
    custom_id: str | None = None,
    payee_email: str | None = None,
    items: list[OrderItem] | None = None,
    return_url: str | None = None,
    cancel_url: str | None = None,
    brand_name: str | None = None,
) -> OrderRequest:
    """The same order the REST client used to send, as typed SDK models."""
    breakdown: AmountBreakdown | None = None
    sdk_items: list[Item] | None = None
    if items:
        item_total = sum((Decimal(i.quantity) * i.unit_amount for i in items), Decimal("0"))
        parts: dict[str, SdkMoney] = {"item_total": _money(item_total, currency)}
        # Anything above the item total (shipping, tax) sits in its own bucket so the
        # breakdown always sums; PayPal rejects the order otherwise.
        diff = amount - item_total
        if diff > 0:
            parts["handling"] = _money(diff, currency)
        elif diff < 0:
            parts["discount"] = _money(-diff, currency)
        breakdown = AmountBreakdown(**parts)
        sdk_items = []
        for i in items:
            extra: dict[str, Any] = {}
            if i.sku:
                extra["sku"] = i.sku[:127]
            if i.description:
                extra["description"] = i.description[:127]
            sdk_items.append(
                Item(
                    name=i.name[:127],
                    unit_amount=_money(i.unit_amount, currency),
                    quantity=str(i.quantity),
                    **extra,
                )
            )

    amount_kwargs: dict[str, Any] = {"currency_code": currency, "value": money_str(amount, currency)}
    if breakdown is not None:
        amount_kwargs["breakdown"] = breakdown

    unit_kwargs: dict[str, Any] = {
        "amount": AmountWithBreakdown(**amount_kwargs),
        "reference_id": reference_id[:256],
        "description": description[:127],
    }
    if sdk_items:
        unit_kwargs["items"] = sdk_items
    if invoice_id:
        unit_kwargs["invoice_id"] = invoice_id[:127]
    if custom_id:
        unit_kwargs["custom_id"] = custom_id[:127]
    if payee_email:
        # The supplier is the payee: the money lands in their PayPal account.
        unit_kwargs["payee"] = PayeeBase(email_address=payee_email)

    order_kwargs: dict[str, Any] = {
        "intent": CheckoutPaymentIntent.CAPTURE if intent == "CAPTURE" else CheckoutPaymentIntent.AUTHORIZE,
        "purchase_units": [PurchaseUnitRequest(**unit_kwargs)],
    }
    if return_url or cancel_url:
        # The generated defaults are GET_FROM_FILE / CONTINUE; a B2B supplier
        # payment needs no shipping address and should finish on "Pay Now".
        context_kwargs: dict[str, Any] = {
            "brand_name": (brand_name or settings.paypal_brand_name)[:127],
            "shipping_preference": PaypalWalletContextShippingPreference.NO_SHIPPING,
            "user_action": PaypalExperienceUserAction.PAY_NOW,
        }
        if return_url:
            context_kwargs["return_url"] = return_url
        if cancel_url:
            context_kwargs["cancel_url"] = cancel_url
        order_kwargs["payment_source"] = PaymentSource(
            paypal=PaypalWallet(experience_context=PaypalWalletExperienceContext(**context_kwargs))
        )
    return OrderRequest(**order_kwargs)


# --------------------------------------------------------------------------- #
# response / error mapping
# --------------------------------------------------------------------------- #
def _header(headers: Any, name: str) -> str:
    if not headers:
        return ""
    try:
        value = headers.get(name)
        if value:
            return str(value)
    except AttributeError:
        return ""
    lowered = name.lower()
    for key, value in dict(headers).items():
        if str(key).lower() == lowered:
            return str(value)
    return ""


def _json_text(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def map_api_exception(exc: ApiException) -> PayPalAPIError:
    """Translate an SDK ``ApiException`` (typed or base) into the app's error."""
    status = int(getattr(exc, "response_code", 0) or 0)
    response = getattr(exc, "response", None)
    body = _json_text(getattr(response, "text", None))
    debug_id = (
        getattr(exc, "debug_id", None)
        or body.get("debug_id")
        or _header(getattr(response, "headers", None), "paypal-debug-id")
        or ""
    )
    name = str(getattr(exc, "name", None) or body.get("name") or body.get("error") or "")
    message = str(
        getattr(exc, "message", None)
        or body.get("message")
        or body.get("error_description")
        or getattr(exc, "reason", None)
        or f"PayPal returned {status}"
    )
    issues = [i for i in (body.get("details") or []) if isinstance(i, dict)]
    if issues and issues[0].get("issue"):
        first = issues[0]
        message = f"{first['issue']}: {first.get('description') or message}"
    log.warning(
        "paypal_api_error",
        http_status=status,
        name=name,
        issues=[i.get("issue") for i in issues][:5],
        debug_id=debug_id,
        via=SDK_NAME,
    )
    return PayPalAPIError(message, http_status=status or 502, name=name, debug_id=str(debug_id), issues=issues)


# --------------------------------------------------------------------------- #
# the orders gateway
# --------------------------------------------------------------------------- #
class PayPalServerSDKOrders:
    """Orders v2 (create, get, capture) on the official PayPal Server SDK."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        environment: str,
        timeout: float | None = None,
        max_retries: int | None = None,
        http_client_instance: Any = None,
    ) -> None:
        self._build_kwargs: dict[str, Any] = {
            "client_id": client_id,
            "client_secret": client_secret,
            "environment": environment,
            "timeout": timeout or settings.paypal_timeout_seconds,
            "max_retries": settings.paypal_max_retries if max_retries is None else max_retries,
            "http_client_instance": http_client_instance,
        }
        self.mode = "LIVE" if environment == "live" else "SANDBOX"
        self._client = build_sdk_client(**self._build_kwargs)

    def __repr__(self) -> str:
        return f"PayPalServerSDKOrders(mode={self.mode})"

    def _rebuild(self) -> None:
        """Fresh client, fresh token: used once when PayPal says a token went stale."""
        self._client = build_sdk_client(**self._build_kwargs)

    async def _call(self, operation: str, options: dict[str, Any]) -> PayPalOrder:
        refreshed = False
        while True:
            started = time.perf_counter()
            try:
                result = await asyncio.to_thread(getattr(self._client.orders, operation), options)
            except OAuthProviderException as exc:
                raise PayPalAuthError(
                    "PayPal rejected the client credentials.",
                    details={
                        "http_status": getattr(exc, "response_code", 0),
                        "paypal_error": getattr(exc, "error", None) or "",
                        "via": SDK_NAME,
                    },
                ) from None
            except ErrorException as exc:
                if getattr(exc, "response_code", 0) == 401 and not refreshed:
                    refreshed = True
                    self._rebuild()
                    continue
                raise map_api_exception(exc) from None
            except ApiException as exc:
                raise map_api_exception(exc) from None
            except AuthValidationException:
                # Raised before the request leaves: nothing was created or captured.
                raise PayPalAuthError(
                    "PayPal credentials could not be validated.", details={"via": SDK_NAME}
                ) from None
            except requests.exceptions.RequestException as exc:
                # A refused connection and a read timeout look the same here, so the
                # outcome of a write is unknown. Retrying with the same
                # PayPal-Request-Id is safe: PayPal answers with the original result.
                raise PayPalAPIError(
                    f"PayPal unreachable ({type(exc).__name__}); outcome unknown, "
                    "retry with the same PayPal-Request-Id is safe.",
                    http_status=503,
                    name="TRANSPORT_ERROR",
                ) from None

            debug_id = _header(result.headers, "paypal-debug-id")
            log.info(
                "paypal_api_call",
                method=operation,
                status=result.status_code,
                debug_id=debug_id,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
                mode=self.mode,
                via=SDK_NAME,
            )
            return PayPalOrder.from_api(_json_text(result.text), debug_id=debug_id)

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
        body = build_order_request(
            intent=intent,
            amount=amount,
            currency=currency,
            reference_id=reference_id,
            description=description,
            invoice_id=invoice_id,
            custom_id=custom_id,
            payee_email=payee_email,
            items=items,
            return_url=return_url,
            cancel_url=cancel_url,
        )
        return await self._call(
            "create_order",
            {"body": body, "paypal_request_id": request_id[:108], "prefer": "return=representation"},
        )

    async def get_order(self, order_id: str) -> PayPalOrder:
        return await self._call("get_order", {"id": order_id})

    async def capture_order(self, order_id: str, *, request_id: str) -> PayPalOrder:
        return await self._call(
            "capture_order",
            {"id": order_id, "paypal_request_id": request_id[:108], "prefer": "return=representation"},
        )


__all__ = [
    "SDK_NAME",
    "PayPalServerSDKOrders",
    "build_order_request",
    "build_sdk_client",
    "map_api_exception",
    "sdk_environment",
]
