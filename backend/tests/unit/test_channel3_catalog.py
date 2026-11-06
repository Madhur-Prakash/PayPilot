"""The Channel3 catalog client against its real response shapes (verified live 2026-11-06).

Network is mocked with ``httpx.MockTransport``; no key and no credits are used. These
cover normalisation (nothing invented), request building (documented filters only),
retries with backoff, and the no-key behaviour (an error, never fake products).
"""

from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest

from app.integrations.sponsors.base import SponsorError, SponsorRequestError
from app.integrations.sponsors.channel3_catalog import (
    Channel3Catalog,
    Channel3NotConfiguredError,
    build_filters,
    parse_catalog_page,
    parse_catalog_product,
    parse_conversation_turn,
)


def offer(domain: str, price: float, *, stock: str = "InStock", compare_at: float | None = None,
          commission: float | None = 0.05) -> dict:
    return {"url": f"https://buy.trychannel3.com/{domain}", "domain": domain, "availability": stock, "condition": "new",
            "price": {"price": price, "currency": "USD", "compare_at_price": compare_at},
            "max_commission_rate": commission, "dimensions": None}


def product(pid: str = "xSuO8lZ", title: str = "Beats Solo Buds", **extra) -> dict:
    body = {
        "id": pid, "title": title, "description": "True wireless earbuds.",
        "brands": [{"id": "ainn", "name": "Beats"}],
        "images": [{"url": "https://cdn.test/raw.jpg", "cleaned_url": "https://cdn.test/clean.png", "is_main_image": True,
                    "shot_type": "hero", "alt_text": "Earbuds"}],
        "category": {"slug": "in-ear-headphones", "title": "In-Ear Headphones",
                     "path": [{"slug": "electronics", "title": "Electronics"}, {"slug": "audio", "title": "Audio"}]},
        "gender": None, "age": None, "materials": [], "key_features": ["Dual-layer drivers", "USB-C charging"],
        "offers": [offer("samsclub.com", 69.95, compare_at=79.95, commission=0.118), offer("adorama.com", 79.95)],
        "variants": None,
        "structured_attributes": {"connectivity-technology": ["Bluetooth", "Wireless"], "microphone-type": ["Built-in"]},
        "ratings": {"value": 3.6, "count": 992, "source_count": 1},
    }
    body.update(extra)
    return body


class TestNormalisation:
    def test_real_shape_is_kept_faithfully(self):
        p = parse_catalog_product(product())
        assert p is not None
        assert p.brand == "Beats" and p.category_slug == "in-ear-headphones" and p.category_path == ["Electronics", "Audio"]
        assert p.best_offer.domain == "samsclub.com" and p.best_offer.price == Decimal("69.95")
        assert p.best_offer.discount_pct == Decimal("12.5")
        assert p.min_price == Decimal("69.95") and p.max_price == Decimal("79.95")
        assert p.image_url == "https://cdn.test/clean.png"
        assert p.ratings == {"value": 3.6, "count": 992}
        out = p.as_dict()
        assert out["retailers"] == ["samsclub.com", "adorama.com"] and out["offers_count"] == 2
        assert out["structured_attributes"]["connectivity-technology"] == ["Bluetooth", "Wireless"]

    def test_missing_ratings_and_specs_are_not_invented(self):
        p = parse_catalog_product(product(ratings=None, structured_attributes={}, key_features=[]))
        assert p.ratings is None and p.structured_attributes == {} and p.key_features == []
        assert p.as_dict()["ratings"] is None

    def test_out_of_stock_offers_lose_to_in_stock_ones(self):
        p = parse_catalog_product(product(offers=[offer("cheap.test", 10, stock="OutOfStock"), offer("ok.test", 20)]))
        assert p.best_offer.domain == "ok.test" and p.in_stock is True

    def test_a_product_without_id_or_title_is_skipped_and_counted(self):
        products, token, skipped = parse_catalog_page({"products": [product(), {"title": "no id"}, product(pid="y", title="")],
                                                       "next_page_token": "abc"})
        assert [p.id for p in products] == ["xSuO8lZ"] and skipped == 2 and token == "abc"

    def test_variants_and_offer_urls(self):
        variants = {"options": [{"name": "Color", "values": [
            {"label": "Black", "exists": True, "available": "InStock", "thumbnail_url": None, "product_id": None},
            {"label": "Red", "exists": False, "available": None, "thumbnail_url": None, "product_id": "p2"}]}],
            "selected": [{"name": "Color", "label": "Black"}]}
        p = parse_catalog_product(product(variants=variants))
        assert p.variants["options"][0]["values"][1]["product_id"] == "p2"
        assert p.as_dict(include_offer_urls=False)["url"] == ""

    def test_conversation_turn_parts(self):
        turn = parse_conversation_turn({
            "conversation_id": "conv_1", "turn_id": "turn_1", "usage": {"credits_charged": 2, "searches_run": 1},
            "message": {"role": "assistant", "suggestions": ["Only ANC models"], "parts": [
                {"type": "text", "text": "Here are some options."},
                {"type": "tool", "tool_name": "search_products", "input": {"query": "earbuds"},
                 "output": {"products": [product(), product(pid="second", title="Other buds")]}},
            ]},
        })
        assert turn.conversation_id == "conv_1" and turn.text == "Here are some options."
        assert [p.id for p in turn.products] == ["xSuO8lZ", "second"]
        assert turn.suggestions == ["Only ANC models"] and turn.usage == {"credits_charged": 2, "searches_run": 1}
        assert turn.searches[0]["tool"] == "search_products" and turn.searches[0]["results"] == 2


class TestFilters:
    def test_only_documented_keys_and_never_color_in_attributes(self):
        filters = build_filters(min_price=10, max_price=Decimal("56.82"), brand_ids=["b1"], category_ids=["audio"],
                                website_ids=["bestbuy.com"], include_out_of_stock=True, on_sale=True,
                                attributes={"color": ["Red"], "material": ["Leather"]})
        assert filters == {"price": {"min_price": 10.0, "max_price": 56.82}, "brand_ids": ["b1"], "category_ids": ["audio"],
                           "website_ids": ["bestbuy.com"], "availability": ["InStock", "OutOfStock"], "sale": "on_sale",
                           "attributes": {"material": ["Leather"]}}

    def test_empty_inputs_give_no_filters(self):
        assert build_filters() == {}


def _client(handler, **kwargs) -> Channel3Catalog:
    async def no_sleep(_: float) -> None:
        return None

    return Channel3Catalog(api_key="test-key", base_url="https://api.trychannel3.com",
                           transport=httpx.MockTransport(handler), sleep=no_sleep, **kwargs)


class TestRequests:
    async def test_search_sends_locale_filters_and_attribution(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"products": [product()], "next_page_token": None})

        page = await _client(handler).search("wireless earbuds", filters={"price": {"max_price": 56.82}}, limit=50,
                                             user_id="paypilot-abc")
        body = json.loads(seen[0].content)
        assert seen[0].url.path == "/v1/search" and seen[0].headers["x-api-key"] == "test-key"
        assert seen[0].headers["x-user-id"] == "paypilot-abc"
        assert body["limit"] == 30  # capped at the documented maximum
        assert body["config"] == {"currency": "USD", "country": "US", "mode": "default"}
        assert body["filters"] == {"price": {"max_price": 56.82}}
        assert len(page.products) == 1 and "x-api-key" not in json.dumps(page.request)

    async def test_similar_detail_lookup_and_taxonomy_paths(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            path = request.url.path
            if path == "/v1/similar":
                return httpx.Response(200, json={"products": [product(pid="xSuO8lZ"), product(pid="alt1", title="Alt")]})
            if path.startswith("/v1/products/"):
                return httpx.Response(200, json=product())
            if path == "/v1/lookup":
                return httpx.Response(200, json={"product": product(pid="looked")})
            if path == "/v1/categories/search":
                return httpx.Response(200, json={"categories": [{"slug": "office-chairs", "title": "Office Chairs", "path": []}]})
            if path == "/v1/brands/search":
                return httpx.Response(200, json={"brands": [{"id": "s1", "name": "Sony"}]})
            return httpx.Response(404)

        client = _client(handler)
        similar = await client.similar("xSuO8lZ", limit=5)
        assert [p.id for p in similar.products] == ["alt1"]  # the source is never its own alternative
        detail = await client.product("xSuO8lZ", selected_options={"Color": "Black"})
        assert detail.id == "xSuO8lZ" and seen[1].url.params["option_Color"] == "Black"
        assert (await client.lookup("https://www.example.com/p/123")).id == "looked"
        assert (await client.categories("office chair"))[0]["slug"] == "office-chairs"
        assert (await client.brands("Sony"))[0]["id"] == "s1"

    async def test_transient_errors_are_retried_with_backoff(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] < 3:
                return httpx.Response(503, json={"detail": "busy"})
            return httpx.Response(200, json={"products": []})

        page = await _client(handler, max_retries=2).search("mugs")
        assert calls["n"] == 3 and page.products == []

    async def test_client_errors_are_not_retried_and_never_echo_the_key(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(401, json={"detail": "bad key test-key"})

        with pytest.raises(SponsorError) as caught:
            await _client(handler, max_retries=3).search("mugs")
        assert calls["n"] == 1 and caught.value.status_code == 401
        assert "test-key" not in str(caught.value)

    async def test_a_turn_is_never_retried(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(502)

        with pytest.raises(SponsorError):
            await _client(handler, max_retries=3).conversation_turn("laptop under $900")
        assert calls["n"] == 1

    async def test_no_key_raises_instead_of_inventing_products(self):
        client = Channel3Catalog(api_key="", base_url="https://api.trychannel3.com")
        assert client.configured is False and client.mode == "NOT_CONFIGURED"
        with pytest.raises(Channel3NotConfiguredError) as caught:
            await client.search("earbuds")
        assert caught.value.status_code == 503 and "CHANNEL3_API_KEY" in str(caught.value)

    async def test_bad_inputs_are_rejected_before_any_call(self):
        client = _client(lambda r: httpx.Response(500))
        with pytest.raises(SponsorRequestError):
            await client.search("   ")
        with pytest.raises(SponsorRequestError):
            await client.product("../../etc/passwd")
        with pytest.raises(SponsorRequestError):
            await client.lookup("ftp://example.com/x")
