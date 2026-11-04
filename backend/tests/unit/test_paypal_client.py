"""PayPal REST client and simulator, against a mocked transport (no network)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from app.integrations.paypal import (
    InvoiceDraft,
    InvoiceLine,
    PayoutBatchRequest,
    PayoutItem,
    PayPalAPIError,
    PayPalClient,
    SimulatedPayPal,
    sign_simulated_webhook,
    split_windows,
)
from app.integrations.paypal.errors import PayPalNotConfiguredError

SECRET = "super-secret-client-secret"


async def _no_sleep(_: float) -> None:
    return None


class Recorder:
    """A tiny PayPal fake: scripted responses per (method, path), every request kept."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.routes: dict[tuple[str, str], list[httpx.Response]] = {}
        self.token_calls = 0

    def add(self, method: str, path: str, *responses: httpx.Response) -> None:
        self.routes.setdefault((method, path), []).extend(responses)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/v1/oauth2/token":
            self.token_calls += 1
            return httpx.Response(200, json={"access_token": f"tok-{self.token_calls}", "expires_in": 32400})
        queue = self.routes.get((request.method, request.url.path))
        if not queue:
            return httpx.Response(404, json={"name": "RESOURCE_NOT_FOUND", "message": "nope"},
                                  headers={"paypal-debug-id": "dbg-404"})
        return queue.pop(0) if len(queue) > 1 else queue[0]


def client(recorder: Recorder, **kw) -> PayPalClient:
    return PayPalClient(client_id="client-id", client_secret=SECRET, base_url="https://api-m.sandbox.paypal.com",
                        webhook_id=kw.pop("webhook_id", "WH-1"), transport=httpx.MockTransport(recorder),
                        sleep=_no_sleep, max_retries=kw.pop("max_retries", 2), environment="sandbox")


ORDER = {"id": "5O190127TN364715T", "status": "PAYER_ACTION_REQUIRED", "intent": "CAPTURE",
         "links": [{"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=5O19"}],
         "purchase_units": [{"amount": {"currency_code": "USD", "value": "1455.00"},
                             "payee": {"email_address": "supplier@example.com"}}]}


class TestAuth:
    def test_missing_credentials_are_refused(self):
        with pytest.raises(PayPalNotConfiguredError):
            PayPalClient(client_id="", client_secret="")

    async def test_the_token_is_cached(self):
        r = Recorder()
        r.add("GET", "/v2/checkout/orders/X", httpx.Response(200, json=ORDER))
        c = client(r)
        await c.get_order("X")
        await c.get_order("X")
        assert r.token_calls == 1
        auth = r.requests[0].headers["authorization"]
        assert auth.startswith("Basic ")

    async def test_a_401_refreshes_the_token_once(self):
        r = Recorder()
        r.add("GET", "/v2/checkout/orders/X", httpx.Response(401, json={"name": "AUTHENTICATION_FAILURE"}),
              httpx.Response(200, json=ORDER))
        order = await client(r).get_order("X")
        assert order.id == ORDER["id"]
        assert r.token_calls == 2

    async def test_secrets_never_appear_in_errors(self):
        r = Recorder()
        r.add("GET", "/v2/checkout/orders/X", httpx.Response(400, json={"name": "INVALID_REQUEST", "message": "bad"},
                                                             headers={"paypal-debug-id": "dbg-1"}))
        with pytest.raises(PayPalAPIError) as info:
            await client(r).get_order("X")
        rendered = f"{info.value} {info.value.details} {info.value!r}"
        assert SECRET not in rendered and "tok-" not in rendered
        assert info.value.debug_id == "dbg-1"


class TestRetries:
    async def test_a_503_is_retried(self):
        r = Recorder()
        r.add("GET", "/v2/checkout/orders/X", httpx.Response(503, json={}), httpx.Response(200, json=ORDER))
        assert (await client(r).get_order("X")).status == "PAYER_ACTION_REQUIRED"

    async def test_retries_are_bounded(self):
        r = Recorder()
        r.add("GET", "/v2/checkout/orders/X", httpx.Response(503, json={"name": "SERVICE_UNAVAILABLE"},
                                                             headers={"paypal-debug-id": "dbg-503"}))
        with pytest.raises(PayPalAPIError) as info:
            await client(r, max_retries=1).get_order("X")
        assert info.value.http_status == 503 and info.value.debug_id == "dbg-503"


class TestOrders:
    async def test_create_order_sends_an_idempotency_key_and_payee(self):
        r = Recorder()
        r.add("POST", "/v2/checkout/orders", httpx.Response(201, json=ORDER))
        order = await client(r).create_order(intent="CAPTURE", amount=Decimal("1455"), currency="USD",
                                             reference_id="PO-00001", description="Beans", request_id="idem-1",
                                             payee_email="supplier@example.com", return_url="https://x/return")
        sent = r.requests[-1]
        body = json.loads(sent.content)
        assert sent.headers["paypal-request-id"] == "idem-1"
        assert body["purchase_units"][0]["amount"]["value"] == "1455.00"
        assert body["purchase_units"][0]["payee"]["email_address"] == "supplier@example.com"
        assert order.approve_url.startswith("https://www.sandbox.paypal.com")

    async def test_capture_extracts_the_capture_id(self):
        r = Recorder()
        captured = {**ORDER, "status": "COMPLETED",
                    "purchase_units": [{"payments": {"captures": [{"id": "CAP-1", "status": "COMPLETED"}]}}]}
        r.add("POST", "/v2/checkout/orders/X/capture", httpx.Response(201, json=captured))
        order = await client(r).capture_order("X", request_id="idem-cap")
        assert order.capture_ids == ["CAP-1"]


class TestTransactionSearch:
    def test_windows_never_exceed_31_days(self):
        start = datetime(2026, 1, 1, tzinfo=UTC)
        windows = split_windows(start, start + timedelta(days=90))
        assert len(windows) == 3
        assert all(upper - lower <= timedelta(days=31) for lower, upper in windows)

    async def test_a_window_over_31_days_is_rejected(self):
        with pytest.raises(ValueError):
            await client(Recorder()).search_transactions(
                start=datetime(2026, 1, 1, tzinfo=UTC), end=datetime(2026, 3, 1, tzinfo=UTC)
            )

    async def test_iteration_pages_through_every_window(self):
        r = Recorder()
        page = {"transaction_details": [{"transaction_info": {
            "transaction_id": "T1", "transaction_event_code": "T0006", "transaction_status": "S",
            "transaction_initiation_date": "2026-01-02T10:00:00+0000",
            "transaction_amount": {"currency_code": "USD", "value": "18.00"}}}],
            "page": 1, "total_pages": 1, "total_items": 1}
        r.add("GET", "/v1/reporting/transactions", httpx.Response(200, json=page))
        start = datetime(2026, 1, 1, tzinfo=UTC)
        rows = [t async for t in client(r).iter_transactions(start=start, end=start + timedelta(days=45))]
        assert len(rows) == 2  # one per window
        assert rows[0].gross.value == Decimal("18.00")
        assert rows[0].category == "PAYMENT"


class TestInvoicesAndPayouts:
    async def test_invoice_wire_format(self):
        draft = InvoiceDraft(recipient_email="a@b.com", items=[InvoiceLine(name="Beans", quantity=Decimal("2"),
                                                                          unit_amount=Decimal("18"))])
        wire = draft.wire()
        assert wire["items"][0]["unit_amount"]["value"] == "18.00"
        assert draft.total == Decimal("36")

    async def test_payout_uses_the_sender_batch_id(self):
        r = Recorder()
        r.add("POST", "/v1/payments/payouts", httpx.Response(201, json={
            "batch_header": {"payout_batch_id": "PB-1", "batch_status": "PENDING",
                             "sender_batch_header": {"sender_batch_id": "batch-1"}}}))
        batch = await client(r).create_payout(PayoutBatchRequest(
            sender_batch_id="batch-1", items=[PayoutItem(receiver="a@b.com", amount=Decimal("5"))]))
        body = json.loads(r.requests[-1].content)
        assert body["sender_batch_header"]["sender_batch_id"] == "batch-1"
        assert body["items"][0]["amount"] == {"value": "5.00", "currency": "USD"}
        assert batch.payout_batch_id == "PB-1"


class TestWebhookVerification:
    HEADERS = {"paypal-transmission-id": "t1", "paypal-transmission-time": "2026-01-01T00:00:00Z",
               "paypal-transmission-sig": "sig", "paypal-cert-url": "https://api.paypal.com/cert",
               "paypal-auth-algo": "SHA256withRSA"}
    BODY = b'{"id":"WH-EVT-1","event_type":"PAYMENT.CAPTURE.COMPLETED","resource":{"id":"CAP-1"}}'

    async def test_success_is_trusted(self):
        r = Recorder()
        r.add("POST", "/v1/notifications/verify-webhook-signature", httpx.Response(200, json={"verification_status": "SUCCESS"}))
        assert await client(r).verify_webhook_signature(headers=self.HEADERS, body=self.BODY) is True
        sent = r.requests[-1].content
        assert self.BODY in sent  # embedded byte-for-byte

    async def test_failure_is_not(self):
        r = Recorder()
        r.add("POST", "/v1/notifications/verify-webhook-signature", httpx.Response(200, json={"verification_status": "FAILURE"}))
        assert await client(r).verify_webhook_signature(headers=self.HEADERS, body=self.BODY) is False

    async def test_no_webhook_id_fails_closed(self):
        assert await client(Recorder(), webhook_id="").verify_webhook_signature(headers=self.HEADERS, body=self.BODY) is False

    async def test_a_simulator_signature_is_never_accepted_by_the_real_client(self):
        headers = sign_simulated_webhook(self.BODY)
        assert await client(Recorder()).verify_webhook_signature(headers=headers, body=self.BODY) is False


class TestSimulator:
    async def test_identifiers_are_visibly_simulated_and_idempotent(self):
        sim = SimulatedPayPal()
        a = await sim.create_order(intent="CAPTURE", amount=Decimal("10"), currency="USD", reference_id="r",
                                   description="d", request_id="same")
        b = await sim.create_order(intent="CAPTURE", amount=Decimal("10"), currency="USD", reference_id="r",
                                   description="d", request_id="same")
        assert a.id == b.id and a.id.startswith("SIM-ORDER-")
        captured = await sim.capture_order(a.id, request_id="cap")
        assert captured.capture_ids[0].startswith("SIM-CAPTURE-")

    async def test_authorize_then_capture_then_no_void(self):
        sim = SimulatedPayPal()
        order = await sim.create_order(intent="AUTHORIZE", amount=Decimal("50"), currency="USD", reference_id="r",
                                       description="d", request_id="auth")
        authorized = await sim.authorize_order(order.id, request_id="a")
        capture = await sim.capture_authorization(authorized.authorization_ids[0], request_id="c")
        assert capture.status == "COMPLETED"
        with pytest.raises(PayPalAPIError):
            await sim.void_authorization(authorized.authorization_ids[0], request_id="v")

    async def test_transactions_are_deterministic(self):
        start = datetime(2026, 2, 1, tzinfo=UTC)
        one = await SimulatedPayPal().search_transactions(start=start, end=start + timedelta(days=7))
        two = await SimulatedPayPal().search_transactions(start=start, end=start + timedelta(days=7))
        assert [t.transaction_id for t in one.transactions] == [t.transaction_id for t in two.transactions]
        assert all(t.transaction_id.startswith("SIM-TXN-") for t in one.transactions)

    async def test_simulated_webhooks_verify_only_with_the_right_signature(self):
        sim = SimulatedPayPal()
        body = b'{"id":"x"}'
        headers = sign_simulated_webhook(body)
        assert await sim.verify_webhook_signature(headers=headers, body=body) is True
        assert await sim.verify_webhook_signature(headers=headers, body=b'{"id":"y"}') is False
        assert await sim.verify_webhook_signature(headers={}, body=body) is False
