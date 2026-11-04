"""Sponsor adapters against mocked HTTP: the real request-building and parsing code
runs; only the network is replaced. No keys, no Docker."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest

from app.core.config import settings
from app.integrations.paypal import set_paypal_gateway
from app.integrations.paypal.mcp import (
    MCPReadOnlyViolation,
    PayPalMCPClient,
    assert_read_only,
    is_read_only,
)
from app.integrations.sponsors import SponsorError, SponsorRequestError, integration_status
from app.integrations.sponsors.channel3 import Channel3Client, parse_products, reference_search
from app.integrations.sponsors.elastic import ElasticClient
from app.integrations.sponsors.kernel import KernelClient, validate_public_https_url
from app.integrations.sponsors.zapier import ZapierClient, sign, verify
from app.services.integrations.evidence import allowed_kinds, keyword_search
from app.services.paypal.sync import CLV_ASSUMED_LIFESPAN_YEARS, _purchase_behaviour


def mock(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


# --------------------------------------------------------------------------- #
# Channel3
# --------------------------------------------------------------------------- #
class TestChannel3:
    async def test_live_search_sends_the_documented_request(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"products": [
                {"title": "Single Origin Beans 12oz", "price": {"price": 18.5, "currency": "USD"},
                 "brands": [{"name": "Ridge"}], "availability": "InStock", "url": "https://x.test/a"},
                {"title": "Espresso Blend", "price": 16, "currency": "USD"},
                {"title": "No price here"},
                "garbage",
            ]})

        client = Channel3Client(api_key="k-test", base_url="https://api.trychannel3.com", transport=mock(handler))
        result = await client.search("coffee beans", limit=5)

        assert result.mode == "LIVE"
        request = seen[0]
        assert request.method == "POST" and request.url.path == "/v1/search"
        assert request.headers["x-api-key"] == "k-test"
        assert json.loads(request.content)["query"] == "coffee beans"
        assert [o.price for o in result.offers] == [Decimal("18.50"), Decimal("16.00")]
        assert result.offers[0].brand == "Ridge" and result.offers[0].in_stock is True
        assert result.skipped == 2  # unparseable results are counted, never invented

    def test_parser_accepts_envelopes_and_never_floats(self):
        offers, skipped = parse_products([{"name": "A", "offers": [{"price": {"amount": "3.999", "currency": "usd"}}]}])
        assert offers[0].price == Decimal("4.00") and offers[0].currency == "USD" and skipped == 0
        assert parse_products({"nope": 1}) == ([], 0)

    async def test_without_a_key_it_is_labelled_simulated_and_deterministic(self):
        client = Channel3Client(api_key="")
        a, b = await client.search("Premium Coffee Beans"), await client.search("Premium Coffee Beans")
        assert a.mode == "SIMULATED" and "not live market data" in a.note
        assert [o.price for o in a.offers] == [o.price for o in b.offers]
        assert reference_search("coffee", 3).offers[0].price > 0

    async def test_http_errors_never_echo_the_key(self):
        client = Channel3Client(api_key="super-secret-key",
                                transport=mock(lambda r: httpx.Response(401, json={"message": "bad key"})))
        with pytest.raises(SponsorError) as raised:
            await client.search("beans")
        assert "401" in str(raised.value) and "super-secret-key" not in str(raised.value)
        assert "super-secret-key" not in repr(client)

    async def test_an_empty_query_is_a_request_error(self):
        with pytest.raises(SponsorRequestError):
            await Channel3Client(api_key="").search("   ")


# --------------------------------------------------------------------------- #
# Kernel
# --------------------------------------------------------------------------- #
class TestKernel:
    @pytest.mark.parametrize("url", [
        "http://supplier.example.com/catalog",      # not https
        "https://127.0.0.1/admin",                  # raw IP
        "https://localhost/x",                      # no public hostname
        "https://intranet.internal/x",
        "https://user:pw@supplier.example.com/",    # embedded credentials
        "ftp://supplier.example.com/",
    ])
    def test_unsafe_urls_are_refused(self, url):
        with pytest.raises(SponsorRequestError):
            validate_public_https_url(url)

    def test_a_public_https_url_is_accepted(self):
        assert validate_public_https_url("https://supplier.example.com/catalog?x=1").startswith("https://")

    async def test_live_session_uses_bearer_auth_and_documented_fields(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            if request.method == "POST":
                return httpx.Response(200, json={"session_id": "sess_1", "browser_live_view_url": "https://live.example/v/1",
                                                 "cdp_ws_url": "wss://cdp.example/1"})
            return httpx.Response(204)

        client = KernelClient(api_key="kernel-key", base_url="https://api.onkernel.com", transport=mock(handler))
        session = await client.open_session("https://supplier.example.com/beans", timeout_seconds=1)
        assert session.mode == "LIVE" and session.live_view_url.startswith("https://live.example")
        assert session.timeout_seconds == 10  # clamped to Kernel's documented minimum
        post = seen[0]
        assert post.url.path == "/browsers" and post.headers["authorization"] == "Bearer kernel-key"
        assert json.loads(post.content)["start_url"] == "https://supplier.example.com/beans"
        assert "cdp_ws_url" not in session.as_dict()  # the CDP socket is never sent to the browser UI
        assert await client.close_session(session) is True
        assert seen[1].method == "DELETE" and seen[1].url.path == "/browsers/sess_1"

    async def test_without_a_key_no_browser_is_started(self):
        session = await KernelClient(api_key="").open_session("https://supplier.example.com/")
        assert session.mode == "SIMULATED" and session.session_id.startswith("SIM-KERNEL-")


# --------------------------------------------------------------------------- #
# Elasticsearch
# --------------------------------------------------------------------------- #
class TestElastic:
    async def test_bulk_upserts_are_keyed_so_reindexing_never_duplicates(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"items": [{"index": {"status": 201}}, {"index": {"error": {"type": "x"}}}]})

        merchant = uuid.uuid4()
        docs = [{"merchant_id": str(merchant), "kind": "audit", "ref": "1", "title": "t", "body": "b"},
                {"merchant_id": str(merchant), "kind": "audit", "ref": "2", "title": "t", "body": "b"}]
        client = ElasticClient(url="http://es:9200", api_key="es-key", transport=mock(handler))
        assert await client.bulk_index(docs) == {"indexed": 1, "errors": 1}
        request = seen[0]
        assert request.url.path == "/_bulk" and request.headers["authorization"] == "ApiKey es-key"
        lines = request.content.decode().strip().split("\n")
        assert json.loads(lines[0])["index"]["_id"] == f"{merchant}:audit:1"
        assert request.headers["content-type"] == "application/x-ndjson"

    async def test_search_is_always_filtered_to_the_merchant(self):
        seen: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(json.loads(request.content))
            return httpx.Response(200, json={"hits": {"hits": [{"_score": 3.2, "_source": {
                "kind": "offer", "ref": "9", "title": "Round 2", "body": "x"},
                "highlight": {"body": ["a <mark>floor</mark> price"]}}]}})

        merchant = uuid.uuid4()
        client = ElasticClient(url="http://es:9200", transport=mock(handler))
        hits = await client.search(merchant, "floor price", kinds=["offer"])
        filters = seen[0]["query"]["bool"]["filter"]
        assert {"term": {"merchant_id": str(merchant)}} in filters
        assert {"terms": {"kind": ["offer"]}} in filters
        assert hits[0]["snippet"] == "a <mark>floor</mark> price" and hits[0]["score"] == 3.2

    async def test_an_unconfigured_client_refuses_instead_of_guessing(self):
        client = ElasticClient(url="")
        assert client.configured is False and client.mode == "SIMULATED"
        with pytest.raises(SponsorError):
            await client.ping()


class TestKeywordFallback:
    DOCS = [
        {"kind": "offer", "ref": "1", "title": "Round 2 counter", "body": "supplier lowered the unit price to 10.10",
         "actor": "", "occurred_at": "2026-11-02T00:00:00+00:00", "correlation_id": "", "link": "/x"},
        {"kind": "review", "ref": "2", "title": "Great coffee", "body": "price was fair", "actor": "",
         "occurred_at": "2026-11-01T00:00:00+00:00", "correlation_id": "", "link": "/y"},
        {"kind": "audit", "ref": "3", "title": "LOGIN", "body": "nothing relevant", "actor": "",
         "occurred_at": None, "correlation_id": "", "link": "/z"},
    ]

    def test_ranks_by_title_and_term_coverage_and_marks_hits(self):
        hits = keyword_search(self.DOCS, "unit price", 10)
        assert [h["ref"] for h in hits] == ["1", "2"]  # matching both terms beats matching one
        assert "<mark>unit</mark>" in hits[0]["snippet"]

    def test_no_terms_no_results(self):
        assert keyword_search(self.DOCS, "!", 5) == []

    def test_a_result_kind_requires_its_permission(self):
        assert allowed_kinds({"audit:read"}) == ["audit"]
        assert allowed_kinds({"dashboard:read"}) == []
        assert set(allowed_kinds({"audit:read", "reviews:read", "events:read"})) == {"audit", "review", "event"}


# --------------------------------------------------------------------------- #
# Zapier
# --------------------------------------------------------------------------- #
class TestZapier:
    def test_signature_round_trip_and_tamper_detection(self):
        body = b'{"event_id":"1"}'
        assert verify(body, f"sha256={sign(body)}")
        assert not verify(b'{"event_id":"2"}', f"sha256={sign(body)}")

    async def test_the_event_is_posted_signed_with_an_id_for_dedupe(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"status": "success"})

        client = ZapierClient(url="https://hooks.zapier.com/hooks/catch/1/abc/", transport=mock(handler))
        assert await client.post_event(b'{"a":1}', event_id="evt-1") == 200
        request = seen[0]
        assert request.headers["x-paypilot-event-id"] == "evt-1"
        assert verify(request.content, request.headers["x-paypilot-signature"])

    async def test_only_https_hooks_are_allowed_and_the_url_stays_secret(self):
        with pytest.raises(SponsorError):
            await ZapierClient(url="http://hooks.zapier.com/x").post_event(b"{}", event_id="1")
        assert "hooks.zapier.com" not in repr(ZapierClient(url="https://hooks.zapier.com/hooks/catch/1/secret/"))

    async def test_a_failing_hook_raises_with_the_status(self):
        client = ZapierClient(url="https://hooks.zapier.com/x/", transport=mock(lambda r: httpx.Response(500)))
        with pytest.raises(SponsorError) as raised:
            await client.post_event(b"{}", event_id="1")
        assert raised.value.status_code == 500


# --------------------------------------------------------------------------- #
# PayPal MCP - the read-only gate
# --------------------------------------------------------------------------- #
class TestMCPReadOnlyGate:
    @pytest.mark.parametrize("name", [
        "create_order", "pay_order", "create_refund", "send_invoice", "send_invoice_reminder", "capture_order",
        "cancel_subscription", "accept_dispute_claim", "update_subscription", "delete_invoice",
        "checkout_cart", "record_invoice_payment", "get_and_pay_invoice", "list_then_refund_create",
        "", "balance", "Create_Order",
    ])
    def test_state_changing_or_unknown_tools_are_blocked(self, name):
        with pytest.raises(MCPReadOnlyViolation):
            assert_read_only(name)

    @pytest.mark.parametrize("name", [
        "list_disputes", "get_dispute", "list_transactions", "get_merchant_insights", "list_invoices",
        "show_product_details", "list_products", "get_order", "get_refund", "show_subscription_details",
    ])
    def test_read_tools_pass(self, name):
        assert_read_only(name)
        assert is_read_only(name)

    def test_a_server_annotation_can_only_tighten_the_gate(self):
        assert is_read_only("get_report", {"readOnlyHint": True})
        assert not is_read_only("get_report", {"readOnlyHint": False})


class FakeToken:
    async def access_token(self) -> str:
        return "paypal-access-token"


@pytest.fixture
def live_mcp(monkeypatch):
    """A 'configured' PayPal with an MCP server that answers like the real protocol."""
    monkeypatch.setattr(settings, "paypal_client_id", "id")
    monkeypatch.setattr(settings, "paypal_client_secret", "secret")
    monkeypatch.setattr(settings, "paypal_mcp_enabled", True)
    set_paypal_gateway(FakeToken())  # type: ignore[arg-type]
    yield
    set_paypal_gateway(None)


class MCPServer:
    """A tiny Streamable-HTTP MCP server: initialize, tools/list, tools/call."""

    def __init__(self, tools: list[dict], *, sse: bool = False) -> None:
        self.tools, self.sse, self.requests = tools, sse, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        message = json.loads(request.content)
        method = message["method"]
        if "id" not in message:
            return httpx.Response(202)
        if method == "initialize":
            result = {"protocolVersion": "2025-03-26", "capabilities": {}, "serverInfo": {"name": "paypal"}}
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": message["id"], "result": result},
                                  headers={"mcp-session-id": "sess-1"})
        if method == "tools/list":
            return self._reply(message, {"tools": self.tools})
        if method == "tools/call":
            text = json.dumps({"currency": "USD", "total": "123.45"})
            return self._reply(message, {"content": [{"type": "text", "text": text}], "isError": False})
        return httpx.Response(400)

    def _reply(self, message: dict, result: dict) -> httpx.Response:
        body = {"jsonrpc": "2.0", "id": message["id"], "result": result}
        if self.sse:
            return httpx.Response(200, text=f"event: message\ndata: {json.dumps(body)}\n\n",
                                  headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=body)

    def methods(self) -> list[str]:
        return [json.loads(r.content)["method"] for r in self.requests]


class TestMCPClient:
    TOOLS = [
        {"name": "get_merchant_insights", "description": "insights", "annotations": {"readOnlyHint": True}},
        {"name": "create_order", "description": "creates", "annotations": {"readOnlyHint": False}},
        {"name": "get_sneaky", "description": "named like a read, annotated as a write",
         "annotations": {"readOnlyHint": False}},
    ]

    async def test_a_read_call_follows_the_mcp_handshake_with_bearer_auth(self, live_mcp):
        server = MCPServer(self.TOOLS)
        client = PayPalMCPClient(transport=mock(server))
        result = await client.call_read_tool("get_merchant_insights", {"insight_type": "SALES"})
        assert result["data"] == {"currency": "USD", "total": "123.45"}
        assert server.methods() == ["initialize", "notifications/initialized", "tools/list", "tools/call"]
        assert all(r.headers["authorization"] == "Bearer paypal-access-token" for r in server.requests)
        assert server.requests[-1].headers["mcp-session-id"] == "sess-1"

    async def test_sse_responses_are_understood(self, live_mcp):
        server = MCPServer(self.TOOLS, sse=True)
        result = await PayPalMCPClient(transport=mock(server)).call_read_tool("get_merchant_insights")
        assert result["data"]["total"] == "123.45"

    async def test_a_write_tool_never_reaches_the_network(self, live_mcp):
        server = MCPServer(self.TOOLS)
        with pytest.raises(MCPReadOnlyViolation):
            await PayPalMCPClient(transport=mock(server)).call_read_tool("create_order", {"amount": "5000"})
        assert server.requests == []  # refused before a socket was opened

    async def test_the_servers_own_annotation_blocks_a_tool_with_an_innocent_name(self, live_mcp):
        server = MCPServer(self.TOOLS)
        with pytest.raises(MCPReadOnlyViolation):
            await PayPalMCPClient(transport=mock(server)).call_read_tool("get_sneaky")
        assert "tools/call" not in server.methods()

    async def test_listing_flags_what_is_callable(self, live_mcp):
        tools = await PayPalMCPClient(transport=mock(MCPServer(self.TOOLS))).list_tools()
        flags = {t["name"]: t["read_only"] for t in tools}
        assert flags == {"get_merchant_insights": True, "create_order": False, "get_sneaky": False}
        assert tools[0]["read_only"] is True  # callable tools sort first

    async def test_rejected_credentials_surface_cleanly(self, live_mcp):
        client = PayPalMCPClient(transport=mock(lambda r: httpx.Response(401)))
        with pytest.raises(SponsorError) as raised:
            await client.list_tools()
        assert "rejected" in str(raised.value) and "paypal-access-token" not in str(raised.value)

    async def test_without_credentials_it_answers_from_a_labelled_simulator(self):
        client = PayPalMCPClient()
        assert client.simulated
        result = await client.call_read_tool("list_disputes")
        assert result["mode"] == "SIMULATED" and result["source"] == "simulator"
        with pytest.raises(MCPReadOnlyViolation):
            await client.call_read_tool("create_refund")
        names = {t["name"]: t["read_only"] for t in await client.list_tools()}
        assert names["create_order"] is False and names["list_disputes"] is True


# --------------------------------------------------------------------------- #
# Transaction intelligence: purchase frequency and CLV
# --------------------------------------------------------------------------- #
def _txn(payer: str, day: int, amount: str = "20.00"):
    from datetime import UTC, datetime

    return SimpleNamespace(category="PAYMENT", status_code="S", payer_hash=payer,
                           initiated_at=datetime(2026, 10, day, 12, tzinfo=UTC), gross_amount=Decimal(amount))


class TestPurchaseBehaviour:
    def test_frequency_cadence_and_an_explicit_clv_estimate(self):
        from datetime import UTC, datetime

        start, end = datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 31, tzinfo=UTC)
        rows = [_txn("a", 2), _txn("a", 12), _txn("a", 22), _txn("b", 5)]
        out = _purchase_behaviour(rows, Decimal("20.00"), start, end)
        assert out["purchase_frequency"] == "2.00"                    # 4 payments / 2 payers
        assert out["avg_days_between_repeat_purchases"] == "10.0"     # a: 10 and 10 days
        assert out["annualised_purchase_frequency"] == "24.33"        # 2.00 * 365 / 30
        # CLV = AOV x annualised frequency x assumed lifespan, all Decimal
        assert out["customer_lifetime_value_estimate"] == str((Decimal("20.00") * Decimal("24.33") * CLV_ASSUMED_LIFESPAN_YEARS).quantize(Decimal("0.01")))
        assert out["clv_assumptions"]["is_estimate"] is True and out["clv_assumptions"]["assumed_lifespan_years"] == "2"

    def test_no_payers_means_zero_not_an_exception(self):
        from datetime import UTC, datetime

        out = _purchase_behaviour([], Decimal("0"), datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 31, tzinfo=UTC))
        assert out["purchase_frequency"] == "0.00" and out["customer_lifetime_value_estimate"] == "0.00"
        assert out["avg_days_between_repeat_purchases"] is None


# --------------------------------------------------------------------------- #
# Honest status
# --------------------------------------------------------------------------- #
class TestStatusReport:
    def test_unused_tools_are_not_claimed(self):
        by_key = {row["key"]: row for row in integration_status()}
        assert by_key["astropods"]["mode"] == "NOT_USED"
        assert "Context Plugin was not used" in by_key["apimatic"]["used_for"]
        assert by_key["render"]["mode"] == "BLUEPRINT"  # prepared, not claimed as deployed

    def test_fallbacks_say_simulated_and_no_secret_leaks(self):
        text = json.dumps(integration_status())
        for secret in (settings.channel3_api_key, settings.kernel_api_key, settings.elastic_api_key,
                       settings.zapier_webhook_url):
            assert not secret or secret not in text
        by_key = {row["key"]: row for row in integration_status()}
        assert by_key["channel3"]["mode"] in ("LIVE", "SIMULATED")
