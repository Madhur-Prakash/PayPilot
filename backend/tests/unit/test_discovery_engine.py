"""Product discovery engine: intent parsing, budgets, ranking, comparison, conversation memory
and agent routing. Pure functions - no network, no database, no LLM (GROQ_API_KEY is blank)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.agents.merchant_os import keyword_route
from app.integrations.sponsors.channel3_catalog import parse_catalog_product
from app.services.discovery import comparison
from app.services.discovery.conversation import describe_constraints, merge_constraints
from app.services.discovery.intent import SearchIntent, budget_in_catalog_currency, parse_intent
from app.services.discovery.ranking import rank_products, score_product
from app.services.discovery.service import explain_similarity


def make(pid: str, title: str, price: float, *, brand: str = "Acme", stock: str = "InStock", category: str = "audio",
         ratings: dict | None = None, attrs: dict | None = None, features: list[str] | None = None, retailers: int = 1):
    offers = [{"url": f"https://r{i}.test/{pid}", "domain": f"r{i}.test", "availability": stock,
               "price": {"price": price + i, "currency": "USD", "compare_at_price": None}} for i in range(retailers)]
    return parse_catalog_product({
        "id": pid, "title": title, "brands": [{"id": brand.lower(), "name": brand}],
        "category": {"slug": category, "title": category.title(), "path": []}, "offers": offers,
        "structured_attributes": attrs or {}, "key_features": features or [], "ratings": ratings,
    })


class TestIntent:
    @pytest.mark.parametrize(("text", "query", "max_price", "currency"), [
        ("Find wireless earbuds under ₹5,000.", "wireless earbuds", 5000.0, "INR"),
        ("Find premium office chairs under ₹15,000", "premium office chairs", 15000.0, "INR"),
        ("Find me a laptop under $900 for machine learning", "laptop for machine learning", 900.0, "USD"),
        ("travel mug 1.5k rupees", "travel mug", 1500.0, "INR"),
    ])
    def test_budget_and_product_phrase(self, text, query, max_price, currency):
        intent = parse_intent(text)
        assert intent.query == query and intent.max_price == max_price and intent.budget_currency == currency

    def test_range_brands_and_preferences(self):
        intent = parse_intent("burr coffee grinder between $50 and $150 from Baratza or Fellow on sale")
        assert (intent.min_price, intent.max_price) == (50.0, 150.0)
        assert intent.brands == ["Baratza", "Fellow"] and intent.on_sale and intent.query == "burr coffee grinder"

    def test_use_case_alternatives_and_exclusions(self):
        assert parse_intent("Discover products suitable for a college student").use_case == "a college student"
        assert parse_intent("Find alternatives to Beats Solo Buds").alternatives_to == "Beats Solo Buds"
        avoid = parse_intent("standing desk around 300 dollars not Ikea")
        assert avoid.exclude_brands == ["Ikea"] and (avoid.min_price, avoid.max_price) == (240.0, 360.0)
        assert avoid.query == "standing desk"

    def test_compare_brands(self):
        intent = parse_intent("Compare Sony vs Bose noise cancelling headphones")
        assert intent.compare_brands and intent.brands == ["Sony", "Bose"]


class TestBudgetConversion:
    def test_inr_is_converted_with_a_labelled_reference_rate(self):
        budget = budget_in_catalog_currency(SearchIntent(max_price=5000, budget_currency="INR"), "USD")
        assert budget["converted"] and budget["max_price"] == pytest.approx(56.82, abs=0.01)
        assert "not a live exchange rate" in budget["note"] and budget["rate"] == "88 INR = 1 USD"

    def test_an_unknown_currency_drops_the_filter_and_says_so(self):
        budget = budget_in_catalog_currency(SearchIntent(max_price=500, budget_currency="XYZ"), "USD")
        assert budget["max_price"] is None and "not applied" in budget["note"]

    def test_same_currency_is_untouched(self):
        budget = budget_in_catalog_currency(SearchIntent(max_price=80, budget_currency="USD"), "USD")
        assert budget["max_price"] == 80 and not budget["converted"] and budget["note"] is None


class TestRanking:
    def test_over_budget_and_out_of_stock_rank_lower(self):
        intent = SearchIntent(query="earbuds", max_price=60)
        within = make("a", "Earbuds A", 40)
        over = make("b", "Earbuds B", 90)
        gone = make("c", "Earbuds C", 30, stock="OutOfStock")
        ranked = rank_products([over, gone, within], intent, min_price=None, max_price=60)
        assert ranked[0]["id"] == "a"
        assert any("over budget" in r for r in next(p for p in ranked if p["id"] == "b")["ranking"]["reasons"])

    def test_a_missing_rating_is_left_out_not_scored_zero(self):
        intent = SearchIntent(query="earbuds")
        unrated = score_product(make("a", "A", 40), position=0, total=2, intent=intent, min_price=None, max_price=None)
        assert "rating" not in unrated["components"] and "rating" not in unrated["weights_used"]
        rated = score_product(make("b", "B", 40, ratings={"value": 4.8, "count": 500}), position=0, total=2,
                              intent=intent, min_price=None, max_price=None)
        assert rated["components"]["rating"] == pytest.approx(0.96)

    def test_requested_features_report_what_is_not_listed(self):
        intent = SearchIntent(query="earbuds", attributes=["noise cancelling", "waterproof"])
        result = score_product(make("a", "Earbuds", 40, features=["Active noise cancelling"]), position=0, total=1,
                               intent=intent, min_price=None, max_price=None)
        assert result["components"]["attribute_match"] == 0.5
        assert "Not listed: waterproof" in result["reasons"]


class TestComparison:
    context = {"catalog_median_price": 12.0, "catalog_p75_price": 18.0, "average_order_value": 15.0, "window": "test"}

    def test_value_without_ratings_is_the_lowest_in_stock_price(self):
        a, b = make("a", "A", 30), make("b", "B", 45)
        result = comparison.compare([a, b], merchant_context=self.context)
        assert result["verdicts"]["best_value"]["product_id"] == "a"
        assert "ratings are not available" in result["verdicts"]["best_value"]["basis"]

    def test_unlisted_specs_stay_none(self):
        a = make("a", "A", 30, attrs={"battery-type": ["Rechargeable"]})
        b = make("b", "B", 45)
        matrix = comparison.build_matrix([a, b])
        row = next(r for r in matrix["rows"] if r["key"] == "attr:battery-type")
        assert row["values"] == ["Rechargeable", None]
        rating_row = next(r for r in matrix["rows"] if r["key"] == "rating")
        assert rating_row["values"] == [None, None]

    def test_customer_fit_uses_the_merchants_own_prices(self):
        cheap, mid, premium = make("a", "A", 14), make("b", "B", 60), make("c", "C", 250)
        result = comparison.compare([premium, mid, cheap], merchant_context=self.context)
        assert result["verdicts"]["best_customer_fit"]["product_id"] == "a"
        assert result["verdicts"]["best_alternative"]["product_id"] in {"b", "c"}
        assert result["overall"]["product_id"] == "a"
        assert comparison.deterministic_narrative(result)

    def test_similarity_explains_price_and_brand(self):
        src = make("s", "Source", 50, brand="Beats", attrs={"connectivity": ["Bluetooth"]})
        alt = make("t", "Alt", 40, brand="JBL", attrs={"connectivity": ["Bluetooth"]})
        why = explain_similarity(src, alt)
        assert why["price_difference"] == "-10.00" and why["price_difference_pct"] == "-20.0"
        assert "Brand alternative: JBL (vs Beats)" in why["reasons"] and "Bluetooth" in why["shared_attributes"]


class TestConversationMemory:
    def test_constraints_survive_turns(self):
        first = merge_constraints({}, "Find me a laptop under $900", "USD")
        assert first["product"] == "laptop" and first["budget"]["catalog"]["max"] == 900.0
        second = merge_constraints(first, "Machine learning and development, with 32GB RAM", "USD")
        assert second["product"] == "laptop" and second["budget"]["catalog"]["max"] == 900.0
        assert "32GB RAM" in second["features"]
        assert second["use_case"] == "Machine learning and development"
        lines = describe_constraints(second)
        assert "Looking for: laptop" in lines and any(line.startswith("Budget: USD up to 900") for line in lines)

    def test_inr_budget_is_pinned_in_catalog_currency(self):
        state = merge_constraints({}, "wireless earbuds under ₹5,000", "USD")
        assert state["budget"]["stated"] == {"min": None, "max": 5000.0, "currency": "INR"}
        assert state["budget"]["catalog"]["max"] == pytest.approx(56.82, abs=0.01)


class TestRouting:
    @pytest.mark.parametrize(("message", "agent"), [
        ("Find wireless earbuds under ₹5,000", "product_discovery"),
        ("What new products should I sell next?", "supply_intelligence"),
        ("Run the growth autopilot", "growth_strategy"),
        ("Are my retail prices competitive?", "pricing_intelligence"),
        ("Show my PayPal payments", "paypal_transaction"),
        ("How are my sales this month?", "business_intelligence"),
        ("blue widget", "product_discovery"),
    ])
    def test_keyword_routing(self, message, agent):
        assert keyword_route(message)[0] == agent


def test_decimal_safety():
    """Prices stay Decimal end to end - no float rounding in money."""
    p = make("a", "A", 19.99)
    assert isinstance(p.best_offer.price, Decimal) and p.as_dict()["price"] == "19.99"
