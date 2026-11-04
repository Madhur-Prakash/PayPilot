"""Versioned API router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    admin,
    agents,
    approvals,
    auth,
    campaigns,
    dashboard,
    growth,
    intelligence,
    inventory,
    memory,
    paypal,
    supply,
    voice,
)

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(admin.health_router)
api_router.include_router(auth.router)
api_router.include_router(dashboard.router)
api_router.include_router(intelligence.router)
api_router.include_router(growth.router)
api_router.include_router(campaigns.router)
api_router.include_router(agents.router)
api_router.include_router(voice.router)
api_router.include_router(inventory.router)
api_router.include_router(supply.router)
api_router.include_router(approvals.router)
api_router.include_router(paypal.router)
api_router.include_router(memory.router)
api_router.include_router(admin.router)

__all__ = ["api_router"]
