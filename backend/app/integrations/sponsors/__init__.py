"""Sponsor-tool adapters and a single honest status report.

``integration_status()`` is what the Integrations screen and ``/health`` show. It
states, for every sponsor tool, *what PayPilot actually uses it for*, whether that
path is running against the real service (``LIVE``) or a labelled fallback
(``SIMULATED``), and which tools are **not** used. Nothing is claimed that the
code does not do.
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.integrations.sponsors.base import LIVE, SIMULATED, SponsorError, SponsorRequestError
from app.integrations.sponsors.channel3 import Channel3Client
from app.integrations.sponsors.elastic import ElasticClient
from app.integrations.sponsors.kernel import KernelClient
from app.integrations.sponsors.zapier import ZapierClient

_channel3: Channel3Client | None = None
_kernel: KernelClient | None = None
_elastic: ElasticClient | None = None
_zapier: ZapierClient | None = None


def _studio_ai_available() -> bool:
    # Imported lazily: the services layer imports this package.
    from app.services.integrations.studio_ai import availability

    return bool(availability()["available"])


def get_channel3() -> Channel3Client:
    global _channel3
    if _channel3 is None:
        _channel3 = Channel3Client()
    return _channel3


def get_kernel() -> KernelClient:
    global _kernel
    if _kernel is None:
        _kernel = KernelClient()
    return _kernel


def get_elastic() -> ElasticClient:
    global _elastic
    if _elastic is None:
        _elastic = ElasticClient()
    return _elastic


def get_zapier() -> ZapierClient:
    global _zapier
    if _zapier is None:
        _zapier = ZapierClient()
    return _zapier


def set_adapters(*, channel3: Channel3Client | None = None, kernel: KernelClient | None = None,
                 elastic: ElasticClient | None = None, zapier: ZapierClient | None = None) -> None:
    """Inject adapters (tests). Passing nothing resets every adapter to its settings."""
    global _channel3, _kernel, _elastic, _zapier
    _channel3, _kernel, _elastic, _zapier = channel3, kernel, elastic, zapier


def integration_status() -> list[dict[str, Any]]:
    """One row per tool: used for what, in which mode, and where to see it."""
    elastic = get_elastic()
    return [
        {
            "key": "paypal",
            "name": "PayPal Developer Platform",
            "category": "core",
            "mode": settings.paypal_mode,
            "used_for": "Transaction Search, Orders v2, Invoicing, Payouts, Subscriptions, verified webhooks, reconciliation",
            "where": "/finance/transactions",
        },
        {
            "key": "paypal_mcp",
            "name": "PayPal Agent Toolkit (MCP, read-only)",
            "category": "core",
            "mode": settings.paypal_mode if settings.paypal_mcp_enabled else "DISABLED",
            "used_for": "Reporting and read tools reached through PayPilot's own tool registry; money-moving tools are blocked",
            "where": "/integrations",
        },
        {
            "key": "ag_grid",
            "name": "AG Grid",
            "category": "sponsor",
            "mode": LIVE,
            "used_for": "Every data-heavy table (transactions, quotes, invoices, receipts, reconciliation, evidence)",
            "where": "/finance/transactions",
        },
        {
            "key": "ag_studio",
            "name": "AG Studio",
            "category": "sponsor",
            "mode": LIVE,
            "used_for": "Pre-built and merchant-built dashboards over PayPilot's computed datasets; Studio's AI agents "
            "run on PayPilot's LLM through the backend"
            + ("" if _studio_ai_available() else " (AI assistant off until GROQ_API_KEY or STUDIO_AI_* is set)"),
            "where": "/studio",
        },
        {
            "key": "bryntum",
            "name": "Bryntum Gantt",
            "category": "sponsor",
            "mode": LIVE,
            "used_for": "Procurement timeline: RFQ, negotiation, approval, delivery, invoice and payment as dependent tasks",
            "where": "/supply/timeline",
        },
        {
            "key": "channel3",
            "name": "Channel3",
            "category": "sponsor",
            "mode": get_channel3().mode,
            "used_for": "Gear shelf: live complementary products with affiliate buy links for the merchant's best "
            "seller; market price reference for purchase approvals (never sets a limit)",
            "where": "/shelf",
        },
        {
            "key": "elastic",
            "name": "Elasticsearch",
            "category": "sponsor",
            "mode": elastic.mode,
            "used_for": "Ranked evidence search across audit, agent messages, offers, invoices, events and reviews"
            + ("" if elastic.configured else " (in-process keyword fallback while ELASTIC_URL is unset)"),
            "where": "/search",
        },
        {
            "key": "kernel",
            "name": "Kernel",
            "category": "sponsor",
            "mode": get_kernel().mode,
            "used_for": "Cloud browser sessions to verify a supplier's public catalogue page; observes only",
            "where": "/integrations",
        },
        {
            "key": "zapier",
            "name": "Zapier",
            "category": "sponsor",
            "mode": get_zapier().mode if get_zapier().configured else SIMULATED,
            "used_for": "Signed business-event notifications to a Catch Hook (Slack, Sheets, email ...); never approves or pays",
            "where": "/integrations",
        },
        {
            "key": "render",
            "name": "Render",
            "category": "sponsor",
            "mode": "BLUEPRINT",
            "used_for": "render.yaml deploys the API (with in-process event relays), web app and Postgres on the free "
            "plan; not deployed from this environment",
            "where": "render.yaml",
        },
        {
            "key": "postman",
            "name": "Postman",
            "category": "sponsor",
            "mode": "COLLECTION",
            "used_for": "Collection and environment that walk the full scenario and the integration endpoints",
            "where": "postman/",
        },
        {
            "key": "apimatic",
            "name": "APIMatic",
            "category": "sponsor",
            "mode": "SDK" if settings.paypal_orders_via_sdk else "SPEC_EXPORT",
            "used_for": "Supplier payments (Orders v2 create / get / capture) run on PayPal's APIMatic-generated "
            "Server SDK, written with the PayPal Context Plugin; PayPilot's own OpenAPI spec and docs portal "
            "build in apimatic/",
            "where": "backend/app/integrations/paypal/server_sdk.py, apimatic/",
        },
        {
            "key": "astropods",
            "name": "Astropods",
            "category": "sponsor",
            "mode": "NOT_USED",
            "used_for": "Not used - agents are deployed with the app and traced with Langfuse",
            "where": "docs/SPONSORS.md",
        },
    ]


__all__ = [
    "LIVE",
    "SIMULATED",
    "Channel3Client",
    "ElasticClient",
    "KernelClient",
    "SponsorError",
    "SponsorRequestError",
    "ZapierClient",
    "get_channel3",
    "get_elastic",
    "get_kernel",
    "get_zapier",
    "integration_status",
    "set_adapters",
]
