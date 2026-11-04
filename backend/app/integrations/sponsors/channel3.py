"""Channel3 product search - an external market reference for the buyer agent.

Channel3 normalises product data across thousands of retailers behind one API.
PayPilot uses it for one narrow, honest purpose: **a market price reference**.
When the buyer agent is about to source a product, the merchant can see what that
product actually retails for elsewhere, which sanity-checks the *expected selling
price* the deterministic margin engine starts from.

What it is not: Channel3 never sets a limit, a budget or an offer. The limits come
from ``services/supply/policy.py`` before any agent speaks, and nothing here can
widen them. Retail prices are also not supplier cost prices; the UI says so.

API (https://docs.trychannel3.com): ``POST {base}/v1/search`` with header
``x-api-key`` and a JSON body ``{"query": ..., "limit": ..., "filters": {...}}``.
The response schema was not available to verify when this was written, so the
parser is deliberately defensive - it accepts a bare list or a ``products`` /
``results`` / ``data`` envelope, and reads price from the shapes the docs and SDK
describe. Anything unparseable is skipped and counted, never invented.
"""

from __future__ import annotations

import hashlib
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


@dataclass(slots=True)
class MarketOffer:
    title: str
    price: Decimal
    currency: str = "USD"
    brand: str = ""
    merchant: str = ""
    url: str = ""
    in_stock: bool | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "price": str(self.price),
            "currency": self.currency,
            "brand": self.brand,
            "merchant": self.merchant,
            "url": self.url,
            "in_stock": self.in_stock,
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


def parse_products(body: Any) -> tuple[list[MarketOffer], int]:
    """Normalise a search response. Returns (offers, number skipped as unparseable)."""
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
        price, currency = _price_of(product)
        title = str(product.get("title") or product.get("name") or "").strip()
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
                merchant=str(product.get("merchant") or product.get("website") or product.get("domain") or "")[:80],
                url=str(product.get("url") or "")[:500],
                in_stock=(availability.lower() == "instock") if availability else None,
            )
        )
    return offers, skipped


# --------------------------------------------------------------------------- #
# Deterministic reference catalogue (used when no API key is configured)
# --------------------------------------------------------------------------- #
#: Typical US retail prices for the categories the demo merchant sells. This is a
#: *labelled stand-in* - the mode on every result says SIMULATED.
_REFERENCE: tuple[tuple[tuple[str, ...], Decimal, str], ...] = (
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

    async def search(self, query: str, *, limit: int = 10, max_price: Decimal | None = None) -> MarketSearch:
        query = query.strip()
        if not query:
            raise SponsorRequestError("A search query is required.")
        limit = max(1, min(limit, 25))
        if not self._key:
            return reference_search(query, limit)

        body: dict[str, Any] = {"query": query, "limit": limit}
        if max_price is not None:
            body["filters"] = {"price": {"max_price": float(max_price)}}
        try:
            async with build_client(self._base, {"x-api-key": self._key}, transport=self._transport) as client:
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
