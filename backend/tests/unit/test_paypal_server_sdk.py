"""Orders v2 on the official PayPal Server SDK, tested through the SDK itself.

Follows the APIMatic Context Plugin's testing guidance: a stub ``requests.Session``
is handed to the client as ``http_client_instance``, so the SDK's own serialization,
deserialization and error mapping all run with no network. The stub routes by URL
because an authenticated call sends two requests - the OAuth token POST first,
then the operation - and a single-status stub would fail on the token.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
import requests
from requests.adapters import HTTPAdapter
from requests.models import Response

from app.integrations.paypal.errors import PayPalAPIError, PayPalAuthError
from app.integrations.paypal.models import OrderItem
from app.integrations.paypal.server_sdk import PayPalServerSDKOrders, sdk_environment

TOKEN_PATH = "/v1/oauth2/token"


class StubAdapter(HTTPAdapter):
    """Answers the token path with a token and everything else with ``status``/``body``."""

    def __init__(self, status: int, body: dict, *, token_status: int = 200) -> None:
        super().__init__()
        self.status = status
        self.body = body
        self.token_status = token_status
        self.requests: list[requests.PreparedRequest] = []

    def send(self, request, **kwargs):  # type: ignore[override]
        self.requests.append(request)
        response = Response()
        response.request = request
        response.url = request.url
        if TOKEN_PATH in request.url:
            response.status_code = self.token_status
            payload = (
                {"access_token": "stub-token", "token_type": "Bearer", "expires_in": 32400}
                if self.token_status == 200
                else {"error": "invalid_client", "error_description": "Client Authentication failed"}
            )
        else:
            response.status_code = self.status
            payload = self.body
        response._content = json.dumps(payload).encode()
        response.headers["Content-Type"] = "application/json"
        response.headers["paypal-debug-id"] = "dbg-123"
        return response


def orders_with(adapter: StubAdapter) -> PayPalServerSDKOrders:
    session = requests.Session()
    session.mount("https://", adapter)
    return PayPalServerSDKOrders(
        client_id="id",
        client_secret="secret",
        environment="sandbox",
        max_retries=0,
        http_client_instance=session,
    )


def operation_requests(adapter: StubAdapter) -> list[requests.PreparedRequest]:
    return [r for r in adapter.requests if TOKEN_PATH not in r.url]


CREATED = {
    "id": "5O190127TN364715T",
    "status": "PAYER_ACTION_REQUIRED",
    "links": [{"href": "https://www.sandbox.paypal.com/checkoutnow?token=5O1", "rel": "payer-action", "method": "GET"}],
}


def test_environment_is_mapped_explicitly():
    from paypalserversdk.configuration import Environment

    assert sdk_environment("sandbox") == Environment.SANDBOX
    assert sdk_environment("live") == Environment.PRODUCTION


async def test_create_order_sends_supplier_payee_and_idempotency_key():
    adapter = StubAdapter(201, CREATED)
    orders = orders_with(adapter)

    order = await orders.create_order(
        intent="CAPTURE",
        amount=Decimal("110.00"),
        currency="USD",
        reference_id="PO-00001",
        description="Coffee beans",
        request_id="po-1-pay",
        payee_email="supplier@example.com",
        items=[OrderItem(name="Beans", quantity=10, unit_amount=Decimal("10.00"))],
        return_url="http://localhost:3000/finance/payments",
        cancel_url="http://localhost:3000/finance/payments?cancelled=1",
    )

    assert order.id == "5O190127TN364715T"
    sent = operation_requests(adapter)[0]
    assert sent.url.endswith("/v2/checkout/orders")
    assert sent.headers["PayPal-Request-Id"] == "po-1-pay"
    body = json.loads(sent.body)
    unit = body["purchase_units"][0]
    assert unit["payee"] == {"email_address": "supplier@example.com"}
    assert unit["amount"]["breakdown"]["handling"]["value"] == "10.00"
    context = body["payment_source"]["paypal"]["experience_context"]
    assert context["shipping_preference"] == "NO_SHIPPING"
    assert context["user_action"] == "PAY_NOW"


async def test_capture_reads_the_debug_id():
    adapter = StubAdapter(201, {"id": "5O1", "status": "COMPLETED"})
    order = await orders_with(adapter).capture_order("5O1", request_id="po-1-capture")

    assert order.status == "COMPLETED"
    assert order.debug_id == "dbg-123"
    assert operation_requests(adapter)[0].url.endswith("/v2/checkout/orders/5O1/capture")


async def test_unprocessable_maps_first_issue_into_the_message():
    adapter = StubAdapter(
        422,
        {
            "name": "UNPROCESSABLE_ENTITY",
            "message": "The requested action could not be performed.",
            "debug_id": "dbg-422",
            "details": [{"issue": "CURRENCY_NOT_SUPPORTED", "description": "Currency not supported."}],
        },
    )
    with pytest.raises(PayPalAPIError) as excinfo:
        await orders_with(adapter).get_order("X")

    assert excinfo.value.http_status == 422
    assert excinfo.value.name == "UNPROCESSABLE_ENTITY"
    assert str(excinfo.value).startswith("CURRENCY_NOT_SUPPORTED")


async def test_rejected_credentials_surface_as_auth_error_not_a_disguised_token_message():
    adapter = StubAdapter(200, {}, token_status=401)
    with pytest.raises(PayPalAuthError):
        await orders_with(adapter).get_order("X")
    assert operation_requests(adapter) == []
