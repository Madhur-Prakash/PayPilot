"""Agent long-term memory (Postgres + pgvector).

The store is exercised for real against the suite's SQLite database, where
recall ranks by the same cosine similarity pgvector computes in Postgres. The
isolation tests are the important ones: one merchant's recall must never return
another merchant's memory, whatever the query.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from app.agents import memory as narrative
from app.core.config import settings
from app.integrations.vector_memory import MemoryHit, MemoryKind, VectorMemory, content_hash
from app.schemas.agent import GrowthRecommendation, MeasurementVerdict
from app.schemas.common import EvidenceItem

MERCHANT_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
MERCHANT_B = uuid.UUID("22222222-2222-4222-8222-222222222222")


@pytest.fixture
def memory_on(monkeypatch):
    monkeypatch.setattr(settings, "memory_enabled", True)


class TestNamespaces:
    def test_each_merchant_gets_its_own_namespace(self):
        store = VectorMemory()
        assert store.dataset_for(MERCHANT_A) != store.dataset_for(MERCHANT_B)
        assert str(MERCHANT_A) in store.dataset_for(MERCHANT_A)

    def test_identical_text_hashes_differently_per_kind(self):
        assert content_hash("note", "x") != content_hash("outcome", "x")


class TestDegradesQuietly:
    """Memory is an enhancement. It may return nothing; it may never raise."""

    def test_recall_is_empty_when_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "memory_enabled", False)
        assert asyncio.run(VectorMemory().recall(MERCHANT_A, "anything")) == []

    def test_remember_is_a_no_op_when_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "memory_enabled", False)
        assert asyncio.run(VectorMemory().remember(MERCHANT_A, "something worth keeping")) is False

    def test_an_empty_query_returns_nothing(self, memory_on):
        assert asyncio.run(VectorMemory().recall(MERCHANT_A, "   ")) == []

    def test_a_broken_backend_reports_disabled(self, memory_on):
        store = VectorMemory()
        store._broken = True
        assert store.enabled is False
        assert asyncio.run(store.recall(MERCHANT_A, "anything")) == []

    def test_queueing_a_write_outside_a_loop_does_not_raise(self, memory_on):
        VectorMemory().remember_later(MERCHANT_A, "no event loop is running here")

    def test_draining_with_nothing_queued_returns(self):
        asyncio.run(VectorMemory().drain())


class TestStore:
    """Real writes and recalls against the suite database."""

    async def test_recall_ranks_the_relevant_memory_first(self, engine, seeded, memory_on):
        store = VectorMemory()
        merchant = seeded["merchant_id"]
        await store.remember(merchant, "Supplier RoastWorks delivered the coffee beans two days late.",
                             kind=MemoryKind.SUPPLIER, tags=("supplier.roastworks",))
        await store.remember(merchant, "Evening customers respond to food pairings, not discounts.",
                             kind=MemoryKind.EXPERIMENT)
        hits = await store.recall(merchant, "which supplier was late delivering beans", top_k=2)
        assert hits, "expected at least one recalled memory"
        assert isinstance(hits[0], MemoryHit)
        assert "RoastWorks" in hits[0].text
        assert hits[0].source == "pgvector"

    async def test_recall_never_crosses_tenants(self, engine, seeded, memory_on):
        store = VectorMemory()
        secret = "Confidential: our floor price with the bakery is 3.10 per croissant."
        await store.remember(seeded["other_merchant_id"], secret, kind=MemoryKind.NOTE)
        hits = await store.recall(seeded["merchant_id"], "floor price bakery croissant", top_k=20)
        assert all("Confidential" not in h.text for h in hits)

    async def test_the_same_memory_is_stored_once(self, engine, seeded, memory_on):
        store = VectorMemory()
        merchant = seeded["merchant_id"]
        text = "Duplicate guard: weekly stock count happens on Mondays."
        assert await store.remember(merchant, text, kind=MemoryKind.NOTE)
        assert await store.remember(merchant, text, kind=MemoryKind.NOTE)
        recent = await store.recent(merchant, limit=100)
        assert sum(1 for h in recent if h.text == text) == 1

    async def test_recall_can_follow_an_entity_tag(self, engine, seeded, memory_on):
        store = VectorMemory()
        merchant = seeded["merchant_id"]
        await store.remember(merchant, "Harbor Beans accepted 13.40 per bag after two rounds.",
                             kind=MemoryKind.PROCUREMENT, tags=("supplier.harbor",))
        hits = await store.recall(merchant, "accepted price per bag", tags=("supplier.harbor",))
        assert hits and all("supplier.harbor" in h.tags for h in hits)

    async def test_forget_erases_only_the_callers_memory(self, engine, seeded, memory_on):
        store = VectorMemory()
        await store.remember(seeded["merchant_id"], "Memory that will be erased for merchant A.")
        await store.remember(seeded["other_merchant_id"], "Memory that must survive for merchant B.")
        assert await store.forget(seeded["merchant_id"]) is True
        assert await store.recent(seeded["merchant_id"]) == []
        survivors = await store.recent(seeded["other_merchant_id"], limit=100)
        assert any("must survive" in h.text for h in survivors)

    async def test_status_counts_this_merchants_memories(self, engine, seeded, memory_on):
        store = VectorMemory()
        await store.remember(seeded["merchant_id"], "Status check memory for the counting test.")
        state = await store.status(seeded["merchant_id"])
        assert state["available"] is True
        assert state["memories"] >= 1
        assert str(seeded["merchant_id"]) in state["dataset"]


class TestNarrative:
    """A memory that needs its original context to make sense is unrecallable."""

    def _recommendation(self) -> GrowthRecommendation:
        return GrowthRecommendation(
            opportunity="Evening daypart bundle",
            summary="Pair coffee with a snack between 4 and 7pm.",
            evidence=[EvidenceItem(metric="Evening ticket", value="$9.40")],
            hypothesis="A food pairing lifts evening ticket size.",
            recommended_action="Launch a cold brew and pastry bundle at 20% off.",
            reasoning="Evening traffic is steady but ticket size trails the day.",
            estimated_impact=1800.0,
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
            merchant_name="Juniper & Oak Coffee",
            question="Why are evenings flat?",
            recommendation=self._recommendation(),
        )
        text = written[0]
        # Merchant, action, money and the question are all present, so the memory
        # is readable months later with no surrounding context.
        assert "Juniper & Oak Coffee" in text
        assert "cold brew and pastry" in text
        assert "1,800" in text
        assert "Why are evenings flat?" in text
        assert "Evening ticket: $9.40" in text

    def test_a_rejection_says_not_to_re_propose(self, monkeypatch):
        written: list[str] = []
        monkeypatch.setattr(
            narrative.memory,
            "remember_later",
            lambda _m, text, **kw: written.append(text),
        )
        narrative.record_approval(
            merchant_id=MERCHANT_A,
            merchant_name="Juniper & Oak Coffee",
            opportunity="Evening daypart bundle",
            approved=False,
            decided_by="Jordan",
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
            merchant_name="Juniper & Oak Coffee",
            opportunity="Evening daypart bundle",
            approved=True,
            decided_by="Jordan",
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
            merchant_name="Juniper & Oak Coffee",
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
            merchant_name="Juniper & Oak Coffee",
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
        ("$$$", "general"),
        ("", "general"),
    ],
)
def test_tags_are_stable_and_never_empty(value, expected):
    """Memory graph links match literally, so a blank tag would match nothing."""
    assert narrative._slug(value) == expected
