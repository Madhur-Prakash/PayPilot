"""Market price reference (Channel3) and supplier-portal verification (Kernel).

Both are *advisory*. Neither writes to a procurement request, widens a policy or
touches an approval - they give the human reviewing a purchase two more facts.
"""

from __future__ import annotations

import uuid
from collections import Counter
from decimal import Decimal
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models.audit import ActorType, AuditAction
from app.db.models.supply import ProcurementRequest
from app.integrations.sponsors import get_channel3, get_kernel
from app.integrations.sponsors.channel3 import attribution_id
from app.integrations.sponsors.kernel import BrowserSession
from app.repositories.merchant import AuditLogRepository
from app.services.supply.policy import ZERO, D, money, pct


def _stats(prices: list[Decimal]) -> dict[str, Decimal]:
    return {
        "min": money(min(prices)),
        "median": money(Decimal(median(prices))),
        "max": money(max(prices)),
    }


def _position(expected: Decimal | None, market_median: Decimal) -> dict[str, Any] | None:
    """Where the merchant's planned selling price sits against the market median."""
    if expected is None or expected <= ZERO or market_median <= ZERO:
        return None
    delta = pct(expected - market_median, market_median)
    if abs(delta) <= Decimal("10"):
        verdict = "in line with the market"
    elif delta > 0:
        verdict = "above the market - confirm customers will pay it"
    else:
        verdict = "below the market - there may be room to price up"
    return {
        "expected_selling_price": str(money(expected)),
        "difference_pct": str(delta),
        "verdict": verdict,
    }


#: A market price is only reported when this many results - and this share of them -
#: sit in one Channel3 category. Otherwise the results are not the same kind of thing.
MIN_CONSISTENT = 3
MIN_CONSISTENT_SHARE = Decimal("0.4")


def consistent_offers(offers: list[Any]) -> tuple[list[Any], str | None]:
    """The results that are the same kind of product, by Channel3 category.

    Search is semantic, so "whole bean coffee" can return canisters, a coffee face
    scrub and an espresso machine. A median across those is meaningless. Keep the
    largest category group if it is big enough; otherwise report nothing. Results
    without categories (the labelled offline reference) are kept as they are.
    """
    categories = Counter(o.category for o in offers if o.category)
    if not categories:
        return offers, None
    slug, count = categories.most_common(1)[0]
    if count >= MIN_CONSISTENT and Decimal(count) >= MIN_CONSISTENT_SHARE * len(offers):
        return [o for o in offers if o.category == slug], slug
    return [], None


async def benchmark(query: str, *, expected_price: Decimal | None = None, currency: str = "USD",
                    limit: int = 10, user_id: str | None = None) -> dict[str, Any]:
    """Market reference for a product. Retail prices only - never a cost or a limit."""
    result = await get_channel3().search(query, limit=limit, user_id=user_id)
    same_currency = [o for o in result.offers if o.currency == currency]
    comparable, category = consistent_offers(same_currency)
    out: dict[str, Any] = {
        "mode": result.mode,
        "query": result.query,
        "currency": currency,
        "offers": [o.as_dict() for o in result.offers],
        "excluded_other_currency": len(result.offers) - len(same_currency),
        "unparseable_results": result.skipped,
        "category": category,
        "comparable_results": len(comparable),
        "note": result.note,
        "disclaimer": "Retail prices from other sellers. They are context for the human reviewer; "
                      "they do not change any limit, budget or offer.",
        "stats": None,
        "position": None,
    }
    if comparable:
        prices = [o.price for o in comparable]
        out["stats"] = {k: str(v) for k, v in _stats(prices).items()}
        out["position"] = _position(expected_price, _stats(prices)["median"])
    elif same_currency:
        seen = sorted({o.category for o in same_currency if o.category})[:4]
        out["note"] = (
            f"Channel3 returned {len(same_currency)} listings across {len(seen)}+ unrelated categories "
            f"({', '.join(seen)}), so there is no consistent market price for this product."
        )
    return out


async def benchmark_procurement(session: AsyncSession, merchant_id: uuid.UUID, procurement_id: uuid.UUID) -> dict[str, Any]:
    request = (await session.execute(
        select(ProcurementRequest).where(ProcurementRequest.id == procurement_id,
                                         ProcurementRequest.merchant_id == merchant_id)
    )).scalar_one_or_none()
    if request is None:
        raise NotFoundError("Procurement request not found.")
    data = await benchmark(request.product_name, expected_price=D(request.expected_selling_price),
                           currency=request.currency or "USD", user_id=attribution_id(merchant_id))
    data["procurement"] = {"id": str(request.id), "reference": request.reference,
                           "product_name": request.product_name}
    if request.final_landed_total and request.quantity:
        unit = money(D(request.final_landed_total) / D(request.quantity))
        data["negotiated_landed_unit_cost"] = str(unit)
    return data


# --------------------------------------------------------------------------- #
# Kernel
# --------------------------------------------------------------------------- #
async def open_portal_session(
    session: AsyncSession, merchant_id: uuid.UUID, *, url: str, actor_id: uuid.UUID | None,
    actor_label: str, supplier_name: str = "", request_id: str | None = None,
) -> BrowserSession:
    browser = await get_kernel().open_session(url, name=f"paypilot-{supplier_name or 'supplier'}"[:60])
    await AuditLogRepository(session).record(
        action=AuditAction.INTEGRATION_ACTION, merchant_id=merchant_id, actor_id=actor_id,
        actor_type=ActorType.USER, actor_label=actor_label, resource="kernel_session",
        resource_id=browser.session_id, request_id=request_id,
        description=f"Opened a {browser.mode} supplier-portal browser session for {url}",
        metadata={"url": url, "mode": browser.mode, "supplier": supplier_name},
    )
    await session.commit()
    return browser


async def close_portal_session(session_id: str) -> bool:
    kernel = get_kernel()
    return await kernel.close_session(BrowserSession(mode=kernel.mode, session_id=session_id, url=""))
