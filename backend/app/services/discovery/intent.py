"""Natural-language request -> structured product search intent.

"Find wireless earbuds under ₹5,000 from Sony or JBL for a college student" becomes::

    query="wireless earbuds for a college student", max_price=5000, budget_currency="INR",
    brands=["Sony", "JBL"], use_case="a college student"

Two layers:

1. **A deterministic parser** that always runs. Prices, currencies, ranges, brands,
   retailers, sale and stock preferences are extracted with rules - no model ever does
   arithmetic or invents a number.
2. **An optional LLM refinement** (Groq) that may improve the *words*: the core product
   phrase, a category hint, desired attributes and the use case. It cannot change a
   price: a budget the model mentions is accepted only if the parser found it too.

Budgets in a currency Channel3 does not price in (e.g. INR) are translated into the
catalog currency with the configurable reference rate in ``DISCOVERY_FX_PER_USD`` and
the response says so - it is never presented as a live exchange rate.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.groq import llm_service
from app.integrations.sponsors.channel3_catalog import SUPPORTED_CURRENCIES

log = get_logger(__name__)


class SearchIntent(BaseModel):
    """What the merchant asked for, in structured form."""

    raw: str = ""
    query: str = Field(default="", description="The product phrase to search for, without price words.")
    category: str | None = Field(default=None, description="A short category hint, e.g. 'office chairs'.")
    min_price: float | None = None
    max_price: float | None = None
    budget_currency: str = "USD"
    brands: list[str] = Field(default_factory=list)
    exclude_brands: list[str] = Field(default_factory=list)
    attributes: list[str] = Field(default_factory=list, description="Desired features, e.g. 'noise cancelling'.")
    use_case: str | None = Field(default=None, description="Who or what it is for, e.g. 'a college student'.")
    retailers: list[str] = Field(default_factory=list)
    on_sale: bool = False
    include_out_of_stock: bool = False
    compare_brands: bool = False
    alternatives_to: str | None = None


class _LLMIntent(BaseModel):
    query: str = ""
    category: str | None = None
    attributes: list[str] = Field(default_factory=list)
    use_case: str | None = None
    brands: list[str] = Field(default_factory=list)
    max_price: float | None = None
    min_price: float | None = None


_CURRENCY_TOKENS: tuple[tuple[str, str], ...] = (
    (r"₹|\brs\.?(?=\s*\d)|\binr\b|\brupees?\b|\blakh|\blac\b|\bcrore", "INR"),
    (r"€|\beur\b|\beuros?\b", "EUR"),
    (r"£|\bgbp\b|\bpounds?\b", "GBP"),
    (r"\bc\$|\bcad\b", "CAD"),
    (r"\ba\$|\baud\b", "AUD"),
    (r"¥|\bjpy\b|\byen\b", "JPY"),
    (r"\$|\busd\b|\bdollars?\b|\bbucks\b", "USD"),
)
_SUFFIX = r"(?:\s*(?:dollars?|usd|bucks|rupees?|inr|euros?|eur|pounds?|gbp|cad|aud))?"
_NUM = rf"(?:₹|rs\.?|\$|€|£|c\$|a\$|usd|inr|eur|gbp)?\s*(\d[\d,]*(?:\.\d+)?)\s*(k|lakh|lac|crore|m)?\b{_SUFFIX}"
_BARE = re.compile(
    r"(?:(?:₹|rs\.?|\$|€|£)\s*(\d[\d,]*(?:\.\d+)?)\s*(k|lakh|lac|crore)?\b{suffix})|"
    r"(?:(\d[\d,]*(?:\.\d+)?)\s*(k|lakh|lac|crore)?\s*(?:dollars?|usd|bucks|rupees?|inr|euros?|pounds?)\b)".format(suffix=_SUFFIX),
    re.I,
)
_RANGE = re.compile(rf"(?:between|from)\s+{_NUM}\s*(?:and|to|-|–)\s*{_NUM}", re.I)
_DASH_RANGE = re.compile(rf"{_NUM}\s*(?:-|–|to)\s*{_NUM}", re.I)
_MAX = re.compile(rf"(?:under|below|less than|cheaper than|up to|upto|max(?:imum)?|within|no more than|at most|<=?)\s*(?:a\s+budget\s+of\s+)?{_NUM}", re.I)
_MIN = re.compile(rf"(?:over|above|more than|at least|min(?:imum)?|starting at|>=?)\s*{_NUM}", re.I)
_AROUND = re.compile(rf"(?:around|about|approximately|approx\.?|~|budget(?: of| is)?)\s*{_NUM}", re.I)
_BRAND = re.compile(r"\b(?:from|by|brand(?:ed)?|made by)\s+([A-Z][\w&'.+-]*(?:\s+[A-Z][\w&'.+-]*)?(?:\s*(?:,|or|and|/)\s*[A-Z][\w&'.+-]*(?:\s+[A-Z][\w&'.+-]*)?)*)")
_VERSUS = re.compile(r"\b([A-Z][\w&'.+-]+)\s+(?:vs\.?|versus|or)\s+([A-Z][\w&'.+-]+)\b")
_NOT_BRAND = re.compile(r"\b(?:not|no|except|excluding|avoid)\s+([A-Z][\w&'.+-]+)")
_DOMAIN = re.compile(r"\b([a-z0-9-]+\.(?:com|co\.uk|in|de|ca|com\.au|fr|it|es|net|org|store|shop))\b", re.I)
_ALTERNATIVE = re.compile(r"\b(?:alternatives?|similar|substitutes?|something like|cheaper version)\s+(?:to|for|of)?\s*(.+)$", re.I)
_FOR = re.compile(r"\b(?:suitable for|ideal for|perfect for|good for|meant for|for)\s+((?:a|an|the|my|our)?\s*[\w\s'-]{3,60}?)(?=$|,|\.|\s+(?:under|below|with|that|which|from|by|and under|between|around)\b)", re.I)
_WITH = re.compile(r"\bwith\s+([\w\s,'-]{3,80}?)(?=$|\.|\s+(?:under|below|for|from|by|between|around)\b)", re.I)
_FILLER = re.compile(
    r"\b(?:please|kindly|can you|could you|i want|i need|we need|we want|i'm looking for|im looking for|"
    r"looking for|show me|find me|find|search for|search|get me|recommend|suggest|discover|products? in|"
    r"some|good|best|top|the|a few|a|an|any|me|us|products?|items?|options?|suitable|ideal)\b",
    re.I,
)
_STOP_BRANDS = {"I", "A", "The", "For", "Find", "Show", "Me", "My", "Our", "Under", "And", "Or", "With", "Best", "Top"}


def _amount(digits: str, unit: str | None) -> float | None:
    try:
        value = Decimal(digits.replace(",", ""))
    except Exception:
        return None
    multiplier = {"k": 1_000, "lakh": 100_000, "lac": 100_000, "crore": 10_000_000, "m": 1_000_000}.get((unit or "").lower(), 1)
    value *= multiplier
    return float(value) if value > 0 else None


def detect_currency(text: str) -> str | None:
    lowered = text.lower()
    for pattern, code in _CURRENCY_TOKENS:
        if re.search(pattern, lowered):
            return code
    return None


def _split_names(chunk: str) -> list[str]:
    names = [n.strip(" .,'") for n in re.split(r"\s*(?:,|/|\bor\b|\band\b)\s*", chunk) if n.strip(" .,'")]
    return [n for n in names if n and n not in _STOP_BRANDS and len(n) <= 40][:5]


def parse_intent(text: str) -> SearchIntent:
    """Deterministic extraction. Always succeeds; unknown parts are simply left empty."""
    raw = (text or "").strip()[:500]
    work = raw
    intent = SearchIntent(raw=raw)
    intent.budget_currency = detect_currency(raw) or settings.channel3_currency.upper()

    # ---- price -------------------------------------------------------------
    if m := _RANGE.search(work):
        intent.min_price, intent.max_price = _amount(m.group(1), m.group(2)), _amount(m.group(3), m.group(4))
        work = work.replace(m.group(0), " ")
    elif m := _MAX.search(work):
        intent.max_price = _amount(m.group(1), m.group(2))
        work = work.replace(m.group(0), " ")
        if m2 := _MIN.search(work):
            intent.min_price = _amount(m2.group(1), m2.group(2))
            work = work.replace(m2.group(0), " ")
    elif m := _MIN.search(work):
        intent.min_price = _amount(m.group(1), m.group(2))
        work = work.replace(m.group(0), " ")
    elif m := _AROUND.search(work):
        center = _amount(m.group(1), m.group(2))
        if center:
            intent.min_price, intent.max_price = round(center * 0.8, 2), round(center * 1.2, 2)
        work = work.replace(m.group(0), " ")
    elif (m := _DASH_RANGE.search(work)) and detect_currency(m.group(0)):
        intent.min_price, intent.max_price = _amount(m.group(1), m.group(2)), _amount(m.group(3), m.group(4))
        work = work.replace(m.group(0), " ")
    elif m := _BARE.search(work):
        # "a travel mug, 1.5k rupees" - a bare amount with a currency reads as a budget ceiling.
        digits, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        intent.max_price = _amount(digits, unit)
        work = work.replace(m.group(0), " ")
    if intent.min_price and intent.max_price and intent.min_price > intent.max_price:
        intent.min_price, intent.max_price = intent.max_price, intent.min_price

    # ---- retailers, alternatives, preferences -------------------------------
    intent.retailers = list(dict.fromkeys(d.lower() for d in _DOMAIN.findall(work)))[:5]
    for domain in intent.retailers:
        work = re.sub(rf"(?:\bfrom|\bon|\bat)?\s*{re.escape(domain)}", " ", work, flags=re.I)
    if m := _ALTERNATIVE.search(work):
        intent.alternatives_to = m.group(1).strip(" .?!")[:200] or None
    lowered = work.lower()
    intent.on_sale = bool(re.search(r"\bon sale\b|\bdiscount(?:ed)?\b|\bdeals?\b|\bclearance\b", lowered))
    intent.include_out_of_stock = bool(re.search(r"out of stock|sold out|unavailable too", lowered))
    intent.compare_brands = bool(re.search(r"\bcompare\b|\bvs\.?\b|\bversus\b", lowered))

    # ---- brands ------------------------------------------------------------
    brands: list[str] = []
    if m := _BRAND.search(work):
        brands += _split_names(m.group(1))
        work = work.replace(m.group(0), " ")
    for a, b in _VERSUS.findall(work):
        brands += [n for n in (a, b) if n not in _STOP_BRANDS]
    intent.exclude_brands = [n for n in _NOT_BRAND.findall(work) if n not in _STOP_BRANDS][:5]
    for excluded in intent.exclude_brands:
        work = re.sub(rf"\b(?:not|no|except|excluding|avoid)\s+{re.escape(excluded)}", " ", work)
    intent.brands = [b for b in dict.fromkeys(brands) if b not in intent.exclude_brands][:5]

    # ---- use case and attributes -------------------------------------------
    if m := _FOR.search(work):
        candidate = re.sub(r"\s+", " ", m.group(1)).strip(" .,")
        if candidate and not re.fullmatch(r"(?:a|an|the|me|us|my|our)", candidate, re.I):
            intent.use_case = candidate[:80]
            work = work.replace(m.group(0), " ")
    if m := _WITH.search(work):
        intent.attributes = [a.strip(" .,") for a in re.split(r",|\band\b", m.group(1)) if a.strip(" .,")][:6]
        # Kept out of the category phrase; re-appended to the query below.
        work = work.replace(m.group(0), " ")

    # ---- the product phrase -------------------------------------------------
    core = work
    if intent.alternatives_to:
        core = intent.alternatives_to
    core = re.sub(r"\b(?:compare|vs\.?|versus|between|alternatives?|similar|substitutes?)\b", " ", core, flags=re.I)
    core = re.sub(r"\b(?:on sale|discounted|deals?|out of stock|in stock)\b", " ", core, flags=re.I)
    core = _FILLER.sub(" ", core)
    core = re.sub(r"\b(?:to|of|in|from|by|on)\s*$", " ", core.strip(), flags=re.I)
    core = re.sub(r"[^\w\s&'+./-]", " ", core)
    core = re.sub(r"\s+", " ", core).strip(" .,-")
    category = core
    if intent.use_case and intent.use_case.lower() not in core.lower():
        core = f"{core} for {intent.use_case}" if core else f"products for {intent.use_case}"
    if intent.attributes and core and not any(a.lower() in core.lower() for a in intent.attributes):
        core = f"{core} with {', '.join(intent.attributes)}"
    intent.query = (core or raw)[:200]
    intent.category = category[:80] or None
    return intent


async def understand(text: str, *, trace: Any = None) -> tuple[SearchIntent, bool]:
    """Parse deterministically, then let the LLM (when configured) refine the words.

    Returns ``(intent, used_llm)``. Prices always come from the deterministic parser.
    """
    base = parse_intent(text)
    if not llm_service.enabled or len(base.raw) < 4:
        return base, False
    refined, result = await llm_service.structured(
        system=(
            "You extract product-search intent for a retail catalog. Return the core product phrase "
            "(no prices, no filler), a short category hint, desired attributes, the use case or audience, "
            "and brand names explicitly mentioned. Never invent brands or prices."
        ),
        user=f"Merchant request: {base.raw}",
        schema=_LLMIntent,
        fallback=_LLMIntent(query=base.query, category=base.category, attributes=base.attributes,
                            use_case=base.use_case, brands=base.brands),
        trace=trace,
        trace_name="discovery_intent",
        max_tokens=400,
    )
    if result.used_fallback:
        return base, False
    merged = base.model_copy()
    # The model may rephrase, never drop what the merchant asked for ("premium", "ergonomic"...).
    required = {w for w in re.findall(r"[a-z0-9]+", base.query.lower()) if len(w) > 2}
    offered = set(re.findall(r"[a-z0-9]+", (refined.query or "").lower()))
    if refined.query and 2 <= len(refined.query) <= 200 and required <= offered:
        merged.query = refined.query.strip()
        if merged.use_case and merged.use_case.lower() not in merged.query.lower() and refined.use_case is None:
            merged.query = f"{merged.query} for {merged.use_case}"
    merged.category = (refined.category or merged.category or "")[:80] or None
    merged.attributes = list(dict.fromkeys([*merged.attributes, *[a[:60] for a in refined.attributes]]))[:8]
    merged.use_case = (refined.use_case or merged.use_case or "")[:80] or None
    raw_lower = base.raw.lower()
    # A brand is accepted only if the merchant actually typed it.
    merged.brands = list(dict.fromkeys([*merged.brands, *[b for b in refined.brands if b and b.lower() in raw_lower]]))[:5]
    return merged, True


def budget_in_catalog_currency(intent: SearchIntent, catalog_currency: str) -> dict[str, Any]:
    """Translate the merchant's budget into the currency Channel3 prices in.

    Returns ``{min_price, max_price, currency, converted, rate, note}`` - the rate and note are
    shown to the merchant whenever a conversion happened.
    """
    source = (intent.budget_currency or catalog_currency).upper()
    out: dict[str, Any] = {"min_price": intent.min_price, "max_price": intent.max_price, "currency": catalog_currency,
                           "budget_currency": source, "converted": False, "rate": None, "note": None}
    if intent.min_price is None and intent.max_price is None:
        return out
    if source == catalog_currency:
        return out
    rates = settings.discovery_fx_rates
    rate_source, rate_target = (rates.get(source) if source != "USD" else 1.0), (rates.get(catalog_currency) if catalog_currency != "USD" else 1.0)
    if source in SUPPORTED_CURRENCIES and source != catalog_currency and rate_source is None:
        out["note"] = (f"Your budget is in {source}; results are priced in {catalog_currency}. "
                       f"Add {source} to DISCOVERY_FX_PER_USD to convert it - the price filter was not applied.")
        out["min_price"] = out["max_price"] = None
        return out
    if not rate_source or not rate_target:
        out["note"] = (f"Channel3 does not price in {source} and no reference rate is configured "
                       f"(DISCOVERY_FX_PER_USD) - the price filter was not applied.")
        out["min_price"] = out["max_price"] = None
        return out
    factor = Decimal(str(rate_target)) / Decimal(str(rate_source))

    def convert(value: float | None) -> float | None:
        if value is None:
            return None
        return float((Decimal(str(value)) * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    out.update(min_price=convert(intent.min_price), max_price=convert(intent.max_price), converted=True,
               rate=f"{rate_source:g} {source} = {rate_target:g} {catalog_currency}")
    bound = intent.max_price if intent.max_price is not None else intent.min_price
    shown = convert(bound)
    out["note"] = (f"Channel3 prices in {catalog_currency}, not {source}. Your budget of {source} {bound:,.0f} was "
                   f"converted to about {catalog_currency} {shown:,.2f} using the configurable reference rate "
                   f"{out['rate']} (DISCOVERY_FX_PER_USD) - not a live exchange rate.")
    return out


__all__ = ["SearchIntent", "budget_in_catalog_currency", "detect_currency", "parse_intent", "understand"]
