"""Zapier - business events fan out to the tools a merchant already uses.

A merchant creates a Zap that starts with **Webhooks by Zapier -> Catch Hook**,
pastes the hook URL into ``ZAPIER_WEBHOOK_URL``, and from then on high-signal
PayPilot events (stockout risk, supplier selected, purchase approved, payment
reconciled ...) land in Slack, Sheets, email or any of Zapier's apps.

This is a *notification* path only. Zapier never approves, pays or changes a
limit; the events it receives are the same ones n8n receives from the
transactional outbox, minus anything it has no business knowing.

Every request is signed: ``X-PayPilot-Signature: sha256=<hmac of the raw body>``
with ``ZAPIER_SIGNING_SECRET`` (derived from ``JWT_SECRET`` when blank), plus
``X-PayPilot-Event-Id`` so a Zap can de-duplicate. Delivery state lives in
``integration_deliveries`` (one row per event per target), so a Zapier outage
never disturbs n8n delivery.

(Zapier also offers an MCP server for agents to *call* Zapier actions; PayPilot
deliberately does not hand its agents that capability - an agent that can trigger
arbitrary third-party actions would sit outside the approval gates.)
"""

from __future__ import annotations

import hashlib
import hmac
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.sponsors.base import LIVE, SIMULATED, SponsorError

log = get_logger(__name__)

TIMEOUT = httpx.Timeout(10.0, connect=5.0)


def sign(body: bytes) -> str:
    return hmac.new(settings.zapier_signing_key, body, hashlib.sha256).hexdigest()


def verify(body: bytes, signature: str) -> bool:
    """For Zaps (or tests) that want to check a PayPilot signature."""
    return hmac.compare_digest(sign(body), signature.removeprefix("sha256="))


class ZapierClient:
    def __init__(self, *, url: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._url = settings.zapier_webhook_url if url is None else url
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(self._url)

    @property
    def mode(self) -> str:
        return LIVE if self.configured else SIMULATED

    def __repr__(self) -> str:  # the hook URL is itself a secret
        return f"ZapierClient(configured={self.configured})"

    def _validated_url(self) -> str:
        parsed = urlparse(self._url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise SponsorError("ZAPIER_WEBHOOK_URL must be an https:// Catch Hook URL.")
        return self._url

    async def post_event(self, body: bytes, *, event_id: str) -> int:
        """POST one signed event. Returns the HTTP status; raises SponsorError on failure."""
        url = self._validated_url()
        headers = {
            "Content-Type": "application/json",
            "X-PayPilot-Signature": f"sha256={sign(body)}",
            "X-PayPilot-Event-Id": event_id,
            "User-Agent": "PayPilot/1.0",
        }
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, transport=self._transport) as client:
                response = await client.post(url, content=body, headers=headers)
        except httpx.HTTPError as exc:
            raise SponsorError(f"Zapier is unreachable ({type(exc).__name__}).") from exc
        if not response.is_success:
            raise SponsorError(f"Zapier returned HTTP {response.status_code}.", status_code=response.status_code)
        return response.status_code
