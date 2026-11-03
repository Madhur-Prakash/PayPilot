"""Agent long-term memory.

No cognee here: these cover the parts that decide whether memory is *safe* and
whether it stays out of the way, both of which are pure logic. The parts that
need a real knowledge graph are exercised separately against a live cognee.

The isolation tests are the important ones. Passing ``datasets=[...]`` to cognee
does not isolate anything on its own - with ``ENABLE_BACKEND_ACCESS_CONTROL``
off, a search for one merchant returns another's chunks *stamped with the
requesting merchant's dataset name*, so the leak cannot be spotted downstream.
Only the environment flag and the per-merchant cognee user prevent it, which is
why both are asserted here rather than trusted.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from app.agents import memory as narrative
from app.core.config import settings
from app.integrations.cognee_memory import (
    CogneeMemory,
    MemoryHit,
    MemoryKind,
    _flatten,
    _harden_environment,
)
from app.schemas.agent import GrowthRecommendation, MeasurementVerdict
from app.schemas.common import EvidenceItem

MERCHANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
MERCHANT_B = uuid.UUID("22222222-2222-4222-8222-222222222222")


class TestTenantIsolation:
    def test_each_merchant_gets_its_own_dataset(self):
        store = CogneeMemory()
        assert store.dataset_for(MERCHANT_A) != store.dataset_for(MERCHANT_B)

    def test_each_merchant_gets_its_own_cognee_identity(self):
        """Datasets alone do not isolate; the owning user is what cognee checks."""
        store = CogneeMemory()
        assert store._identity_for(MERCHANT_A) != store._identity_for(MERCHANT_B)

    def test_the_dataset_name_carries_the_merchant_id(self):
        store = CogneeMemory()
        assert str(MERCHANT_A) in store.dataset_for(MERCHANT_A)

    def test_access_control_is_forced_on(self, monkeypatch):
        """The regression test for a real cross-tenant leak.

        With this flag off, cognee keeps one shared vector collection and merchant
        A's search returns merchant B's rows. It must not be possible to turn that
        back on from the environment.
        """
        monkeypatch.setenv("ENABLE_BACKEND_ACCESS_CONTROL", "false")
        _harden_environment()
        assert os.environ["ENABLE_BACKEND_ACCESS_CONTROL"] == "true"

    def test_session_cache_is_off(self, monkeypatch):
        """It costs an LLM round trip per recall and we never pass a session."""
        monkeypatch.setenv("CACHING", "true")
        _harden_environment()
        assert os.environ["CACHING"] == "false"

    def test_cognee_telemetry_is_off_by_default(self, monkeypatch):
        monkeypatch.setattr(settings, "memory_tracing_enabled", False)
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://example.invalid/v1/traces")
        _harden_environment()
        assert os.environ["COGNEE_TRACING_ENABLED"] == "false"
        assert "OTEL_EXPORTER_OTLP_ENDPOINT" not in os.environ


class TestDegradesQuietly:
    """Memory is an enhancement. It may return nothing; it may never raise."""

    def test_recall_is_empty_when_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "memory_enabled", False)
        store = CogneeMemory()
        assert asyncio.run(store.recall(MERCHANT_A, "anything")) == []

    def test_remember_is_a_no_op_when_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "memory_enabled", False)
        store = CogneeMemory()
        assert asyncio.run(store.remember(MERCHANT_A, "something worth keeping")) is False

    def test_an_empty_query_never_reaches_cognee(self, monkeypatch):
        monkeypatch.setattr(settings, "memory_enabled", True)
        store = CogneeMemory()
        # Would raise if it tried to initialise; it must short-circuit first.
        assert asyncio.run(store.recall(MERCHANT_A, "   ")) == []

    def test_a_broken_backend_stays_broken_without_retrying(self, monkeypatch):
        """Retrying a failed import on every agent run would tax every request."""
        monkeypatch.setattr(settings, "memory_enabled", True)
        store = CogneeMemory()
        store._broken = True
        assert store.enabled is False
        assert asyncio.run(store.recall(MERCHANT_A, "anything")) == []

    def test_queueing_a_write_outside_a_loop_does_not_raise(self, monkeypatch):
        monkeypatch.setattr(settings, "memory_enabled", True)
        store = CogneeMemory()
        store.remember_later(MERCHANT_A, "no event loop is running here")

    def test_draining_with_nothing_queued_returns(self):
        asyncio.run(CogneeMemory().drain())


class TestFlatten:
    """cognee returns a discriminated union, and adds variants between releases."""

    class _Entry:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    def test_reads_the_text_field(self):
        hits = _flatten([self._Entry(text="a conclusion", source="graph")])
        assert hits == [MemoryHit(text="a conclusion", source="graph", kind="", score=None)]

    def test_falls_back_through_other_prose_fields(self):
        hits = _flatten([self._Entry(answer="from the answer field", source="session")])
        assert hits[0].text == "from the answer field"

    def test_skips_entries_with_no_prose(self):
        assert _flatten([self._Entry(source="graph", score=0.5)]) == []

    def test_survives_none(self):
        assert _flatten(None) == []

    def test_carries_the_node_set_through_as_the_kind(self):
        hits = _flatten([self._Entry(text="x", node_set=["experiment", "bundle"])])
        assert hits[0].kind == "experiment"


class TestNarrative:
    """A memory that needs its original context to make sense is unrecallable."""

    def _recommendation(self) -> GrowthRecommendation:
        return GrowthRecommendation(
            opportunity="Evening daypart bundle",
            summary="Pair coffee with a snack between 4 and 7pm.",
            evidence=[EvidenceItem(metric="Evening ticket", value="₹142")],
            hypothesis="A food pairing lifts evening ticket size.",
            recommended_action="Launch a filter coffee and vada bundle at 20% off.",
            reasoning="Evening traffic is steady but ticket size trails the day.",
            estimated_impact=18000.0,
            confidence=0.72,
            risk="low",
            requires_approval=True,
        )

    def test_a_recommendation_memory_stands_alone(self, monkeypatch):
        written: list[str] = []
        monkeypatch.setattr(
            narrative.memory,
            "remember_later",
            lambda _m, text, **kw: written.append(text),
        )
        narrative.record_recommendation(
            merchant_id=MERCHANT_A,
            merchant_name="Sharma Cafe",
            question="Why are evenings flat?",
            recommendation=self._recommendation(),
        )
        text = written[0]
        # Merchant, action, money and the question are all present, so the memory
        # is readable months later with no surrounding context.
        assert "Sharma Cafe" in text
        assert "filter coffee and vada" in text
        assert "18,000" in text
        assert "Why are evenings flat?" in text
        assert "Evening ticket: ₹142" in text

    def test_a_rejection_says_not_to_re_propose(self, monkeypatch):
        written: list[str] = []
        monkeypatch.setattr(
            narrative.memory,
            "remember_later",
            lambda _m, text, **kw: written.append(text),
        )
        narrative.record_approval(
            merchant_id=MERCHANT_A,
            merchant_name="Sharma Cafe",
            opportunity="Evening daypart bundle",
            approved=False,
            decided_by="Priya",
            note="Kitchen cannot handle the evening rush.",
        )
        text = written[0]
        assert "rejected" in text
        assert "Kitchen cannot handle" in text
        assert "do not re-propose" in text

    def test_an_approval_does_not_carry_the_rejection_warning(self, monkeypatch):
        written: list[str] = []
        monkeypatch.setattr(
            narrative.memory,
            "remember_later",
            lambda _m, text, **kw: written.append(text),
        )
        narrative.record_approval(
            merchant_id=MERCHANT_A,
            merchant_name="Sharma Cafe",
            opportunity="Evening daypart bundle",
            approved=True,
            decided_by="Priya",
        )
        assert "do not re-propose" not in written[0]

    def test_a_measurement_memory_records_what_was_proved(self, monkeypatch):
        written: list[str] = []
        monkeypatch.setattr(
            narrative.memory,
            "remember_later",
            lambda _m, text, **kw: written.append(text),
        )
        narrative.record_measurement(
            merchant_id=MERCHANT_A,
            merchant_name="Sharma Cafe",
            experiment_name="Evening Bundle",
            verdict=MeasurementVerdict(
                decision="SCALE",
                rationale="Ticket size rose and held for three weeks.",
                learning="Evening customers respond to food pairings, not discounts.",
                confidence=0.86,
            ),
            metrics={"ticket_size": 181},
        )
        text = written[0]
        assert "SCALE" in text
        assert "food pairings" in text
        assert "ticket_size=181" in text

    def test_the_kind_is_tagged_for_narrowed_recall(self, monkeypatch):
        kinds: list[str] = []
        monkeypatch.setattr(
            narrative.memory,
            "remember_later",
            lambda _m, _t, **kw: kinds.append(str(kw.get("kind"))),
        )
        narrative.record_recommendation(
            merchant_id=MERCHANT_A,
            merchant_name="Sharma Cafe",
            question="q",
            recommendation=self._recommendation(),
        )
        assert kinds == [str(MemoryKind.RECOMMENDATION)]


class TestPromptRendering:
    def test_nothing_recalled_renders_nothing(self):
        assert narrative.format_for_prompt([]) == ""

    def test_entries_with_no_text_render_nothing(self):
        assert narrative.format_for_prompt([{"text": ""}, {"text": "   "}]) == ""

    def test_recalled_memory_is_labelled_as_a_prior_conclusion(self):
        """The model must not read last month's guess as today's measurement."""
        rendered = narrative.format_for_prompt([{"text": "Bundles beat discounts."}])
        assert "previously concluded" in rendered
        assert "computed figures win" in rendered
        assert "Bundles beat discounts." in rendered

    def test_the_number_of_entries_is_capped(self):
        hits = [{"text": f"conclusion {i}"} for i in range(20)]
        rendered = narrative.format_for_prompt(hits, limit=3)
        assert "conclusion 2" in rendered
        assert "conclusion 5" not in rendered


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Evening daypart bundle", "evening-daypart-bundle"),
        ("  Spaced   Out  ", "spaced-out"),
        ("₹₹₹", "general"),
        ("", "general"),
    ],
)
def test_tags_are_stable_and_never_empty(value, expected):
    """cognee matches node sets literally, so a blank tag would match nothing."""
    assert narrative._slug(value) == expected
