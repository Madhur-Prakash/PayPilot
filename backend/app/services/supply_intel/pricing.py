"""Market price intelligence: the merchant's selling price against live retail listings.

For each product the merchant sells at retail, Channel3 is searched for comparable
listings, constrained to a sane price band. Search is semantic, so results are kept
only when they cluster in one Channel3 category (the same rule as the purchase-approval
market reference) - a median over canisters, face scrubs and espresso machines would be
meaningless.

What this is **not**: a cost. These are other sellers' *retail* prices. The merchant's
own unit cost is shown beside them, labelled as such, and nothing here touches a
procurement budget or limit. Any suggested price is a test the merchant must approve,
and its impact estimate states that it assumes unit sales hold.
"""

from __future__ import annotations

import time
import uuid
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.commerce import Product
from app.db.models.discovery import ProductSearch, SearchSource
from app.db.models.inventory import InventoryItem
from app.integrations.sponsors import get_channel3_catalog
from app.integrations.sponsors.base import SponsorError
from app.integrations.sponsors.channel3 import attribution_id
from app.integrations.sponsors.channel3_catalog import CatalogProduct, build_filters
from app.services.discovery.service import ProductDiscoveryService, _throttle

MIN_COMPARABLES = 3
MIN_SHARE = Decimal("0.4")
#: Smallest gap to the market median worth a merchant's attention.
MATERIAL_GAP_PCT = Decimal("10")
#: A suggested price test never moves more than this in one step.
MAX_STEP_PCT = Decimal("0.10")


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _search_phrase(product: Product) -> str:
    name = product.name.replace("(", " ").replace(")", " ")
    return " ".join(name.split())[:120]


def consistent(products: list[CatalogProduct]) -> tuple[list[CatalogProduct], str | None, str | None]:
    """The comparables that are the same kind of product, by Channel3 category."""
    cats = Counter(p.category_slug for p in products if p.category_slug)
    if not cats:
        return [], None, None
    slug, count = cats.most_common(1)[0]
    if count >= MIN_COMPARABLES and Decimal(count) >= MIN_SHARE * len(products):
        kept = [p for p in products if p.category_slug == slug]
        return kept, slug, kept[0].category_title
    return [], None, None


class PricingIntelligence:
    def __init__(self, session: AsyncSession, merchant_id: uuid.UUID, *, user_id: uuid.UUID | None = None,
                 agent_run_id: uuid.UUID | None = None) -> None:
        self.session = session
        self.merchant_id = merchant_id
        self.user_id = user_id
        self.agent_run_id = agent_run_id
        self.catalog = get_channel3_catalog()

    async def _candidates(self, product_ids: list[uuid.UUID] | None, limit: int) -> list[Product]:
        stmt = select(Product).where(Product.merchant_id == self.merchant_id, Product.is_active.is_(True))
        if product_ids:
            stmt = stmt.where(Product.id.in_(product_ids))
        products = list((await self.session.execute(stmt)).scalars().all())
        if product_ids:
            return products[:limit]
        # Only retail products are compared automatically: a shopper can buy those elsewhere. A cafe
        # drink is not the same product as a bottled retail pack, so prepared items are compared only
        # when the merchant explicitly asks (product_ids) and judges the comparables themselves.
        retail = [p for p in products if (p.attributes or {}).get("channel") == "online_store"
                  or p.category in ("retail", "merchandise") or (p.attributes or {}).get("source") == "channel3"]
        return retail[:limit]

    async def analyze(self, *, product_ids: list[uuid.UUID] | None = None, limit: int = 3,
                      units_by_product: dict[str, float] | None = None) -> dict[str, Any]:
        products = await self._candidates(product_ids, max(1, min(limit, 5)))
        results = []
        for product in products:
            results.append(await self._one(product, (units_by_product or {}).get(str(product.id))))
        await self.session.flush()
        return {
            "mode": self.catalog.mode,
            "currency": self.catalog.currency,
            "products": results,
            "disclaimer": "Comparable prices are retail listings from other sellers (Channel3). They are not your "
                          "wholesale or procurement cost, and they never change a purchasing budget or limit.",
        }

    async def _one(self, product: Product, units_30d: float | None) -> dict[str, Any]:
        price = _q(Decimal(str(product.price)))
        item = (await self.session.execute(
            select(InventoryItem).where(InventoryItem.merchant_id == self.merchant_id,
                                        InventoryItem.product_id == product.id)
        )).scalars().first()
        unit_cost = Decimal(str(item.unit_cost)) if item and item.unit_cost else Decimal(str(product.cost_price or 0))
        base: dict[str, Any] = {
            "product_id": str(product.id), "name": product.name, "sku": product.sku, "category": product.category,
            "merchant_price": str(price), "merchant_unit_cost": str(_q(unit_cost)) if unit_cost > 0 else None,
            "merchant_margin_pct": str(_q((price - unit_cost) / price * 100)) if unit_cost > 0 and price > 0 else None,
            "currency": self.catalog.currency, "comparables": [], "stats": None, "position": None,
            "opportunity": None, "error": None,
        }
        query = _search_phrase(product)
        filters = build_filters(min_price=price * Decimal("0.35"), max_price=price * 3)
        started = time.perf_counter()
        record = ProductSearch(merchant_id=self.merchant_id, user_id=self.user_id, source=SearchSource.PRICING,
                               query=query, intent={"product_id": str(product.id), "merchant_price": str(price)},
                               request={"query": query, "filters": filters, "limit": 15}, mode=self.catalog.mode,
                               agent_run_id=self.agent_run_id)
        try:
            _throttle(self.merchant_id)
            page = await self.catalog.search(query, filters=filters, limit=15, user_id=attribution_id(self.merchant_id))
        except SponsorError as exc:
            record.error = str(exc)[:1000]
            record.duration_ms = int((time.perf_counter() - started) * 1000)
            self.session.add(record)
            if exc.status_code == 503:
                raise
            return {**base, "error": str(exc)}
        record.result_count, record.product_ids = len(page.products), [p.id for p in page.products]
        record.duration_ms = int((time.perf_counter() - started) * 1000)
        self.session.add(record)
        await ProductDiscoveryService(self.session, self.merchant_id, user_id=self.user_id)._remember(page.products, SearchSource.PRICING)

        same_currency = [p for p in page.products if p.best_offer and p.currency == self.catalog.currency]
        kept, slug, title = consistent(same_currency)
        base["query"] = query
        base["searched"] = len(page.products)
        base["comparable_category"] = {"slug": slug, "title": title} if slug else None
        base["comparables"] = [{
            "id": p.id, "title": p.title, "brand": p.brand, "image_url": p.image_url, "retailer": p.best_offer.domain,
            "price": str(p.best_offer.price), "url": p.best_offer.url, "in_stock": p.in_stock,
        } for p in sorted(kept, key=lambda p: p.best_offer.price)[:10]]  # type: ignore[union-attr]
        if not kept:
            base["note"] = ("Channel3 returned listings across unrelated categories, so there is no consistent "
                            "market price for this product." if same_currency else "No comparable listings found.")
            return base
        prices = [p.best_offer.price for p in kept]  # type: ignore[union-attr]
        mid = _q(Decimal(median(prices)))
        stats = {"min": str(min(prices)), "median": str(mid), "max": str(max(prices)), "count": len(prices)}
        base["stats"] = stats
        gap = _q((price - mid) / mid * 100) if mid > 0 else Decimal(0)
        if abs(gap) < MATERIAL_GAP_PCT:
            verdict = "in line with the market"
        elif gap < 0:
            verdict = "below the market median"
        else:
            verdict = "above the market median"
        base["position"] = {"difference_pct": str(gap), "difference": str(_q(price - mid)), "verdict": verdict}
        if gap <= -MATERIAL_GAP_PCT:
            step = min(mid - price, price * MAX_STEP_PCT)
            suggested = _q(price + step)
            monthly_units = Decimal(str(units_30d)) if units_30d else None
            base["opportunity"] = {
                "type": "PRICE_TEST_UP",
                "suggested_price": str(suggested),
                "step_pct": str(_q(step / price * 100)),
                "estimated_monthly_revenue_change": str(_q(monthly_units * (suggested - price))) if monthly_units else None,
                "assumptions": [
                    f"Your price {price} is {abs(gap)}% below the median of {len(prices)} comparable listings ({mid}).",
                    f"Test is capped at +{MAX_STEP_PCT * 100:.0f}% per step.",
                    "Revenue change assumes unit sales hold at the last 30 days' level - real demand will respond to "
                    "price, which is why this is a test, not a change.",
                ],
            }
        elif gap >= MATERIAL_GAP_PCT:
            base["opportunity"] = {
                "type": "PRICE_REVIEW",
                "suggested_price": None,
                "assumptions": [
                    f"Your price {price} is {gap}% above the median of {len(prices)} comparable listings ({mid}).",
                    "Confirm what justifies the premium (freshness, origin, service) or test a bundle instead of a cut.",
                ],
            }
        return base


__all__ = ["PricingIntelligence", "consistent"]
