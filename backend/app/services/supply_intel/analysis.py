"""Assortment analysis: what the merchant sells, what is growing, and where to expand.

Everything here is SQL over the merchant's own transactions and inventory - no model
and no external call:

* product and category performance, current window vs the window before it;
* demand patterns (sales channel and daypart split) for the products that matter;
* basket pairs (what is bought together) from the existing analytics service;
* inventory turnover and days of cover;
* **expansion candidates** - complementary product slots next to the products whose
  demand is real and rising. Each candidate carries the signals that justify it and
  becomes a Channel3 search in ``recommendations.py``.

The analysis window is anchored to the last transaction in the data, like the rest of
PayPilot's analytics, so a demo dataset analyses the same way on any day.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.commerce import Product, Transaction, TransactionItem
from app.db.models.inventory import InventoryItem
from app.services.integrations.shelf import COFFEE_SHELF

MIN_ORDERS_FOR_CONFIDENCE = 20


@dataclass(frozen=True, slots=True)
class ComplementSlot:
    key: str
    label: str
    query: str
    category: str | None  # a Channel3 category slug, when verified
    max_price: Decimal | None


#: Complementary product slots by what the anchor product is. The coffee slots are the
#: gear shelf's, whose Channel3 category slugs were verified against the live catalog.
COMPLEMENTS: tuple[tuple[tuple[str, ...], tuple[ComplementSlot, ...]], ...] = (
    (("coffee", "bean", "espresso", "roast", "brew"),
     tuple(ComplementSlot(s.key, s.label, s.query, s.category, s.max_price) for s in COFFEE_SHELF)),
    (("tea", "matcha", "chai"), (
        ComplementSlot("tea-infusers", "Tea infusers", "loose leaf tea infuser", None, Decimal("40")),
        ComplementSlot("teapots", "Teapots", "glass teapot with infuser", None, Decimal("80")),
        ComplementSlot("tea-storage", "Tea tins", "airtight tea storage tin", None, Decimal("40")),
    )),
    (("chocolate", "brownie", "cookie", "dessert", "pastry", "cake"), (
        ComplementSlot("gift-boxes", "Gift boxes", "bakery gift box", None, Decimal("40")),
        ComplementSlot("baking", "Home baking kits", "brownie baking kit", None, Decimal("60")),
    )),
)


def complements_for(product: dict[str, Any]) -> tuple[ComplementSlot, ...]:
    text = " ".join([product.get("name", ""), product.get("category", ""), " ".join(product.get("tags") or [])]).lower()
    for keywords, slots in COMPLEMENTS:
        if any(re.search(rf"\b{k}", text) for k in keywords):
            return slots
    name = re.sub(r"\(.*?\)", "", product.get("name", "")).strip()
    return (ComplementSlot(f"accessories-{_slug(name)}", f"{name} accessories", f"{name} accessories", None, None),)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "product"


def _pct(current: float, previous: float) -> float | None:
    if previous <= 0:
        return None
    return round((current - previous) / previous * 100, 1)


class AssortmentAnalyzer:
    def __init__(self, session: AsyncSession, merchant_id: uuid.UUID) -> None:
        self.session = session
        self.merchant_id = merchant_id

    async def _window(self, days: int) -> tuple[date, date, date, date] | None:
        latest = (await self.session.execute(
            select(func.max(Transaction.business_date)).where(Transaction.merchant_id == self.merchant_id)
        )).scalar_one_or_none()
        if latest is None:
            return None
        start = latest - timedelta(days=days - 1)
        return start, latest, start - timedelta(days=days), start - timedelta(days=1)

    async def _product_rows(self, start: date, end: date) -> dict[uuid.UUID, dict[str, float]]:
        rows = (await self.session.execute(
            select(
                TransactionItem.product_id,
                func.sum(TransactionItem.quantity),
                func.sum(TransactionItem.line_total),
                func.count(distinct(TransactionItem.transaction_id)),
                func.count(distinct(Transaction.customer_id)),
            )
            .join(Transaction, Transaction.id == TransactionItem.transaction_id)
            .where(TransactionItem.merchant_id == self.merchant_id,
                   Transaction.business_date >= start, Transaction.business_date <= end)
            .group_by(TransactionItem.product_id)
        )).all()
        return {pid: {"units": float(u or 0), "revenue": float(r or 0), "orders": int(o or 0), "customers": int(c or 0)}
                for pid, u, r, o, c in rows}

    async def _channel_split(self, product_ids: list[uuid.UUID], start: date, end: date) -> dict[uuid.UUID, list[dict[str, Any]]]:
        if not product_ids:
            return {}
        rows = (await self.session.execute(
            select(TransactionItem.product_id, Transaction.channel, func.sum(TransactionItem.quantity))
            .join(Transaction, Transaction.id == TransactionItem.transaction_id)
            .where(TransactionItem.merchant_id == self.merchant_id, TransactionItem.product_id.in_(product_ids),
                   Transaction.business_date >= start, Transaction.business_date <= end)
            .group_by(TransactionItem.product_id, Transaction.channel)
        )).all()
        out: dict[uuid.UUID, list[dict[str, Any]]] = {}
        for pid, channel, units in rows:
            out.setdefault(pid, []).append({"channel": channel, "units": float(units or 0)})
        for pid, splits in out.items():
            total = sum(s["units"] for s in splits) or 1
            for s in splits:
                s["share_pct"] = round(s["units"] / total * 100, 1)
            splits.sort(key=lambda s: -s["units"])
        return out

    async def _daypart_split(self, start: date, end: date) -> list[dict[str, Any]]:
        rows = (await self.session.execute(
            select(Transaction.daypart, func.count(Transaction.id), func.sum(Transaction.net_amount))
            .where(Transaction.merchant_id == self.merchant_id, Transaction.business_date >= start,
                   Transaction.business_date <= end)
            .group_by(Transaction.daypart)
        )).all()
        total = sum(float(r[2] or 0) for r in rows) or 1
        return sorted(({"daypart": d, "orders": int(o), "revenue": round(float(r or 0), 2),
                        "share_pct": round(float(r or 0) / total * 100, 1)} for d, o, r in rows),
                      key=lambda x: -x["revenue"])

    async def analyze(self, *, days: int = 30) -> dict[str, Any]:
        window = await self._window(days)
        products = (await self.session.execute(select(Product).where(Product.merchant_id == self.merchant_id))).scalars().all()
        if window is None or not products:
            return {"has_data": False, "note": "No sales yet - Supply Intelligence needs transactions to analyse.",
                    "categories": [], "top_products": [], "expansion_candidates": [], "inventory": [], "pairs": []}
        start, end, prev_start, prev_end = window
        current = await self._product_rows(start, end)
        previous = await self._product_rows(prev_start, prev_end)
        by_id = {p.id: p for p in products}

        product_rows: list[dict[str, Any]] = []
        for pid, cur in current.items():
            product = by_id.get(pid)
            if product is None:
                continue
            prev = previous.get(pid, {"units": 0.0, "revenue": 0.0, "orders": 0, "customers": 0})
            product_rows.append({
                "product_id": str(pid), "name": product.name, "sku": product.sku, "category": product.category,
                "tags": list(product.tags or []), "price": float(product.price), "cost_price": float(product.cost_price or 0),
                "channel": (product.attributes or {}).get("channel"),
                "units": round(cur["units"], 2), "revenue": round(cur["revenue"], 2), "orders": cur["orders"],
                "buyers": cur["customers"] or cur["orders"],
                "previous_units": round(prev["units"], 2), "previous_revenue": round(prev["revenue"], 2),
                "units_growth_pct": _pct(cur["units"], prev["units"]),
                "revenue_growth_pct": _pct(cur["revenue"], prev["revenue"]),
                "daily_units": round(cur["units"] / days, 2),
            })
        product_rows.sort(key=lambda r: -r["revenue"])
        total_revenue = sum(r["revenue"] for r in product_rows) or 1.0
        for r in product_rows:
            r["revenue_share_pct"] = round(r["revenue"] / total_revenue * 100, 1)

        categories: dict[str, dict[str, Any]] = {}
        for r in product_rows:
            cat = categories.setdefault(r["category"], {"category": r["category"], "revenue": 0.0, "units": 0.0,
                                                        "previous_revenue": 0.0, "products": 0, "orders": 0})
            cat["revenue"] += r["revenue"]
            cat["units"] += r["units"]
            cat["previous_revenue"] += r["previous_revenue"]
            cat["products"] += 1
            cat["orders"] += r["orders"]
        category_rows = []
        for cat in categories.values():
            category_rows.append({**cat, "revenue": round(cat["revenue"], 2), "units": round(cat["units"], 2),
                                  "share_pct": round(cat["revenue"] / total_revenue * 100, 1),
                                  "growth_pct": _pct(cat["revenue"], cat["previous_revenue"])})
        category_rows.sort(key=lambda c: -c["revenue"])

        orders_total = (await self.session.execute(
            select(func.count(Transaction.id)).where(Transaction.merchant_id == self.merchant_id,
                                                     Transaction.business_date >= start, Transaction.business_date <= end)
        )).scalar_one()

        # ---- inventory turnover ------------------------------------------------
        inventory_rows = []
        items = (await self.session.execute(
            select(InventoryItem).where(InventoryItem.merchant_id == self.merchant_id, InventoryItem.is_tracked.is_(True))
        )).scalars().all()
        sold = {uuid.UUID(r["product_id"]): r for r in product_rows}
        for item in items:
            on_hand = float(item.quantity_on_hand or 0)
            units = sold.get(item.product_id, {}).get("units", 0.0)
            inventory_rows.append({
                "inventory_item_id": str(item.id), "product_id": str(item.product_id), "name": item.product_name,
                "sku": item.sku, "unit": item.unit, "on_hand": round(on_hand, 2),
                "avg_daily_demand": round(float(item.avg_daily_demand or 0), 3),
                "days_of_cover": round(float(item.days_of_cover), 1) if item.days_of_cover is not None else None,
                "status": item.status, "units_sold": round(units, 2),
                "turnover": round(units / on_hand, 2) if on_hand > 0 else None,
            })
        inventory_rows.sort(key=lambda r: (r["days_of_cover"] is None, r["days_of_cover"] or 0))

        # ---- basket pairs (existing analytics) ---------------------------------
        pairs: list[dict[str, Any]] = []
        try:
            from app.schemas.common import DateRange
            from app.services.analytics.service import AnalyticsService

            mix = await AnalyticsService(self.session, self.merchant_id).product_mix(DateRange(start=start, end=end), limit=5)
            pairs = [m.model_dump(mode="json") for m in mix]
        except Exception:  # analytics is context, never a reason to fail the analysis
            pairs = []

        anchors = self._anchors(product_rows)
        channel = await self._channel_split([uuid.UUID(a["product_id"]) for a in anchors], start, end)
        for anchor in anchors:
            anchor["channel_split"] = channel.get(uuid.UUID(anchor["product_id"]), [])
        candidates = self._candidates(anchors, orders_total=int(orders_total))
        sufficient = int(orders_total) >= MIN_ORDERS_FOR_CONFIDENCE
        return {
            "has_data": True,
            "window": {"start": start.isoformat(), "end": end.isoformat(), "days": days,
                       "previous_start": prev_start.isoformat(), "previous_end": prev_end.isoformat()},
            "summary": {"revenue": round(sum(r["revenue"] for r in product_rows), 2), "orders": int(orders_total),
                        "units": round(sum(r["units"] for r in product_rows), 2), "products_sold": len(product_rows),
                        "catalog_products": len(products)},
            "categories": category_rows,
            "top_products": product_rows[:10],
            "growing_products": sorted([r for r in product_rows if (r["units_growth_pct"] or 0) > 10],
                                       key=lambda r: -(r["units_growth_pct"] or 0))[:5],
            "anchors": anchors,
            "pairs": pairs,
            "inventory": inventory_rows[:15],
            "daypart_split": await self._daypart_split(start, end),
            "expansion_candidates": candidates,
            "data_quality": {"orders": int(orders_total), "sufficient": sufficient,
                             "note": None if sufficient else
                             f"Only {orders_total} orders in the window - recommendations carry low confidence."},
        }

    @staticmethod
    def _anchors(product_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Products worth building around: online/retail sellers first, then rising best-sellers."""
        retail = [r for r in product_rows if r.get("channel") == "online_store" or r["category"] in ("retail", "merchandise")]
        growing = sorted([r for r in product_rows if (r["units_growth_pct"] or 0) > 0 and r not in retail],
                         key=lambda r: -(r["revenue"] * (1 + (r["units_growth_pct"] or 0) / 100)))
        return [*retail[:2], *growing[: max(0, 2 - len(retail[:2]))]]

    @staticmethod
    def _candidates(anchors: list[dict[str, Any]], *, orders_total: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for anchor in anchors:
            growth = anchor["units_growth_pct"]
            for slot in complements_for(anchor):
                signals = [
                    {"label": f"{anchor['name']} buyers (last window)", "value": anchor["buyers"], "source": "Your sales data"},
                    {"label": f"{anchor['name']} units sold", "value": anchor["units"], "source": "Your sales data"},
                ]
                if growth is not None:
                    signals.append({"label": f"{anchor['name']} unit growth vs prior window", "value": f"{growth:+.1f}%",
                                    "source": "Your sales data"})
                online = next((c for c in anchor.get("channel_split", []) if c["channel"] == "online_store"), None)
                if online:
                    signals.append({"label": "Share sold through your online store", "value": f"{online['share_pct']}%",
                                    "source": "Your sales data"})
                score = anchor["buyers"] * (1 + max(growth or 0, 0) / 100)
                out.append({
                    "key": f"{anchor['sku']}:{slot.key}",
                    "anchor": {k: anchor[k] for k in ("product_id", "name", "sku", "category", "price", "buyers",
                                                      "units", "units_growth_pct", "daily_units", "orders")},
                    "slot": {"key": slot.key, "label": slot.label, "query": slot.query, "category": slot.category,
                             "max_price": str(slot.max_price) if slot.max_price is not None else None},
                    "rationale": (f"Customers who buy {anchor['name']} need {slot.label.lower()}, which you do not stock."
                                  + (f" Demand for {anchor['name']} is up {growth:+.0f}%." if growth and growth > 0 else "")),
                    "signals": signals,
                    "score": round(score, 2),
                    "orders_in_window": orders_total,
                })
        out.sort(key=lambda c: -c["score"])
        return out


__all__ = ["COMPLEMENTS", "AssortmentAnalyzer", "ComplementSlot", "complements_for"]
