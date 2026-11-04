"""Vapi voice integration.

Vapi owns speech only. Every capability the voice assistant exposes is a thin
server-tool that calls the *same* backend agents the web UI calls - there is no
second copy of the business logic.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

VAPI_API_BASE = "https://api.vapi.ai"

#: Tools the assistant may call. Each maps to a backend agent workflow.
VOICE_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_business_snapshot",
            "description": (
                "Get the merchant's current headline numbers: revenue, orders, average "
                "order value and repeat rate, each with its change versus the previous period."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "Look-back window in days. Defaults to 30.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "investigate_growth",
            "description": (
                "Run the Growth Scientist investigation to explain why a metric moved and "
                "return the recommended intervention. Use for questions like 'why did my "
                "sales fall' or 'what should I do today'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The merchant's question, verbatim.",
                    }
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_opportunity",
            "description": (
                "Return the merchant's highest-value detected growth opportunity with its "
                "estimated monthly value, confidence and recommended action."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_experiment_status",
            "description": (
                "Report on running or recently completed experiments: lift, incremental "
                "revenue, ROI and the SCALE/STOP/WATCH decision."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_growth_allocation",
            "description": (
                "Answer 'where should my next dollar of growth budget go' - business-side "
                "(existing customers) versus PayPal-powered levers (cashback via Payouts, Pay Later, checkout offers). "
                "Reports how past budget has actually split and performed, and whether "
                "there's a measured growth arbitrage between the two surfaces yet."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

#: Every page the voice assistant may navigate the merchant to. Mirrors
#: ``frontend/src/lib/constants/voice-pages.ts`` (and, in turn, ``NAV_SECTIONS``) -
#: the two lists must be kept in sync by hand, since the frontend cannot import
#: Python and this router has no reason to serve raw TypeScript.
PAGE_DIRECTORY: list[dict[str, Any]] = [
    {
        "key": "dashboard",
        "label": "Command Center",
        "path": "/dashboard",
        "permission": "dashboard:read",
        "description": "How the business is performing right now",
    },
    {
        "key": "growth",
        "label": "Growth Graph",
        "path": "/growth",
        "permission": "growth:read",
        "description": "What changed, and where it concentrates",
    },
    {
        "key": "opportunities",
        "label": "Opportunities",
        "path": "/opportunities",
        "permission": "growth:read",
        "description": "Quantified, evidence-backed growth opportunities",
    },
    {
        "key": "reviews",
        "label": "Reviews",
        "path": "/reviews",
        "permission": "reviews:read",
        "description": "What customers are actually saying",
    },
    {
        "key": "competitors",
        "label": "Competitors",
        "path": "/competitors",
        "permission": "competitors:read",
        "description": "Where rivals are ahead, and where you are",
    },
    {
        "key": "campaigns",
        "label": "Campaigns",
        "path": "/campaigns",
        "permission": "campaign:read",
        "description": "Interventions, and their approval state",
    },
    {
        "key": "experiments",
        "label": "Experiments",
        "path": "/experiments",
        "permission": "experiment:read",
        "description": "Control vs test, lift, ROI and the decision",
    },
    {
        "key": "impact",
        "label": "Impact Tree",
        "path": "/impact",
        "permission": "growth:read",
        "description": "What launched, what moved, what the control proved",
    },
    {
        "key": "customers",
        "label": "Customers",
        "path": "/customers",
        "permission": "customers:read",
        "description": "Segments, retention and churn risk",
    },
    {
        "key": "products",
        "label": "Products",
        "path": "/products",
        "permission": "products:read",
        "description": "Performance and market-basket pairs",
    },
    {
        "key": "inventory",
        "label": "Inventory",
        "path": "/inventory",
        "permission": "inventory:read",
        "description": "Days of cover and revenue at risk",
    },
    {
        "key": "purchase_orders",
        "label": "Purchase Orders",
        "path": "/purchase-orders",
        "permission": "purchase_order:read",
        "description": "Automated and manual orders, and the approval gate",
    },
    {
        "key": "inventory_automation",
        "label": "Automation",
        "path": "/inventory/automation",
        "permission": "automation:view",
        "description": "Every automated decision and why it was made",
    },
    {
        "key": "agents",
        "label": "Agent Activity",
        "path": "/agents",
        "permission": "agents:view",
        "description": "What the agents did, and why",
    },
    {
        "key": "voice",
        "label": "Voice",
        "path": "/voice",
        "permission": "agents:run",
        "description": "Ask the Growth Scientist out loud",
    },
    {
        "key": "observability",
        "label": "AI Observability",
        "path": "/observability",
        "permission": "agents:view",
        "description": "Langfuse traces, token usage, latency per agent run",
    },
    {
        "key": "activity",
        "label": "Audit Log",
        "path": "/activity",
        "permission": "audit:read",
        "description": "Every consequential action, with its actor",
    },
    {
        "key": "settings",
        "label": "Settings",
        "path": "/settings",
        "permission": "settings:manage",
        "description": "Merchant, integrations and RBAC",
    },
    {
        "key": "command",
        "label": "Command Center",
        "path": "/command",
        "permission": "dashboard:read",
        "description": "Revenue, profit, stock risk, negotiations and approvals in one place",
    },
    {
        "key": "supply",
        "label": "Supply Command Center",
        "path": "/supply",
        "permission": "procurement:read",
        "description": "Stockout risks, active RFQs, negotiations and deliveries",
    },
    {
        "key": "supply_negotiations",
        "label": "Live Negotiations",
        "path": "/supply/negotiations",
        "permission": "procurement:read",
        "description": "Buyer and supplier agents negotiating in real time",
    },
    {
        "key": "supply_suppliers",
        "label": "Supplier Network",
        "path": "/supply/suppliers",
        "permission": "vendor:read",
        "description": "Supplier agents, reliability and indicative pricing",
    },
    {
        "key": "approvals",
        "label": "Approval Center",
        "path": "/approvals",
        "permission": "approval:read",
        "description": "Every money-moving decision waiting for a human",
    },
    {
        "key": "finance_transactions",
        "label": "PayPal Transactions",
        "path": "/finance/transactions",
        "permission": "paypal:read",
        "description": "Synced PayPal transactions and transaction intelligence",
    },
]


def _read_tool(name: str, description: str, properties: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties or {}, "required": []},
        },
    }


#: Supply, approvals and PayPal - all read-only over voice. Voice can describe and
#: prepare; it can never approve or move money (no such tool is exposed).
VOICE_TOOLS.extend(
    [
        _read_tool("get_stockout_risks", "Which products are about to run out, with days of cover and the suggested reorder quantity."),
        _read_tool("get_procurement_overview", "Open procurement requests, active supplier negotiations and negotiated savings to date."),
        _read_tool(
            "get_procurement_status",
            "Status, recommendation and savings for one procurement request.",
            {"reference": {"type": "string", "description": "Procurement reference such as PR-00001."}},
        ),
        _read_tool("list_supplier_agents", "The supplier network: reliability, terms and indicative prices per supplier."),
        _read_tool("get_pending_approvals", "Purchases, supplier payments and payouts waiting for a human approval."),
        _read_tool(
            "get_paypal_transaction_insights",
            "PayPal transaction analytics: gross and net revenue, refund rate, failures, repeat payers.",
            {"days": {"type": "integer", "description": "Look-back window in days. Defaults to 30."}},
        ),
    ]
)

VOICE_TOOLS.append(
    {
        "type": "function",
        "function": {
            "name": "navigate_page",
            "description": (
                "Move the merchant's screen to a different page of the dashboard. Use this "
                "whenever they ask to see, open or go to something, e.g. 'show me inventory', "
                "'take me to the dashboard', 'open opportunities'. The screen changes instantly; "
                "confirm briefly once it has ('Opening Inventory.')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "page": {
                        "type": "string",
                        "enum": [entry["key"] for entry in PAGE_DIRECTORY],
                        "description": "The page key. " + "; ".join(
                            f"{entry['key']} = {entry['label']} ({entry['description']})"
                            for entry in PAGE_DIRECTORY
                        ),
                    }
                },
                "required": ["page"],
            },
        },
    }
)


def resolve_page(key: str) -> dict[str, Any] | None:
    """Look up a ``navigate_page`` key. ``None`` if the model hallucinated one."""
    return next((entry for entry in PAGE_DIRECTORY if entry["key"] == key), None)


SYSTEM_PROMPT = (
    "You are the Growth Scientist for a PayPal merchant, speaking out loud.\n"
    "\n"
    "Rules:\n"
    "- Always call a tool before stating any number. Never invent or estimate figures.\n"
    "- Speak US dollar amounts naturally, e.g. 'nine thousand eight hundred and forty dollars'.\n"
    "- Keep replies under three sentences unless asked to elaborate.\n"
    "- Lead with the answer, then the single most important reason.\n"
    "- You may recommend an action, but you can never approve or execute one. If the merchant "
    "wants to launch something, tell them it needs their approval in the dashboard.\n"
    "- If the merchant asks to see, open or go to a page (e.g. 'show me campaigns'), never say "
    "you can't - the app itself is already listening for that phrase and moves the screen the "
    "instant it hears it, before you even respond. Just answer as if you're already looking at "
    "it: confirm briefly and use get_business_snapshot, get_top_opportunity or "
    "get_experiment_status if their question needs a number from it.\n"
    "- The merchant's on-screen context (their current page and, where available, what is "
    "visible on it) is provided in your context. Prefer it over calling a tool again for numbers "
    "already in view.\n"
    "- If asked whether this is connected to a live PayPal account, answer plainly: analytics use seeded demo data; PayPal runs in sandbox or simulation mode.\n"
)


class VapiClient:
    """Thin async client for Vapi's REST API (assistant config + call metadata)."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    @property
    def enabled(self) -> bool:
        return settings.vapi_active

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=VAPI_API_BASE,
                timeout=httpx.Timeout(20.0),
                headers={
                    "Authorization": f"Bearer {settings.vapi_private_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    def assistant_overrides(
        self,
        *,
        merchant_name: str,
        merchant_id: str,
        snapshot_line: str = "",
        session_token: str = "",
    ) -> dict[str, Any]:
        """Per-session context handed to the assistant at call start.

        ``variableValues`` are echoed back on every server message, so the
        short-lived session token travels with the call and each tool call is
        authenticated and merchant-scoped exactly like a dashboard request. That
        token is already held by this browser and expires in minutes.
        """
        greeting = (
            f"Hi! I'm your Growth Scientist for {merchant_name}. "
            "Ask me why your numbers moved, or what to do about it."
        )
        context = f"Merchant: {merchant_name} (id {merchant_id})."
        if snapshot_line:
            context = f"{context} Current snapshot: {snapshot_line}"
        # Context travels as variables, not as a partial `model` override.
        #
        # Vapi's assistantOverrides.model is the full model object - supplying only
        # `messages` without `provider` and `model` is rejected, and the browser SDK
        # surfaces that as a bare 400 from POST /call/web naming no field. The
        # documented mechanism is variableValues, referenced from the assistant's own
        # prompt as {{merchantName}} and {{merchantContext}}.
        variable_values: dict[str, Any] = {
            "merchantName": merchant_name,
            "merchantId": merchant_id,
            "merchantContext": context,
        }
        if session_token:
            variable_values["sessionToken"] = session_token
        return {
            "firstMessage": greeting,
            "variableValues": variable_values,
        }

    def verify_request(self, *, headers: Mapping[str, str], body: bytes) -> bool:
        """Authenticate a Vapi server-URL request.

        Vapi offers three credential types for a server URL
        (https://docs.vapi.ai/server-url/server-authentication). All three are
        accepted here so the assistant can be configured either way:

        1. Bearer token   ``Authorization: Bearer <secret>``   (recommended)
        2. Legacy header  ``X-Vapi-Secret: <secret>``          (plain value)
        3. HMAC           ``<signature header>: <hex digest>`` of the raw body

        With no secret configured the request is rejected rather than trusted -
        an anonymous caller must never be able to drive an agent run.
        """
        secret = settings.vapi_webhook_secret
        if not secret:
            return False

        lowered = {key.lower(): value for key, value in headers.items()}

        # 1. Authorization: Bearer <secret>
        authorization = lowered.get("authorization", "")
        if authorization.lower().startswith("bearer ") and hmac.compare_digest(
            authorization.split(" ", 1)[1].strip(), secret
        ):
            return True

        # 2. X-Vapi-Secret: <secret>
        plain = lowered.get("x-vapi-secret")
        if plain and hmac.compare_digest(plain.strip(), secret):
            return True

        # 3. HMAC of the raw body, hex encoded, optionally "sha256=" prefixed.
        signature = lowered.get(settings.vapi_signature_header.lower())
        if signature:
            try:
                digestmod = getattr(hashlib, settings.vapi_signature_algorithm)
            except AttributeError:  # pragma: no cover - guarded by config default
                digestmod = hashlib.sha256
            expected = hmac.new(secret.encode("utf-8"), body, digestmod).hexdigest()
            candidate = signature.split("=", 1)[-1].strip()
            if hmac.compare_digest(expected, candidate):
                return True

        return False

    async def get_call(self, call_id: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        try:
            response = await self._http().get(f"/call/{call_id}")
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            log.warning("vapi_get_call_failed", detail=str(exc)[:200])
            return None

    async def get_assistant(self) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        try:
            response = await self._http().get(f"/assistant/{settings.vapi_assistant_id}")
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            log.warning("vapi_get_assistant_failed", detail=str(exc)[:200])
            return None

    async def sync_assistant(self) -> bool:
        """Push this backend's ``VOICE_TOOLS`` and ``SYSTEM_PROMPT`` onto the live assistant.

        The assistant's tools and system prompt live on Vapi's platform, keyed by
        ``VAPI_ASSISTANT_ID`` - they are **not** derived from this backend automatically.
        Adding a tool here (like ``navigate_page``) only teaches the *backend* how to
        execute it; the assistant Vapi actually runs still won't know it exists until
        this is called. That mismatch is exactly what makes the assistant say "I can't
        show you that" for a tool that works fine once it's actually offered to it.

        Called once at startup (``main.py``) whenever Vapi is configured, and exposed at
        ``POST /voice/sync`` for an on-demand push after changing a tool without a
        restart. Fetches the current assistant first and only touches ``model.messages``
        (replacing the system message, keeping everything else) and ``model.tools``, so
        a provider/model/voice choice made in the Vapi dashboard is never overwritten.
        """
        current = await self.get_assistant()
        if current is None:
            return False

        model = dict(current.get("model") or {})
        if not model.get("provider") or not model.get("model"):
            # A partial `model` update is rejected without these - and if they're
            # missing here, the assistant was never fully configured to begin with.
            log.warning("vapi_sync_assistant_skipped", reason="assistant has no model configured")
            return False

        other_messages = [
            m for m in (model.get("messages") or []) if m.get("role") != "system"
        ]
        model["messages"] = [{"role": "system", "content": SYSTEM_PROMPT}, *other_messages]
        model["tools"] = VOICE_TOOLS

        try:
            response = await self._http().patch(
                f"/assistant/{settings.vapi_assistant_id}", json={"model": model}
            )
            response.raise_for_status()
        except Exception as exc:
            log.warning("vapi_sync_assistant_failed", detail=str(exc)[:200])
            return False

        log.info("vapi_assistant_synced", tools=[t["function"]["name"] for t in VOICE_TOOLS])
        return True

    async def close(self) -> None:
        if self._client is not None:
            with contextlib.suppress(Exception):
                await self._client.aclose()
            self._client = None


vapi_client = VapiClient()


# --------------------------------------------------------------------------- #
# Server-message helpers
#
# Vapi POSTs `{"message": {"type": ...}}` to the server URL and expects a
# type-specific reply. Shapes below follow docs.vapi.ai/server-url/events.
# --------------------------------------------------------------------------- #
def parse_tool_calls(message: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Normalise a ``tool-calls`` message into ``[{id, name, arguments}]``.

    Vapi sends ``toolCallList`` (and a richer ``toolWithToolCallList``). Older
    assistants send an OpenAI-shaped ``toolCalls`` with a JSON-string argument
    payload, so both are handled.
    """
    calls: list[dict[str, Any]] = []

    for entry in message.get("toolCallList") or []:
        if not isinstance(entry, dict):
            continue
        calls.append(
            {
                "id": entry.get("id") or "",
                "name": entry.get("name") or "",
                "arguments": _as_object(entry.get("arguments") or entry.get("parameters")),
            }
        )

    if calls:
        return calls

    for entry in message.get("toolCalls") or []:
        if not isinstance(entry, dict):
            continue
        function = entry.get("function") or {}
        calls.append(
            {
                "id": entry.get("id") or "",
                "name": function.get("name") or entry.get("name") or "",
                "arguments": _as_object(function.get("arguments")),
            }
        )
    return calls


def _as_object(value: Any) -> dict[str, Any]:
    """Arguments arrive either as an object or as a JSON string."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        with contextlib.suppress(json.JSONDecodeError):
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
    return {}


def tool_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """The exact response body Vapi expects for ``tool-calls``."""
    return {"results": results}


def tool_result(call_id: str, name: str, result: Any) -> dict[str, Any]:
    """One entry of that response. ``result`` must be a string."""
    payload = result if isinstance(result, str) else json.dumps(result, default=str)
    return {"toolCallId": call_id, "name": name, "result": payload}


def call_variable_values(message: Mapping[str, Any]) -> dict[str, Any]:
    """Per-session values the browser passed in ``assistantOverrides``.

    Vapi echoes them back on the call object, which is how a server tool learns
    which merchant the session belongs to.
    """
    call = message.get("call")
    if not isinstance(call, dict):
        return {}
    for holder in (call.get("assistantOverrides"), call):
        if isinstance(holder, dict):
            values = holder.get("variableValues")
            if isinstance(values, dict):
                return values
    return {}
