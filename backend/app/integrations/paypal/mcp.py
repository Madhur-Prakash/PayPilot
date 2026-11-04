"""PayPal Agent Toolkit tools, reached through PayPal's MCP server - read-only.

PayPal publishes its Agent Toolkit as a remote MCP server: ``mcp.sandbox.paypal.com``
for the sandbox and ``mcp.paypal.com`` for production, authenticated with
``Authorization: Bearer <PayPal access token>``. It exposes 46 operations as agent
tools (verified against the live sandbox): invoicing, subscriptions, catalog,
shipment tracking, orders, disputes, reporting - and tools that **move money**.

Transport: the server speaks the MCP **HTTP+SSE** transport. ``GET /sse`` opens an
event stream whose first event (``endpoint``) names a per-session URL; JSON-RPC
requests are ``POST``ed there (``202 Accepted``) and the replies arrive as
``message`` events on the stream. (``/http`` does not exist on the sandbox host - a
POST there is a 404 - so the default endpoint is ``/sse``.) A URL that does not end
in ``/sse`` is treated as a Streamable-HTTP endpoint, which keeps the client working
if PayPal moves transports.

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
     when the name looks harmless. (PayPal's server sends no annotations today, so
     rules 1 and 2 are what protect you; rule 3 only ever tightens.)

Of PayPal's 46 tools, 16 pass (``list_disputes``, ``get_merchant_insights``,
``list_transactions`` ...) and 30 are blocked, including every one that creates an
order, pays, refunds, sends an invoice or accepts a dispute claim.

The bridge is reached through PayPilot's own tool registry (``paypal_mcp_read``),
so it also inherits tenant scoping, RBAC (``paypal:read``), logging and tracing.
Money-moving PayPal operations stay on the approval-gated REST path in
``services/paypal/finance.py``.

Without PayPal credentials the bridge answers from a small labelled simulator, so
the feature is demonstrable offline - ``mode`` is ``SIMULATED`` on every result.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.paypal import get_paypal_gateway
from app.integrations.sponsors.base import SponsorError, as_dict

log = get_logger(__name__)

SSE_PROTOCOL_VERSION = "2024-11-05"
HTTP_PROTOCOL_VERSION = "2025-03-26"
TIMEOUT = httpx.Timeout(30.0, connect=8.0, read=45.0)
REPLY_TIMEOUT_SECONDS = 30.0

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
    if "structuredContent" in result:
        return result["structuredContent"]
    parts: list[Any] = []
    for item in result.get("content") or []:
        text = as_dict(item).get("text")
        if text is None:
            continue
        try:
            parts.append(json.loads(text))
        except ValueError:
            parts.append(text)
    return parts[0] if len(parts) == 1 else parts


def _check_status(response: httpx.Response) -> None:
    if response.status_code in (401, 403):
        raise SponsorError(f"PayPal MCP rejected the credentials (HTTP {response.status_code}).",
                           status_code=response.status_code)
    if not response.is_success:
        raise SponsorError(f"PayPal MCP returned HTTP {response.status_code}.", status_code=response.status_code)


# --------------------------------------------------------------------------- #
# Transports
# --------------------------------------------------------------------------- #
class _StreamableSession:
    """MCP Streamable HTTP: every request is a POST answered with JSON or one SSE event."""

    protocol_version = HTTP_PROTOCOL_VERSION

    def __init__(self, client: httpx.AsyncClient, endpoint: str, headers: dict[str, str]) -> None:
        self._client, self._endpoint, self._headers = client, endpoint, dict(headers)
        self._ids = 0

    async def start(self) -> None:
        response = await self._post({"jsonrpc": "2.0", "id": self._next_id(), "method": "initialize",
                                     "params": _initialize_params(self.protocol_version)})
        reply = _parse_rpc(response)
        if "error" in reply:
            raise SponsorError(f"PayPal MCP initialize failed: {as_dict(reply['error']).get('message', 'error')}")
        if session_id := response.headers.get("mcp-session-id"):
            self._headers["Mcp-Session-Id"] = session_id
        await self.notify("notifications/initialized")

    def _next_id(self) -> int:
        self._ids += 1
        return self._ids

    async def _post(self, body: dict[str, Any]) -> httpx.Response:
        try:
            response = await self._client.post(self._endpoint, json=body, headers=self._headers)
        except httpx.HTTPError as exc:
            raise SponsorError(f"PayPal MCP is unreachable ({type(exc).__name__}).") from exc
        _check_status(response)
        return response

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        await self._post(body)

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        response = await self._post({"jsonrpc": "2.0", "id": self._next_id(), "method": method, "params": params})
        return _parse_rpc(response)


class _SSESession:
    """MCP HTTP+SSE: GET /sse for the event stream, POST to the announced endpoint.

    The ``endpoint`` event is untrusted input that decides where the bearer token is
    sent next, so it must resolve to the *same host* as the stream - a hostile or
    misconfigured server cannot redirect the credential elsewhere.
    """

    protocol_version = SSE_PROTOCOL_VERSION

    def __init__(self, client: httpx.AsyncClient, stream_url: str, headers: dict[str, str]) -> None:
        self._client, self._stream_url, self._headers = client, stream_url, dict(headers)
        self._queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        self._reader: asyncio.Task[None] | None = None
        self._stream_cm: Any = None
        self._response: httpx.Response | None = None
        self._post_url = ""
        self._ids = 0

    async def __aenter__(self) -> _SSESession:
        try:
            self._stream_cm = self._client.stream(
                "GET", self._stream_url, headers={**self._headers, "Accept": "text/event-stream"})
            self._response = await self._stream_cm.__aenter__()
        except httpx.HTTPError as exc:
            raise SponsorError(f"PayPal MCP is unreachable ({type(exc).__name__}).") from exc
        try:
            _check_status(self._response)
            self._reader = asyncio.create_task(self._read_events(), name="paypal-mcp-sse")
            event, data = await self._next_event()
            if event != "endpoint":
                raise SponsorError("The PayPal MCP server did not announce a message endpoint.")
            self._post_url = self._resolve(data)
            reply = await self.request("initialize", _initialize_params(self.protocol_version))
            if "error" in reply:
                raise SponsorError(f"PayPal MCP initialize failed: {as_dict(reply['error']).get('message', 'error')}")
            await self.notify("notifications/initialized")
        except BaseException:
            await self.__aexit__(None, None, None)
            raise
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._reader is not None:
            self._reader.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reader
        if self._stream_cm is not None:
            with contextlib.suppress(Exception):
                await self._stream_cm.__aexit__(None, None, None)

    def _resolve(self, announced: str) -> str:
        url = urljoin(self._stream_url, announced.strip())
        if urlparse(url).netloc != urlparse(self._stream_url).netloc or (urlparse(url).scheme != "https" and \
                urlparse(self._stream_url).scheme == "https"):
            raise SponsorError("The PayPal MCP server announced an endpoint on a different host; refusing to send credentials.")
        return url

    async def _read_events(self) -> None:
        assert self._response is not None
        event = "message"
        data: list[str] = []
        try:
            async for line in self._response.aiter_lines():
                if line == "":
                    if data:
                        await self._queue.put((event, "\n".join(data)))
                    event, data = "message", []
                elif line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data.append(line[5:].lstrip())
            await self._queue.put(("__closed__", ""))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._queue.put(("__error__", type(exc).__name__))

    async def _next_event(self) -> tuple[str, str]:
        try:
            event, data = await asyncio.wait_for(self._queue.get(), REPLY_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            raise SponsorError("PayPal MCP did not answer in time.") from exc
        if event in ("__closed__", "__error__"):
            raise SponsorError("The PayPal MCP stream closed unexpectedly.")
        return event, data

    async def _post(self, body: dict[str, Any]) -> None:
        try:
            response = await self._client.post(self._post_url, json=body, headers=self._headers)
        except httpx.HTTPError as exc:
            raise SponsorError(f"PayPal MCP is unreachable ({type(exc).__name__}).") from exc
        _check_status(response)

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        await self._post(body)

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._ids += 1
        request_id = self._ids
        await self._post({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        while True:
            event, data = await self._next_event()
            if event != "message":
                continue
            try:
                message = as_dict(json.loads(data))
            except ValueError:
                continue
            if message.get("id") == request_id:
                return message


def _initialize_params(version: str) -> dict[str, Any]:
    return {"protocolVersion": version, "capabilities": {},
            "clientInfo": {"name": "paypilot", "version": settings.app_version}}


# --------------------------------------------------------------------------- #
# Simulator
# --------------------------------------------------------------------------- #
_SIM_TOOLS: list[dict[str, Any]] = [
    {"name": "get_merchant_insights", "description": "Sales or order insights over a period"},
    {"name": "list_transactions", "description": "List transactions in a date range"},
    {"name": "list_disputes", "description": "List disputes"},
    {"name": "get_dispute", "description": "Get one dispute"},
    {"name": "list_invoices", "description": "List invoices"},
    {"name": "list_products", "description": "List catalog products"},
    {"name": "create_order", "description": "Create a PayPal order"},
    {"name": "pay_order", "description": "Pay (capture) an approved order"},
    {"name": "create_refund", "description": "Refund a captured payment"},
    {"name": "send_invoice", "description": "Send an invoice to a customer"},
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

    @property
    def uses_sse(self) -> bool:
        return urlparse(self.endpoint).path.rstrip("/").endswith("/sse")

    def __repr__(self) -> str:
        return f"PayPalMCPClient(mode={self.mode}, enabled={settings.paypal_mcp_enabled})"

    # ------------------------------------------------------------------ transport
    async def _token(self) -> str:
        gateway = get_paypal_gateway()
        token_fn = getattr(gateway, "access_token", None)
        if token_fn is None:
            raise SponsorError("PayPal credentials are required to reach the MCP server.")
        return str(await token_fn())

    @contextlib.asynccontextmanager
    async def _open(self) -> AsyncIterator[_SSESession | _StreamableSession]:
        """An initialised MCP session over whichever transport the endpoint speaks."""
        if not settings.paypal_mcp_enabled:
            raise SponsorError("The PayPal MCP bridge is disabled (PAYPAL_MCP_ENABLED=false).")
        headers = {
            "Authorization": f"Bearer {await self._token()}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        async with httpx.AsyncClient(timeout=TIMEOUT, transport=self._transport) as client:
            if self.uses_sse:
                async with _SSESession(client, self.endpoint, headers) as session:
                    yield session
            else:
                streamable = _StreamableSession(client, self.endpoint, headers)
                await streamable.start()
                yield streamable

    @staticmethod
    def _result(reply: dict[str, Any], what: str) -> dict[str, Any]:
        if "error" in reply:
            raise SponsorError(f"PayPal MCP {what} failed: {as_dict(reply['error']).get('message', 'error')}")
        return as_dict(reply.get("result"))

    # ------------------------------------------------------------------ public API
    async def list_tools(self) -> list[dict[str, Any]]:
        """Every tool the server offers, each flagged ``read_only`` (callable) or not."""
        if self.simulated:
            raw: list[Any] = _SIM_TOOLS
        else:
            async with self._open() as session:
                reply = await session.request("tools/list", {})
            raw = self._result(reply, "tools/list").get("tools") or []
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

        async with self._open() as session:
            # Second gate: the server's own annotations, when it sends any.
            listing = self._result(await session.request("tools/list", {}), "tools/list")
            for tool in listing.get("tools") or []:
                if as_dict(tool).get("name") == name:
                    assert_read_only(name, as_dict(as_dict(tool).get("annotations")) or None)
            reply = await session.request("tools/call", {"name": name, "arguments": arguments})
        data = _unwrap_tool_result(self._result(reply, "call"))
        # PayPal's toolkit reports its own failures *inside* a successful MCP response
        # as {"ok": false, "code": ..., "message": ...}. That is an error, not data -
        # showing it as a result would let a failure read like an empty answer.
        if isinstance(data, dict) and data.get("ok") is False:
            raise SponsorError(
                f"PayPal's MCP server could not run {name}: {data.get('code', 'error')} - "
                f"{str(data.get('message', 'no detail'))[:200]}"
            )
        log.info("paypal_mcp_read", tool=name, mode=self.mode)
        return {"mode": self.mode, "tool": name, "data": data, "source": "paypal-mcp"}


_client: PayPalMCPClient | None = None


def get_mcp_client() -> PayPalMCPClient:
    global _client
    if _client is None:
        _client = PayPalMCPClient()
    return _client


def set_mcp_client(client: PayPalMCPClient | None) -> None:
    global _client
    _client = client
