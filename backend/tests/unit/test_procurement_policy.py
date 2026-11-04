"""The deterministic financial and negotiation engine.

These are the numbers money moves on, so they are tested as pure functions:
Decimal in, Decimal out, no database, no model.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.db.models.supply import OfferKind, PaymentTerms, SupplierStrategy
from app.services.supply.buyer_agent import (
    BuyerMove,
    BuyerStrategy,
    OfferSnapshot,
    StrategistMove,
    apply_strategist,
)
from app.services.supply.evaluation import Candidate, evaluate
from app.services.supply.policy import (
    compute_constraints,
    landed_cost,
    margin_pct,
    max_unit_price_for,
    savings,
    shipping_charge,
    validate_buyer_counter,
    validate_offer,
    weighted_average_cost,
)
from app.services.supply.supplier_agent import (
    CounterView,
    RFQView,
    SupplierAgentEngine,
    SupplierPrivatePolicy,
)

D = Decimal


def constraints(**kw):
    base = {"expected_selling_price": "25", "quantity": "100", "target_margin": "0.40",
            "max_delivery_days": 3, "min_reliability": "0.80", "max_rounds": 3}
    base.update(kw)
    return compute_constraints(**base)


class TestConstraints:
    def test_the_product_brief_example(self):
        c = constraints()
        assert c.max_unit_cost == D("15.0000")
        assert c.max_budget == D("1500.00")
        assert isinstance(c.max_budget, Decimal)

    def test_a_tighter_budget_cap_governs(self):
        c = constraints(budget_cap="1200")
        assert c.max_budget == D("1200.00")
        assert c.max_unit_cost == D("12.0000")
        assert c.notes

    def test_the_policy_version_is_a_content_hash(self):
        assert constraints().version == constraints().version
        assert constraints().version != constraints(target_margin="0.35").version

    @pytest.mark.parametrize("bad", [{"expected_selling_price": "0"}, {"quantity": "0"}, {"target_margin": "1"}])
    def test_invalid_inputs_are_refused(self, bad):
        with pytest.raises(ValueError):
            constraints(**bad)

    def test_rounds_are_capped_by_configuration(self):
        assert constraints(max_rounds=99).max_rounds <= 4


class TestLandedCost:
    def test_landed_cost_is_exact_decimal(self):
        landed = landed_cost(unit_price="9.70", quantity="150", shipping="0", tax_rate="0")
        assert landed.total == D("1455.00")
        assert landed.unit_cost == D("9.7000")

    def test_tax_and_shipping_are_included(self):
        landed = landed_cost(unit_price="10", quantity="100", shipping="25", tax_rate="0.08")
        assert landed.subtotal == D("1000.00")
        assert landed.tax == D("80.00")
        assert landed.total == D("1105.00")

    def test_free_shipping_threshold(self):
        assert shipping_charge(flat="25", per_unit="0", free_threshold="1500", subtotal="1600", quantity=100) == 0
        assert shipping_charge(flat="25", per_unit="0.5", free_threshold="1500", subtotal="900", quantity=100) == D("75.00")

    def test_the_ceiling_price_respects_shipping_and_tax(self):
        c = constraints()
        price = max_unit_price_for(constraints=c, shipping="100", tax_rate="0")
        assert landed_cost(unit_price=price, quantity="100", shipping="100", tax_rate="0").total <= c.max_budget


class TestOfferValidation:
    def test_an_offer_inside_policy_is_valid(self):
        check = validate_offer(constraints=constraints(), unit_price="14", quantity="100", shipping="0",
                               tax_rate="0", lead_time_days=2, reliability="0.95")
        assert check.status == "VALID" and check.within_policy

    def test_over_ceiling_slow_and_unreliable_offers_are_out_of_policy(self):
        check = validate_offer(constraints=constraints(), unit_price="16", quantity="100", shipping="0",
                               tax_rate="0", lead_time_days=9, reliability="0.5")
        codes = {e["code"] for e in check.errors}
        assert check.status == "OUT_OF_POLICY"
        assert {"OVER_MAX_UNIT_COST", "OVER_BUDGET", "TOO_SLOW", "BELOW_MIN_RELIABILITY"} <= codes

    def test_partial_quantity_is_out_of_policy(self):
        check = validate_offer(constraints=constraints(), unit_price="12", quantity="60", shipping="0",
                               tax_rate="0", lead_time_days=2, reliability="0.9")
        assert any(e["code"] == "PARTIAL_QUANTITY" for e in check.errors)

    def test_a_claimed_total_that_does_not_add_up_is_invalid(self):
        """How a hallucinated or tampered total is caught."""
        check = validate_offer(constraints=constraints(), unit_price="10", quantity="100", shipping="0",
                               tax_rate="0", lead_time_days=2, reliability="0.9", claimed_total="900.00")
        assert check.status == "INVALID"
        assert check.errors[0]["code"] == "TOTAL_MISMATCH"

    def test_more_than_the_supplier_holds_is_invalid(self):
        check = validate_offer(constraints=constraints(), unit_price="10", quantity="100", shipping="0",
                               tax_rate="0", lead_time_days=2, reliability="0.9", available_quantity="50")
        assert check.status == "INVALID"

    def test_non_positive_values_are_invalid(self):
        check = validate_offer(constraints=constraints(), unit_price="0", quantity="100", shipping="0",
                               tax_rate="0", lead_time_days=2, reliability="0.9")
        assert check.status == "INVALID"


class TestBuyerCounterBounds:
    def test_a_counter_above_the_ceiling_is_refused_not_clamped(self):
        price, reason = validate_buyer_counter(proposed_unit_price="16", supplier_unit_price="17", ceiling_unit_price="15")
        assert price is None and "ceiling" in reason

    def test_a_counter_at_or_above_the_ask_is_refused(self):
        price, _ = validate_buyer_counter(proposed_unit_price="12", supplier_unit_price="12", ceiling_unit_price="15")
        assert price is None

    def test_a_counter_inside_the_bounds_is_accepted(self):
        price, _ = validate_buyer_counter(proposed_unit_price="11.5", supplier_unit_price="12", ceiling_unit_price="15")
        assert price == D("11.5000")

    def test_an_llm_proposal_outside_policy_is_recorded_and_refused(self):
        offer = OfferSnapshot(session_id="s1", supplier_label="X", unit_price=D("12"), quantity=D("100"),
                              shipping=D("0"), tax_rate=D("0"), lead_time_days=2, landed_total=D("1200"),
                              landed_unit_cost=D("12"), within_policy=True)
        move = BuyerMove(kind="COUNTER", unit_price=D("10"), quantity=D("100"))
        result = apply_strategist(move, StrategistMove(session_id="s1", counter_unit_price=99.0, message="Deal?"),
                                  offer=offer, ceiling=D("15"))
        assert result.unit_price == D("10")
        assert result.proposed_by == "BUYER_STRATEGY"
        assert result.ai_proposal["accepted"] is False

    def test_an_llm_proposal_inside_policy_is_used_and_labelled(self):
        offer = OfferSnapshot(session_id="s1", supplier_label="X", unit_price=D("12"), quantity=D("100"),
                              shipping=D("0"), tax_rate=D("0"), lead_time_days=2, landed_total=D("1200"),
                              landed_unit_cost=D("12"), within_policy=True)
        move = BuyerMove(kind="COUNTER", unit_price=D("10"), quantity=D("100"))
        result = apply_strategist(move, StrategistMove(session_id="s1", counter_unit_price=10.75),
                                  offer=offer, ceiling=D("15"))
        assert result.unit_price == D("10.7500")
        assert result.proposed_by == "LLM"


class TestBuyerStrategy:
    def test_the_buyer_holds_when_the_target_is_met(self):
        c = constraints()
        offer = OfferSnapshot(session_id="s", supplier_label="X", unit_price=D("12"), quantity=D("100"),
                              shipping=D("0"), tax_rate=D("0"), lead_time_days=2, landed_total=D("1200"),
                              landed_unit_cost=D("12"), within_policy=True)
        assert BuyerStrategy(c).counter(offer, round_number=1, best_competing_landed_unit=None).kind == "HOLD"

    def test_a_counter_never_exceeds_the_ceiling(self):
        c = constraints()
        offer = OfferSnapshot(session_id="s", supplier_label="X", unit_price=D("20"), quantity=D("100"),
                              shipping=D("40"), tax_rate=D("0"), lead_time_days=9, landed_total=D("2040"),
                              landed_unit_cost=D("20.40"), within_policy=False)
        move = BuyerStrategy(c).counter(offer, round_number=3, best_competing_landed_unit=D("14"))
        assert move.kind == "COUNTER"
        assert move.unit_price <= D("15")
        assert move.request_expedite and move.request_free_shipping and move.competitive_pressure


def supplier_policy(**kw) -> SupplierPrivatePolicy:
    base = {
        "agent_key": "supplier.test", "display_name": "Test", "strategy": SupplierStrategy.FLEXIBLE_VOLUME,
        "currency": "USD", "list_price": D("10.90"), "floor_price": D("9.70"), "available_quantity": D("600"),
        "min_order_quantity": D("60"), "lead_time_days": 2, "shipping_flat": D("40"), "shipping_per_unit": D("0"),
        "free_shipping_threshold": D("0"), "tax_rate": D("0"), "expedite_fee": D("35"), "expedite_days": 1,
        "payment_terms": PaymentTerms.NET_30, "opening_markup": D("0.06"), "concession_rate": D("0.4"),
        "max_rounds": 3, "volume_breaks": ((D("150"), D("0.04")),),
    }
    base.update(kw)
    return SupplierPrivatePolicy(**base)


RFQ = RFQView(rfq_reference="RFQ-1", sku="JO-BEAN-012", product_name="Beans", quantity=D("150"), unit="bags",
              required_within_days=3)


class TestSupplierAgent:
    def test_the_rfq_view_carries_no_merchant_limits(self):
        """A supplier cannot condition on the budget: its input type does not contain it."""
        assert not {"max_budget", "max_unit_cost", "target_unit_cost"} & set(RFQView.__dataclass_fields__)

    def test_the_opening_quote_applies_markup_and_volume_break(self):
        move = SupplierAgentEngine(supplier_policy()).respond_to_rfq(RFQ)
        assert move.kind == OfferKind.QUOTE
        assert move.unit_price == D("11.0918")  # 10.90 x 1.06 x 0.96

    def test_a_supplier_never_goes_below_its_floor(self):
        engine = SupplierAgentEngine(supplier_policy(strategy=SupplierStrategy.PREMIUM_RELIABLE))
        last = engine.respond_to_rfq(RFQ)
        for round_number in (1, 2, 3):
            last = engine.respond_to_counter(CounterView(round=round_number, unit_price=D("1"), quantity=D("150")), last)
            assert last.unit_price >= D("9.70")

    def test_limited_stock_offers_a_partial_quantity(self):
        engine = SupplierAgentEngine(supplier_policy(strategy=SupplierStrategy.LOW_PRICE_LIMITED, available_quantity=D("90")))
        assert engine.respond_to_rfq(RFQ).quantity == D("90")

    def test_out_of_stock_declines(self):
        engine = SupplierAgentEngine(supplier_policy(available_quantity=D("0")))
        assert engine.respond_to_rfq(RFQ).kind == OfferKind.DECLINE

    def test_a_flexible_supplier_waives_shipping_when_asked(self):
        engine = SupplierAgentEngine(supplier_policy())
        quote = engine.respond_to_rfq(RFQ)
        reply = engine.respond_to_counter(
            CounterView(round=1, unit_price=D("9.50"), quantity=D("150"), request_free_shipping=True), quote
        )
        assert reply.shipping == 0 and reply.shipping_waived

    def test_accepting_a_counter_at_or_above_the_floor(self):
        engine = SupplierAgentEngine(supplier_policy())
        quote = engine.respond_to_rfq(RFQ)
        reply = engine.respond_to_counter(CounterView(round=3, unit_price=D("9.80"), quantity=D("150")), quote)
        assert reply.kind == OfferKind.ACCEPT and reply.unit_price == D("9.8000")


def candidate(name, landed, lead, reliability, *, within=True, terms=PaymentTerms.NET_30, quality="0.9"):
    return Candidate(session_id=name, offer_id=name, supplier_agent_id=name, agent_key=f"supplier.{name}",
                     supplier_name=name, unit_price=landed / 150, quantity=D("150"), shipping=D("0"), tax=D("0"),
                     landed_total=landed, landed_unit_cost=landed / 150, lead_time_days=lead, payment_terms=terms,
                     reliability=D(reliability), quality=D(quality), within_policy=within,
                     violations=() if within else ("Delivers in 9 days",))


class TestEvaluation:
    def test_only_eligible_offers_can_win(self):
        c = constraints(expected_selling_price="18", quantity="150")
        result = evaluate([candidate("cheap", D("900"), 9, "0.8", within=False),
                           candidate("ok", D("1455"), 2, "0.9")], c)
        assert result.winner.supplier_name == "ok"
        assert result.ineligible[0]["supplier_name"] == "cheap"

    def test_scoring_is_deterministic(self):
        c = constraints(expected_selling_price="18", quantity="150")
        offers = [candidate("a", D("1570.80"), 2, "0.97", quality="0.95"), candidate("c", D("1455"), 2, "0.92")]
        assert evaluate(offers, c).winner.supplier_name == evaluate(list(reversed(offers)), c).winner.supplier_name

    def test_no_eligible_offer_recommends_nothing(self):
        c = constraints()
        result = evaluate([candidate("x", D("2000"), 9, "0.5", within=False)], c)
        assert result.winner is None and "No supplier" in result.explanation


class TestOutcomes:
    def test_weighted_average_cost(self):
        assert weighted_average_cost(on_hand_before="42", cost_before="11.60", received_quantity="150",
                                     received_unit_cost="9.70") == D("10.1156")

    def test_margin_and_savings(self):
        assert margin_pct(price="18", unit_cost="9.70") == D("46.11")
        saved, percent = savings(baseline_total="1703.65", final_total="1455.00")
        assert saved == D("248.65") and percent == D("14.60")
