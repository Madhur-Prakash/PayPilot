"""The gear shelf: complementary products a merchant can recommend, from Channel3.

A coffee shop's online store sells beans; its customers also buy grinders, brewers,
filters, mugs and canisters - which the shop does not stock. Channel3's catalogue
(25,000+ retailers) has exactly those products, with live prices, images and
affiliate-tracked buy links. The shelf finds them for the merchant's best-selling
online product and estimates what recommending them could earn.

* **Live product data** - one ``POST /v1/search`` per shelf slot, constrained by a
  Channel3 category slug and a price band (filters, not query-stuffing), tagged with
  ``x-user-id`` so the merchant's clicks and sales show up in Channel3's reporting.
* **An honest estimate** - the buyer count is real (distinct customers who bought
  the anchor product in the last 30 days of data); the attach rate is an *assumption*,
  stated as one; commission comes from the offers Channel3 returned.
* **Cheap on credits** - results are cached per merchant for ``CACHE_TTL_SECONDS``
  (Channel3 asks callers not to cache prices or offer links for hours).
* **Nothing moves money** - the shelf only reads. Buying happens on the retailer's
  site through the link; PayPilot never places an order here.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.commerce import Product, Transaction, TransactionItem
from app.integrations.sponsors import SponsorError, get_channel3
from app.integrations.sponsors.base import LIVE, SIMULATED
from app.integrations.sponsors.channel3 import MarketOffer, attribution_id
from app.services.supply.policy import money

#: Assumed share of the anchor product's buyers who also buy one shelf item a month.
#: Stated in the response as an assumption - not measured.
ATTACH_RATE = Decimal("0.06")
CACHE_TTL_SECONDS = 30 * 60
PER_SLOT = 3


@dataclass(frozen=True, slots=True)
class Slot:
    key: str
    label: str
    query: str
    category: str  # a Channel3 category slug (found with GET /v1/categories/search)
    max_price: Decimal


#: What a whole-bean coffee buyer also needs. Category slugs verified against
#: Channel3's catalogue on 2026-11-05.
COFFEE_SHELF: tuple[Slot, ...] = (
    Slot("grinders", "Grinders", "burr coffee grinder", "coffee-grinders", Decimal("250")),
    Slot("brewing", "Pour-over & brewing kits", "pour over coffee brewing kit", "coffee-making-kits", Decimal("150")),
    Slot("filters", "Filters", "pour over coffee filters", "coffee-filters", Decimal("40")),
    Slot("mugs", "Travel mugs", "insulated travel coffee mug", "travel-mugs", Decimal("60")),
    Slot("storage", "Bean storage", "airtight coffee bean canister", "food-storage-containers", Decimal("80")),
)

_cache: dict[uuid.UUID, tuple[float, dict[str, Any]]] = {}


def clear_cache() -> None:
    _cache.clear()


async def _anchor_product(session: AsyncSession, merchant_id: uuid.UUID) -> Product | None:
    """The product the shelf is built around: the merchant's online-store product, else the best seller."""
    products = (await session.execute(
        select(Product).where(Product.merchant_id == merchant_id)
    )).scalars().all()
    online = [p for p in products if (p.attributes or {}).get("channel") == "online_store" or "online" in (p.tags or [])]
    if online:
        return online[0]
    top = (await session.execute(
        select(TransactionItem.product_id, func.sum(TransactionItem.line_total).label("revenue"))
        .where(TransactionItem.merchant_id == merchant_id)
        .group_by(TransactionItem.product_id)
        .order_by(func.sum(TransactionItem.line_total).desc())
        .limit(1)
    )).first()
    return next((p for p in products if top and p.id == top.product_id), None)


async def _recent_buyers(session: AsyncSession, merchant_id: uuid.UUID, product_id: uuid.UUID) -> dict[str, Any]:
    """Distinct customers (orders, when a customer is unknown) for the product in the last 30 days of data."""
    latest = (await session.execute(
        select(func.max(Transaction.business_date)).where(Transaction.merchant_id == merchant_id)
    )).scalar_one_or_none()
    if latest is None:
        return {"buyers": 0, "orders": 0, "window_end": None}
    since = latest - timedelta(days=29)
    rows = (await session.execute(
        select(Transaction.id, Transaction.customer_id)
        .join(TransactionItem, TransactionItem.transaction_id == Transaction.id)
        .where(
            Transaction.merchant_id == merchant_id,
            TransactionItem.product_id == product_id,
            Transaction.business_date >= since,
            Transaction.business_date <= latest,
        )
        .distinct()
    )).all()
    orders = {r.id for r in rows}
    customers = {r.customer_id for r in rows if r.customer_id is not None}
    return {"buyers": len(customers) or len(orders), "orders": len(orders), "window_end": latest.isoformat()}


async def _fill_slot(slot: Slot, user_id: str) -> dict[str, Any]:
    client = get_channel3()
    try:
        result = await client.search(slot.query, limit=8, max_price=slot.max_price,
                                     category_ids=[slot.category], user_id=user_id)
    except SponsorError as exc:
        return {"key": slot.key, "label": slot.label, "category": slot.category, "products": [],
                "error": str(exc)}
    picked: list[MarketOffer] = [o for o in result.offers if o.currency == "USD" and o.in_stock is not False]
    picked = sorted(picked, key=lambda o: (o.commission_rate is None, -(o.commission_rate or 0), o.price))[:PER_SLOT]
    return {
        "key": slot.key, "label": slot.label, "category": slot.category, "mode": result.mode,
        "products": [o.as_dict() for o in picked],
    }


def _estimate(buyers: int, slots: list[dict[str, Any]]) -> dict[str, Any]:
    items = [p for s in slots for p in s["products"]]
    prices = [Decimal(p["price"]) for p in items]
    rates = [Decimal(p["commission_rate"]) for p in items if p.get("commission_rate")]
    typical_price = money(Decimal(median(prices))) if prices else None
    typical_rate = (sum(rates) / len(rates)).quantize(Decimal("0.0001")) if rates else None
    sales = money(Decimal(buyers) * ATTACH_RATE * typical_price) if typical_price is not None else None
    commission = money(sales * typical_rate) if sales is not None and typical_rate is not None else None
    return {
        "buyers_30d": buyers,
        "attach_rate": str(ATTACH_RATE),
        "typical_item_price": str(typical_price) if typical_price is not None else None,
        "typical_commission_rate": str(typical_rate) if typical_rate is not None else None,
        "monthly_shelf_sales": str(sales) if sales is not None else None,
        "monthly_commission": str(commission) if commission is not None else None,
        "assumptions": [
            f"{buyers} customers bought the anchor product in the last 30 days of data (measured).",
            f"{ATTACH_RATE * 100:.0f}% of them buy one shelf item a month (assumed, not measured).",
            "Price and commission are the median price and mean commission of the products shown (from Channel3).",
        ],
    }


async def build_shelf(session: AsyncSession, merchant_id: uuid.UUID, *, refresh: bool = False) -> dict[str, Any]:
    cached = _cache.get(merchant_id)
    if cached and not refresh and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
        return {**cached[1], "cached": True}

    anchor = await _anchor_product(session, merchant_id)
    if anchor is None:
        return {"anchor": None, "slots": [], "estimate": None, "mode": get_channel3().mode,
                "note": "No products yet - the shelf is built around your best-selling product."}
    demand = await _recent_buyers(session, merchant_id, anchor.id)
    user_id = attribution_id(merchant_id)
    slots = list(await asyncio.gather(*(_fill_slot(slot, user_id) for slot in COFFEE_SHELF)))
    mode = get_channel3().mode
    payload: dict[str, Any] = {
        "mode": mode,
        "anchor": {"product_id": str(anchor.id), "name": anchor.name, "sku": anchor.sku,
                   "price": str(money(anchor.price)), **demand},
        "slots": slots,
        "estimate": _estimate(demand["buyers"], slots),
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "cache_ttl_seconds": CACHE_TTL_SECONDS,
        "cached": False,
        "note": (
            "Live products from Channel3. Buy links are affiliate-tracked and short-lived; prices refresh "
            "every 30 minutes." if mode == LIVE else
            "No CHANNEL3_API_KEY: a labelled offline reference stands in for live Channel3 products."
        ),
        "disclaimer": "Recommendations only. PayPilot never places an order here; buying happens on the "
                      "retailer's site.",
    }
    if mode == SIMULATED:
        payload["estimate"]["assumptions"].append("Prices are from the offline reference, not live data.")
    _cache[merchant_id] = (time.monotonic(), payload)
    return payload
