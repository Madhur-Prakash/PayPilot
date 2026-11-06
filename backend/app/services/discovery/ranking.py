"""AI-assisted product ranking.

Every product gets a 0-100 score built from transparent components, each computed
from data Channel3 returned:

==================  =====================================================  ======
component           what it measures                                       weight
==================  =====================================================  ======
relevance           Channel3's own ranking position for the query          0.30
budget_fit          price against the merchant's min/max budget            0.20
availability        in stock at the best offer                             0.15
attribute_match     requested features found in title/features/attributes  0.15
use_case_fit        LLM judgement of fit for the stated use (optional)     0.15
brand_preference    matches a requested brand                              0.10
rating              Channel3 rating, only when >= 10 reviews exist         0.10
market_breadth      number of retailers listing it                         0.05
==================  =====================================================  ======

A component that does not apply (no budget given, no rating returned, no LLM) is left
out and the remaining weights are renormalised - a missing rating is never scored as
zero and never invented. ``reasons`` explains each score in plain language.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.integrations.groq import llm_service
from app.integrations.sponsors.channel3_catalog import CatalogProduct
from app.services.discovery.intent import SearchIntent

log = get_logger(__name__)

WEIGHTS: dict[str, float] = {
    "relevance": 0.30,
    "budget_fit": 0.20,
    "availability": 0.15,
    "attribute_match": 0.15,
    "use_case_fit": 0.15,
    "brand_preference": 0.10,
    "rating": 0.10,
    "market_breadth": 0.05,
}
MIN_REVIEWS_FOR_RATING = 10
_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return {t for t in _WORD.findall(text.lower()) if len(t) > 1}


def _haystack(product: CatalogProduct) -> str:
    attrs = " ".join(f"{k} {' '.join(v)}" for k, v in product.structured_attributes.items())
    return " ".join([product.title, product.description[:600], " ".join(product.key_features), attrs,
                     " ".join(product.materials)]).lower()


def _money(value: Decimal | None) -> str:
    return f"{value:,.2f}" if value is not None else "-"


class UseCaseVerdict(BaseModel):
    product_id: str
    fit: float = Field(ge=0, le=1)
    reason: str = Field(default="", max_length=240)


class UseCaseVerdicts(BaseModel):
    verdicts: list[UseCaseVerdict] = Field(default_factory=list)


def score_product(
    product: CatalogProduct,
    *,
    position: int,
    total: int,
    intent: SearchIntent,
    min_price: float | None,
    max_price: float | None,
    use_case_fit: UseCaseVerdict | None = None,
) -> dict[str, Any]:
    components: dict[str, float] = {}
    reasons: list[str] = []
    best = product.best_offer

    components["relevance"] = 1.0 - (position / max(total, 1)) * 0.6
    if position == 0:
        reasons.append("Channel3's top match for this request")

    price = float(best.price) if best else None
    if price is not None and (max_price or min_price):
        if max_price and price > max_price:
            over = (price - max_price) / max_price
            components["budget_fit"] = max(0.0, 1.0 - over * 2.5)
            reasons.append(f"{over * 100:.0f}% over budget ({best.currency} {_money(best.price)})")
        elif min_price and price < min_price:
            components["budget_fit"] = 0.5
            reasons.append(f"Below the minimum price you set ({best.currency} {_money(best.price)})")
        else:
            headroom = (1 - price / max_price) if max_price else 0.5
            components["budget_fit"] = 0.75 + 0.25 * max(0.0, min(headroom, 1.0))
            reasons.append(f"Within budget at {best.currency} {_money(best.price)}"
                           + (f" ({headroom * 100:.0f}% headroom)" if max_price and headroom >= 0.15 else ""))

    stock = product.in_stock
    components["availability"] = 1.0 if stock else (0.55 if stock is None else 0.0)
    if stock:
        reasons.append(f"In stock at {best.domain}" if best and best.domain else "In stock")
    elif stock is False:
        reasons.append("Currently out of stock everywhere Channel3 checked")

    wanted = [a for a in intent.attributes if a.strip()]
    if wanted:
        hay = _haystack(product)
        matched = [a for a in wanted if _tokens(a) and _tokens(a) <= _tokens(hay)]
        components["attribute_match"] = len(matched) / len(wanted)
        if matched:
            reasons.append("Matches: " + ", ".join(matched))
        missing = [a for a in wanted if a not in matched]
        if missing:
            reasons.append("Not listed: " + ", ".join(missing))

    if intent.brands:
        brand = product.brand.lower()
        hit = any(b.lower() == brand or b.lower() in product.title.lower() for b in intent.brands)
        components["brand_preference"] = 1.0 if hit else 0.25
        if hit:
            reasons.append(f"Preferred brand ({product.brand})")
    if intent.exclude_brands and any(b.lower() == product.brand.lower() for b in intent.exclude_brands):
        components["brand_preference"] = 0.0
        reasons.append(f"{product.brand} is a brand you asked to avoid")

    if product.ratings and product.ratings.get("count", 0) >= MIN_REVIEWS_FOR_RATING:
        components["rating"] = max(0.0, min(product.ratings["value"] / 5.0, 1.0))
        reasons.append(f"Rated {product.ratings['value']:.1f}/5 from {product.ratings['count']:,} reviews")

    retailers = len(product.retailers)
    components["market_breadth"] = min(1.0, retailers / 4)
    if retailers >= 2:
        reasons.append(f"Listed by {retailers} retailers")

    if best and best.discount_pct:
        reasons.append(f"{best.discount_pct}% off the list price")
        if intent.on_sale:
            components["budget_fit"] = min(1.0, components.get("budget_fit", 0.75) + 0.1)

    if use_case_fit is not None:
        components["use_case_fit"] = use_case_fit.fit
        if use_case_fit.reason:
            reasons.append(f"AI fit for {intent.use_case}: {use_case_fit.reason}")

    weight_total = sum(WEIGHTS[k] for k in components)
    score = sum(WEIGHTS[k] * v for k, v in components.items()) / weight_total if weight_total else 0.0
    return {
        "score": round(score * 100, 1),
        "components": {k: round(v, 3) for k, v in components.items()},
        "weights_used": {k: WEIGHTS[k] for k in components},
        "reasons": reasons[:8],
    }


def _label(rank: int, product: CatalogProduct, cheapest_id: str | None) -> str | None:
    if rank == 0:
        return "Top match"
    if product.id == cheapest_id:
        return "Best price"
    if product.ratings and product.ratings.get("count", 0) >= 100 and product.ratings.get("value", 0) >= 4.3:
        return "Highly rated"
    return None


async def use_case_verdicts(
    products: list[CatalogProduct], intent: SearchIntent, *, trace: Any = None,
) -> tuple[dict[str, UseCaseVerdict], bool]:
    """Ask the LLM how well each product fits the stated use, from Channel3's facts only."""
    if not llm_service.enabled or not intent.use_case or not products:
        return {}, False
    facts = [
        {
            "product_id": p.id,
            "title": p.title,
            "brand": p.brand,
            "category": p.category_title,
            "price": str(p.best_offer.price) if p.best_offer else None,
            "key_features": p.key_features[:6],
            "attributes": {k: v[:3] for k, v in list(p.structured_attributes.items())[:10]},
        }
        for p in products[:12]
    ]
    verdicts, result = await llm_service.structured(
        system=(
            "You judge how well retail products fit a stated use case, using ONLY the facts given. "
            "If a needed specification is not in the facts, say it is not listed and lower the fit - "
            "never assume it. fit is 0..1. Keep each reason under 25 words."
        ),
        user=f"Use case: {intent.use_case}\nRequest: {intent.raw}\nProducts: {facts}",
        schema=UseCaseVerdicts,
        fallback=UseCaseVerdicts(),
        trace=trace,
        trace_name="discovery_use_case_fit",
        max_tokens=1200,
    )
    if result.used_fallback:
        return {}, False
    known = {p.id for p in products}
    return {v.product_id: v for v in verdicts.verdicts if v.product_id in known}, True


def rank_products(
    products: list[CatalogProduct],
    intent: SearchIntent,
    *,
    min_price: float | None,
    max_price: float | None,
    verdicts: dict[str, UseCaseVerdict] | None = None,
) -> list[dict[str, Any]]:
    """Score, sort and serialise. Channel3's order breaks ties."""
    verdicts = verdicts or {}
    in_stock_prices = [(p.best_offer.price, p.id) for p in products if p.best_offer and p.in_stock is not False]
    cheapest_id = min(in_stock_prices)[1] if in_stock_prices else None
    scored = []
    for index, product in enumerate(products):
        ranking = score_product(product, position=index, total=len(products), intent=intent,
                                min_price=min_price, max_price=max_price, use_case_fit=verdicts.get(product.id))
        scored.append((ranking["score"], -index, product, ranking))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    out = []
    for rank, (_, _, product, ranking) in enumerate(scored):
        out.append({**product.as_dict(), "ranking": {**ranking, "rank": rank + 1,
                                                     "label": _label(rank, product, cheapest_id)}})
    return out


__all__ = ["WEIGHTS", "UseCaseVerdict", "rank_products", "score_product", "use_case_verdicts"]
