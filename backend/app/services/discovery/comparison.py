"""Product comparison engine.

Builds a side-by-side matrix from fresh Channel3 product details and answers four
questions, each with the evidence behind the answer:

* **Better value** - the lowest in-stock price, adjusted by rating only when every
  compared product has a Channel3 rating (otherwise ratings are left out entirely).
* **More suitable specifications** - which product documents more of what matters:
  requested features first, then how many structured attributes and key features the
  retailer actually lists.
* **Fit for the merchant's customers** - which price sits inside the band the
  merchant's own customers already pay (median and 75th percentile of the catalog,
  average order value - all from the merchant's transactions).
* **Best alternative** - the runner-up, and how it differs from the winner.

A specification a retailer did not list is shown as ``None`` ("Not listed") - never
guessed. The optional LLM narrative is handed only these computed facts.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.core.logging import get_logger
from app.integrations.groq import llm_service
from app.integrations.sponsors.channel3_catalog import CatalogProduct

log = get_logger(__name__)

NOT_LISTED = None


class ComparisonNarrative(BaseModel):
    summary: str = Field(default="", max_length=1200)


def _price(product: CatalogProduct) -> Decimal | None:
    return product.best_offer.price if product.best_offer else None


def _fmt(product: CatalogProduct) -> str:
    price = _price(product)
    return f"{product.currency} {price:,.2f}" if price is not None else "no price listed"


def _variants_summary(product: CatalogProduct) -> str | None:
    if not product.variants:
        return None
    parts = [f"{o['name']}: {len(o['values'])}" for o in product.variants.get("options", [])]
    return ", ".join(parts) or None


def build_matrix(products: list[CatalogProduct]) -> dict[str, Any]:
    """Rows of comparable fields. Attribute rows are the union of what any retailer listed."""
    attribute_keys: list[str] = []
    for product in products:
        for key in product.structured_attributes:
            if key not in attribute_keys:
                attribute_keys.append(key)
    # Attributes every product lists first: those are the comparable ones.
    attribute_keys.sort(key=lambda k: -sum(1 for p in products if k in p.structured_attributes))

    def row(key: str, label: str, values: list[Any], *, kind: str = "text") -> dict[str, Any]:
        return {"key": key, "label": label, "kind": kind, "values": values}

    rows = [
        row("price", "Best price", [str(_price(p)) if _price(p) is not None else NOT_LISTED for p in products], kind="money"),
        row("compare_at", "List price", [str(p.best_offer.compare_at_price) if p.best_offer and p.best_offer.compare_at_price else NOT_LISTED
                                         for p in products], kind="money"),
        row("price_range", "Price range across retailers",
            [f"{p.min_price} - {p.max_price}" if p.min_price is not None and p.max_price is not None and p.min_price != p.max_price
             else (str(p.min_price) if p.min_price is not None else NOT_LISTED) for p in products]),
        row("currency", "Currency", [p.currency for p in products]),
        row("brand", "Brand", [p.brand or NOT_LISTED for p in products]),
        row("category", "Category", [p.category_title or NOT_LISTED for p in products]),
        row("retailer", "Best-price retailer", [p.best_offer.domain if p.best_offer else NOT_LISTED for p in products]),
        row("retailers", "Retailers", [len(p.retailers) for p in products], kind="number"),
        row("availability", "Availability", ["In stock" if p.in_stock else ("Out of stock" if p.in_stock is False else NOT_LISTED)
                                             for p in products]),
        row("variants", "Variants", [_variants_summary(p) for p in products]),
        row("rating", "Rating (Channel3)", [f"{p.ratings['value']:.1f}/5 ({p.ratings['count']:,})" if p.ratings else NOT_LISTED
                                            for p in products]),
        row("materials", "Materials", [", ".join(p.materials) if p.materials else NOT_LISTED for p in products]),
        row("key_features", "Key features", [p.key_features[:6] or NOT_LISTED for p in products], kind="list"),
    ]
    for key in attribute_keys[:24]:
        rows.append(row(f"attr:{key}", key.replace("-", " ").capitalize(),
                        [", ".join(p.structured_attributes[key]) if key in p.structured_attributes else NOT_LISTED
                         for p in products]))
    return {"rows": rows, "attribute_keys": attribute_keys[:24]}


def _value_verdict(products: list[CatalogProduct]) -> dict[str, Any] | None:
    priced = [p for p in products if _price(p) is not None and p.in_stock is not False]
    if not priced:
        return None
    currencies = {p.currency for p in priced}
    if len(currencies) > 1:
        return {"product_id": None, "title": None,
                "reason": f"Prices are in different currencies ({', '.join(sorted(currencies))}); value is not comparable.",
                "evidence": []}
    rated_all = all(p.ratings and p.ratings.get("count", 0) >= 10 for p in priced)
    if rated_all and len(priced) > 1:
        # Rating points per unit of price - only when every product has a meaningful rating.
        winner = max(priced, key=lambda p: Decimal(str(p.ratings["value"])) / _price(p))  # type: ignore[index,operator]
        basis = "rating per unit of price (every product has a Channel3 rating)"
    else:
        winner = min(priced, key=lambda p: _price(p))  # type: ignore[arg-type,return-value]
        basis = "lowest in-stock price" + ("" if rated_all else " (ratings are not available for every product, so they are not used)")
    others = [p for p in priced if p.id != winner.id]
    evidence = [{"label": p.title[:80], "value": _fmt(p), "source": "Channel3"} for p in [winner, *others]]
    savings = ""
    if others:
        cheapest_other = min(others, key=lambda p: _price(p))  # type: ignore[arg-type,return-value]
        diff = _price(cheapest_other) - _price(winner)  # type: ignore[operator]
        if diff > 0:
            savings = f" - {winner.currency} {diff:,.2f} less than the next option"
    return {"product_id": winner.id, "title": winner.title, "basis": basis,
            "reason": f"{winner.title} offers the better value by {basis}: {_fmt(winner)}{savings}.",
            "evidence": evidence}


def _spec_verdict(products: list[CatalogProduct], wanted: list[str]) -> dict[str, Any] | None:
    if not products:
        return None

    def coverage(p: CatalogProduct) -> tuple[int, int]:
        hay = " ".join([p.title, " ".join(p.key_features),
                        " ".join(f"{k} {' '.join(v)}" for k, v in p.structured_attributes.items())]).lower()
        matched = sum(1 for w in wanted if w and all(t in hay for t in w.lower().split()))
        return matched, len(p.structured_attributes) + len(p.key_features)

    scored = sorted(products, key=coverage, reverse=True)
    winner = scored[0]
    matched, documented = coverage(winner)
    evidence = []
    for p in scored:
        m, d = coverage(p)
        evidence.append({"label": p.title[:80],
                         "value": (f"{m}/{len(wanted)} requested features, " if wanted else "") + f"{d} specifications listed",
                         "source": "Channel3"})
    if wanted:
        reason = (f"{winner.title} documents {matched} of {len(wanted)} requested features "
                  f"({', '.join(wanted)}) and {documented} specifications in total.")
    else:
        reason = (f"{winner.title} has the most complete specification: {documented} attributes and key features "
                  "listed by the retailer. Fewer listed specs means less is known, not that the product lacks them.")
    return {"product_id": winner.id, "title": winner.title, "reason": reason, "evidence": evidence}


def _fit_verdict(products: list[CatalogProduct], context: dict[str, Any]) -> dict[str, Any] | None:
    median = context.get("catalog_median_price")
    p75 = context.get("catalog_p75_price")
    aov = context.get("average_order_value")
    priced = [p for p in products if _price(p) is not None]
    if not priced or median is None:
        return {"product_id": None, "title": None,
                "reason": "Not enough sales data to know what your customers usually pay.", "evidence": []}
    target = Decimal(str(aov or p75 or median))
    upper = Decimal(str(max(p75 or median, aov or 0))) * Decimal("1.5")
    winner = min(priced, key=lambda p: abs(_price(p) - target))  # type: ignore[operator]
    inside = [p for p in priced if _price(p) <= upper]  # type: ignore[operator]
    evidence = [
        {"label": "Your catalog median price", "value": f"{median:,.2f}", "source": "Your sales data"},
        {"label": "Your average order value", "value": f"{aov:,.2f}" if aov else "-", "source": "Your sales data"},
        *[{"label": p.title[:80], "value": _fmt(p), "source": "Channel3"} for p in priced],
    ]
    if not inside:
        reason = (f"All options are priced well above what your customers usually spend (average order "
                  f"{aov:,.2f}); {winner.title} is the closest at {_fmt(winner)}." if aov else
                  f"{winner.title} is closest to your catalog's price points.")
    else:
        reason = (f"{winner.title} at {_fmt(winner)} sits closest to what your customers already spend "
                  f"(average order {aov:,.2f}, catalog median {median:,.2f})." if aov else
                  f"{winner.title} sits closest to your catalog's price points.")
    return {"product_id": winner.id, "title": winner.title, "reason": reason, "evidence": evidence,
            "within_customer_band": [p.id for p in inside]}


def _alternative_verdict(products: list[CatalogProduct], primary_id: str | None) -> dict[str, Any] | None:
    if len(products) < 2 or primary_id is None:
        return None
    primary = next(p for p in products if p.id == primary_id)
    others = [p for p in products if p.id != primary_id]

    def closeness(p: CatalogProduct) -> tuple[int, int, float]:
        same_category = int(bool(p.category_slug) and p.category_slug == primary.category_slug)
        shared = len(set(p.structured_attributes) & set(primary.structured_attributes))
        gap = float(abs((_price(p) or 0) - (_price(primary) or 0)))
        return same_category, shared, -gap

    alt = max(others, key=closeness)
    diff = (_price(alt) - _price(primary)) if _price(alt) is not None and _price(primary) is not None else None  # type: ignore[operator]
    pct = (diff / _price(primary) * 100) if diff is not None and _price(primary) else None  # type: ignore[operator]
    parts = []
    if alt.category_slug and alt.category_slug == primary.category_slug:
        parts.append(f"same category ({alt.category_title})")
    if alt.brand and alt.brand != primary.brand:
        parts.append(f"a different brand ({alt.brand})")
    shared = sorted(set(alt.structured_attributes) & set(primary.structured_attributes))
    if shared:
        parts.append(f"{len(shared)} shared specifications")
    price_note = ""
    if diff is not None:
        direction = "cheaper" if diff < 0 else "more expensive"
        price_note = f", {alt.currency} {abs(diff):,.2f} ({abs(pct):.0f}%) {direction}" if diff else ", the same price"
    return {"product_id": alt.id, "title": alt.title,
            "reason": f"If {primary.title} is unavailable, {alt.title} is the closest alternative: "
                      f"{', '.join(parts) or 'the next best overall'}{price_note}.",
            "price_difference": str(diff) if diff is not None else None,
            "price_difference_pct": f"{pct:.1f}" if pct is not None else None,
            "evidence": [{"label": "Shared specifications", "value": ", ".join(shared[:8]) or "none listed",
                          "source": "Channel3"}]}


def compare(products: list[CatalogProduct], *, merchant_context: dict[str, Any], wanted: list[str] | None = None) -> dict[str, Any]:
    wanted = [w for w in (wanted or []) if w.strip()]
    value = _value_verdict(products)
    specs = _spec_verdict(products, wanted)
    fit = _fit_verdict(products, merchant_context)
    # Overall: one point per verdict won; ties go to the better value.
    tally: dict[str, int] = {p.id: 0 for p in products}
    for verdict in (value, specs, fit):
        if verdict and verdict.get("product_id") in tally:
            tally[verdict["product_id"]] += 1
    overall_id = max(tally, key=lambda pid: (tally[pid], pid == (value or {}).get("product_id"))) if tally else None
    alternative = _alternative_verdict(products, overall_id)
    missing = {p.id: [k for k in build_matrix(products)["attribute_keys"] if k not in p.structured_attributes]
               for p in products}
    return {
        "products": [p.as_dict() for p in products],
        "matrix": build_matrix(products),
        "verdicts": {"best_value": value, "best_specifications": specs, "best_customer_fit": fit,
                     "best_alternative": alternative},
        "overall": {"product_id": overall_id, "wins": tally},
        "not_listed": missing,
        "merchant_context": merchant_context,
        "notes": [
            "Prices are retail listings from other sellers, refreshed from Channel3 just now - not wholesale cost.",
            "\"Not listed\" means the retailer did not publish that specification; it is never filled in.",
        ],
    }


def deterministic_narrative(result: dict[str, Any]) -> str:
    lines = []
    for key in ("best_value", "best_specifications", "best_customer_fit", "best_alternative"):
        verdict = result["verdicts"].get(key)
        if verdict and verdict.get("reason"):
            lines.append(verdict["reason"])
    return " ".join(lines)


async def narrate(result: dict[str, Any], *, trace: Any = None) -> tuple[str, bool]:
    fallback = deterministic_narrative(result)
    if not llm_service.enabled:
        return fallback, False
    facts = {k: {"title": v.get("title"), "reason": v.get("reason")} for k, v in result["verdicts"].items() if v}
    narrative, llm = await llm_service.structured(
        system=("You write a short, plain-language product comparison for a small-business owner. Use ONLY the "
                "verdicts provided; do not add specifications, ratings or prices that are not in them. 3-5 sentences."),
        user=f"Verdicts: {facts}",
        schema=ComparisonNarrative,
        fallback=ComparisonNarrative(summary=fallback),
        trace=trace,
        trace_name="discovery_comparison",
        max_tokens=500,
    )
    return (narrative.summary or fallback), not llm.used_fallback


__all__ = ["build_matrix", "compare", "deterministic_narrative", "narrate"]
