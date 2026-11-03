"""The agent memory endpoints.

These assert that the surface is correctly guarded, and that a deployment with
memory switched off still answers sensibly rather than erroring. Whether cognee
itself recalls the right thing is covered elsewhere - it needs a real knowledge
graph.

The flag is pinned per test rather than inherited from ``.env``. Reading the
ambient value made these pass or fail depending on whether the machine happened
to have memory enabled, which is not a property worth testing.
"""

from __future__ import annotations

import pytest

from app.core.config import settings


@pytest.fixture
def memory_off(monkeypatch):
    """A deployment that has not turned memory on."""
    monkeypatch.setattr(settings, "memory_enabled", False)


@pytest.fixture
def memory_on(monkeypatch):
    """Memory configured, without requiring a real cognee behind it."""
    monkeypatch.setattr(settings, "memory_enabled", True)


class TestReadAccess:
    async def test_status_is_readable_by_any_role(self, client, viewer_headers, memory_off):
        response = await client.get("/memory/status", headers=viewer_headers)
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["enabled"] is False
        assert "dataset" in data

    async def test_the_dataset_is_scoped_to_the_callers_merchant(
        self, client, owner_headers, seeded
    ):
        """The scope comes from the principal - there is no parameter to tamper with."""
        response = await client.get("/memory/status", headers=owner_headers)
        assert str(seeded["merchant_id"]) in response.json()["data"]["dataset"]

    async def test_another_merchants_dataset_is_never_named(
        self, client, owner_headers, seeded
    ):
        response = await client.get("/memory/status", headers=owner_headers)
        assert str(seeded["other_merchant_id"]) not in response.json()["data"]["dataset"]

    async def test_searching_with_memory_off_is_empty_not_an_error(
        self, client, viewer_headers, memory_off
    ):
        """Callers should not have to branch on whether memory is deployed."""
        response = await client.get(
            "/memory/search", params={"q": "evening sales"}, headers=viewer_headers
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["hits"] == []
        assert data["available"] is False

    async def test_status_reports_enabled_when_it_is_on(
        self, client, viewer_headers, memory_on
    ):
        """The UI shows a different, non-empty state for this."""
        response = await client.get("/memory/status", headers=viewer_headers)
        assert response.status_code == 200
        assert response.json()["data"]["enabled"] is True

    async def test_anonymous_callers_are_refused(self, client):
        assert (await client.get("/memory/status")).status_code == 401

    @pytest.mark.parametrize("query", ["", "x"])
    async def test_a_too_short_query_is_rejected(self, client, viewer_headers, query):
        response = await client.get(
            "/memory/search", params={"q": query}, headers=viewer_headers
        )
        assert response.status_code == 422


class TestWriteAccess:
    NOTE = {"text": "Evening customers respond to food pairings, not discounts."}

    async def test_a_viewer_cannot_teach_the_agents(self, client, viewer_headers):
        response = await client.post("/memory/remember", json=self.NOTE, headers=viewer_headers)
        assert response.status_code == 403

    async def test_an_analyst_may_write_but_gets_a_clear_error_when_memory_is_off(
        self, client, analyst_headers, memory_off
    ):
        """Permitted, then refused on configuration - not on permission."""
        response = await client.post("/memory/remember", json=self.NOTE, headers=analyst_headers)
        assert response.status_code == 400
        assert "MEMORY_ENABLED" in response.json()["error"]["message"]

    async def test_a_note_that_is_too_short_is_rejected(self, client, analyst_headers):
        response = await client.post(
            "/memory/remember", json={"text": "short"}, headers=analyst_headers
        )
        assert response.status_code == 422


class TestErasure:
    async def test_an_analyst_cannot_erase_memory(self, client, analyst_headers):
        response = await client.request(
            "DELETE", "/memory", json={"confirm": True}, headers=analyst_headers
        )
        assert response.status_code == 403

    async def test_erasing_requires_explicit_confirmation(self, client, owner_headers):
        """Irreversible, so an empty body must never be enough."""
        response = await client.request(
            "DELETE", "/memory", json={"confirm": False}, headers=owner_headers
        )
        assert response.status_code == 400
        assert "confirm" in response.json()["error"]["message"]
