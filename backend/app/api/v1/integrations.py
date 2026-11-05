"""Sponsor and platform integrations.

Everything here is merchant-scoped and permission-gated, and none of it can move
money: Channel3 and Elasticsearch read, Kernel observes, Zapier is outbound
notification only, and the PayPal MCP bridge refuses any tool that is not a read.
No response contains a credential, token or webhook URL.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import Field

from app.api.deps import DbSession, Principal, require_permission
from app.core.exceptions import AppError, BadRequestError, IntegrationError, PermissionDeniedError
from app.core.permissions import Permission
from app.integrations.paypal.mcp import MCPReadOnlyViolation, get_mcp_client
from app.integrations.sponsors import (
    SponsorError,
    SponsorRequestError,
    get_elastic,
    get_zapier,
    integration_status,
)
from app.schemas.common import APIResponse, SchemaBase
from app.services.integrations import evidence, market, studio_ai
from app.services.integrations.zapier import delivery_summary
from app.services.intelligence.datasets import build_datasets

router = APIRouter(prefix="/integrations", tags=["integrations"])


def _upstream(exc: SponsorError) -> AppError:
    """Map a sponsor failure to the right HTTP status: 403 policy, 400 bad input, 502 upstream."""
    if isinstance(exc, MCPReadOnlyViolation):
        return PermissionDeniedError(str(exc))
    if isinstance(exc, SponsorRequestError):
        return BadRequestError(str(exc))
    return IntegrationError(str(exc))


class BenchmarkRequest(SchemaBase):
    query: str = Field(min_length=2, max_length=160)
    expected_price: Decimal | None = Field(default=None, gt=0, le=Decimal("100000"))
    limit: int = Field(default=8, ge=1, le=20)


class PortalRequest(SchemaBase):
    url: str = Field(min_length=10, max_length=500)
    supplier_name: str = Field(default="", max_length=120)


class MCPCall(SchemaBase):
    tool: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_\-]+$")
    arguments: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #
@router.get("/status", summary="Every integration, what it is used for, and whether it is live")
async def status_(
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.DASHBOARD_READ)),
) -> APIResponse[dict[str, Any]]:
    elastic = get_elastic()
    elastic_state: dict[str, Any] = {"configured": elastic.configured, "reachable": None, "index": elastic.index}
    if elastic.configured:
        try:
            elastic_state.update(reachable=True, **await elastic.ping())
        except SponsorError as exc:
            elastic_state.update(reachable=False, error=str(exc))
    return APIResponse(data={
        "integrations": integration_status(),
        "elastic": elastic_state,
        "zapier": await delivery_summary(session, principal.merchant_id),
    })


# --------------------------------------------------------------------------- #
# Channel3 - market reference
# --------------------------------------------------------------------------- #
@router.post("/market/benchmark", summary="Market price reference for a product (Channel3)")
async def market_benchmark(
    body: BenchmarkRequest,
    principal: Principal = Depends(require_permission(Permission.PROCUREMENT_READ)),
) -> APIResponse[dict[str, Any]]:
    try:
        data = await market.benchmark(body.query, expected_price=body.expected_price, limit=body.limit)
    except SponsorError as exc:
        raise _upstream(exc) from exc
    return APIResponse(data=data)


@router.get("/market/procurement/{procurement_id}", summary="Market reference for one procurement request")
async def market_for_procurement(
    procurement_id: uuid.UUID,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PROCUREMENT_READ)),
) -> APIResponse[dict[str, Any]]:
    try:
        data = await market.benchmark_procurement(session, principal.merchant_id, procurement_id)
    except SponsorError as exc:
        raise _upstream(exc) from exc
    return APIResponse(data=data)


# --------------------------------------------------------------------------- #
# Elasticsearch - evidence search
# --------------------------------------------------------------------------- #
@router.get("/search", summary="Search the evidence behind decisions (Elasticsearch)")
async def search_evidence(
    session: DbSession,
    q: Annotated[str, Query(min_length=2, max_length=200)],
    kinds: Annotated[str | None, Query(description="comma-separated: audit,agent_message,offer,...")] = None,
    size: Annotated[int, Query(ge=1, le=50)] = 20,
    principal: Principal = Depends(require_permission(Permission.DASHBOARD_READ)),
) -> APIResponse[dict[str, Any]]:
    wanted = [k.strip() for k in kinds.split(",") if k.strip()] if kinds else None
    data = await evidence.search(session, principal.merchant_id, q, principal.permissions, kinds=wanted, size=size)
    return APIResponse(data=data)


@router.post("/search/reindex", summary="Index this merchant's evidence into Elasticsearch")
async def reindex_evidence(
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.SETTINGS_MANAGE)),
) -> APIResponse[dict[str, Any]]:
    try:
        return APIResponse(data=await evidence.reindex(session, principal.merchant_id))
    except SponsorError as exc:
        raise _upstream(exc) from exc


# --------------------------------------------------------------------------- #
# Kernel - supplier portal verification
# --------------------------------------------------------------------------- #
@router.post("/kernel/sessions", summary="Open a cloud browser on a supplier's public page (Kernel)")
async def open_portal(
    body: PortalRequest,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PROCUREMENT_NEGOTIATE)),
) -> APIResponse[dict[str, Any]]:
    try:
        browser = await market.open_portal_session(
            session, principal.merchant_id, url=body.url, actor_id=principal.user_id,
            actor_label=principal.label, supplier_name=body.supplier_name, request_id=principal.request_id,
        )
    except SponsorError as exc:
        raise _upstream(exc) from exc
    return APIResponse(data=browser.as_dict())


@router.delete("/kernel/sessions/{session_id}", summary="Close a supplier-portal browser session")
async def close_portal(
    session_id: str,
    principal: Principal = Depends(require_permission(Permission.PROCUREMENT_NEGOTIATE)),
) -> APIResponse[dict[str, Any]]:
    closed = await market.close_portal_session(str(session_id))
    return APIResponse(data={"session_id": session_id, "closed": closed})


# --------------------------------------------------------------------------- #
# Zapier - outbound notifications
# --------------------------------------------------------------------------- #
@router.get("/zapier", summary="Zapier delivery state")
async def zapier_state(
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.EVENTS_READ)),
) -> APIResponse[dict[str, Any]]:
    return APIResponse(data=await delivery_summary(session, principal.merchant_id))


@router.post("/zapier/test", summary="Send a signed test event to the Zapier Catch Hook")
async def zapier_test(
    principal: Principal = Depends(require_permission(Permission.SETTINGS_MANAGE)),
) -> APIResponse[dict[str, Any]]:
    client = get_zapier()
    if not client.configured:
        return APIResponse(data={"sent": False, "mode": client.mode,
                                 "note": "ZAPIER_WEBHOOK_URL is not set - nothing was sent."})
    event_id = str(uuid.uuid4())
    body = json.dumps({
        "event_id": event_id, "event_type": "paypilot.test", "label": "PayPilot test event",
        "merchant_id": str(principal.merchant_id), "data": {"message": "Zapier is connected to PayPilot."},
        "source": "paypilot",
    }, sort_keys=True, separators=(",", ":")).encode()
    try:
        status_code = await client.post_event(body, event_id=event_id)
    except SponsorError as exc:
        raise _upstream(exc) from exc
    return APIResponse(data={"sent": True, "mode": client.mode, "http_status": status_code, "event_id": event_id})


# --------------------------------------------------------------------------- #
# PayPal Agent Toolkit via MCP - read-only
# --------------------------------------------------------------------------- #
@router.get("/paypal-mcp/tools", summary="PayPal MCP tools, flagged callable or blocked")
async def mcp_tools(
    principal: Principal = Depends(require_permission(Permission.PAYPAL_READ)),
) -> APIResponse[dict[str, Any]]:
    client = get_mcp_client()
    try:
        tools = await client.list_tools()
    except SponsorError as exc:
        raise _upstream(exc) from exc
    return APIResponse(data={
        "mode": client.mode, "endpoint": client.endpoint if not client.simulated else None, "tools": tools,
        "policy": "Only list_/get_/show_/search_ tools can be called. Tools that create, pay, capture, "
                  "send or cancel are blocked here; money moves only through PayPilot's approval flow.",
    })


@router.post("/paypal-mcp/call", summary="Call one read-only PayPal MCP tool")
async def mcp_call(
    body: MCPCall,
    principal: Principal = Depends(require_permission(Permission.PAYPAL_READ)),
) -> APIResponse[dict[str, Any]]:
    try:
        return APIResponse(data=await get_mcp_client().call_read_tool(body.tool, body.arguments))
    except SponsorError as exc:
        raise _upstream(exc) from exc


# --------------------------------------------------------------------------- #
# AG Studio - datasets
# --------------------------------------------------------------------------- #
@router.get("/studio/datasets", summary="Computed datasets for AG Studio dashboards")
async def studio_datasets(
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.DASHBOARD_READ)),
) -> APIResponse[dict[str, Any]]:
    data = await build_datasets(session, principal.merchant_id, principal.permissions)
    data["ai"] = studio_ai.availability()
    return APIResponse(data=data)


# --------------------------------------------------------------------------- #
# AG Studio - AI assistant (Studio's agent harness, run on PayPilot's LLM)
# --------------------------------------------------------------------------- #
@router.get("/studio/ai", summary="Whether Studio's AI assistant is available, and on which model")
async def studio_ai_status(
    principal: Principal = Depends(require_permission(Permission.DASHBOARD_READ)),
) -> APIResponse[dict[str, Any]]:
    return APIResponse(data=studio_ai.availability())


@router.post("/studio/ai/turn", summary="Run one AG Studio agent turn on PayPilot's LLM")
async def studio_ai_turn(
    body: studio_ai.StudioTurnRequest,
    principal: Principal = Depends(require_permission(Permission.DASHBOARD_READ)),
) -> APIResponse[dict[str, Any]]:
    """Relay one ``AgLlmAdapter.executeTurn``. Studio's tools run in the browser against the
    dashboard only; this endpoint holds the model key and returns the model's output."""
    return APIResponse(data=await studio_ai.run_turn(body))

