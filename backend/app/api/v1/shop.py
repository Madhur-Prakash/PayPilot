"""The public online store: browse, pay with PayPal, and see the sale land.

Unauthenticated on purpose - a customer is not a PayPilot user - so it is narrow:
only merchants flagged ``is_demo`` sell here, carts carry product ids and quantities
(the server prices them), order creation is rate limited per client address, and every
failure for an unknown shop is the same 404. See :mod:`app.services.shop` for the flow.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Path, Request
from pydantic import BaseModel, Field

from app.api.deps import DbSession
from app.core.exceptions import RateLimitError
from app.core.ratelimit import WindowLimiter
from app.schemas.common import APIResponse
from app.services.shop import MAX_LINES, MAX_QUANTITY, ShopService, get_shop_merchant

router = APIRouter(prefix="/shop", tags=["shop"])

#: Creating a PayPal order costs a PayPal call; keep one address from spamming them.
_limiter = WindowLimiter("shop", limit=20, window_seconds=300)

Slug = Annotated[str, Path(pattern=r"^[a-z0-9][a-z0-9-]{1,80}$")]
OrderId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{6,64}$")]


class CartLine(BaseModel):
    product_id: uuid.UUID
    quantity: int = Field(ge=1, le=MAX_QUANTITY)


class CreateOrderBody(BaseModel):
    items: list[CartLine] = Field(min_length=1, max_length=MAX_LINES)
    #: Makes a retried click return the same PayPal order instead of a second one.
    client_key: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


async def _guard(request: Request) -> None:
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")
    result = await _limiter.hit(ip)
    if not result.allowed:
        raise RateLimitError(f"Too many checkout attempts - try again in {result.retry_after} seconds.")


@router.get("/{slug}", summary="The online store's catalog (public)")
async def catalog(slug: Slug, session: DbSession) -> APIResponse[dict[str, Any]]:
    merchant = await get_shop_merchant(session, slug)
    return APIResponse(data=await ShopService(session, merchant).catalog())


@router.post("/{slug}/orders", summary="Start a PayPal checkout (public)")
async def create_order(slug: Slug, body: CreateOrderBody, request: Request, session: DbSession) -> APIResponse[dict[str, Any]]:
    await _guard(request)
    merchant = await get_shop_merchant(session, slug)
    data = await ShopService(session, merchant).create_order(
        [(line.product_id, line.quantity) for line in body.items], client_key=body.client_key)
    return APIResponse(data=data)


@router.post("/{slug}/orders/{order_id}/capture", summary="Capture an approved PayPal order and record the sale (public)")
async def capture_order(slug: Slug, order_id: OrderId, request: Request, session: DbSession) -> APIResponse[dict[str, Any]]:
    await _guard(request)
    merchant = await get_shop_merchant(session, slug)
    return APIResponse(data=await ShopService(session, merchant).capture(order_id))
