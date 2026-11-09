"""Product Discovery: natural language -> Channel3 -> ranked, explained, remembered.

``ProductDiscoveryService`` is merchant-scoped. Every call that reaches Channel3:

1. is throttled per merchant (``CHANNEL3_CALLS_PER_MINUTE``) on top of the API-wide limiter,
2. sends the merchant's opaque attribution tag (``x-user-id``) - never a name or email,
3. is recorded in ``product_searches`` (request, intent, result ids, duration, error),
4. upserts what it found into ``discovered_products`` (a snapshot without offer links).

Nothing is simulated: with no ``CHANNEL3_API_KEY`` the catalog client raises
``Channel3NotConfiguredError`` and the API answers 503 with setup instructions.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import SharedCache
from app.core.config import settings
from app.core.exceptions import BadRequestError, RateLimitError
from app.core.logging import get_logger
from app.core.ratelimit import WindowLimiter
from app.db.models.commerce import Product, Transaction
from app.db.models.discovery import (
    DiscoveredProduct,
    ProductComparison,
    ProductSearch,
    SearchSource,
)
from app.integrations.sponsors import get_channel3_catalog
from app.integrations.sponsors.base import SponsorError
from app.integrations.sponsors.channel3 import attribution_id
from app.integrations.sponsors.channel3_catalog import (
    CatalogProduct,
    build_filters,
    product_from_cache,
    product_to_cache,
    valid_product_id,
)
from app.services.discovery import comparison as comparison_engine
from app.services.discovery.intent import SearchIntent, budget_in_catalog_currency, understand
from app.services.discovery.ranking import rank_products, use_case_verdicts

log = get_logger(__name__)

CHANNEL3_CALLS_PER_MINUTE = 40
#: Per-merchant Channel3 call budget. Shared through Redis when it is configured, so the
#: budget survives restarts (and a deploy overlap cannot double it); per-process otherwise.
_calls = WindowLimiter("channel3", limit=CHANNEL3_CALLS_PER_MINUTE, window_seconds=60)
#: Product-detail lookups, reused for ``DISCOVERY_DETAIL_CACHE_SECONDS``. Each miss is a
#: Channel3 call, and Render restarts the API on every deploy and after every idle sleep.
_details = SharedCache("discovery-detail", encode=product_to_cache, decode=product_from_cache)


def reset_caches() -> None:
    _calls.reset()
    _details.clear_local()


async def _throttle(merchant_id: uuid.UUID, cost: int = 1) -> None:
    result = await _calls.hit(str(merchant_id), cost)
    if not result.allowed:
        raise RateLimitError("Product discovery is limited to "
                             f"{CHANNEL3_CALLS_PER_MINUTE} catalog calls a minute per merchant - try again shortly.")


def explain_similarity(source: CatalogProduct, candidate: CatalogProduct) -> dict[str, Any]:
    """Why a product is similar, and how its price compares - from Channel3 data only."""
    reasons: list[str] = []
    if candidate.category_slug and candidate.category_slug == source.category_slug:
        reasons.append(f"Same category: {candidate.category_title}")
    elif candidate.category_title:
        reasons.append(f"Related category: {candidate.category_title}")
    if candidate.brand and source.brand:
        reasons.append("Same brand" if candidate.brand == source.brand else f"Brand alternative: {candidate.brand} (vs {source.brand})")
    shared: list[str] = []
    for key, values in candidate.structured_attributes.items():
        common = set(values) & set(source.structured_attributes.get(key, []))
        shared += sorted(common)
    if shared:
        reasons.append("Shares: " + ", ".join(dict.fromkeys(shared[:6])))
    src_price = source.best_offer.price if source.best_offer else None
    cand_price = candidate.best_offer.price if candidate.best_offer else None
    diff = pct = None
    if src_price is not None and cand_price is not None and source.currency == candidate.currency:
        diff = cand_price - src_price
        pct = (diff / src_price * 100).quantize(Decimal("0.1")) if src_price else None
        if diff < 0:
            reasons.append(f"{candidate.currency} {abs(diff):,.2f} cheaper ({abs(pct or 0)}% less)")
        elif diff > 0:
            reasons.append(f"{candidate.currency} {diff:,.2f} more expensive (+{pct}%)")
        else:
            reasons.append("Same price")
    if candidate.in_stock and source.in_stock is False:
        reasons.append("In stock while the original is not")
    return {
        "reasons": reasons,
        "shared_attributes": list(dict.fromkeys(shared))[:12],
        "price_difference": str(diff) if diff is not None else None,
        "price_difference_pct": str(pct) if pct is not None else None,
        "same_brand": bool(candidate.brand and candidate.brand == source.brand),
        "same_category": bool(candidate.category_slug and candidate.category_slug == source.category_slug),
    }


class ProductDiscoveryService:
    def __init__(self, session: AsyncSession, merchant_id: uuid.UUID, *, user_id: uuid.UUID | None = None,
                 agent_run_id: uuid.UUID | None = None) -> None:
        self.session = session
        self.merchant_id = merchant_id
        self.user_id = user_id
        self.agent_run_id = agent_run_id
        self.catalog = get_channel3_catalog()
        self.attribution = attribution_id(merchant_id)

    # ------------------------------------------------------------------ status
    def status(self) -> dict[str, Any]:
        return {
            "configured": self.catalog.configured,
            "mode": self.catalog.mode,
            "currency": self.catalog.currency,
            "country": self.catalog.country,
            "fx_reference_rates": settings.discovery_fx_rates,
            "setup": None if self.catalog.configured else
            "Set CHANNEL3_API_KEY in .env (https://trychannel3.com/developers) and restart the backend.",
        }

    # ------------------------------------------------------------------ search
    async def search(
        self,
        text: str,
        *,
        min_price: float | None = None,
        max_price: float | None = None,
        brands: list[str] | None = None,
        category: str | None = None,
        retailers: list[str] | None = None,
        include_out_of_stock: bool | None = None,
        on_sale: bool | None = None,
        limit: int = 12,
        page_token: str | None = None,
        mode: str = "default",
        source: str = SearchSource.DISCOVERY,
        trace: Any = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        intent, used_llm = await understand(text, trace=trace)
        # Explicit filters from the UI win over what was parsed from the sentence.
        if brands:
            intent.brands = list(dict.fromkeys([*intent.brands, *[b.strip() for b in brands if b.strip()]]))[:5]
        if retailers:
            intent.retailers = list(dict.fromkeys([*intent.retailers, *[r.strip().lower() for r in retailers if r.strip()]]))[:5]
        if include_out_of_stock is not None:
            intent.include_out_of_stock = include_out_of_stock
        if on_sale is not None:
            intent.on_sale = on_sale
        budget = budget_in_catalog_currency(intent, self.catalog.currency)
        lo = min_price if min_price is not None else budget["min_price"]
        hi = max_price if max_price is not None else budget["max_price"]
        notes: list[str] = [budget["note"]] if budget["note"] and min_price is None and max_price is None else []

        cost = 1 + (1 if not category and intent.category else 0) + len(intent.brands) + len(intent.exclude_brands)
        await _throttle(self.merchant_id, cost)
        record = ProductSearch(merchant_id=self.merchant_id, user_id=self.user_id, source=source, query=text[:2000],
                               intent=intent.model_dump(mode="json"), mode=self.catalog.mode, used_llm=used_llm,
                               agent_run_id=self.agent_run_id)
        try:
            brand_ids, query = await self._resolve_brands(intent.brands, intent.query)
            exclude_ids, _ = await self._resolve_brands(intent.exclude_brands, "")
            category_slug, category_title = (category, None) if category else await self._resolve_category(intent)
            filters = build_filters(min_price=lo, max_price=hi, brand_ids=brand_ids,
                                    category_ids=[category_slug] if category_slug else None,
                                    website_ids=intent.retailers, include_out_of_stock=intent.include_out_of_stock,
                                    on_sale=intent.on_sale)
            if exclude_ids:
                filters["exclude_brand_ids"] = exclude_ids
            page = await self.catalog.search(query, filters=filters, limit=limit, page_token=page_token,
                                             mode=mode, user_id=self.attribution)
            if category_slug and not category and len(page.products) < 3 and not page_token:
                # A guessed category can be too narrow - widen once, and say so.
                await _throttle(self.merchant_id)
                filters.pop("category_ids", None)
                wider = await self.catalog.search(query, filters=filters, limit=limit, mode=mode, user_id=self.attribution)
                if len(wider.products) > len(page.products):
                    notes.append(f"Few results in the '{category_title or category_slug}' category, so the search was widened.")
                    page, category_slug = wider, None
            verdicts, used_fit = await use_case_verdicts(page.products, intent, trace=trace)
            ranked = rank_products(page.products, intent, min_price=lo, max_price=hi, verdicts=verdicts)
        except SponsorError as exc:
            record.error = str(exc)[:1000]
            record.duration_ms = int((time.perf_counter() - started) * 1000)
            self.session.add(record)
            await self.session.flush()
            raise
        record.request = {"query": query, "filters": filters, "limit": limit, "mode": mode,
                          "currency": self.catalog.currency, "country": self.catalog.country}
        record.result_count = len(ranked)
        record.product_ids = [p["id"] for p in ranked]
        record.duration_ms = int((time.perf_counter() - started) * 1000)
        record.used_llm = used_llm or used_fit
        self.session.add(record)
        await self._remember(page.products, source)
        await self.session.flush()
        if page.skipped:
            notes.append(f"{page.skipped} result(s) without a title were skipped.")
        return {
            "search_id": str(record.id),
            "query": text,
            "intent": intent.model_dump(mode="json"),
            "budget": budget,
            "applied_filters": filters,
            "channel3_query": query,
            "category": {"slug": category_slug, "title": category_title} if category_slug else None,
            "products": ranked,
            "next_page_token": page.next_page_token,
            "notes": notes,
            "mode": self.catalog.mode,
            "used_llm": record.used_llm,
            "duration_ms": record.duration_ms,
            "ranking_note": "Scores combine Channel3 relevance, budget fit, availability, requested features, brand "
                            "preference, retailer coverage and - only when Channel3 returns them - ratings.",
        }

    async def _resolve_brands(self, names: list[str], query: str) -> tuple[list[str], str]:
        """Brand names -> Channel3 brand ids (exact name match only). Unresolved names stay in the query."""
        ids: list[str] = []
        for name in names[:5]:
            try:
                matches = await self.catalog.brands(name, limit=5)
            except SponsorError:
                continue
            exact = next((b for b in matches if b["name"].lower() == name.lower()), None)
            if exact:
                ids.append(exact["id"])
                if len(names) > 1:
                    query = " ".join(w for w in query.split() if w.lower() != name.lower())
        return ids, (query.strip() or " ".join(names))

    async def _resolve_category(self, intent: SearchIntent) -> tuple[str | None, str | None]:
        hint = (intent.category or "").strip()
        if len(hint) < 3:
            return None, None
        try:
            categories = await self.catalog.categories(hint, limit=3)
        except SponsorError:
            return None, None
        if not categories:
            return None, None
        return categories[0]["slug"], categories[0]["title"]

    # ------------------------------------------------------------------ product detail
    async def product(self, product_id: str, *, with_similar: bool = True, fresh: bool = False) -> dict[str, Any]:
        product = await self._fetch(product_id, fresh=fresh)
        out: dict[str, Any] = {"product": product.as_dict(), "fetched_at": datetime.now(tz=UTC).isoformat(),
                               "similar": [], "similar_error": None}
        seen = await self._seen(product.id)
        if seen:
            out["history"] = {"first_seen_at": seen.first_seen_at.isoformat(), "times_seen": seen.times_seen,
                              "is_shortlisted": seen.is_shortlisted,
                              "previous_min_price": str(seen.min_price) if seen.min_price is not None else None}
        await self._remember([product], SearchSource.DISCOVERY)
        if with_similar:
            try:
                similar = await self.similar(product_id, limit=8, source_product=product)
                out["similar"] = similar["products"]
            except SponsorError as exc:
                out["similar_error"] = str(exc)
        await self.session.flush()
        return out

    async def _fetch(self, product_id: str, *, fresh: bool = False) -> CatalogProduct:
        pid = valid_product_id(product_id)
        key = f"{self.merchant_id}:{pid}"
        if not fresh:
            cached = await _details.get(key)
            if cached is not None:
                return cached
        await _throttle(self.merchant_id)
        product = await self.catalog.product(pid, user_id=self.attribution)
        await _details.set(key, product, settings.discovery_detail_cache_seconds)
        return product

    async def similar(
        self, product_id: str, *, limit: int = 12, max_price: float | None = None, min_price: float | None = None,
        same_brand: bool | None = None, source_product: CatalogProduct | None = None,
        source: str = SearchSource.SIMILAR,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        base = source_product or await self._fetch(product_id)
        filters = build_filters(min_price=min_price, max_price=max_price,
                                brand_ids=[base.brand_id] if same_brand and base.brand_id else None)
        if same_brand is False and base.brand_id:
            filters["exclude_brand_ids"] = [base.brand_id]
        await _throttle(self.merchant_id)
        fallback_used = False
        try:
            page = await self.catalog.similar(base.id, filters=filters or None, limit=limit, user_id=self.attribution)
        except SponsorError as exc:
            if exc.status_code != 404:
                raise
            # Not in Channel3's similarity index yet - the documented fallback is a title search.
            await _throttle(self.merchant_id)
            page = await self.catalog.search(base.title, filters=filters or None, limit=limit + 1, user_id=self.attribution)
            page.products = [p for p in page.products if p.id != base.id]
            fallback_used = True
        products = []
        for candidate in page.products[:limit]:
            products.append({**candidate.as_dict(), "similarity": explain_similarity(base, candidate)})
        self.session.add(ProductSearch(
            merchant_id=self.merchant_id, user_id=self.user_id, source=source, query=f"similar:{base.id} {base.title}"[:2000],
            intent={"source_product_id": base.id, "source_title": base.title}, request=page.request,
            result_count=len(products), product_ids=[p["id"] for p in products], mode=self.catalog.mode,
            duration_ms=int((time.perf_counter() - started) * 1000), agent_run_id=self.agent_run_id,
        ))
        await self._remember(page.products[:limit], source)
        await self.session.flush()
        return {"source": base.as_dict(), "products": products, "fallback_used": fallback_used,
                "note": "Channel3 has not indexed this product for similarity yet - these come from a search by its title."
                if fallback_used else None}

    async def enrich(self, url: str) -> dict[str, Any]:
        """Product URL -> structured Channel3 product (``POST /v1/lookup``), then full details."""
        started = time.perf_counter()
        await _throttle(self.merchant_id, 2)
        record = ProductSearch(merchant_id=self.merchant_id, user_id=self.user_id, source=SearchSource.ENRICH,
                               query=url[:2000], intent={"url": url}, request={"url": url}, mode=self.catalog.mode,
                               agent_run_id=self.agent_run_id)
        try:
            looked_up = await self.catalog.lookup(url, user_id=self.attribution)
            try:
                product = await self.catalog.product(looked_up.id, user_id=self.attribution)
            except SponsorError:
                product = looked_up
        except SponsorError as exc:
            record.error = str(exc)[:1000]
            record.duration_ms = int((time.perf_counter() - started) * 1000)
            self.session.add(record)
            await self.session.flush()
            raise
        await _details.set(f"{self.merchant_id}:{product.id}", product, settings.discovery_detail_cache_seconds)
        record.result_count, record.product_ids = 1, [product.id]
        record.duration_ms = int((time.perf_counter() - started) * 1000)
        self.session.add(record)
        await self._remember([product], SearchSource.ENRICH)
        await self.session.flush()
        return {"product": product.as_dict(), "source_url": url}

    # ------------------------------------------------------------------ compare
    async def compare(self, product_ids: list[str], *, wanted: list[str] | None = None, trace: Any = None) -> dict[str, Any]:
        ids = list(dict.fromkeys(valid_product_id(p) for p in product_ids))
        if not 2 <= len(ids) <= 4:
            raise BadRequestError("Compare between 2 and 4 products.")
        products = [await self._fetch(pid, fresh=True) for pid in ids]
        context = await self.merchant_context()
        result = comparison_engine.compare(products, merchant_context=context, wanted=wanted)
        narrative, used_llm = await comparison_engine.narrate(result, trace=trace)
        row = ProductComparison(merchant_id=self.merchant_id, user_id=self.user_id, product_ids=ids,
                                titles=[p.title for p in products], used_llm=used_llm, narrative=narrative,
                                analysis={k: v for k, v in result.items() if k != "products"})
        self.session.add(row)
        await self._remember(products, SearchSource.DISCOVERY)
        await self.session.flush()
        return {**result, "comparison_id": str(row.id), "narrative": narrative, "used_llm": used_llm}

    async def merchant_context(self) -> dict[str, Any]:
        """The price band the merchant's own customers pay - catalog prices and average order value."""
        prices = sorted(float(p) for (p,) in (await self.session.execute(
            select(Product.price).where(Product.merchant_id == self.merchant_id, Product.is_active.is_(True))
        )).all() if p is not None)
        latest = (await self.session.execute(
            select(func.max(Transaction.business_date)).where(Transaction.merchant_id == self.merchant_id)
        )).scalar_one_or_none()
        aov = None
        if latest is not None:
            total, orders = (await self.session.execute(
                select(func.sum(Transaction.net_amount), func.count(Transaction.id)).where(
                    Transaction.merchant_id == self.merchant_id,
                    Transaction.business_date >= latest - timedelta(days=89),
                )
            )).one()
            aov = round(float(total) / orders, 2) if orders else None
        return {
            "catalog_median_price": round(median(prices), 2) if prices else None,
            "catalog_p75_price": round(prices[int(len(prices) * 0.75) - 1 if len(prices) > 1 else 0], 2) if prices else None,
            "catalog_products": len(prices),
            "average_order_value": aov,
            "window": "last 90 days of transactions",
        }

    # ------------------------------------------------------------------ memory
    async def _seen(self, product_id: str) -> DiscoveredProduct | None:
        return (await self.session.execute(
            select(DiscoveredProduct).where(DiscoveredProduct.merchant_id == self.merchant_id,
                                            DiscoveredProduct.channel3_product_id == product_id)
        )).scalars().first()

    async def _remember(self, products: list[CatalogProduct], source: str) -> None:
        if not products:
            return
        ids = [p.id for p in products]
        existing = {row.channel3_product_id: row for row in (await self.session.execute(
            select(DiscoveredProduct).where(DiscoveredProduct.merchant_id == self.merchant_id,
                                            DiscoveredProduct.channel3_product_id.in_(ids))
        )).scalars().all()}
        now = datetime.now(tz=UTC)
        for product in products:
            snapshot = product.as_dict(include_offer_urls=False)
            row = existing.get(product.id)
            if row is None:
                row = DiscoveredProduct(merchant_id=self.merchant_id, channel3_product_id=product.id,
                                        first_seen_at=now, times_seen=0)
                self.session.add(row)
                existing[product.id] = row
            row.title = product.title[:300]
            row.brand = product.brand[:120]
            row.category_slug = product.category_slug[:80]
            row.category_title = product.category_title[:120]
            row.image_url = product.image_url[:2000]
            row.currency = product.currency
            row.min_price = product.min_price
            row.max_price = product.max_price
            row.offers_count = len(product.offers)
            row.retailer = (product.best_offer.domain if product.best_offer else "")[:120]
            row.in_stock = product.in_stock
            row.snapshot = snapshot
            row.last_seen_at = now
            row.times_seen = (row.times_seen or 0) + 1
            row.last_source = source

    async def history(self, *, limit: int = 30) -> list[dict[str, Any]]:
        rows = (await self.session.execute(
            select(ProductSearch).where(ProductSearch.merchant_id == self.merchant_id)
            .order_by(ProductSearch.created_at.desc()).limit(limit)
        )).scalars().all()
        return [{
            "id": str(r.id), "query": r.query, "source": r.source, "result_count": r.result_count,
            "intent": r.intent, "filters": (r.request or {}).get("filters", {}), "mode": r.mode,
            "used_llm": r.used_llm, "duration_ms": r.duration_ms, "error": r.error,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in rows]

    async def discovered(self, *, limit: int = 24, shortlisted: bool | None = None) -> list[dict[str, Any]]:
        stmt = select(DiscoveredProduct).where(DiscoveredProduct.merchant_id == self.merchant_id)
        if shortlisted is not None:
            stmt = stmt.where(DiscoveredProduct.is_shortlisted.is_(shortlisted))
        rows = (await self.session.execute(stmt.order_by(DiscoveredProduct.last_seen_at.desc()).limit(limit))).scalars().all()
        return [discovered_out(r) for r in rows]

    async def shortlist(self, product_id: str, *, value: bool) -> dict[str, Any]:
        row = await self._seen(valid_product_id(product_id))
        if row is None:
            product = await self._fetch(product_id)
            await self._remember([product], SearchSource.DISCOVERY)
            await self.session.flush()
            row = await self._seen(product.id)
        assert row is not None
        row.is_shortlisted = value
        await self.session.flush()
        return discovered_out(row)

    async def comparisons(self, *, limit: int = 10) -> list[dict[str, Any]]:
        rows = (await self.session.execute(
            select(ProductComparison).where(ProductComparison.merchant_id == self.merchant_id)
            .order_by(ProductComparison.created_at.desc()).limit(limit)
        )).scalars().all()
        return [{"id": str(r.id), "product_ids": r.product_ids, "titles": r.titles, "narrative": r.narrative,
                 "used_llm": r.used_llm, "overall": (r.analysis or {}).get("overall"),
                 "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]


def discovered_out(row: DiscoveredProduct) -> dict[str, Any]:
    return {
        "id": row.channel3_product_id,
        "title": row.title,
        "brand": row.brand,
        "category": {"slug": row.category_slug, "title": row.category_title},
        "image_url": row.image_url,
        "currency": row.currency,
        "min_price": str(row.min_price) if row.min_price is not None else None,
        "max_price": str(row.max_price) if row.max_price is not None else None,
        "offers_count": row.offers_count,
        "retailer": row.retailer,
        "in_stock": row.in_stock,
        "times_seen": row.times_seen,
        "is_shortlisted": row.is_shortlisted,
        "last_source": row.last_source,
        "first_seen_at": row.first_seen_at.isoformat() if row.first_seen_at else None,
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        "price_is_snapshot": True,
    }


__all__ = ["ProductDiscoveryService", "discovered_out", "explain_similarity", "reset_caches"]
