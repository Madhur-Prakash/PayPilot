"""Analytics determinism, tool authorization, and the full growth loop.

The seed builds 60 days where the recent 30 are deliberately worse than the prior
30, so these assertions check real period-over-period behaviour rather than
whatever the data happened to contain.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.permissions import Role, permissions_for_role
from app.db.models.agent import AgentRunStatus
from app.services.analytics.service import AnalyticsService
from app.tools import registry
from app.tools.base import ToolContext


class TestAnalyticsDeterminism:
    async def test_the_same_query_returns_the_same_numbers(self, session, seeded):
        """Analytics must be reproducible - the agents reason over these figures."""
        service = AnalyticsService(session, seeded["merchant_id"])
        period = await service.resolve_period(days=30, end=seeded["anchor"])

        first, _, _ = await service.kpis(period)
        second, _, _ = await service.kpis(period)
        assert [k.value for k in first] == [k.value for k in second]

    async def test_revenue_equals_orders_times_aov(self, session, seeded):
        """The growth graph presents this as arithmetic, so it had better be."""
        service = AnalyticsService(session, seeded["merchant_id"])
        period = await service.resolve_period(days=30, end=seeded["anchor"])
        kpis, summary, _ = await service.kpis(period)

        by_key = {k.key: k.value for k in kpis}
        assert by_key["revenue"] == pytest.approx(by_key["orders"] * by_key["aov"], rel=0.01)
        assert summary.revenue == pytest.approx(by_key["revenue"])

    async def test_the_recent_period_is_measurably_worse(self, session, seeded):
        service = AnalyticsService(session, seeded["merchant_id"])
        period = await service.resolve_period(days=30, end=seeded["anchor"])
        kpis, current, previous = await service.kpis(period)

        assert current.revenue < previous.revenue
        revenue = next(k for k in kpis if k.key == "revenue")
        assert revenue.change_pct is not None and revenue.change_pct < 0

    async def test_a_decline_is_flagged_as_an_anomaly(self, session, seeded):
        service = AnalyticsService(session, seeded["merchant_id"])
        period = await service.resolve_period(days=30, end=seeded["anchor"])
        anomalies = await service.detect_anomalies(period)
        assert anomalies, "a large revenue drop should surface as an anomaly"
        assert any(a.metric == "revenue" for a in anomalies)

    async def test_daypart_revenue_sums_to_the_total(self, session, seeded):
        service = AnalyticsService(session, seeded["merchant_id"])
        period = await service.resolve_period(days=30, end=seeded["anchor"])
        _, summary, _ = await service.kpis(period)
        dayparts = await service.daypart_breakdown(period)

        assert sum(d.revenue for d in dayparts) == pytest.approx(summary.revenue, rel=0.001)
        assert sum(d.revenue_share_pct for d in dayparts) == pytest.approx(100.0, abs=0.5)

    async def test_analytics_are_merchant_scoped(self, session, seeded):
        mine = AnalyticsService(session, seeded["merchant_id"])
        theirs = AnalyticsService(session, seeded["other_merchant_id"])
        period = await mine.resolve_period(days=30, end=seeded["anchor"])

        _, my_summary, _ = await mine.kpis(period)
        _, their_summary, _ = await theirs.kpis(period)
        # The rival's seed uses half the ticket value.
        assert my_summary.revenue == pytest.approx(their_summary.revenue * 2, rel=0.01)


class TestToolAuthorization:
    def _context(self, session, merchant_id, role: Role) -> ToolContext:
        return ToolContext(
            session=session,
            merchant_id=merchant_id,
            merchant_name="Test Cafe",
            user_id=uuid.uuid4(),
            permissions=frozenset(str(p) for p in permissions_for_role(role)),
        )

    async def test_a_tool_runs_for_a_permitted_role(self, session, seeded):
        ctx = self._context(session, seeded["merchant_id"], Role.OWNER)
        result = await registry.execute("get_sales_summary", ctx, {"days": 30})
        assert result.ok, result.error
        assert "metrics" in result.data
        assert result.summary

    async def test_a_tool_is_denied_without_the_permission(self, session, seeded):
        """A Viewer holds dashboard:read but not campaign:create."""
        ctx = self._context(session, seeded["merchant_id"], Role.VIEWER)
        result = await registry.execute(
            "create_campaign", ctx, {"name": "Nope", "objective": "should be denied"}
        )
        assert not result.ok
        assert "permission" in (result.error or "").lower()

    async def test_invalid_arguments_fail_cleanly(self, session, seeded):
        ctx = self._context(session, seeded["merchant_id"], Role.OWNER)
        result = await registry.execute("get_sales_summary", ctx, {"days": 9999})
        assert not result.ok
        assert "invalid arguments" in (result.error or "").lower()

    async def test_an_unknown_tool_does_not_raise(self, session, seeded):
        ctx = self._context(session, seeded["merchant_id"], Role.OWNER)
        result = await registry.execute("definitely_not_a_tool", ctx, {})
        assert not result.ok
        assert "unknown tool" in (result.error or "").lower()

    async def test_execute_campaign_is_gated_on_approval_not_permission_alone(
        self, session, seeded
    ):
        """Even with campaign:execute, the tool refuses - approval runs through the API."""
        ctx = self._context(session, seeded["merchant_id"], Role.OWNER)
        result = await registry.execute("execute_campaign", ctx, {})
        assert not result.ok
        assert "approval" in (result.error or "").lower()

    async def test_tools_cannot_be_pointed_at_another_merchant(self, session, seeded):
        """The tool takes no merchant argument; scope comes from the context."""
        mine = self._context(session, seeded["merchant_id"], Role.OWNER)
        theirs = self._context(session, seeded["other_merchant_id"], Role.OWNER)

        my_result = await registry.execute("get_sales_summary", mine, {"days": 30})
        their_result = await registry.execute("get_sales_summary", theirs, {"days": 30})
        assert my_result.data["summary"]["revenue"] != their_result.data["summary"]["revenue"]


class TestGrowthLoopEndToEnd:
    """Detect -> investigate -> approve -> execute -> measure, over HTTP."""

    async def test_detection_produces_quantified_opportunities(self, client, owner_headers):
        response = await client.post(
            "/opportunities/detect", json={"days": 30}, headers=owner_headers
        )
        assert response.status_code == 200
        radar = response.json()["data"]
        assert radar["opportunities"], "the seeded decline should produce an opportunity"
        for opportunity in radar["opportunities"]:
            assert opportunity["estimated_value_monthly"] > 0
            assert 0 <= opportunity["confidence"] <= 1
            assert opportunity["evidence"], "every opportunity must carry its evidence"

    async def test_detection_is_idempotent(self, client, owner_headers):
        first = await client.post("/opportunities/detect", json={"days": 30}, headers=owner_headers)
        second = await client.post(
            "/opportunities/detect", json={"days": 30}, headers=owner_headers
        )
        first_keys = sorted(o["key"] for o in first.json()["data"]["opportunities"])
        second_keys = sorted(o["key"] for o in second.json()["data"]["opportunities"])
        assert first_keys == second_keys

    async def test_the_growth_graph_never_claims_causation(self, client, owner_headers):
        response = await client.get("/growth/graph", params={"days": 30}, headers=owner_headers)
        assert response.status_code == 200
        graph = response.json()["data"]

        allowed = {"decomposes_into", "correlates_with", "evidenced_by"}
        assert {edge["relationship"] for edge in graph["edges"]} <= allowed
        assert "not causal" in graph["caveat"].lower()

        text = " ".join(node["interpretation"].lower() for node in graph["nodes"])
        for forbidden in ("caused by", "because of", "is causing"):
            assert forbidden not in text

    async def test_investigation_runs_the_graph_and_records_a_trace(self, client, owner_headers):
        response = await client.post(
            "/agents/investigate",
            json={"question": "Why did revenue fall?", "days": 30},
            headers=owner_headers,
        )
        assert response.status_code == 200, response.text
        payload = response.json()["data"]
        run = payload["run"]

        assert run["status"] in (AgentRunStatus.COMPLETED, AgentRunStatus.AWAITING_APPROVAL)
        assert len(run["steps"]) >= 5, "the workflow should record each node it ran"
        assert len(run["tools_used"]) >= 4
        # Steps must not repeat - a state-channel bug would duplicate them.
        assert len(run["steps"]) == len({step["sequence"] for step in run["steps"]})
        # Raw model reasoning must never be exposed.
        assert "reasoning_trace" not in run
        assert "chain_of_thought" not in run
        assert "never recorded" in run["trace_disclaimer"].lower()

    async def test_the_recommendation_is_deterministic_without_an_llm(self, client, owner_headers):
        """No GROQ key is set in tests, so the figures come from the detector."""
        response = await client.post(
            "/agents/investigate", json={"days": 30}, headers=owner_headers
        )
        payload = response.json()["data"]
        assert payload["run"]["used_fallback"] is True

        recommendation = payload["recommendation"]
        assert recommendation is not None
        assert recommendation["estimated_impact"] > 0
        assert recommendation["requires_approval"] is True
        assert recommendation["evidence"]

    async def test_approval_creates_a_campaign_and_a_controlled_experiment(
        self, client, owner_headers
    ):
        await client.post("/opportunities/detect", json={"days": 30}, headers=owner_headers)
        radar = await client.get("/opportunities", headers=owner_headers)
        opportunity = radar.json()["data"]["opportunities"][0]

        approved = await client.post(
            f"/agents/opportunities/{opportunity['id']}/approve",
            json={"approve": True, "execute_now": True, "note": "test"},
            headers=owner_headers,
        )
        assert approved.status_code == 200, approved.text
        outcome = approved.json()["data"]

        assert outcome["approved"] is True
        assert outcome["campaign_id"] and outcome["experiment_id"]
        assert outcome["steps"]

        # The experiment must have a real control arm, not a single group.
        experiment = await client.get(
            f"/experiments/{outcome['experiment_id']}", headers=owner_headers
        )
        variants = experiment.json()["data"]["variants"]
        roles = {variant["role"] for variant in variants}
        assert roles == {"CONTROL", "TEST"}
        assert all(variant["audience_size"] > 0 for variant in variants)

    async def test_rejecting_an_opportunity_creates_nothing(self, client, owner_headers):
        await client.post("/opportunities/detect", json={"days": 30}, headers=owner_headers)
        radar = await client.get("/opportunities", headers=owner_headers)
        opportunities = radar.json()["data"]["opportunities"]
        target = opportunities[-1]

        response = await client.post(
            f"/agents/opportunities/{target['id']}/approve",
            json={"approve": False, "note": "not now"},
            headers=owner_headers,
        )
        assert response.status_code == 200
        outcome = response.json()["data"]
        assert outcome["approved"] is False
        assert outcome["campaign_id"] is None
        assert outcome["experiment_id"] is None
        assert outcome["status"] == "DISMISSED"


class TestProvenanceLabelling:
    """Nothing may present baseline or preview data as if it were live."""

    async def test_competitor_data_is_labelled(self, client, owner_headers):
        response = await client.get("/competitors/intelligence", headers=owner_headers)
        provenance = response.json()["data"]["provenance"]
        assert provenance["is_simulated"] is True
        assert "no competitor platform" in provenance["note"].lower()

    async def test_campaign_delivery_is_labelled(self, client, owner_headers):
        created = await client.post(
            "/campaigns", json={"name": "Labelled", "objective": "x"}, headers=owner_headers
        )
        detail = created.json()["data"]
        assert detail["is_simulated"] is True
        assert "no messaging provider" in detail["provenance"]["note"].lower()

    async def test_the_health_endpoint_is_honest_about_integrations(self, client):
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["checks"]["llm"] == "not_configured"
        assert "without any external integration" in data["note"].lower()
