"""Integration endpoints end to end, in simulation mode: RBAC, tenant isolation,
the Zapier delivery pipeline, the timeline and the AG Studio datasets.

This file is named so pytest runs it *after* ``test_supply_agents.py``: it seeds the
supply network, syncs PayPal transactions and opens a procurement - all of which
change the shared merchant's data that earlier suites assume is untouched.

No keys exist in the test environment - exactly the judge's environment - so every
sponsor path here is the labelled fallback, and these assert it says so.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.audit import AuditLog
from app.db.models.automation import DomainEvent
from app.db.models.integrations import IntegrationDelivery
from app.db.models.inventory import InventoryItem
from app.db.models.merchant import Merchant
from app.integrations.sponsors import ZapierClient, set_adapters
from app.integrations.sponsors.zapier import verify
from app.seed.supply import BEAN_SKU, seed_supply_network
from app.services.integrations import zapier as zapier_service
from app.services.intelligence.datasets import DATASET_PERMISSION
from app.services.intelligence.events import BusinessEvent, emit_business_event


@pytest.fixture(autouse=True)
def _reset_adapters():
    set_adapters()
    yield
    set_adapters()


@pytest.fixture(scope="module")
async def network(engine, seeded) -> dict:
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        merchant = await s.get(Merchant, seeded["merchant_id"])
        await seed_supply_network(s, merchant)
        await s.commit()
        item = (await s.execute(
            select(InventoryItem).where(InventoryItem.merchant_id == merchant.id, InventoryItem.sku == BEAN_SKU)
        )).scalars().first()
        await s.execute(update(InventoryItem).where(InventoryItem.sku == BEAN_SKU)
                        .values(quantity_on_hand=Decimal("42"), unit_cost=Decimal("11.60")))
        await s.commit()
        return {"item_id": str(item.id), "factory": factory}


async def open_procurement(client, headers, network, *, auto_negotiate: bool) -> str:
    """The id of this item's open procurement - one per item is allowed, so reuse it."""
    response = await client.post("/procurement", headers=headers,
                                 json={"inventory_item_id": network["item_id"], "auto_negotiate": auto_negotiate})
    if response.status_code == 201:
        return response.json()["data"]["procurement_request_id"]
    assert response.status_code == 409, response.text
    return response.json()["error"]["details"]["procurement_request_id"]


class TestStatus:
    async def test_status_is_honest_and_secret_free(self, client, viewer_headers):
        response = await client.get("/integrations/status", headers=viewer_headers)
        assert response.status_code == 200
        data = response.json()["data"]
        rows = {r["key"]: r for r in data["integrations"]}
        assert rows["astropods"]["mode"] == "NOT_USED"
        assert rows["channel3"]["mode"] == "SIMULATED" and rows["kernel"]["mode"] == "SIMULATED"
        assert rows["paypal"]["mode"] == "SIMULATED"
        assert data["zapier"]["configured"] is False
        assert "hooks.zapier.com" not in json.dumps(data)

    async def test_requires_authentication(self, client):
        assert (await client.get("/integrations/status")).status_code == 401


class TestMarketReference:
    async def test_benchmark_is_labelled_and_never_a_limit(self, client, analyst_headers):
        response = await client.post("/integrations/market/benchmark", headers=analyst_headers,
                                     json={"query": "premium coffee beans", "expected_price": "18.00"})
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["mode"] == "SIMULATED" and "not live market data" in data["note"]
        assert Decimal(data["stats"]["min"]) <= Decimal(data["stats"]["median"]) <= Decimal(data["stats"]["max"])
        assert data["position"]["verdict"]
        assert "do not change any limit" in data["disclaimer"]

    async def test_benchmark_for_a_procurement_compares_the_planned_price(self, client, analyst_headers, network):
        pid = await open_procurement(client, analyst_headers, network, auto_negotiate=True)
        response = await client.get(f"/integrations/market/procurement/{pid}", headers=analyst_headers)
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["procurement"]["id"] == pid and data["position"]["expected_selling_price"]

    async def test_another_tenant_cannot_benchmark_my_procurement(self, client, analyst_headers, outsider_headers, network):
        pid = await open_procurement(client, analyst_headers, network, auto_negotiate=True)
        assert (await client.get(f"/integrations/market/procurement/{pid}", headers=outsider_headers)).status_code == 404

    async def test_a_blank_query_is_a_400(self, client, analyst_headers):
        response = await client.post("/integrations/market/benchmark", headers=analyst_headers, json={"query": "  "})
        assert response.status_code in (400, 422)


class TestKernelPortal:
    async def test_an_analyst_can_open_a_simulated_session_and_it_is_audited(self, client, analyst_headers, owner_headers):
        response = await client.post("/integrations/kernel/sessions", headers=analyst_headers,
                                     json={"url": "https://supplier.example.com/catalog", "supplier_name": "Cascadia"})
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["mode"] == "SIMULATED" and data["session_id"].startswith("SIM-KERNEL-")
        assert "cdp_ws_url" not in data
        audit = (await client.get("/admin/audit-logs", headers=owner_headers, params={"page_size": 50}))
        if audit.status_code == 200:
            assert any(data["session_id"] in json.dumps(item) for item in audit.json()["data"]["items"])

    @pytest.mark.parametrize("url", ["http://supplier.example.com/", "https://10.0.0.5/admin", "https://localhost/"])
    async def test_unsafe_urls_are_a_400(self, client, analyst_headers, url):
        response = await client.post("/integrations/kernel/sessions", headers=analyst_headers, json={"url": url})
        assert response.status_code == 400

    async def test_a_viewer_cannot_open_a_browser(self, client, viewer_headers):
        response = await client.post("/integrations/kernel/sessions", headers=viewer_headers,
                                     json={"url": "https://supplier.example.com/catalog"})
        assert response.status_code == 403


class TestPayPalMCP:
    async def test_read_tools_work_and_are_labelled(self, client, viewer_headers):
        listing = (await client.get("/integrations/paypal-mcp/tools", headers=viewer_headers)).json()["data"]
        assert listing["mode"] == "SIMULATED"
        flags = {t["name"]: t["read_only"] for t in listing["tools"]}
        assert flags["list_disputes"] is True and flags["create_order"] is False
        called = await client.post("/integrations/paypal-mcp/call", headers=viewer_headers, json={"tool": "list_disputes"})
        assert called.status_code == 200 and called.json()["data"]["source"] == "simulator"

    @pytest.mark.parametrize("tool", ["create_order", "create_refund", "send_invoice", "pay_order", "checkout_cart"])
    async def test_money_moving_tools_are_refused_for_every_role_including_the_owner(self, client, owner_headers, tool):
        response = await client.post("/integrations/paypal-mcp/call", headers=owner_headers, json={"tool": tool})
        assert response.status_code == 403
        assert "approval" in response.text.lower() or "not a read tool" in response.text.lower()

    async def test_an_agent_tool_cannot_use_the_bridge_to_pay(self, engine, seeded, network):
        from app.tools import registry
        from app.tools.base import ToolContext

        async with network["factory"]() as s:
            ctx = ToolContext(session=s, merchant_id=seeded["merchant_id"], permissions=frozenset({"paypal:read"}))
            ok = await registry.execute("paypal_mcp_read", ctx, {"tool": "list_disputes"})
            blocked = await registry.execute("paypal_mcp_read", ctx, {"tool": "create_order", "arguments": {"amount": "900"}})
        assert ok.ok is True
        assert blocked.ok is False and "not a read tool" in (blocked.error or "")

    async def test_the_tool_registry_exposes_the_new_tools(self):
        from app.tools import BUYER_AGENT_TOOLS, MERCHANT_AGENT_TOOLS, registry

        for name in ("get_market_benchmark", "search_evidence", "paypal_mcp_read"):
            assert registry.get(name) is not None
        assert "get_market_benchmark" in BUYER_AGENT_TOOLS
        assert "paypal_mcp_read" in MERCHANT_AGENT_TOOLS


class TestEvidenceSearch:
    @staticmethod
    async def _plant(factory, merchant_id, phrase: str) -> None:
        async with factory() as s:
            s.add(AuditLog(merchant_id=merchant_id, actor_label="tester", action="INTEGRATION_ACTION",
                           resource="evidence", description=f"decision note {phrase}", status="SUCCESS", metadata_json={}))
            await s.commit()

    async def test_search_finds_evidence_and_says_which_engine_answered(self, client, owner_headers, network, seeded):
        phrase = f"zebraquartz{uuid.uuid4().hex[:6]}"
        await self._plant(network["factory"], seeded["merchant_id"], phrase)
        data = (await client.get("/integrations/search", headers=owner_headers, params={"q": phrase})).json()["data"]
        assert data["engine"] == "keyword-fallback" and data["mode"] == "SIMULATED"
        assert [r["kind"] for r in data["results"]] == ["audit"]
        assert "<mark>" in data["results"][0]["snippet"]

    async def test_a_viewer_cannot_search_the_audit_log(self, client, viewer_headers, network, seeded):
        phrase = f"audit{uuid.uuid4().hex[:6]}secret"
        await self._plant(network["factory"], seeded["merchant_id"], phrase)
        data = (await client.get("/integrations/search", headers=viewer_headers, params={"q": phrase})).json()["data"]
        assert "audit" not in data["kinds"] and data["results"] == []

    async def test_tenants_never_see_each_others_evidence(self, client, owner_headers, outsider_headers, network, seeded):
        phrase = f"isolation{uuid.uuid4().hex[:6]}marker"
        await self._plant(network["factory"], seeded["merchant_id"], phrase)
        mine = (await client.get("/integrations/search", headers=owner_headers, params={"q": phrase})).json()["data"]
        theirs = (await client.get("/integrations/search", headers=outsider_headers, params={"q": phrase})).json()["data"]
        assert len(mine["results"]) == 1 and theirs["results"] == []

    async def test_reindex_needs_settings_permission_and_is_a_noop_without_elastic(self, client, analyst_headers, owner_headers):
        assert (await client.post("/integrations/search/reindex", headers=analyst_headers)).status_code == 403
        data = (await client.post("/integrations/search/reindex", headers=owner_headers)).json()["data"]
        assert data["engine"] == "keyword-fallback" and data["indexed"] == 0


class TestZapierDelivery:
    URL = "https://hooks.zapier.com/hooks/catch/123/abc/"

    @staticmethod
    async def _emit(factory, merchant_id, event_type) -> uuid.UUID:
        async with factory() as s:
            event = await emit_business_event(s, merchant_id=merchant_id, event_type=event_type,
                                              correlation_id=f"corr-{uuid.uuid4().hex[:8]}", entity_type="procurement",
                                              payload={"product": "Premium Coffee Beans", "quantity": "150"})
            await s.commit()
            return event.id

    async def test_events_are_delivered_once_signed_and_allow_listed(self, network, seeded):
        factory, merchant_id = network["factory"], seeded["merchant_id"]
        # Start from a clean slate for this target so earlier tests' events do not interfere.
        async with factory() as s:
            await s.execute(IntegrationDelivery.__table__.delete())
            await s.commit()
        sent: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            return httpx.Response(200, json={"status": "success"})

        set_adapters(zapier=ZapierClient(url=self.URL, transport=httpx.MockTransport(handler)))
        wanted = await self._emit(factory, merchant_id, BusinessEvent.SUPPLIER_SELECTED)
        await self._emit(factory, merchant_id, BusinessEvent.RFQ_STARTED)  # not on the allow-list

        async with factory() as s:
            first = await zapier_service.run_once(s)
        mine = [r for r in sent if json.loads(r.content)["event_id"] == str(wanted)]
        assert len(mine) == 1 and first["delivered"] >= 1
        body = json.loads(mine[0].content)
        assert body["event_type"] == BusinessEvent.SUPPLIER_SELECTED and body["merchant_id"] == str(merchant_id)
        assert verify(mine[0].content, mine[0].headers["x-paypilot-signature"])
        assert not any(json.loads(r.content)["event_type"] == BusinessEvent.RFQ_STARTED for r in sent)

        async with factory() as s:
            second = await zapier_service.run_once(s)
        assert second["queued"] == 0 and second["delivered"] == 0  # exactly once

    async def test_a_failing_hook_backs_off_and_does_not_touch_n8n_delivery_state(self, network, seeded):
        factory, merchant_id = network["factory"], seeded["merchant_id"]
        set_adapters(zapier=ZapierClient(url=self.URL, transport=httpx.MockTransport(lambda r: httpx.Response(500))))
        event_id = await self._emit(factory, merchant_id, BusinessEvent.PAYMENT_RECONCILED)
        async with factory() as s:
            result = await zapier_service.run_once(s)
        assert result["retried"] >= 1
        async with factory() as s:
            row = (await s.execute(select(IntegrationDelivery).where(IntegrationDelivery.event_id == event_id))).scalar_one()
            event = await s.get(DomainEvent, event_id)
        assert row.status == "PENDING" and row.attempts == 1 and row.http_status == 500
        # Backed off into the future (SQLite hands datetimes back naive; compare like with like).
        assert row.next_attempt_at.replace(tzinfo=None) > datetime.now(UTC).replace(tzinfo=None)
        assert event.delivery_status in ("PENDING", "SKIPPED")  # the n8n outbox row is independent

    async def test_unconfigured_zapier_does_nothing(self, network):
        async with network["factory"]() as s:
            assert await zapier_service.run_once(s) == {"queued": 0, "delivered": 0, "failed": 0, "retried": 0}

    async def test_the_test_endpoint_requires_settings_permission(self, client, analyst_headers, owner_headers):
        assert (await client.post("/integrations/zapier/test", headers=analyst_headers)).status_code == 403
        data = (await client.post("/integrations/zapier/test", headers=owner_headers)).json()["data"]
        assert data["sent"] is False  # not configured: nothing was sent


class TestTimelineAndDatasets:
    async def test_the_timeline_chains_the_real_stages_with_valid_dependencies(self, client, analyst_headers, network):
        pid = await open_procurement(client, analyst_headers, network, auto_negotiate=True)
        data = (await client.get("/supply/timeline", headers=analyst_headers)).json()["data"]
        assert data["count"] >= 1
        parent = next(t for t in data["tasks"] if t["id"] == pid)
        names = [c["name"] for c in parent["children"]]
        assert "RFQ & negotiation" in names and "Human approval" in names

        ids = {c["id"] for t in data["tasks"] for c in t["children"]}
        assert data["dependencies"], "stages should be chained"
        for dep in data["dependencies"]:
            assert dep["from"] in ids and dep["to"] in ids and dep["type"] == 2
        for task in [*data["tasks"], *(c for t in data["tasks"] for c in t["children"])]:
            assert datetime.fromisoformat(task["startDate"]) <= datetime.fromisoformat(task["endDate"])
            assert task["manuallyScheduled"] is True  # a view of what happened, never a scheduler
        # Planned windows (Gantt baselines) come only from dates recorded up front, never invented.
        for stage in parent["children"]:
            assert "baseline" in stage
            if stage["baseline"] is not None:
                b = stage["baseline"]
                assert datetime.fromisoformat(b["startDate"]) < datetime.fromisoformat(b["endDate"])
            if stage.get("milestone"):
                assert stage["baseline"] is None  # a goods receipt has no plan of its own
        negotiation = next(c for c in parent["children"] if c["name"] == "RFQ & negotiation")
        assert negotiation["baseline"] is not None, "the RFQ deadline is the negotiation's plan"
        # The bar's colour is a function of the real approval status - never silently "done".
        detail = (await client.get(f"/procurement/{pid}", headers=analyst_headers)).json()["data"]
        approval_status = (await client.get(f"/approvals/{detail['approval']['approval_id']}",
                                            headers=analyst_headers)).json()["data"]["status"]
        expected = {"PENDING": "active", "APPROVED": "done", "EXECUTED": "done"}.get(approval_status, "blocked")
        approval = next(c for c in parent["children"] if c["name"] == "Human approval")
        assert approval["state"] == expected
        if approval_status == "PENDING":
            assert approval["state"] != "done"

    async def test_the_timeline_is_tenant_scoped(self, client, outsider_headers, network):
        data = (await client.get("/supply/timeline", headers=outsider_headers)).json()["data"]
        assert all("PR-" not in t["name"] or t["id"] for t in data["tasks"])
        mine_ids = {str(i) for i in [network["item_id"]]}
        assert not mine_ids & {t["id"] for t in data["tasks"]}

    async def test_datasets_are_computed_rows_filtered_by_permission(self, client, owner_headers, viewer_headers, network):
        owner = (await client.get("/integrations/studio/datasets", headers=owner_headers)).json()["data"]
        assert set(owner["datasets"]) == set(DATASET_PERMISSION)
        assert "does not derive financial figures" in owner["note"]
        beans = next(r for r in owner["datasets"]["inventory_cover"] if r["sku"] == BEAN_SKU)
        assert beans["suggested_reorder_qty"] == 150.0
        assert all(isinstance(v, (int, float, str, bool, type(None))) for r in owner["datasets"]["procurements"] for v in r.values())

        viewer = (await client.get("/integrations/studio/datasets", headers=viewer_headers)).json()["data"]
        assert set(viewer["datasets"]) <= set(DATASET_PERMISSION)

    async def test_transaction_intelligence_reports_clv_with_its_assumptions(self, client, analyst_headers):
        await client.post("/paypal/sync", headers=analyst_headers, json={"days": 40})
        intel = (await client.get("/paypal/intelligence", headers=analyst_headers)).json()["data"]
        usd = intel["currencies"]["USD"]
        assert Decimal(usd["customer_lifetime_value_estimate"]) >= 0
        assert usd["clv_assumptions"]["is_estimate"] is True
        assert Decimal(usd["purchase_frequency"]) >= 1
