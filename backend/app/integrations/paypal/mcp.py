"""PayPal Agent Toolkit tools, reached through PayPal's MCP server - read-only.

PayPal publishes its Agent Toolkit as an MCP server
(``https://mcp.sandbox.paypal.com/http`` for the sandbox, ``mcp.paypal.com`` for
production, Streamable-HTTP transport, ``Authorization: Bearer <token>``). It
exposes ~40 PayPal operations as agent tools: reporting, disputes, invoices,
subscriptions, catalog, orders ... and also tools that **move money**.

PayPilot's rule is that an agent never moves money on its own authority: every
payment needs a recorded human approval bound to exact terms. A raw MCP
connection would bypass that, so this bridge is built around one invariant:

    **only read tools can be called, and that is decided here, before any
    network request - not by the model, and not by the remote server.**

How the gate works (``assert_read_only``):

  1. the tool name must start with ``list_``, ``get_``, ``show_`` or ``search_``;
  2. it must not contain a money-moving or state-changing fragment (``create``,
     ``pay``, ``capture``, ``send``, ``cancel`` ...) - defence in depth against a
     server that names a write tool ``get_and_pay_...``;
  3. if the server annotates the tool ``readOnlyHint: false`` it is refused even
     when the name looks harmless.

The bridge is reached through PayPilot's own tool registry (``paypal_mcp_read``),
so it also inherits tenant scoping, RBAC (``paypal:read``), logging and tracing.
Money-moving PayPal operations stay on the approval-gated REST path in
``services/paypal/finance.py``.

Without PayPal credentials the bridge answers from a small labelled simulator, so
the feature is demonstrable offline - ``mode`` is ``SIMULATED`` on every result.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.paypal import get_paypal_gateway
from app.integrations.sponsors.base import SponsorError, as_dict

log = get_logger(__name__)

PROTOCOL_VERSION = "2025-03-26"
TIMEOUT = httpx.Timeout(30.0, connect=8.0)

READ_PREFIXES = ("list_", "get_", "show_", "search_")
#: Fragments that mean "this changes state or moves money". Deliberately broad:
#: a false positive costs a refused read; a false negative could cost money.
DENY_FRAGMENTS = (
    "create", "update", "delete", "cancel", "void", "capture", "authorize", "pay", "send",
    "remind", "record", "accept", "approve", "checkout", "refund_create", "suspend", "activate",
    "revise", "provide", "escalate", "appeal", "offer", "payout", "transfer", "charge", "submit",
    "set_", "add_", "remove_", "reset",
)


class MCPReadOnlyViolation(SponsorError):
    """Raised when something other than a read tool is requested."""


def assert_read_only(name: str, annotations: dict[str, Any] | None = None) -> None:
    lowered = name.strip().lower()
    if not lowered.startswith(READ_PREFIXES):
        raise MCPReadOnlyViolation(
            f"'{name}' is not a read tool. Only list_/get_/show_/search_ tools can be called; "
            "money movement goes through PayPilot's approval flow."
        )
    for fragment in DENY_FRAGMENTS:
        if fragment in lowered:
            raise MCPReadOnlyViolation(f"'{name}' looks state-changing ('{fragment}') and is blocked.")
    if annotations is not None and annotations.get("readOnlyHint") is False:
        raise MCPReadOnlyViolation(f"'{name}' is annotated as not read-only by the MCP server and is blocked.")


def is_read_only(name: str, annotations: dict[str, Any] | None = None) -> bool:
    try:
        assert_read_only(name, annotations)
    except MCPReadOnlyViolation:
        return False
    return True


def _parse_rpc(response: httpx.Response) -> dict[str, Any]:
    """Streamable HTTP answers with JSON or a single SSE ``data:`` event."""
    content_type = response.headers.get("content-type", "")
    text = response.text
    if "text/event-stream" in content_type:
        payloads = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
        text = payloads[-1] if payloads else ""
    if not text.strip():
        return {}
    try:
        return as_dict(json.loads(text))
    except ValueError as exc:
        raise SponsorError("The PayPal MCP server returned an unreadable response.") from exc


def _unwrap_tool_result(result: dict[str, Any]) -> Any:
    """MCP wraps results as ``content: [{type: text, text: ...}]``; surface the JSON inside."""
    if result.get("isError"):
        message = " ".join(str(as_dict(c).get("text", "")) for c in result.get("content") or [])[:300]
        raise SponsorError(f"PayPal MCP tool error: {message or 'unknown error'}")
    parts: list[Any] = []
    for item in result.get("content") or []:
        text = as_dict(item).get("text")
        if text is None:
            continue
        try:
            parts.append(json.loads(text))
        except ValueError:
            parts.append(text)
    if "structuredContent" in result:
        return result["structuredContent"]
    return parts[0] if len(parts) == 1 else parts


# --------------------------------------------------------------------------- #
# Simulator
# --------------------------------------------------------------------------- #
_SIM_TOOLS: list[dict[str, Any]] = [
    {"name": "get_merchant_insights", "description": "Sales or order insights over a period", "annotations": {"readOnlyHint": True}},
    {"name": "list_transactions", "description": "List transactions in a date range", "annotations": {"readOnlyHint": True}},
    {"name": "list_disputes", "description": "List disputes", "annotations": {"readOnlyHint": True}},
    {"name": "get_dispute", "description": "Get one dispute", "annotations": {"readOnlyHint": True}},
    {"name": "list_invoices", "description": "List invoices", "annotations": {"readOnlyHint": True}},
    {"name": "list_products", "description": "List catalog products", "annotations": {"readOnlyHint": True}},
    {"name": "create_order", "description": "Create a PayPal order", "annotations": {"readOnlyHint": False}},
    {"name": "create_refund", "description": "Refund a captured payment", "annotations": {"readOnlyHint": False}},
    {"name": "send_invoice", "description": "Send an invoice to a customer", "annotations": {"readOnlyHint": False}},
]

_SIM_RESULTS: dict[str, Any] = {
    "get_merchant_insights": {"insight_type": "SALES", "time_frame": "MONTHLY", "currency": "USD",
                              "note": "Simulated insight - connect PayPal credentials for real data."},
    "list_transactions": {"transaction_details": [], "total_items": 0, "note": "Simulated: no transactions."},
    "list_disputes": {"items": [], "note": "Simulated: no open disputes."},
    "list_invoices": {"items": [], "total_items": 0, "note": "Simulated: no invoices."},
    "list_products": {"products": [], "note": "Simulated: no catalog products."},
}


class PayPalMCPClient:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    @property
    def mode(self) -> str:
        return settings.paypal_mode

    @property
    def simulated(self) -> bool:
        return not settings.paypal_configured

    @property
    def endpoint(self) -> str:
        return settings.paypal_mcp_endpoint

    def __repr__(self) -> str:
        return f"PayPalMCPClient(mode={self.mode}, enabled={settings.paypal_mcp_enabled})"

    # ------------------------------------------------------------------ transport
    async def _token(self) -> str:
        gateway = get_paypal_gateway()
        token_fn = getattr(gateway, "access_token", None)
        if token_fn is None:
            raise SponsorError("PayPal credentials are required to reach the MCP server.")
        return str(await token_fn())

    async def _rpc(self, client: httpx.AsyncClient, headers: dict[str, str], method: str,
                   params: dict[str, Any] | None = None, *, request_id: int | None = 1) -> httpx.Response:
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if request_id is not None:
            body["id"] = request_id
        if params is not None:
            body["params"] = params
        try:
            response = await client.post(self.endpoint, json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise SponsorError(f"PayPal MCP is unreachable ({type(exc).__name__}).") from exc
        if response.status_code in (401, 403):
            raise SponsorError(f"PayPal MCP rejected the credentials (HTTP {response.status_code}).",
                               status_code=response.status_code)
        if not response.is_success:
            raise SponsorError(f"PayPal MCP returned HTTP {response.status_code}.", status_code=response.status_code)
        return response

    async def _session(self, client: httpx.AsyncClient) -> dict[str, str]:
        """initialize -> notifications/initialized; returns the headers for later calls."""
        headers = {
            "Authorization": f"Bearer {await self._token()}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        response = await self._rpc(client, headers, "initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "paypilot", "version": settings.app_version},
        })
        reply = _parse_rpc(response)
        if "error" in reply:
            raise SponsorError(f"PayPal MCP initialize failed: {as_dict(reply['error']).get('message', 'error')}")
        session_id = response.headers.get("mcp-session-id")
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        await self._rpc(client, headers, "notifications/initialized", request_id=None)
        return headers

    # ------------------------------------------------------------------ public API
    async def list_tools(self) -> list[dict[str, Any]]:
        """Every tool the server offers, each flagged ``read_only`` and ``callable``."""
        if self.simulated:
            raw = _SIM_TOOLS
        else:
            if not settings.paypal_mcp_enabled:
                raise SponsorError("The PayPal MCP bridge is disabled (PAYPAL_MCP_ENABLED=false).")
            async with httpx.AsyncClient(timeout=TIMEOUT, transport=self._transport) as client:
                headers = await self._session(client)
                reply = _parse_rpc(await self._rpc(client, headers, "tools/list", {}, request_id=2))
            if "error" in reply:
                raise SponsorError(f"PayPal MCP tools/list failed: {as_dict(reply['error']).get('message', 'error')}")
            raw = as_dict(reply.get("result")).get("tools") or []
        tools = []
        for tool in raw:
            tool = as_dict(tool)
            name = str(tool.get("name", ""))
            annotations = as_dict(tool.get("annotations")) or None
            tools.append({
                "name": name,
                "description": str(tool.get("description", ""))[:300],
                "read_only": is_read_only(name, annotations),
            })
        return sorted(tools, key=lambda t: (not t["read_only"], t["name"]))

    async def call_read_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        # The gate runs first, before a socket is opened.
        assert_read_only(name)
        arguments = arguments or {}
        if self.simulated:
            data = _SIM_RESULTS.get(name)
            if data is None:
                raise SponsorError(f"The simulated PayPal MCP has no '{name}' tool.")
            return {"mode": self.mode, "tool": name, "data": data, "source": "simulator"}
        if not settings.paypal_mcp_enabled:
            raise SponsorError("The PayPal MCP bridge is disabled (PAYPAL_MCP_ENABLED=false).")

        async with httpx.AsyncClient(timeout=TIMEOUT, transport=self._transport) as client:
            headers = await self._session(client)
            # Second gate: the server's own annotations.
            listing = _parse_rpc(await self._rpc(client, headers, "tools/list", {}, request_id=2))
            for tool in as_dict(listing.get("result")).get("tools") or []:
                if as_dict(tool).get("name") == name:
                    assert_read_only(name, as_dict(as_dict(tool).get("annotations")) or None)
            reply = _parse_rpc(await self._rpc(client, headers, "tools/call",
                                               {"name": name, "arguments": arguments}, request_id=3))
        if "error" in reply:
            raise SponsorError(f"PayPal MCP call failed: {as_dict(reply['error']).get('message', 'error')}")
        log.info("paypal_mcp_read", tool=name, mode=self.mode)
        return {"mode": self.mode, "tool": name, "data": _unwrap_tool_result(as_dict(reply.get("result"))),
                "source": "paypal-mcp"}


_client: PayPalMCPClient | None = None


def get_mcp_client() -> PayPalMCPClient:
    global _client
    if _client is None:
        _client = PayPalMCPClient()
    return _client


def set_mcp_client(client: PayPalMCPClient | None) -> None:
    global _client
    _client = client
