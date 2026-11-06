"""Supply Intelligence end to end: discovery API, recommendations, approvals, PayPal orders,
webhooks and the Merchant OS agents.

Channel3 is mocked at the HTTP transport (the real client, request builder and parser
run); PayPal is the labelled simulator. Nothing here touches a real service.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.commerce import Customer, DayPart, Product, Transaction, TransactionItem
from app.db.models.discovery import MerchantRecommendation, RecommendationKind, RecommendationStatus
from app.db.models.governance import FinancialExecution
from app.db.models.merchant import Merchant
from app.integrations.paypal import sign_simulated_webhook
from app.integrations.sponsors import set_adapters
from app.integrations.sponsors.channel3_catalog import Channel3Catalog
from app.services.discovery.service import reset_caches
from app.services.supply_intel.recommendations import RecommendationService


def c3_product(pid: str, title: str, price: float, *, category: str = "in-ear-headphones", brand: str = "Acme",
               stock: str = "InStock") -> dict:
    return {
        "id": pid, "title": title, "description": f"{title} description",
        "brands": [{"id": brand.lower(), "name": brand}],
        "images": [{"url": f"https://cdn.test/{pid}.jpg", "cleaned_url": None, "is_main_image": True}],
        "category": {"slug": category, "title": category.replace("-", " ").title(), "path": []},
        "key_features": ["Bluetooth 5.3"], "materials": [],
        "offers": [{"url": f"https://buy.test/{pid}", "domain": "bestbuy.com", "availability": stock,
                    "price": {"price": price, "currency": "USD", "compare_at_price": None}, "max_commission_rate": 0.05}],
        "structured_attributes": {"connectivity-technology": ["Bluetooth"]}, "variants": None, "ratings": None,
    }


EARBUDS = [c3_product("e1", "Soundcore P31i", 32.99, brand="Soundcore"), c3_product("e2", "JBL Vibe Beam", 39.95, brand="JBL"),
           c3_product("e3", "Generic Earbuds", 17.99), c3_product("e4", "Pro Earbuds", 89.0, brand="Sony")]
BEANS = [c3_product(f"b{i}", f"Whole Bean Coffee {i}", p, category="coffee-beans", brand="Roaster")
         for i, p in enumerate([22.0, 23.5, 24.0, 26.0])]
GEAR = [c3_product(f"g{i}", f"Coffee Gear {i}", p, category="coffee-grinders", brand="Fellow")
        for i, p in enumerate([45.0, 89.0, 120.0, 150.0])]


def channel3_handler(seen: list[httpx.Request], *, similar_404: bool = False):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path == "/v1/search":
            body = json.loads(request.content)
            query = body.get("query", "").lower()
            products = BEANS if "bean" in query else GEAR if any(k in query for k in ("grinder", "coffee", "mug", "filter", "canister", "brew")) else EARBUDS
            return httpx.Response(200, json={"products": products, "next_page_token": None})
        if path == "/v1/similar":
            if similar_404:
                return httpx.Response(404, json={"detail": "not indexed"})
            return httpx.Response(200, json={"products": EARBUDS[1:]})
        if path.startswith("/v1/products/"):
            pid = path.rsplit("/", 1)[-1]
            match = next((p for p in [*EARBUDS, *BEANS, *GEAR] if p["id"] == pid), EARBUDS[0])
            return httpx.Response(200, json=match)
        if path == "/v1/lookup":
            return httpx.Response(200, json={"product": EARBUDS[0]})
        if path == "/v1/categories/search":
            return httpx.Response(200, json={"categories": [{"slug": "in-ear-headphones", "title": "In-Ear Headphones", "path": []}]})
        if path == "/v1/brands/search":
            return httpx.Response(200, json={"brands": [{"id": "sony", "name": "Sony"}]})
        if path == "/v1/conversations":
            return httpx.Response(200, json={
                "conversation_id": "conv_test", "turn_id": "turn_1", "usage": {"credits_charged": 2, "searches_run": 1},
                "message": {"role": "assistant", "suggestions": ["Only noise cancelling"], "parts": [
                    {"type": "text", "text": "What will you mainly use it for?"},
                    {"type": "tool", "tool_name": "search_products", "input": {"query": "earbuds"}, "output": {"products": EARBUDS[:2]}},
                ]},
            })
        return httpx.Response(404)
    return handler


async def _no_sleep(_: float) -> None:
    return None


@pytest.fixture
def seen() -> list[httpx.Request]:
    return []


@pytest.fixture(autouse=True)
def channel3(seen):
    reset_caches()
    set_adapters(catalog=Channel3Catalog(api_key="test-key", base_url="https://api.trychannel3.com",
                                         transport=httpx.MockTransport(channel3_handler(seen)), sleep=_no_sleep))
    yield
    set_adapters()
    reset_caches()


@pytest.fixture
def factory(engine):
    return async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)


async def _recommendation(factory, merchant_id: uuid.UUID, **overrides) -> uuid.UUID:
    async with factory() as s:
        row = MerchantRecommendation(
            merchant_id=merchant_id, reference=f"REC-T{uuid.uuid4().hex[:6]}", kind=RecommendationKind.ASSORTMENT_EXPANSION,
            title="Add earbuds next to the best seller", description="test", evidence=[{"label": "buyers", "value": 40, "source": "Your sales data"}],
            recommended_action="Stock 6 units", expected_impact={"metric": "monthly_revenue", "value": "120.00", "is_estimate": True},
            confidence=Decimal("0.700"), confidence_reasons=["test"], requires_approval=True, status=RecommendationStatus.RECOMMENDED,
            lifecycle=[{"status": s_, "at": datetime.now(tz=UTC).isoformat(), "actor": "test", "note": ""} for s_ in ("DETECTED", "ANALYZED", "RECOMMENDED")],
            products=[{"id": "e1", "title": "Soundcore P31i", "price": "32.99", "currency": "USD", "retailer": "bestbuy.com"}],
            suggested_test_quantity=6, suggested_retail_price=Decimal("32.99"), currency="USD", dedupe_key=f"TEST:{uuid.uuid4()}",
            execution={}, measurement={}, **overrides,
        )
        s.add(row)
        await s.commit()
        return row.id


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
class TestDiscoveryAPI:
    async def test_no_key_is_a_503_with_setup_steps_never_fake_products(self, client, viewer_headers):
        set_adapters(catalog=Channel3Catalog(api_key=""))
        response = await client.post("/supply/search", headers=viewer_headers, json={"query": "wireless earbuds"})
        assert response.status_code == 503
        error = response.json()["error"]
        assert error["code"] == "CHANNEL3_NOT_CONFIGURED" and "CHANNEL3_API_KEY" in error["details"]["setup"]
        status = (await client.get("/supply/discovery/status", headers=viewer_headers)).json()["data"]
        assert status["configured"] is False and status["setup"]

    async def test_search_ranks_explains_and_remembers(self, client, viewer_headers, seen):
        response = await client.post("/supply/search", headers=viewer_headers,
                                     json={"query": "Find wireless earbuds under ₹5,000", "limit": 8})
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["intent"]["budget_currency"] == "INR" and data["budget"]["converted"] is True
        assert data["applied_filters"]["price"]["max_price"] == pytest.approx(56.82, abs=0.01)
        assert data["category"]["slug"] == "in-ear-headphones"
        assert [p["ranking"]["rank"] for p in data["products"]] == [1, 2, 3, 4]
        assert all(p["ranking"]["reasons"] for p in data["products"])
        assert data["products"][-1]["id"] == "e4"  # $89 is over the converted budget
        search_body = json.loads(next(r for r in seen if r.url.path == "/v1/search").content)
        assert search_body["filters"]["category_ids"] == ["in-ear-headphones"]
        assert all(r.headers["x-user-id"].startswith("paypilot-") for r in seen if r.url.path == "/v1/search")
        history = (await client.get("/supply/searches", headers=viewer_headers)).json()["data"]
        assert history[0]["query"].startswith("Find wireless earbuds") and history[0]["result_count"] == 4
        discovered = (await client.get("/supply/discovered", headers=viewer_headers)).json()["data"]
        assert {"e1", "e2", "e3", "e4"} <= {d["id"] for d in discovered}
        assert all(d["price_is_snapshot"] for d in discovered)

    async def test_brand_names_resolve_to_brand_filters(self, client, viewer_headers, seen):
        response = await client.post("/supply/search", headers=viewer_headers, json={"query": "earbuds by Sony"})
        assert response.status_code == 200
        body = json.loads(next(r for r in seen if r.url.path == "/v1/search").content)
        assert body["filters"]["brand_ids"] == ["sony"]

    async def test_compare_has_evidence_and_not_listed_specs(self, client, analyst_headers):
        response = await client.post("/supply/compare", headers=analyst_headers, json={"product_ids": ["e1", "e2", "e3"]})
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["verdicts"]["best_value"]["product_id"] == "e3"
        assert data["overall"]["product_id"] in {"e1", "e2", "e3"} and data["narrative"]
        rating = next(r for r in data["matrix"]["rows"] if r["key"] == "rating")
        assert rating["values"] == [None, None, None]
        listed = (await client.get("/supply/comparisons", headers=analyst_headers)).json()["data"]
        assert listed[0]["id"] == data["comparison_id"]

    async def test_compare_needs_two_to_four(self, client, analyst_headers):
        assert (await client.post("/supply/compare", headers=analyst_headers, json={"product_ids": ["e1"]})).status_code == 422

    async def test_similar_explains_and_falls_back_on_404(self, client, viewer_headers, seen):
        data = (await client.post("/supply/similar", headers=viewer_headers, json={"product_id": "e1"})).json()["data"]
        assert [p["id"] for p in data["products"]] == ["e2", "e3", "e4"] and not data["fallback_used"]
        assert data["products"][0]["similarity"]["price_difference"] == "6.96"
        set_adapters(catalog=Channel3Catalog(api_key="k", transport=httpx.MockTransport(channel3_handler(seen, similar_404=True)),
                                             sleep=_no_sleep))
        reset_caches()
        fallback = (await client.post("/supply/similar", headers=viewer_headers, json={"product_id": "e1"})).json()["data"]
        assert fallback["fallback_used"] is True and "e1" not in [p["id"] for p in fallback["products"]]

    async def test_product_details_and_enrich(self, client, viewer_headers):
        detail = (await client.get("/supply/products/e1", headers=viewer_headers)).json()["data"]
        assert detail["product"]["id"] == "e1" and detail["product"]["offers"][0]["domain"] == "bestbuy.com"
        assert len(detail["similar"]) == 3
        enriched = await client.post("/supply/enrich", headers=viewer_headers, json={"url": "https://www.bestbuy.com/site/p/123"})
        assert enriched.status_code == 200 and enriched.json()["data"]["product"]["id"] == "e1"
        bad = await client.post("/supply/enrich", headers=viewer_headers, json={"url": "javascript:alert(1)//x"})
        assert bad.status_code == 400

    async def test_assistant_keeps_constraints_across_turns(self, client, viewer_headers):
        first = (await client.post("/supply/assistant", headers=viewer_headers,
                                   json={"message": "Find me a laptop under $900"})).json()["data"]
        conv = first["conversation"]
        assert conv["channel3_conversation_id"] == "conv_test" and first["reply"]["products"]
        assert first["pinned_filters"] == {"price": {"max_price": 900.0}}
        second = (await client.post("/supply/assistant", headers=viewer_headers,
                                    json={"message": "Machine learning and development", "conversation_id": conv["id"]})).json()["data"]
        assert second["conversation"]["turn_count"] == 2 and second["conversation"]["credits_used"] == 4
        assert "Used for: Machine learning and development" in second["conversation"]["remembered"]
        assert second["pinned_filters"] == {"price": {"max_price": 900.0}}

    async def test_requires_authentication(self, client):
        assert (await client.post("/supply/search", json={"query": "earbuds"})).status_code == 401


# --------------------------------------------------------------------------- #
# Recommendations, approvals and PayPal
# --------------------------------------------------------------------------- #
class TestRecommendationLifecycle:
    async def test_full_path_from_recommendation_to_captured_paypal_order(
        self, client, factory, seeded, owner_headers, analyst_headers,
    ):
        rec_id = await _recommendation(factory, seeded["merchant_id"])
        # Analysts propose; only procurement:approve decides.
        assert (await client.post(f"/supply/recommendations/{rec_id}/approve", headers=analyst_headers, json={})).status_code == 403
        approved = (await client.post(f"/supply/recommendations/{rec_id}/approve", headers=owner_headers,
                                      json={"note": "Worth a test"})).json()["data"]
        assert approved["status"] == "APPROVED" and approved["stages"][3]["reached"]
        again = await client.post(f"/supply/recommendations/{rec_id}/approve", headers=owner_headers, json={})
        assert again.status_code == 409

        executed = (await client.post(f"/supply/recommendations/{rec_id}/execute", headers=owner_headers,
                                      json={"retail_price": "34.99"})).json()["data"]
        assert executed["status"] == "EXECUTED" and executed["execution"]["action"] == "ADDED_TO_CATALOG"
        async with factory() as s:
            product = await s.get(Product, uuid.UUID(executed["execution"]["catalog_product_id"]))
            assert product.attributes["channel3_product_id"] == "e1" and str(product.price) == "34.99"

        requested = await client.post(f"/supply/recommendations/{rec_id}/purchase", headers=analyst_headers,
                                      json={"quantity": 6, "unit_cost": "18.50", "payee_email": "Supplier@Example.com"})
        assert requested.status_code == 200, requested.text
        approval = requested.json()["data"]
        assert approval["status"] == "PENDING" and approval["amount"] == "111.00"
        assert approval["required_permission"] == "payment:approve" and approval["details"]["payee_email"] == "supplier@example.com"

        # No order before a human approves; analysts cannot approve or execute payments.
        early = await client.post("/payments/orders", headers=owner_headers, json={"approval_id": approval["approval_id"]})
        assert early.status_code == 409
        assert (await client.post(f"/approvals/{approval['approval_id']}/decide", headers=analyst_headers,
                                  json={"approve": True})).status_code == 403
        decided = (await client.post(f"/approvals/{approval['approval_id']}/decide", headers=owner_headers,
                                     json={"approve": True, "note": "ok"})).json()["data"]
        assert decided["status"] == "APPROVED"
        assert (await client.post("/payments/orders", headers=analyst_headers,
                                  json={"approval_id": approval["approval_id"]})).status_code == 403

        order = (await client.post("/payments/orders", headers={**owner_headers, "Idempotency-Key": "k-1"},
                                   json={"approval_id": approval["approval_id"]})).json()["data"]
        assert order["mode"] == "SIMULATED" and order["paypal_order_id"].startswith("SIM-ORDER")
        assert order["status"] == "PENDING"  # simulated payer approval; capture is still a human click
        repeat = (await client.post("/payments/orders", headers=owner_headers, json={"approval_id": approval["approval_id"]})).json()["data"]
        assert repeat["execution_id"] == order["execution_id"]

        captured = (await client.post("/payments/capture", headers=owner_headers, json={"execution_id": order["execution_id"]})).json()["data"]
        assert captured["status"] == "CAPTURED" and captured["paypal_capture_id"].startswith("SIM-CAPTURE")
        twice = (await client.post("/payments/capture", headers=owner_headers, json={"execution_id": order["execution_id"]})).json()["data"]
        assert twice["paypal_capture_id"] == captured["paypal_capture_id"]

        rec = (await client.get(f"/supply/recommendations/{rec_id}", headers=owner_headers)).json()["data"]
        assert rec["execution"]["purchase_capture_id"] == captured["paypal_capture_id"]
        history = (await client.get("/payments/history", headers=owner_headers)).json()["data"]
        row = next(i for i in history["items"] if i["execution_id"] == order["execution_id"])
        assert row["approval_reference"] == approval["reference"] and row["kind"] == "MERCHANT_PURCHASE"
        detail = (await client.get(f"/payments/orders/{order['execution_id']}", headers=owner_headers)).json()["data"]
        assert detail["paypal"]["status"] == "COMPLETED" and detail["recommendation"]["id"] == str(rec_id)

        measured = (await client.post(f"/supply/recommendations/{rec_id}/measure", headers=owner_headers)).json()["data"]
        assert measured["status"] == "MEASURED" and measured["measurement"]["units_sold"] == 0
        assert measured["measurement"]["payment"]["status"] == "CAPTURED"
        assert "No sales recorded" in measured["measurement"]["verdict"]

    async def test_changed_terms_invalidate_the_payment_approval(self, client, factory, seeded, owner_headers):
        rec_id = await _recommendation(factory, seeded["merchant_id"])
        await client.post(f"/supply/recommendations/{rec_id}/approve", headers=owner_headers, json={})
        approval = (await client.post(f"/supply/recommendations/{rec_id}/purchase", headers=owner_headers,
                                      json={"quantity": 4, "unit_cost": "10", "payee_email": "s@example.com"})).json()["data"]
        async with factory() as s:
            row = await s.get(MerchantRecommendation, rec_id)
            row.products = [{"id": "e2", "title": "JBL Vibe Beam", "price": "39.95"}]
            await s.commit()
        response = await client.post(f"/approvals/{approval['approval_id']}/decide", headers=owner_headers, json={"approve": True})
        assert response.status_code == 409 and response.json()["error"]["details"]["code"] == "APPROVAL_INVALIDATED"

    async def test_rejected_recommendations_cannot_be_executed_or_bought(self, client, factory, seeded, owner_headers):
        rec_id = await _recommendation(factory, seeded["merchant_id"])
        rejected = (await client.post(f"/supply/recommendations/{rec_id}/reject", headers=owner_headers,
                                      json={"note": "Not our customers"})).json()["data"]
        assert rejected["status"] == "REJECTED"
        assert (await client.post(f"/supply/recommendations/{rec_id}/execute", headers=owner_headers, json={})).status_code == 409
        assert (await client.post(f"/supply/recommendations/{rec_id}/purchase", headers=owner_headers,
                                  json={"quantity": 1, "unit_cost": "5", "payee_email": "s@example.com"})).status_code == 409

    async def test_verified_webhook_settles_the_order(self, client, factory, seeded, owner_headers):
        rec_id = await _recommendation(factory, seeded["merchant_id"])
        await client.post(f"/supply/recommendations/{rec_id}/approve", headers=owner_headers, json={})
        approval = (await client.post(f"/supply/recommendations/{rec_id}/purchase", headers=owner_headers,
                                      json={"quantity": 2, "unit_cost": "12", "payee_email": "s@example.com"})).json()["data"]
        await client.post(f"/approvals/{approval['approval_id']}/decide", headers=owner_headers, json={"approve": True})
        order = (await client.post("/payments/orders", headers=owner_headers, json={"approval_id": approval["approval_id"]})).json()["data"]
        event = {"id": f"WH-{uuid.uuid4().hex[:12]}", "event_type": "PAYMENT.CAPTURE.COMPLETED", "resource_type": "capture",
                 "resource": {"id": "SIM-CAPTURE-WEBHOOK1", "status": "COMPLETED",
                              "custom_id": f"{seeded['merchant_id']}|{rec_id}",
                              "supplementary_data": {"related_ids": {"order_id": order["paypal_order_id"]}}}}
        body = json.dumps(event).encode()
        unsigned = await client.post("/payments/webhooks/paypal", content=body, headers={"content-type": "application/json"})
        assert unsigned.status_code == 401
        signed = await client.post("/payments/webhooks/paypal", content=body,
                                   headers={"content-type": "application/json", **sign_simulated_webhook(body)})
        assert signed.status_code == 200 and signed.json()["data"]["outcome"] == "verified"
        async with factory() as s:
            execution = await s.get(FinancialExecution, uuid.UUID(order["execution_id"]))
            assert execution.status == "CAPTURED" and execution.paypal_capture_id == "SIM-CAPTURE-WEBHOOK1"
            rec = await s.get(MerchantRecommendation, rec_id)
            assert rec.status == "EXECUTED" and rec.execution["purchase_capture_id"] == "SIM-CAPTURE-WEBHOOK1"

    async def test_another_tenant_cannot_see_or_decide(self, client, factory, seeded, outsider_headers):
        rec_id = await _recommendation(factory, seeded["merchant_id"])
        assert (await client.get(f"/supply/recommendations/{rec_id}", headers=outsider_headers)).status_code == 404
        assert (await client.post(f"/supply/recommendations/{rec_id}/approve", headers=outsider_headers, json={})).status_code == 404
        mine = (await client.get("/supply/recommendations", headers=outsider_headers)).json()["data"]
        assert str(rec_id) not in {r["id"] for r in mine}


class TestGeneration:
    async def _merchant_with_sales(self, factory) -> uuid.UUID:
        async with factory() as s:
            merchant = Merchant(name="Gen Cafe", slug=f"gen-{uuid.uuid4().hex[:6]}", category="cafe", is_demo=True)
            s.add(merchant)
            await s.flush()
            beans = Product(merchant_id=merchant.id, sku="GEN-BEAN", name="Premium Coffee Beans (12 oz)", category="retail",
                            price=18, cost_price=11.6, tags=["retail", "beans", "online"], attributes={"channel": "online_store"})
            s.add(beans)
            customers = [Customer(merchant_id=merchant.id, external_ref=f"g{i}", name=f"Buyer {i}") for i in range(40)]
            s.add_all(customers)
            await s.flush()
            anchor = datetime(2025, 6, 30, tzinfo=UTC)
            n = 0
            for offset in range(60):
                day = anchor - timedelta(days=offset)
                for k in range(2 if offset < 30 else 1):  # demand doubled in the recent window
                    n += 1
                    txn = Transaction(merchant_id=merchant.id, customer_id=customers[n % 40].id, order_ref=f"G{n}", occurred_at=day,
                                      business_date=day.date(), daypart=DayPart.MORNING, hour_of_day=9, day_of_week=day.weekday(),
                                      gross_amount=18, net_amount=18, cost_amount=11.6, item_count=1, channel="online_store")
                    s.add(txn)
                    await s.flush()
                    s.add(TransactionItem(merchant_id=merchant.id, transaction_id=txn.id, product_id=beans.id,
                                          product_name=beans.name, quantity=1, unit_price=18, unit_cost=11.6, line_total=18))
            await s.commit()
            return merchant.id

    async def test_generate_from_sales_and_channel3_then_dedupe(self, factory):
        merchant_id = await self._merchant_with_sales(factory)
        async with factory() as s:
            result = await RecommendationService(s, merchant_id).generate(days=30, max_recommendations=4)
            await s.commit()
        recs = result["recommendations"]
        assortment = [r for r in recs if r["kind"] == "ASSORTMENT_EXPANSION"]
        pricing = [r for r in recs if r["kind"] == "PRICING_OPPORTUNITY"]
        assert len(assortment) == 3 and len(pricing) == 1
        first = assortment[0]
        assert first["status"] == "RECOMMENDED" and [s_["status"] for s_ in first["lifecycle"]] == ["DETECTED", "ANALYZED", "RECOMMENDED"]
        assert first["expected_impact"]["is_estimate"] is True and first["expected_impact"]["assumptions"]
        assert any(e["source"] == "Channel3" for e in first["evidence"]) and any(e["source"] == "Your sales data" for e in first["evidence"])
        assert first["suggested_test_quantity"] is not None and 6 <= first["suggested_test_quantity"] <= 48
        assert first["products"] and "url" not in first["products"][0]  # short-lived offer links are never stored
        assert 0.4 <= first["confidence"] <= 0.9
        price = pricing[0]
        assert price["suggested_retail_price"] == "19.80"  # capped +10% step toward the market median
        assert any("not your cost" in e["label"] or "unit cost" in e["label"].lower() for e in price["evidence"])

        async with factory() as s:
            again = await RecommendationService(s, merchant_id).generate(days=30, max_recommendations=4)
            await s.commit()
            rows = (await s.execute(select(MerchantRecommendation).where(MerchantRecommendation.merchant_id == merchant_id))).scalars().all()
        assert len(rows) == 4 and len(again["recommendations"]) == 4  # refreshed in place, not duplicated
        refreshed = next(r for r in rows if r.id == uuid.UUID(first["id"]))
        assert sum(1 for s_ in refreshed.lifecycle if s_["status"] == "ANALYZED") == 2


# --------------------------------------------------------------------------- #
# Merchant OS agents
# --------------------------------------------------------------------------- #
class TestAgents:
    async def test_discovery_agent_calls_channel3_tools_and_is_traced(self, client, analyst_headers):
        response = await client.post("/agents/execute", headers=analyst_headers,
                                     json={"message": "Find wireless earbuds under $60", "agent": "product_discovery"})
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["agent"] == "product_discovery" and data["route"]["source"] == "explicit"
        assert [c["tool"] for c in data["tool_calls"]] == ["discover_products"] and data["tool_calls"][0]["ok"]
        assert data["products"] and data["products"][0]["id"] in {"e1", "e2", "e3", "e4"}
        activity = (await client.get("/agents/activity", headers=analyst_headers)).json()["data"]
        run = next(i for i in activity["items"] if i["run_id"] == data["run_id"])
        assert run["specialists"] == ["Product Discovery Agent"] and run["tools"][0]["tool"] == "discover_products"
        assert run["tools"][0]["agent"] == "Product Discovery Agent"

    async def test_keyword_routing_without_an_llm(self, client, analyst_headers):
        data = (await client.post("/agents/execute", headers=analyst_headers,
                                  json={"message": "How are my sales this month?"})).json()["data"]
        assert data["agent"] == "business_intelligence" and data["route"]["source"] == "keywords"
        assert {c["tool"] for c in data["tool_calls"]} == {"get_sales_summary", "get_product_performance", "analyze_assortment"}

    async def test_paypal_agent_can_request_but_never_pay(self, client, factory, seeded, owner_headers):
        rec_id = await _recommendation(factory, seeded["merchant_id"])
        await client.post(f"/supply/recommendations/{rec_id}/approve", headers=owner_headers, json={})
        data = (await client.post("/agents/execute", headers=owner_headers, json={
            "message": "Request payment for the test stock", "agent": "paypal_transaction",
            "params": {"recommendation_id": str(rec_id), "quantity": 3, "unit_cost": 9.5, "payee_email": "s@example.com"},
        })).json()["data"]
        assert data["requires_approval"] is True and data["status"] == "AWAITING_APPROVAL"
        approval = data["approvals"][0]
        assert approval["status"] == "PENDING" and approval["amount"] == "28.50"
        async with factory() as s:
            executions = (await s.execute(select(FinancialExecution).where(
                FinancialExecution.approval_request_id == uuid.UUID(approval["approval_id"])))).scalars().all()
        assert executions == []  # an agent request moves no money

    async def test_a_viewer_cannot_run_agents_or_the_autopilot(self, client, viewer_headers):
        assert (await client.post("/agents/execute", headers=viewer_headers, json={"message": "find mugs"})).status_code == 403
        assert (await client.post("/growth/autopilot/run", headers=viewer_headers, json={})).status_code == 403

    async def test_catalogue_lists_seven_agents_none_can_move_money(self, client, viewer_headers):
        agents = (await client.get("/agents/catalogue", headers=viewer_headers)).json()["data"]
        assert len(agents) == 7 and not any(a["can_move_money"] for a in agents)
        paypal = next(a for a in agents if a["key"] == "paypal_transaction")
        assert {"name": "request_purchase_payment", "requires_approval": True} in paypal["tools"]
