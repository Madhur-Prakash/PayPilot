"""Channel3 catalog client - the full product API behind Product Discovery and Supply Intelligence.

``channel3.py`` keeps the original, deliberately small ``search`` used by the gear shelf
and the market price reference (which may fall back to a labelled offline reference).
This module is the *catalog* client, and it never falls back: without
``CHANNEL3_API_KEY`` every call raises :class:`Channel3NotConfiguredError` (HTTP 503 with
setup instructions) instead of inventing products.

Endpoints (verified against the live API on 2026-11-06, and against
``.claude/skills/channel3-api/references/api-reference.md``):

==========================  ==========================================================
``POST /v1/search``         ``{query, limit<=30, page_token, filters, config}`` -> ``{products, next_page_token}``
``POST /v1/similar``        ``{product_id, limit, filters, config}`` -> same shape (404 = not catalogued)
``GET  /v1/products/{id}``  full product, variants hydrated; free call
``POST /v1/lookup``         ``{url}`` -> ``{product}`` (2-10 s uncached; 422 not a product page)
``GET  /v1/categories/search``  ``?query&limit<=20`` -> ``{categories: [{slug,title,path}]}``
``GET  /v1/brands/search``  ``?query&limit<=20`` -> ``{brands: [{id,name}]}``
``POST /v1/conversations``  ``{message:{role,parts}, conversation_id?, filters?, stream:false}``
                            -> ``{conversation_id, turn_id, usage, message:{parts, suggestions}}``
==========================  ==========================================================

Auth is the ``x-api-key`` header (server side only - the key never reaches a browser,
a log line or a response). ``x-user-id`` attributes clicks and sales to the merchant.

Reliability: bounded retries with exponential backoff (honouring ``Retry-After``) on
network errors, timeouts, 429 and 5xx; 4xx are never retried. Normalisation keeps only
what Channel3 returned - a missing specification stays missing, a rating is shown only
when Channel3 sends one.
"""

from __future__ import annotations

import asyncio
import random
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.sponsors.base import LIVE, SponsorError, SponsorRequestError, as_dict

log = get_logger(__name__)

SEARCH_PATH = "/v1/search"
SIMILAR_PATH = "/v1/similar"
PRODUCT_PATH = "/v1/products/{product_id}"
LOOKUP_PATH = "/v1/lookup"
CATEGORIES_PATH = "/v1/categories/search"
BRANDS_PATH = "/v1/brands/search"
CONVERSATIONS_PATH = "/v1/conversations"

#: Currencies Channel3 can price offers in.
SUPPORTED_CURRENCIES = ("USD", "CAD", "AUD", "GBP", "EUR", "SEK", "CZK", "RON")
_RETRYABLE = {408, 425, 429, 500, 502, 503, 504}
_USER_ID = re.compile(r"^[A-Za-z0-9._@-]{1,128}$")
_PRODUCT_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SETUP_HINT = (
    "Set CHANNEL3_API_KEY in .env (free key at https://trychannel3.com/developers) and restart the "
    "backend. Product Discovery never substitutes invented products for live Channel3 data."
)


class Channel3NotConfiguredError(SponsorError):
    """No API key: the catalog cannot be reached. Rendered as HTTP 503 with setup steps."""

    def __init__(self) -> None:
        super().__init__("Channel3 is not configured. " + SETUP_HINT, status_code=503)


# --------------------------------------------------------------------------- #
# Normalised model
# --------------------------------------------------------------------------- #
def _money(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return amount.quantize(Decimal("0.01")) if amount > 0 else None


def _fraction(value: Any, *, upper: Decimal = Decimal("0.5")) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        rate = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return rate.quantize(Decimal("0.0001")) if Decimal(0) <= rate <= upper else None


def _text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _str_list(value: Any, *, limit: int = 20, size: int = 200) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip()[:size] for v in value if isinstance(v, str | int | float) and str(v).strip()][:limit]


@dataclass(slots=True)
class CatalogOffer:
    """One retailer's listing of a product."""

    domain: str
    url: str
    price: Decimal
    currency: str
    compare_at_price: Decimal | None = None
    availability: str | None = None
    condition: str | None = None
    commission_rate: Decimal | None = None
    dimensions: dict[str, Any] | None = None

    @property
    def in_stock(self) -> bool | None:
        if not self.availability:
            return None
        return self.availability.lower() == "instock"

    @property
    def discount_pct(self) -> Decimal | None:
        if self.compare_at_price and self.compare_at_price > self.price:
            return ((self.compare_at_price - self.price) / self.compare_at_price * 100).quantize(Decimal("0.1"))
        return None

    def as_dict(self, *, include_url: bool = True) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "url": self.url if include_url else "",
            "price": str(self.price),
            "currency": self.currency,
            "compare_at_price": str(self.compare_at_price) if self.compare_at_price is not None else None,
            "discount_pct": str(self.discount_pct) if self.discount_pct is not None else None,
            "availability": self.availability,
            "in_stock": self.in_stock,
            "condition": self.condition,
            "commission_rate": str(self.commission_rate) if self.commission_rate is not None else None,
            "dimensions": self.dimensions,
        }


@dataclass(slots=True)
class CatalogProduct:
    """A Channel3 product with exactly the fields Channel3 returned."""

    id: str
    title: str
    description: str = ""
    brand: str = ""
    brand_id: str = ""
    images: list[dict[str, Any]] = field(default_factory=list)
    category_slug: str = ""
    category_title: str = ""
    category_path: list[str] = field(default_factory=list)
    gender: str | None = None
    age: str | None = None
    materials: list[str] = field(default_factory=list)
    key_features: list[str] = field(default_factory=list)
    structured_attributes: dict[str, list[str]] = field(default_factory=dict)
    variants: dict[str, Any] | None = None
    offers: list[CatalogOffer] = field(default_factory=list)
    #: ``{"value": 3.6, "count": 992}`` only when Channel3 returns ratings; never invented.
    ratings: dict[str, Any] | None = None

    # ------------------------------------------------------------------ derived
    @property
    def image_url(self) -> str:
        main = next((i for i in self.images if i.get("is_main")), self.images[0] if self.images else {})
        return str(main.get("cleaned_url") or main.get("url") or "")

    @property
    def best_offer(self) -> CatalogOffer | None:
        """The lowest in-stock price, else the lowest price at all."""
        if not self.offers:
            return None
        in_stock = [o for o in self.offers if o.in_stock is not False]
        return min(in_stock or self.offers, key=lambda o: o.price)

    @property
    def currency(self) -> str:
        best = self.best_offer
        return best.currency if best else settings.channel3_currency

    @property
    def min_price(self) -> Decimal | None:
        prices = [o.price for o in self.offers if o.currency == self.currency]
        return min(prices) if prices else None

    @property
    def max_price(self) -> Decimal | None:
        prices = [o.price for o in self.offers if o.currency == self.currency]
        return max(prices) if prices else None

    @property
    def in_stock(self) -> bool | None:
        states = [o.in_stock for o in self.offers if o.in_stock is not None]
        if not states:
            return None
        return any(states)

    @property
    def retailers(self) -> list[str]:
        seen: list[str] = []
        for offer in self.offers:
            if offer.domain and offer.domain not in seen:
                seen.append(offer.domain)
        return seen

    def as_dict(self, *, include_offer_urls: bool = True) -> dict[str, Any]:
        best = self.best_offer
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "brand": self.brand,
            "brand_id": self.brand_id,
            "image_url": self.image_url,
            "images": self.images,
            "category": {"slug": self.category_slug, "title": self.category_title, "path": self.category_path},
            "gender": self.gender,
            "age": self.age,
            "materials": self.materials,
            "key_features": self.key_features,
            "structured_attributes": self.structured_attributes,
            "variants": self.variants,
            "ratings": self.ratings,
            "price": str(best.price) if best else None,
            "compare_at_price": str(best.compare_at_price) if best and best.compare_at_price is not None else None,
            "discount_pct": str(best.discount_pct) if best and best.discount_pct is not None else None,
            "currency": self.currency,
            "min_price": str(self.min_price) if self.min_price is not None else None,
            "max_price": str(self.max_price) if self.max_price is not None else None,
            "in_stock": self.in_stock,
            "retailer": best.domain if best else "",
            "url": (best.url if best else "") if include_offer_urls else "",
            "retailers": self.retailers,
            "offers_count": len(self.offers),
            "offers": [o.as_dict(include_url=include_offer_urls) for o in sorted(self.offers, key=lambda o: o.price)],
            "commission_rate": str(best.commission_rate) if best and best.commission_rate is not None else None,
        }


def _parse_offer(raw: Any) -> CatalogOffer | None:
    offer = as_dict(raw)
    price_obj = as_dict(offer.get("price"))
    amount = _money(price_obj.get("price", price_obj.get("amount")))
    if amount is None:
        return None
    dims = offer.get("dimensions")
    return CatalogOffer(
        domain=_text(offer.get("domain"), 120),
        url=_text(offer.get("url"), 1000),
        price=amount,
        currency=_text(price_obj.get("currency") or settings.channel3_currency, 3).upper(),
        compare_at_price=_money(price_obj.get("compare_at_price")),
        availability=_text(offer.get("availability"), 24) or None,
        condition=_text(offer.get("condition"), 16) or None,
        commission_rate=_fraction(offer.get("max_commission_rate")),
        dimensions=dims if isinstance(dims, dict) else None,
    )


def _parse_images(raw: Any) -> list[dict[str, Any]]:
    images: list[dict[str, Any]] = []
    for item in raw if isinstance(raw, list) else []:
        image = as_dict(item)
        url = _text(image.get("url"), 1000)
        if not url:
            continue
        images.append({
            "url": url,
            "cleaned_url": _text(image.get("cleaned_url"), 1000) or None,
            "alt": _text(image.get("alt_text"), 300),
            "shot_type": _text(image.get("shot_type"), 32) or None,
            "is_main": bool(image.get("is_main_image")),
        })
    return images[:12]


def _parse_variants(raw: Any) -> dict[str, Any] | None:
    variants = as_dict(raw)
    if not variants:
        return None
    options = []
    for option in variants.get("options") or []:
        opt = as_dict(option)
        values = []
        for value in opt.get("values") or []:
            val = as_dict(value)
            if not val.get("label"):
                continue
            values.append({
                "label": _text(val.get("label"), 80),
                "exists": bool(val.get("exists", True)),
                "available": val.get("available") if val.get("available") in ("InStock", "OutOfStock") else None,
                "thumbnail_url": _text(val.get("thumbnail_url"), 1000) or None,
                "product_id": _text(val.get("product_id"), 64) or None,
            })
        if opt.get("name") and values:
            options.append({"name": _text(opt.get("name"), 60), "values": values[:40]})
    selected = [
        {"name": _text(as_dict(s).get("name"), 60), "label": _text(as_dict(s).get("label"), 80)}
        for s in variants.get("selected") or [] if as_dict(s).get("name")
    ]
    return {"options": options, "selected": selected} if options else None


def _parse_ratings(raw: Any) -> dict[str, Any] | None:
    ratings = as_dict(raw)
    try:
        value = float(ratings["value"])
        count = int(ratings.get("count") or 0)
    except (KeyError, TypeError, ValueError):
        return None
    if not 0 <= value <= 5:
        return None
    return {"value": round(value, 2), "count": count}


def parse_catalog_product(raw: Any) -> CatalogProduct | None:
    """Normalise one product. Returns None when it has no id or title (it cannot be shown honestly)."""
    product = as_dict(raw)
    pid = _text(product.get("id"), 64)
    title = _text(product.get("title") or product.get("name"), 300)
    if not pid or not title:
        return None
    brands = [as_dict(b) for b in product.get("brands") or []]
    category = as_dict(product.get("category"))
    attributes: dict[str, list[str]] = {}
    for key, values in as_dict(product.get("structured_attributes")).items():
        cleaned = _str_list(values, limit=12, size=120)
        if cleaned:
            attributes[str(key)[:60]] = cleaned
    offers = [o for o in (_parse_offer(raw_offer) for raw_offer in product.get("offers") or []) if o is not None]
    return CatalogProduct(
        id=pid,
        title=title,
        description=_text(product.get("description"), 4000),
        brand=_text(brands[0].get("name"), 120) if brands else "",
        brand_id=_text(brands[0].get("id"), 32) if brands else "",
        images=_parse_images(product.get("images")),
        category_slug=_text(category.get("slug"), 80),
        category_title=_text(category.get("title"), 120),
        category_path=[_text(as_dict(p).get("title"), 80) for p in category.get("path") or [] if as_dict(p).get("title")],
        gender=product.get("gender") if product.get("gender") in ("male", "female") else None,
        age=_text(product.get("age"), 16) or None,
        materials=_str_list(product.get("materials"), limit=10, size=80),
        key_features=_str_list(product.get("key_features"), limit=15, size=300),
        structured_attributes=attributes,
        variants=_parse_variants(product.get("variants")),
        offers=offers,
        ratings=_parse_ratings(product.get("ratings")),
    )


@dataclass(slots=True)
class CatalogPage:
    products: list[CatalogProduct]
    next_page_token: str | None = None
    skipped: int = 0
    duration_ms: int = 0
    request: dict[str, Any] = field(default_factory=dict)


def parse_catalog_page(body: Any) -> tuple[list[CatalogProduct], str | None, int]:
    data = as_dict(body)
    items = data.get("products")
    if not isinstance(items, list):
        return [], None, 0
    products: list[CatalogProduct] = []
    skipped = 0
    seen: set[str] = set()
    for raw in items:
        product = parse_catalog_product(raw)
        if product is None or product.id in seen:
            skipped += 1
            continue
        seen.add(product.id)
        products.append(product)
    token = data.get("next_page_token")
    return products, (str(token) if token else None), skipped


@dataclass(slots=True)
class ConversationTurn:
    conversation_id: str
    turn_id: str
    text: str
    products: list[CatalogProduct]
    searches: list[dict[str, Any]]
    suggestions: list[str]
    usage: dict[str, Any]


def parse_conversation_turn(body: Any) -> ConversationTurn:
    data = as_dict(body)
    message = as_dict(data.get("message"))
    texts: list[str] = []
    products: list[CatalogProduct] = []
    searches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_part in message.get("parts") or []:
        part = as_dict(raw_part)
        if part.get("type") == "text" and part.get("text"):
            texts.append(str(part["text"]))
        elif part.get("type") == "tool":
            output = as_dict(part.get("output"))
            found, _, _ = parse_catalog_page(output)
            searches.append({
                "tool": _text(part.get("tool_name"), 64),
                "input": as_dict(part.get("input")),
                "results": len(found),
            })
            for product in found:
                if product.id not in seen:
                    seen.add(product.id)
                    products.append(product)
    usage = as_dict(data.get("usage"))
    return ConversationTurn(
        conversation_id=_text(data.get("conversation_id"), 80),
        turn_id=_text(data.get("turn_id"), 80),
        text="\n\n".join(t.strip() for t in texts if t.strip()),
        products=products,
        searches=searches,
        suggestions=_str_list(message.get("suggestions") or data.get("suggestions"), limit=6, size=200),
        usage={k: usage[k] for k in ("credits_charged", "searches_run") if k in usage},
    )


# --------------------------------------------------------------------------- #
# Filters
# --------------------------------------------------------------------------- #
def build_filters(
    *,
    min_price: Decimal | float | None = None,
    max_price: Decimal | float | None = None,
    brand_ids: list[str] | None = None,
    category_ids: list[str] | None = None,
    website_ids: list[str] | None = None,
    exclude_website_ids: list[str] | None = None,
    include_out_of_stock: bool = False,
    on_sale: bool = False,
    gender: str | None = None,
    attributes: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """A ``SearchFilters`` object containing only documented keys."""
    filters: dict[str, Any] = {}
    price: dict[str, float] = {}
    if min_price is not None and float(min_price) > 0:
        price["min_price"] = round(float(min_price), 2)
    if max_price is not None and float(max_price) > 0:
        price["max_price"] = round(float(max_price), 2)
    if price:
        filters["price"] = price
    for key, values in (("brand_ids", brand_ids), ("category_ids", category_ids),
                        ("website_ids", website_ids), ("exclude_website_ids", exclude_website_ids)):
        cleaned = [str(v).strip()[:120] for v in values or [] if str(v).strip()][:10]
        if cleaned:
            filters[key] = cleaned
    if include_out_of_stock:
        filters["availability"] = ["InStock", "OutOfStock"]
    if on_sale:
        filters["sale"] = "on_sale"
    if gender in ("male", "female"):
        filters["gender"] = gender
    if attributes:
        cleaned_attrs = {k[:60]: [str(v)[:80] for v in vs][:10] for k, vs in attributes.items()
                         if k and k.lower() != "color" and vs}
        if cleaned_attrs:
            filters["attributes"] = cleaned_attrs
    return filters


def valid_product_id(product_id: str) -> str:
    pid = (product_id or "").strip()
    if not _PRODUCT_ID.match(pid):
        raise SponsorRequestError("That is not a valid Channel3 product id.")
    return pid


def validate_product_url(raw: str) -> str:
    parsed = urlparse((raw or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise SponsorRequestError("Enter a product page URL starting with https://.")
    host = (parsed.hostname or "").lower()
    if not host or "." not in host or host.endswith((".local", ".internal", ".localhost")):
        raise SponsorRequestError("The URL must point to a public retailer website.")
    if parsed.username or parsed.password:
        raise SponsorRequestError("URLs with embedded credentials are not allowed.")
    return parsed.geturl()[:2000]


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #
class Channel3Catalog:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        max_retries: int | None = None,
        timeout: float | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._key = settings.channel3_api_key if api_key is None else api_key
        self._base = (base_url or settings.channel3_base_url).rstrip("/")
        self._transport = transport
        self._max_retries = settings.channel3_max_retries if max_retries is None else max(0, max_retries)
        self._timeout = timeout or settings.channel3_timeout_seconds
        self._sleep = sleep or asyncio.sleep
        self.currency = settings.channel3_currency.upper() if settings.channel3_currency.upper() in SUPPORTED_CURRENCIES else "USD"
        self.country = settings.channel3_country.upper()[:2] or "US"

    @property
    def configured(self) -> bool:
        return bool(self._key)

    @property
    def mode(self) -> str:
        return LIVE if self._key else "NOT_CONFIGURED"

    def __repr__(self) -> str:  # never leak the key
        return f"Channel3Catalog(mode={self.mode})"

    def _locale(self) -> dict[str, str]:
        return {"currency": self.currency, "country": self.country}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        user_id: str | None = None,
        timeout: float | None = None,
        retry: bool = True,
    ) -> tuple[Any, int]:
        if not self._key:
            raise Channel3NotConfiguredError()
        headers = {"x-api-key": self._key, "accept": "application/json"}
        if user_id and _USER_ID.match(user_id):
            headers["x-user-id"] = user_id
        attempts = (self._max_retries if retry else 0) + 1
        started = time.perf_counter()
        last_error: SponsorError | None = None
        async with httpx.AsyncClient(
            base_url=self._base, headers=headers, transport=self._transport,
            timeout=httpx.Timeout(timeout or self._timeout, connect=8.0),
        ) as client:
            for attempt in range(attempts):
                try:
                    response = await client.request(method, path, json=json_body, params=params)
                except httpx.TimeoutException:
                    last_error = SponsorError("Channel3 did not respond in time.", status_code=504)
                    delay = _backoff(attempt)
                except httpx.HTTPError as exc:
                    last_error = SponsorError(f"Channel3 is unreachable ({type(exc).__name__}).", status_code=502)
                    delay = _backoff(attempt)
                else:
                    if response.is_success:
                        try:
                            body = response.json()
                        except ValueError as exc:
                            raise SponsorError("Channel3 returned a response that is not JSON.") from exc
                        duration = int((time.perf_counter() - started) * 1000)
                        log.info("channel3_call", path=_redact_path(path), status=response.status_code,
                                 attempts=attempt + 1, duration_ms=duration)
                        return body, duration
                    last_error = _error_for(response)
                    if response.status_code not in _RETRYABLE:
                        raise last_error
                    delay = _retry_after(response) or _backoff(attempt)
                if attempt + 1 < attempts:
                    log.warning("channel3_retry", path=_redact_path(path), attempt=attempt + 1,
                                detail=str(last_error)[:160], delay_s=round(delay, 2))
                    await self._sleep(delay)
        assert last_error is not None
        raise last_error

    # ------------------------------------------------------------------ products
    async def search(
        self,
        query: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 12,
        page_token: str | None = None,
        mode: str = "default",
        user_id: str | None = None,
    ) -> CatalogPage:
        query = (query or "").strip()[:500]
        if not query and not page_token:
            raise SponsorRequestError("Describe the product you are looking for.")
        body: dict[str, Any] = {"limit": max(1, min(int(limit), 30)),
                                "config": {**self._locale(), "mode": mode if mode in ("default", "agentic", "keyword") else "default"}}
        if query:
            body["query"] = query
        if page_token:
            body["page_token"] = page_token[:500]
        if filters:
            body["filters"] = filters
        data, duration = await self._request("POST", SEARCH_PATH, json_body=body, user_id=user_id,
                                             timeout=max(self._timeout, 60.0) if mode == "agentic" else None)
        products, token, skipped = parse_catalog_page(data)
        return CatalogPage(products=products, next_page_token=token, skipped=skipped, duration_ms=duration,
                           request={k: v for k, v in body.items() if k != "page_token"})

    async def similar(
        self, product_id: str, *, filters: dict[str, Any] | None = None, limit: int = 12, user_id: str | None = None,
    ) -> CatalogPage:
        body: dict[str, Any] = {"product_id": valid_product_id(product_id), "limit": max(1, min(int(limit), 30)),
                                "config": self._locale()}
        if filters:
            body["filters"] = filters
        data, duration = await self._request("POST", SIMILAR_PATH, json_body=body, user_id=user_id)
        products, token, skipped = parse_catalog_page(data)
        return CatalogPage(products=[p for p in products if p.id != body["product_id"]], next_page_token=token,
                           skipped=skipped, duration_ms=duration, request=body)

    async def product(
        self, product_id: str, *, user_id: str | None = None, selected_options: dict[str, str] | None = None,
    ) -> CatalogProduct:
        params: dict[str, Any] = dict(self._locale())
        for name, label in (selected_options or {}).items():
            if name and label:
                params[f"option_{str(name)[:40]}"] = str(label)[:80]
        data, _ = await self._request("GET", PRODUCT_PATH.format(product_id=valid_product_id(product_id)),
                                      params=params, user_id=user_id)
        product = parse_catalog_product(data)
        if product is None:
            raise SponsorError("Channel3 returned a product without an id or title.")
        return product

    async def lookup(self, url: str, *, user_id: str | None = None) -> CatalogProduct:
        data, _ = await self._request("POST", LOOKUP_PATH, json_body={"url": validate_product_url(url)},
                                      user_id=user_id, timeout=max(self._timeout, 45.0), retry=False)
        product = parse_catalog_product(as_dict(data).get("product") or data)
        if product is None:
            raise SponsorError("Channel3 could not extract a product from that page.", status_code=422)
        return product

    # ------------------------------------------------------------------ taxonomy
    async def categories(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        query = (query or "").strip()[:120]
        if len(query) < 2:
            return []
        data, _ = await self._request("GET", CATEGORIES_PATH, params={"query": query, "limit": max(1, min(limit, 20))})
        out = []
        for raw in as_dict(data).get("categories") or []:
            cat = as_dict(raw)
            if cat.get("slug"):
                out.append({"slug": _text(cat["slug"], 80), "title": _text(cat.get("title"), 120),
                            "path": [_text(as_dict(p).get("title"), 80) for p in cat.get("path") or []]})
        return out

    async def brands(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        query = (query or "").strip()[:120]
        if len(query) < 2:
            return []
        data, _ = await self._request("GET", BRANDS_PATH, params={"query": query, "limit": max(1, min(limit, 20))})
        return [{"id": _text(as_dict(b).get("id"), 32), "name": _text(as_dict(b).get("name"), 120)}
                for b in as_dict(data).get("brands") or [] if as_dict(b).get("id")]

    # ------------------------------------------------------------------ conversations
    async def conversation_turn(
        self, text: str, *, conversation_id: str | None = None, filters: dict[str, Any] | None = None,
        user_id: str | None = None,
    ) -> ConversationTurn:
        text = (text or "").strip()[:2000]
        if not text:
            raise SponsorRequestError("Type a message for the shopping assistant.")
        body: dict[str, Any] = {"message": {"role": "user", "parts": [{"type": "text", "text": text}]}, "stream": False}
        if conversation_id:
            body["conversation_id"] = conversation_id[:80]
        if filters:
            body["filters"] = filters
        # A turn is not idempotent (it would append twice), so it is never retried.
        data, _ = await self._request("POST", CONVERSATIONS_PATH, json_body=body, user_id=user_id,
                                      timeout=max(self._timeout, 90.0), retry=False)
        return parse_conversation_turn(data)


def _backoff(attempt: int) -> float:
    return min(4.0, 0.5 * (2 ** attempt)) + random.uniform(0, 0.25)  # noqa: S311 - jitter, not crypto


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if not value:
        return None
    try:
        return max(0.0, min(float(value), 5.0))
    except ValueError:
        return None


def _redact_path(path: str) -> str:
    return path.split("?", 1)[0][:80]


def _error_for(response: httpx.Response) -> SponsorError:
    detail = ""
    try:
        body = response.json()
        if isinstance(body, dict):
            raw = body.get("detail") or body.get("message") or body.get("error") or ""
            detail = (raw if isinstance(raw, str) else str(raw))[:200]
    except ValueError:
        detail = response.text[:120]
    status = response.status_code
    if status in (401, 403):
        message = "Channel3 rejected the API key - check CHANNEL3_API_KEY."
    elif status == 404:
        message = "Channel3 does not have that product in its catalog (yet)."
    elif status == 422:
        message = "Channel3 could not use that request" + (f": {detail}" if detail else ".")
    elif status == 429:
        message = "Channel3 rate limit reached - try again in a moment."
    else:
        message = f"Channel3 returned HTTP {status}" + (f": {detail}" if detail else "")
    return SponsorError(message, status_code=status)


__all__ = [
    "SUPPORTED_CURRENCIES",
    "CatalogOffer",
    "CatalogPage",
    "CatalogProduct",
    "Channel3Catalog",
    "Channel3NotConfiguredError",
    "ConversationTurn",
    "build_filters",
    "parse_catalog_page",
    "parse_catalog_product",
    "parse_conversation_turn",
    "valid_product_id",
    "validate_product_url",
]
