"""Unified Business Intelligence endpoints: the Command Center and the event stream
that ties Growth, Supply and Finance together."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, Principal, require_permission
from app.core.permissions import Permission
from app.schemas.common import APIResponse
from app.services.intelligence.events import BusinessEvent, describe_event, recent_events
from app.services.intelligence.unified import command_center, inventory_signals, margin_signals

router = APIRouter(tags=["intelligence"])


@router.get("/command-center", summary="The merchant's whole operating picture")
async def get_command_center(
    session: DbSession,
    days: Annotated[int, Query(ge=7, le=365)] = 30,
    principal: Principal = Depends(require_permission(Permission.DASHBOARD_READ)),
) -> APIResponse[dict[str, Any]]:
    return APIResponse(data=await command_center(session, principal.merchant_id, days=days))


@router.get("/events", summary="Cross-module business events")
async def list_events(
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    module: Annotated[str | None, Query(description="growth | supply | finance | governance")] = None,
    correlation_id: Annotated[str | None, Query()] = None,
    include_inventory: Annotated[bool, Query()] = False,
    principal: Principal = Depends(require_permission(Permission.EVENTS_READ)),
) -> APIResponse[list[dict[str, Any]]]:
    prefix = None if include_inventory or correlation_id else "business."
    rows = await recent_events(session, principal.merchant_id, limit=limit, prefix=prefix, correlation_id=correlation_id)
    items = [describe_event(r) for r in rows]
    if module:
        items = [i for i in items if i["module"] == module]
    return APIResponse(data=items, meta={"catalogue": BusinessEvent.LABELS})


@router.get("/intelligence/signals", summary="Inventory and margin signals that shape growth recommendations")
async def get_signals(
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.GROWTH_READ)),
) -> APIResponse[dict[str, Any]]:
    return APIResponse(data={
        "inventory": await inventory_signals(session, principal.merchant_id),
        "margins": await margin_signals(session, principal.merchant_id),
    })
