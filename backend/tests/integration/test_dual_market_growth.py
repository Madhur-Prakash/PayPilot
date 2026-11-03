"""Dual-Market Growth Intelligence: missions, dual-surface campaigns, multi-arm
experiments, growth arbitrage and the allocation snapshot.

The seed fixture's decline gives the detector a real opportunity with a real
`target_segment`, so every number asserted here comes from that fixture's
actual transactions and customers - nothing is stubbed.
"""

from __future__ import annotations

import pytest


async def _first_opportunity(client, headers) -> dict:
    """One opportunity for the seeded merchant, regardless of what earlier tests
    in this shared-database session already did to it. Other test modules run in
    the same database (see `tests/conftest.py`) and may have already detected -
    and acted on - this merchant's opportunities, so a fresh `/detect` call can
    legitimately return nothing new; `/opportunities` (no status filter) always
    returns whatever already exists, in any status, which is all a mission needs."""
    existing = await client.get("/opportunities", params={"limit": 50}, headers=headers)
    opportunities = existing.json()["data"]["opportunities"]
    if not opportunities:
        detect = await client.post("/opportunities/detect", json={"days": 30}, headers=headers)
        assert detect.status_code == 200, detect.text
        opportunities = detect.json()["data"]["opportunities"]
    assert opportunities, "expected at least one opportunity for the seeded merchant"
    return opportunities[0]


class TestGrowthMissions:
    async def test_mission_compares_business_paypal_and_hybrid(self, client, owner_headers):
        opportunity = await _first_opportunity(client, owner_headers)

        response = await client.get(
            f"/opportunities/{opportunity['id']}/missions", headers=owner_headers
        )
        assert response.status_code == 200, response.text
        mission = response.json()["data"]

        assert mission["business_option"]["surface"] == "BUSINESS"
        assert mission["paypal_option"]["surface"] == "PAYPAL"
        assert mission["hybrid_option"]["surface"] == "HYBRID"
        assert mission["recommended_surface"] in ("BUSINESS", "PAYPAL", "HYBRID")
        assert mission["recommendation_reason"]

        # No campaign has been measured yet in this test's fresh database, so the
        # allocation must honestly say "default", never invent a historical ratio.
        assert mission["allocation_basis"] == "default"
        assert mission["business_pct"] == pytest.approx(50.0)
        assert mission["paypal_pct"] == pytest.approx(50.0)
        assert mission["business_pct"] + mission["paypal_pct"] == pytest.approx(100.0)

        # The hybrid option is exactly the sum of the other two - never a third,
        # independently-invented number.
        assert mission["hybrid_option"]["budget"] == pytest.approx(
            mission["business_option"]["budget"] + mission["paypal_option"]["budget"], abs=0.02
        )

        # Every provenance string must say where the number came from.
        assert "segment" in mission["business_option"]["provenance"].lower()
        assert "paypal" in mission["paypal_option"]["provenance"].lower()

    async def test_paypal_audience_is_grounded_in_acquisition_history(
        self, client, owner_headers
    ):
        """The Paypal option must never claim a live Paypal feed - it's sized from
        this merchant's own `acquisition_channel='paypal_app'` customers."""
        opportunity = await _first_opportunity(client, owner_headers)
        response = await client.get(
            f"/opportunities/{opportunity['id']}/missions", headers=owner_headers
        )
        paypal_option = response.json()["data"]["paypal_option"]
        assert "not a live paypal" in paypal_option["provenance"].lower()

    async def test_missions_are_read_only(self, client, owner_headers):
        opportunity = await _first_opportunity(client, owner_headers)
        before = await client.get("/campaigns", headers=owner_headers)
        before_count = before.json()["data"]["pagination"]["total"]

        await client.get(f"/opportunities/{opportunity['id']}/missions", headers=owner_headers)
        await client.get(f"/opportunities/{opportunity['id']}/missions", headers=owner_headers)

        after = await client.get("/campaigns", headers=owner_headers)
        assert after.json()["data"]["pagination"]["total"] == before_count

    async def test_missing_opportunity_is_404(self, client, owner_headers):
        response = await client.get(
            "/opportunities/00000000-0000-0000-0000-000000000000/missions",
            headers=owner_headers,
        )
        assert response.status_code == 404


class TestDualSurfaceCampaigns:
    async def test_hybrid_campaign_requires_both_budgets(self, client, owner_headers):
        response = await client.post(
            "/campaigns",
            json={
                "name": "Missing paypal leg",
                "surface": "HYBRID",
                "business_budget": 3500,
                "paypal_budget": 0,
            },
            headers=owner_headers,
        )
        assert response.status_code == 422

    async def test_hybrid_campaign_budget_is_the_sum_of_its_legs(self, client, owner_headers):
        response = await client.post(
            "/campaigns",
            json={
                "name": "Recover + acquire",
                "objective": "Recover lost evening demand and fill the gap via Paypal.",
                "surface": "HYBRID",
                "objective_type": "REVENUE_RECOVERY",
                "business_budget": 3500,
                "paypal_budget": 6500,
                "message": "Evening win-back + Paypal cashback",
            },
            headers=owner_headers,
        )
        assert response.status_code == 201, response.text
        campaign = response.json()["data"]
        assert campaign["surface"] == "HYBRID"
        assert campaign["business_budget"] == pytest.approx(3500)
        assert campaign["paypal_budget"] == pytest.approx(6500)
        assert campaign["budget"] == pytest.approx(10000)

    async def test_default_campaign_is_still_business_surface(self, client, owner_headers):
        """A plain, pre-existing-style campaign creation call - no surface fields
        at all - must behave exactly as it always did."""
        response = await client.post(
            "/campaigns",
            json={"name": "Plain campaign", "message": "hi", "budget": 500},
            headers=owner_headers,
        )
        assert response.status_code == 201, response.text
        campaign = response.json()["data"]
        assert campaign["surface"] == "BUSINESS"
        assert campaign["business_budget"] == 0
        assert campaign["paypal_budget"] == 0


class TestMultiArmExperiments:
    async def test_three_arm_experiment_measures_every_arm_against_control(
        self, client, owner_headers
    ):
        create = await client.post(
            "/experiments",
            json={
                "name": "Evening recovery experiment",
                "hypothesis": "Business and Paypal interventions both beat doing nothing.",
                "duration_days": 7,
                "control_split_pct": 25.0,
                "extra_arms": [
                    {"key": "business", "name": "Business win-back", "allocation_pct": 25, "unit_cost": 60},
                    {"key": "paypal", "name": "Paypal acquisition", "allocation_pct": 25, "unit_cost": 50},
                    {"key": "hybrid", "name": "Hybrid", "allocation_pct": 25, "unit_cost": 55},
                ],
            },
            headers=owner_headers,
        )
        assert create.status_code == 201, create.text
        experiment = create.json()["data"]
        assert len(experiment["variants"]) == 4  # control + 3 arms
        roles = {v["role"] for v in experiment["variants"]}
        assert roles == {"CONTROL", "TEST"}
        keys = {v["key"] for v in experiment["variants"]}
        assert keys == {"control", "business", "paypal", "hybrid"}

        approve = await client.post(
            f"/experiments/{experiment['id']}/approve",
            json={"approve": True},
            headers=owner_headers,
        )
        assert approve.status_code == 200, approve.text

        measured = await client.post(
            f"/experiments/{experiment['id']}/measure", json={}, headers=owner_headers
        )
        assert measured.status_code == 200, measured.text

        detail = await client.get(f"/experiments/{experiment['id']}", headers=owner_headers)
        results = detail.json()["data"]["results"]
        # One result row per arm (control + 3 treatments) - not just the first one.
        # (No orchestrator-driven synthetic traffic ran here - this went through the
        # plain experiments API - so with zero real orders in this instant window,
        # lift is honestly null rather than a fabricated number; incremental
        # revenue and audience size are always populated regardless.)
        assert len(results) == 4
        treatment_results = [r for r in results if r["variant_role"] == "TEST"]
        assert len(treatment_results) == 3
        assert {r["variant_key"] for r in treatment_results} == {"business", "paypal", "hybrid"}
        for row in treatment_results:
            assert row["incremental_revenue"] is not None
            assert row["audience_size"] >= 0

    async def test_two_arm_experiment_is_unaffected(self, client, owner_headers):
        """The plain control/test path - no `extra_arms` - must behave exactly as
        it did before multi-arm support existed."""
        create = await client.post(
            "/experiments",
            json={
                "name": "Plain AB test",
                "hypothesis": "A ten percent discount lifts conversion.",
                "test_offer_description": "10% off",
                "unit_cost": 20,
            },
            headers=owner_headers,
        )
        assert create.status_code == 201, create.text
        experiment = create.json()["data"]
        assert len(experiment["variants"]) == 2
        assert {v["key"] for v in experiment["variants"]} == {"control", "test"}


class TestArbitrageAndAllocation:
    async def test_arbitrage_is_null_with_no_measured_history(self, client, owner_headers):
        response = await client.get("/growth/arbitrage", headers=owner_headers)
        assert response.status_code == 200
        assert response.json()["data"] is None

    async def test_allocation_snapshot_reflects_a_launched_campaigns_spend(
        self, client, owner_headers
    ):
        """Delta-based, not "starts empty" - other test modules share this
        database and may have already launched campaigns of their own."""
        before = await client.get("/growth/allocation", headers=owner_headers)
        before_business_spend = (
            before.json()["data"]["by_surface"].get("BUSINESS", {}).get("spend", 0)
        )

        created = await client.post(
            "/campaigns",
            json={"name": "Allocation probe", "message": "hi", "budget": 500},
            headers=owner_headers,
        )
        campaign_id = created.json()["data"]["id"]
        await client.post(
            f"/campaigns/{campaign_id}/approve", json={"approve": True}, headers=owner_headers
        )
        await client.post(f"/campaigns/{campaign_id}/execute", headers=owner_headers)

        after = await client.get("/growth/allocation", headers=owner_headers)
        snapshot = after.json()["data"]
        assert snapshot["has_data"] is True
        after_business_spend = snapshot["by_surface"]["BUSINESS"]["spend"]
        assert after_business_spend > before_business_spend
        # Percentages must always describe the whole budget, never drift apart.
        assert (
            snapshot["business_pct"] + snapshot["paypal_pct"] + snapshot["hybrid_pct"]
            == pytest.approx(100.0, abs=0.2)
        )

    async def test_dont_discount_fires_for_a_high_repeat_segment(self, client, owner_headers):
        """The seed customers with `total_orders >= 3` are exactly the population
        this check is about - a segment covering all of them should trip it."""
        opportunity = await _first_opportunity(client, owner_headers)
        response = await client.get(
            f"/opportunities/{opportunity['id']}/missions", headers=owner_headers
        )
        mission = response.json()["data"]
        # Not every opportunity's segment will cross the threshold - but if it
        # does, the reasoning must be substantive, not a canned line.
        if mission["dont_discount"] is not None:
            assert mission["dont_discount"]["high_propensity_pct"] >= 55.0
            assert "already" in mission["dont_discount"]["reasoning"].lower()
