"""Agent tools backed by sponsor integrations and PayPal's MCP server.

Same contract as every tool: typed arguments, a permission check, merchant scope,
logging, tracing and a recorded call. All three are **read-only** - an agent can
look things up here, it cannot buy, pay or notify anyone.

``paypal_mcp_read`` is the one place PayPal's Agent Toolkit tools reach an agent,
and it goes through the read-only gate in ``integrations/paypal/mcp.py``: a request
for ``create_order`` or ``create_refund`` never leaves the process.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.core.exceptions import BadRequestError, IntegrationError, PermissionDeniedError
from app.core.permissions import Permission
from app.integrations.paypal.mcp import MCPReadOnlyViolation, get_mcp_client
from app.integrations.sponsors import SponsorError, SponsorRequestError
from app.services.integrations import evidence, market
from app.tools.base import ToolContext, registry


class MarketArgs(BaseModel):
    product_name: str = Field(min_length=2, max_length=160, description="Product to look up, e.g. 'premium coffee beans'.")
    expected_selling_price: float | None = Field(default=None, gt=0, description="Planned retail price, to compare against the market.")


class EvidenceArgs(BaseModel):
    query: str = Field(min_length=2, max_length=200, description="Words to look for in audit, messages, offers, invoices, events, reviews.")
    limit: int = Field(default=8, ge=1, le=20)


class MCPReadArgs(BaseModel):
    tool: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_\-]+$",
                      description="A PayPal MCP read tool, e.g. get_merchant_insights, list_transactions, list_disputes.")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Arguments for that tool.")


@registry.register(
    "get_market_benchmark",
    description="Market retail-price reference for a product (Channel3). Context for the human reviewing a "
    "purchase; it never changes a budget, limit or offer.",
    args_model=MarketArgs,
    permission=Permission.PROCUREMENT_READ,
)
async def get_market_benchmark(ctx: ToolContext, args: MarketArgs) -> tuple[dict[str, Any], str]:
    try:
        expected = Decimal(str(args.expected_selling_price)) if args.expected_selling_price else None
        data = await market.benchmark(args.product_name, expected_price=expected)
    except SponsorRequestError as exc:
        raise BadRequestError(str(exc)) from exc
    except SponsorError as exc:
        raise IntegrationError(str(exc)) from exc
    stats = data.get("stats")
    if not stats:
        return data, f"No market prices found for '{args.product_name}' ({data['mode'].lower()})."
    return data, (f"{data['mode'].title()} market reference for '{args.product_name}': median {stats['median']} "
                  f"({stats['min']}-{stats['max']}). Retail context only.")


@registry.register(
    "search_evidence",
    description="Ranked full-text search over the merchant's audit log, agent messages, negotiation offers, "
    "procurements, supplier invoices, business events and reviews. Results respect the caller's permissions.",
    args_model=EvidenceArgs,
    permission=Permission.DASHBOARD_READ,
)
async def search_evidence(ctx: ToolContext, args: EvidenceArgs) -> tuple[dict[str, Any], str]:
    data = await evidence.search(ctx.session, ctx.merchant_id, args.query, ctx.permissions, size=args.limit)
    return data, f"{len(data['results'])} evidence hits via {data['engine']}."


@registry.register(
    "paypal_mcp_read",
    description="Call a READ-ONLY tool on PayPal's Agent Toolkit MCP server (reporting, disputes, invoices, "
    "catalog). Tools that create, pay, capture, refund, send or cancel are refused - money moves only "
    "through PayPilot's human approval flow.",
    args_model=MCPReadArgs,
    permission=Permission.PAYPAL_READ,
)
async def paypal_mcp_read(ctx: ToolContext, args: MCPReadArgs) -> tuple[dict[str, Any], str]:
    try:
        result = await get_mcp_client().call_read_tool(args.tool, args.arguments)
    except MCPReadOnlyViolation as exc:
        raise PermissionDeniedError(str(exc)) from exc
    except SponsorError as exc:
        raise IntegrationError(str(exc)) from exc
    return result, f"PayPal MCP {args.tool} ({result['mode'].lower()}) returned data."
