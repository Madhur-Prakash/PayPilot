"""The signing contract between the backend and n8n.

These are pure functions, so they are tested directly - no database, no HTTP.

Everything here exists because the failure mode is silent and expensive. The
body is parsed into a JavaScript object before any n8n node can look at it, so
the exact bytes are gone by the time the signature is checked; both sides
therefore serialise to a pinned canonical form and hash *that*. If the two
implementations ever drift, nothing raises - every real event simply starts
looking forged, and reordering stops happening.

The JavaScript half lives in ``n8n/lib/pga-hmac.js`` (``canon``). **Change the
two together.**
"""

from __future__ import annotations

import json

import pytest

from app.core.config import settings
from app.services.inventory.events import canonical_json, sign, verify


class TestCanonicalJson:
    def test_keys_are_sorted_regardless_of_insertion_order(self):
        """JavaScript object key order is not something to rely on."""
        assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})
        assert canonical_json({"b": 1, "a": 2}) == b'{"a":2,"b":1}'

    def test_nested_keys_are_sorted_too(self):
        assert canonical_json({"z": {"y": 1, "x": 2}}) == b'{"z":{"x":2,"y":1}}'

    def test_no_incidental_whitespace(self):
        assert b" " not in canonical_json({"a": [1, 2], "b": {"c": 3}})

    def test_integral_floats_are_narrowed(self):
        """The one that actually bit us.

        Python writes ``13.0`` and JavaScript writes ``13`` for the same
        quantity, and a stock level is a float all the way down.
        """
        assert canonical_json({"qty": 13.0}) == b'{"qty":13}'
        assert canonical_json({"qty": 13}) == b'{"qty":13}'

    def test_fractional_floats_are_left_alone(self):
        assert canonical_json({"ratio": 0.5}) == b'{"ratio":0.5}'

    def test_booleans_are_not_mistaken_for_numbers(self):
        """``bool`` is a subclass of ``int``; narrowing must not reach it."""
        assert canonical_json({"ok": True, "no": False}) == b'{"no":false,"ok":true}'

    def test_non_ascii_survives_unescaped(self):
        """JSON.stringify does not escape these, so neither may we."""
        assert canonical_json({"n": "café"}) == '{"n":"café"}'.encode()

    def test_nan_is_refused_rather_than_written(self):
        """``NaN`` is not JSON, and JSON.parse would reject it on arrival."""
        with pytest.raises(ValueError):
            canonical_json({"x": float("nan")})

    def test_output_is_still_valid_json(self):
        payload = {"b": [1, 2.5, {"d": 4.0}], "a": None, "c": "x"}
        assert json.loads(canonical_json(payload)) == {
            "b": [1, 2.5, {"d": 4}],
            "a": None,
            "c": "x",
        }

    def test_golden_vector(self):
        """Pinned bytes for a realistic envelope.

        Produced by ``canon()`` in n8n/lib/pga-hmac.js. If this test fails, the
        n8n workflows will reject every event until they are rebuilt - check
        that the JavaScript still agrees before updating the expectation.
        """
        envelope = {
            "event_id": "440d1e3d",
            "event_type": "inventory.low_stock",
            "merchant_id": "90a86a7a",
            "entity_type": "inventory_item",
            "entity_id": "c0ffee",
            "correlation_id": "INV-20260918-10abd65700",
            "source": "backend",
            "timestamp": "2026-09-18T16:01:42+00:00",
            "payload": {"sku": "N8N-LOOP-01", "available": 13.0, "reorder_point": 15.0},
        }
        assert canonical_json(envelope) == (
            b'{"correlation_id":"INV-20260918-10abd65700","entity_id":"c0ffee",'
            b'"entity_type":"inventory_item","event_id":"440d1e3d",'
            b'"event_type":"inventory.low_stock","merchant_id":"90a86a7a",'
            b'"payload":{"available":13,"reorder_point":15,"sku":"N8N-LOOP-01"},'
            b'"source":"backend","timestamp":"2026-09-18T16:01:42+00:00"}'
        )


class TestSignatures:
    def test_a_signature_verifies(self, monkeypatch):
        monkeypatch.setattr(settings, "n8n_webhook_secret", "shared-secret")
        body = canonical_json({"action": "replenish"})
        assert verify(body, f"sha256={sign(body)}") is True

    def test_the_sha256_prefix_is_optional(self, monkeypatch):
        monkeypatch.setattr(settings, "n8n_webhook_secret", "shared-secret")
        body = b'{"a":1}'
        assert verify(body, sign(body)) is True

    def test_a_tampered_body_fails(self, monkeypatch):
        monkeypatch.setattr(settings, "n8n_webhook_secret", "shared-secret")
        original = b'{"qty":1}'
        signature = "sha256=" + sign(original)
        assert verify(b'{"qty":9999}', signature) is False

    def test_a_wrong_secret_fails(self, monkeypatch):
        body = b'{"a":1}'
        monkeypatch.setattr(settings, "n8n_webhook_secret", "one-secret")
        signature = sign(body)
        monkeypatch.setattr(settings, "n8n_webhook_secret", "another-secret")
        assert verify(body, signature) is False

    def test_a_missing_signature_fails_closed(self, monkeypatch):
        monkeypatch.setattr(settings, "n8n_webhook_secret", "shared-secret")
        assert verify(b'{"a":1}', None) is False
        assert verify(b'{"a":1}', "") is False

    def test_an_unconfigured_secret_fails_closed(self, monkeypatch):
        """No secret must mean "refuse everything", never "accept everything"."""
        monkeypatch.setattr(settings, "n8n_webhook_secret", "")
        assert verify(b'{"a":1}', "sha256=" + "0" * 64) is False

    def test_known_hmac_vector(self, monkeypatch):
        """RFC-style fixed vector, so a change of algorithm cannot pass quietly."""
        monkeypatch.setattr(settings, "n8n_webhook_secret", "key")
        assert sign(b"The quick brown fox jumps over the lazy dog") == (
            "f7bc83f430538424b13298e6aa6fb143ef4d59a14946175997479dbc2d1a3cd8"
        )
