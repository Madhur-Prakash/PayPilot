"""Channel3 against its real response shape (verified live 2026-11-05), the market check's
category consistency rule, and the gear shelf. Network mocked; no keys, no credits."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.merchant import Merchant
from app.integrations.sponsors.channel3 import Channel3Client, attribution_id, parse_products
from app.seed.supply import seed_supply_network
from app.services.integrations import market, shelf


def product(pid: str, title: str, category: str, offers: list[dict], **extra) -> dict:
    return {"id": pid, "title": title, "brands": [{"id": "b1", "name": "Fellow"}],
            "images": [{"url": "https://img.test/raw.jpg", "cleaned_url": "https://cdn.test/clean.png", "is_main_image": True}],
            "category": {"slug": category, "title": category.title()}, "offers": offers,
            "structured_attributes": {}, **extra}


def offer(domain: str, price: float, *, stock: str = "InStock", commission: float | None = 0.06,
          compare_at: float | None = None) -> dict:
    return {"url": f"https://{domain}/p?aff=1", "domain": domain, "availability": stock,
            "price": {"price": price, "currency": "USD", "compare_at_price": compare_at},
            "max_commission_rate": commission}


class TestRealShape:
    def test_the_best_offer_is_the_cheapest_in_stock_one(self):
        body = {"products": [product("p1", "Ode Brew Grinder", "coffee-grinders", [
            offer("cheap.test", 150.0, stock="OutOfStock"),
            offer("fellow.test", 195.0, commission=0.08, compare_at=225.0),
            offer("big.test", 199.0),
        ])], "next_page_token": "x"}
        (item,), skipped = parse_products(body)
        assert skipped == 0
        assert item.price == Decimal("195.00") and item.merchant == "fellow.test"
        assert item.url == "https://fellow.test/p?aff=1" and item.in_stock is True
        assert item.compare_at_price == Decimal("225.00") and item.commission_rate == Decimal("0.0800")
        assert item.image_url == "https://cdn.test/clean.png" and item.category == "coffee-grinders"
        assert item.product_id == "p1" and item.offers_count == 3

    def test_an_out_of_range_commission_is_dropped(self):
        (item,), _ = parse_products({"products": [product("p", "Mug", "travel-mugs", [offer("a.test", 20, commission=7.7)])]})
        assert item.commission_rate is None

    async def test_search_sends_category_price_and_attribution(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"products": []})

        client = Channel3Client(api_key="k", base_url="https://api.trychannel3.com", transport=httpx.MockTransport(handler))
        await client.search("burr grinder", max_price=Decimal("250"), category_ids=["coffee-grinders"],
                            user_id="paypilot-abc123")
        await client.search("burr grinder", user_id="bad id with spaces!")
        body = json.loads(seen[0].content)
        assert body["filters"] == {"price": {"max_price": 250.0}, "category_ids": ["coffee-grinders"]}
        assert seen[0].headers["x-user-id"] == "paypilot-abc123"
        assert "x-user-id" not in seen[1].headers  # an invalid tag is never sent

    def test_attribution_id_is_opaque_and_valid(self):
        tag = attribution_id("5140a403-2b54-48bb-adc7-e2ce19957471")
        assert tag == "paypilot-5140a4032b5448bb" and len(tag) <= 128


class TestConsistentMarketPrice:
    def _offers(self, categories: list[str]):
        body = {"products": [product(f"p{i}", f"Item {i}", c, [offer("x.test", 10 + i)]) for i, c in enumerate(categories)]}
        return parse_products(body)[0]

    def test_unrelated_results_give_no_market_price(self):
        mixed = self._offers(["food-storage-containers", "facial-cleansers", "espresso-machines", "travel-mugs", "coffee-filters"])
        assert market.consistent_offers(mixed) == ([], None)

    def test_a_clear_majority_category_is_used(self):
        offers = self._offers(["travel-mugs"] * 4 + ["coffee-filters"])
        kept, slug = market.consistent_offers(offers)
        assert slug == "travel-mugs" and len(kept) == 4

    async def test_benchmark_explains_when_it_cannot_price(self, monkeypatch):
        body = {"products": [product(f"p{i}", t, c, [offer("x.test", p)]) for i, (t, c, p) in enumerate([
            ("Coffee Bean Canister", "food-storage-containers", 29.95), ("Coffee Bean Face Scrub", "facial-cleansers", 26.0),
            ("Smart Coffee System", "espresso-machines", 5999.0), ("12 oz mug", "travel-mugs", 17.17)])]}
        client = Channel3Client(api_key="k", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
        monkeypatch.setattr(market, "get_channel3", lambda: client)
        data = await market.benchmark("Premium Coffee Beans (12 oz)", expected_price=Decimal("18"))
        assert data["stats"] is None and data["position"] is None
        assert "no consistent market price" in data["note"]


@pytest.fixture
async def shelf_merchant(engine, seeded):
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    async with factory() as s:
        merchant = Merchant(name="Shelf Cafe", slug=f"shelf-cafe-{uuid.uuid4().hex[:8]}", category="cafe", city="Portland")
        s.add(merchant)
        await s.flush()
        await seed_supply_network(s, merchant)
        await s.commit()
        yield s, merchant


class TestShelf:
    async def test_live_shelf_fills_every_slot_and_estimates_honestly(self, shelf_merchant, monkeypatch):
        session, merchant = shelf_merchant
        calls: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            calls.append({"body": body, "user": request.headers.get("x-user-id")})
            slug = body["filters"]["category_ids"][0]
            return httpx.Response(200, json={"products": [
                product(f"{slug}-{i}", f"{slug} {i}", slug, [offer("shop.test", 20 + 10 * i, commission=0.05)])
                for i in range(5)
            ]})

        client = Channel3Client(api_key="k", transport=httpx.MockTransport(handler))
        monkeypatch.setattr(shelf, "get_channel3", lambda: client)
        shelf.clear_cache()

        data = await shelf.build_shelf(session, merchant.id)
        assert data["mode"] == "LIVE" and data["anchor"]["sku"] == "JO-BEAN-012"
        assert [s["key"] for s in data["slots"]] == [s.key for s in shelf.COFFEE_SHELF]
        assert all(len(s["products"]) == shelf.PER_SLOT for s in data["slots"])
        assert {c["user"] for c in calls} == {attribution_id(merchant.id)}
        estimate = data["estimate"]
        assert estimate["buyers_30d"] > 0 and estimate["attach_rate"] == "0.06"
        assert Decimal(estimate["monthly_commission"]) > 0
        assert any("assumed" in a for a in estimate["assumptions"])

        again = await shelf.build_shelf(session, merchant.id)
        assert again["cached"] is True and len(calls) == len(shelf.COFFEE_SHELF)  # no extra credits spent

    async def test_without_a_key_the_shelf_is_labelled_simulated(self, shelf_merchant):
        session, merchant = shelf_merchant
        shelf.clear_cache()
        data = await shelf.build_shelf(session, merchant.id, refresh=True)
        assert data["mode"] == "SIMULATED" and "offline reference" in data["note"]
        grinders = next(s for s in data["slots"] if s["key"] == "grinders")
        assert "grinder" in grinders["products"][0]["title"].lower()

    async def test_the_endpoint_needs_growth_read(self, client, viewer_headers):
        assert (await client.get("/integrations/shelf")).status_code == 401
        response = await client.get("/integrations/shelf", headers=viewer_headers)
        assert response.status_code == 200 and "slots" in response.json()["data"]
