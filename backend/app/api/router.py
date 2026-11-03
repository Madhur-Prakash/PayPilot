"""Versioned API router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    admin,
    agents,
    auth,
    campaigns,
    dashboard,
    growth,
    inventory,
    memory,
    voice,
)

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(admin.health_router)
api_router.include_router(auth.router)
api_router.include_router(dashboard.router)
api_router.include_router(growth.router)
api_router.include_router(campaigns.router)
api_router.include_router(agents.router)
api_router.include_router(voice.router)
api_router.include_router(inventory.router)
api_router.include_router(memory.router)
api_router.include_router(admin.router)

__all__ = ["api_router"]
