"""Channel3 product search - live retail products for PayPilot's merchants.

Channel3 normalises product data across 25,000+ retailers behind one API. PayPilot
uses it for two things:

* **The gear shelf** (``services/integrations/shelf.py``): complementary products a
  merchant can recommend next to their best seller - live prices, retailers, images
  and affiliate-tracked buy links.
* **A market price reference** (``services/integrations/market.py``): what a product
  retails for elsewhere, as context for the human approving a purchase.

What it is not: Channel3 never sets a limit, a budget or an offer. The limits come
from ``services/supply/policy.py`` before any agent speaks, and nothing here can
widen them. Retail prices are also not supplier cost prices; the UI says so.

API (https://docs.trychannel3.com, and the ``channel3-api`` agent skill in
``.agents/skills``): ``POST {base}/v1/search`` with header ``x-api-key``. A product
is ``{id, title, brands[], images[], category{slug}, offers[]}`` and each offer is
``{url, domain, price{price, currency, compare_at_price}, availability,
max_commission_rate}`` - retailer, link and stock live on the *offer*. Verified
against the live API on 2026-11-05. Anything unparseable is skipped and counted,
never invented.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.sponsors.base import (
    LIVE,
    SIMULATED,
    SponsorError,
    SponsorRequestError,
    as_dict,
    build_client,
    raise_for_status,
)

log = get_logger(__name__)

SEARCH_PATH = "/v1/search"

#: Channel3 accepts letters, digits and ``. _ @ -`` in ``x-user-id`` (max 128).
_USER_ID = re.compile(r"^[A-Za-z0-9._@-]{1,128}$")


def attribution_id(merchant_id: Any) -> str:
    """The ``x-user-id`` that attributes a merchant's Channel3 clicks and sales in reporting.
    An opaque, stable tag - no name or email leaves PayPilot."""
    return f"paypilot-{str(merchant_id).replace('-', '')[:16]}"


@dataclass(slots=True)
class MarketOffer:
    """One Channel3 product, reduced to its best offer (lowest in-stock price)."""

    title: str
    price: Decimal
    currency: str = "USD"
    brand: str = ""
    merchant: str = ""
    url: str = ""
    in_stock: bool | None = None
    product_id: str = ""
    image_url: str = ""
    category: str = ""
    compare_at_price: Decimal | None = None
    #: Affiliate commission on the best offer, as a fraction (0.05 = 5%).
    commission_rate: Decimal | None = None
    offers_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "price": str(self.price),
            "currency": self.currency,
            "brand": self.brand,
            "merchant": self.merchant,
            "url": self.url,
            "in_stock": self.in_stock,
            "product_id": self.product_id,
            "image_url": self.image_url,
            "category": self.category,
            "compare_at_price": str(self.compare_at_price) if self.compare_at_price is not None else None,
            "commission_rate": str(self.commission_rate) if self.commission_rate is not None else None,
            "offers_count": self.offers_count,
        }


@dataclass(slots=True)
class MarketSearch:
    mode: str
    query: str
    offers: list[MarketOffer] = field(default_factory=list)
    skipped: int = 0
    note: str = ""


def _money(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return amount.quantize(Decimal("0.01")) if amount > 0 else None


def _price_of(product: dict[str, Any]) -> tuple[Decimal | None, str]:
    """Pull (price, currency) from the shapes Channel3 documents, most specific first."""
    candidates: list[Any] = [product.get("price")]
    for key in ("offers", "merchant_offers"):
        offers = product.get(key)
        if isinstance(offers, list) and offers:
            candidates.append(as_dict(offers[0]).get("price"))
    for candidate in candidates:
        if isinstance(candidate, dict):
            amount = _money(candidate.get("price", candidate.get("amount", candidate.get("value"))))
            if amount is not None:
                return amount, str(candidate.get("currency") or "USD").upper()[:3]
        else:
            amount = _money(candidate)
            if amount is not None:
                return amount, str(product.get("currency") or "USD").upper()[:3]
    return None, "USD"


def _rate(value: Any) -> Decimal | None:
    """A commission fraction (0-0.5) as Decimal, or None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        rate = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return rate.quantize(Decimal("0.0001")) if Decimal(0) <= rate <= Decimal("0.5") else None


def _best_offer(product: dict[str, Any]) -> dict[str, Any] | None:
    """The offer to show: the lowest in-stock price, else the lowest price at all."""
    parsed = []
    for raw in product.get("offers") or []:
        offer = as_dict(raw)
        price_obj = as_dict(offer.get("price"))
        amount = _money(price_obj.get("price", price_obj.get("amount", price_obj.get("value"))))
        if amount is None:
            continue
        availability = str(offer.get("availability") or "")
        parsed.append({
            "price": amount,
            "currency": str(price_obj.get("currency") or "USD").upper()[:3],
            "compare_at": _money(price_obj.get("compare_at_price")),
            "domain": str(offer.get("domain") or ""),
            "url": str(offer.get("url") or ""),
            "in_stock": (availability.lower() == "instock") if availability else None,
            "commission": _rate(offer.get("max_commission_rate")),
        })
    if not parsed:
        return None
    in_stock = [o for o in parsed if o["in_stock"] is not False]
    best = min(in_stock or parsed, key=lambda o: o["price"])
    best["count"] = len(parsed)
    return best


def _image_of(product: dict[str, Any]) -> str:
    images = [as_dict(i) for i in product.get("images") or []]
    main = next((i for i in images if i.get("is_main_image")), images[0] if images else {})
    return str(main.get("cleaned_url") or main.get("url") or "")[:500]


def parse_products(body: Any) -> tuple[list[MarketOffer], int]:
    """Normalise a search response. Returns (products, number skipped as unparseable)."""
    items: Any = body
    if isinstance(body, dict):
        for key in ("products", "results", "data", "items"):
            if isinstance(body.get(key), list):
                items = body[key]
                break
    if not isinstance(items, list):
        return [], 0

    offers: list[MarketOffer] = []
    skipped = 0
    for raw in items:
        product = as_dict(raw)
        title = str(product.get("title") or product.get("name") or "").strip()
        best = _best_offer(product)
        if best is not None:
            price, currency = best["price"], best["currency"]
        else:  # older or partial shapes: a price on the product itself
            price, currency = _price_of(product)
        if price is None or not title:
            skipped += 1
            continue
        brands = product.get("brands")
        brand_name = as_dict(brands[0]).get("name") if isinstance(brands, list) and brands else ""
        availability = str(product.get("availability") or "")
        offers.append(
            MarketOffer(
                title=title[:200],
                price=price,
                currency=currency,
                brand=str(product.get("brand") or brand_name or "")[:80],
                merchant=(best["domain"] if best else "")
                or str(product.get("merchant") or product.get("website") or product.get("domain") or "")[:80],
                url=((best["url"] if best else "") or str(product.get("url") or ""))[:500],
                in_stock=best["in_stock"] if best else ((availability.lower() == "instock") if availability else None),
                product_id=str(product.get("id") or "")[:64],
                image_url=_image_of(product),
                category=str(as_dict(product.get("category")).get("slug") or "")[:80],
                compare_at_price=best["compare_at"] if best else None,
                commission_rate=best["commission"] if best else None,
                offers_count=best["count"] if best else 0,
            )
        )
    return offers, skipped


# --------------------------------------------------------------------------- #
# Deterministic reference catalogue (used when no API key is configured)
# --------------------------------------------------------------------------- #
#: Typical US retail prices for the categories the demo merchant sells. This is a
#: *labelled stand-in* - the mode on every result says SIMULATED.
_REFERENCE: tuple[tuple[tuple[str, ...], Decimal, str], ...] = (
    # Specific gear first, so "coffee filters" is a filter, not a bag of coffee.
    (("grinder",), Decimal("120.00"), "burr coffee grinder"),
    (("kit", "pour over", "dripper"), Decimal("45.00"), "pour-over brewing kit"),
    (("filter",), Decimal("8.50"), "paper coffee filters"),
    (("canister", "storage", "container"), Decimal("28.00"), "airtight coffee canister"),
    (("coffee", "bean", "espresso", "roast"), Decimal("17.50"), "12 oz specialty coffee beans"),
    (("tea", "matcha", "chai"), Decimal("14.00"), "loose-leaf tea tin"),
    (("syrup", "vanilla", "caramel"), Decimal("9.50"), "flavouring syrup 750 ml"),
    (("oat", "milk", "almond"), Decimal("4.80"), "barista plant milk 1 L"),
    (("mug", "cup", "tumbler"), Decimal("16.00"), "ceramic coffee mug"),
    (("grinder", "kettle", "brewer", "press"), Decimal("38.00"), "pour-over brewing gear"),
    (("pastry", "croissant", "muffin", "cookie"), Decimal("3.75"), "bakery item"),
)
_SPREAD = (Decimal("-0.14"), Decimal("-0.06"), Decimal("0.00"), Decimal("0.07"), Decimal("0.15"))
_RETAILERS = ("BeanBarn", "Northwest Roasters", "Marketplace Co.", "PantryDirect", "Local Grocer")


def reference_search(query: str, limit: int) -> MarketSearch:
    text = query.lower()
    base, label = Decimal("12.00"), "general merchandise"
    for keywords, price, name in _REFERENCE:
        if any(k in text for k in keywords):
            base, label = price, name
            break
    # A stable per-query nudge so different products do not share one price.
    nudge = Decimal(int(hashlib.sha256(text.encode()).hexdigest()[:4], 16) % 400) / Decimal(100) - Decimal(2)
    anchor = max(Decimal("1.00"), base + nudge)
    offers = [
        MarketOffer(
            title=f"{query.strip().title()} - {label}",
            price=(anchor * (Decimal(1) + spread)).quantize(Decimal("0.01")),
            merchant=_RETAILERS[i % len(_RETAILERS)],
            in_stock=True,
        )
        for i, spread in enumerate(_SPREAD[: max(1, min(limit, len(_SPREAD)))])
    ]
    return MarketSearch(
        mode=SIMULATED,
        query=query,
        offers=offers,
        note="No CHANNEL3_API_KEY configured: this is a deterministic reference catalogue, not live market data.",
    )


class Channel3Client:
    def __init__(self, *, api_key: str | None = None, base_url: str | None = None,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._key = settings.channel3_api_key if api_key is None else api_key
        self._base = base_url or settings.channel3_base_url
        self._transport = transport

    @property
    def mode(self) -> str:
        return LIVE if self._key else SIMULATED

    def __repr__(self) -> str:  # never leak the key
        return f"Channel3Client(mode={self.mode})"

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        max_price: Decimal | None = None,
        min_price: Decimal | None = None,
        category_ids: list[str] | None = None,
        user_id: str | None = None,
    ) -> MarketSearch:
        """``POST /v1/search``. Category slugs and a price band keep results in the right
        slice of the catalogue (filters beat query-stuffing). ``user_id`` attributes the
        merchant's clicks and sales in Channel3's reporting."""
        query = query.strip()
        if not query:
            raise SponsorRequestError("A search query is required.")
        limit = max(1, min(limit, 25))
        if not self._key:
            return reference_search(query, limit)

        body: dict[str, Any] = {"query": query, "limit": limit}
        filters: dict[str, Any] = {}
        price: dict[str, float] = {}
        if min_price is not None:
            price["min_price"] = float(min_price)
        if max_price is not None:
            price["max_price"] = float(max_price)
        if price:
            filters["price"] = price
        if category_ids:
            filters["category_ids"] = [c for c in category_ids if c][:10]
        if filters:
            body["filters"] = filters
        headers = {"x-api-key": self._key}
        if user_id and _USER_ID.match(user_id):
            headers["x-user-id"] = user_id
        try:
            async with build_client(self._base, headers, transport=self._transport) as client:
                response = await client.post(SEARCH_PATH, json=body)
        except httpx.HTTPError as exc:
            raise SponsorError(f"Channel3 is unreachable ({type(exc).__name__}).") from exc
        raise_for_status(response, "Channel3")
        try:
            offers, skipped = parse_products(response.json())
        except ValueError as exc:
            raise SponsorError("Channel3 returned a response that is not JSON.") from exc
        log.info("channel3_search", results=len(offers), skipped=skipped)
        return MarketSearch(
            mode=LIVE, query=query, offers=offers[:limit], skipped=skipped,
            note="Live Channel3 product search." if offers else "Channel3 returned no priced products.",
        )
