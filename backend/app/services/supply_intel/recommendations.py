"""AI product recommendations and their lifecycle.

    DETECTED   a signal in the merchant's own data (rising demand, a price gap)
    ANALYZED   live Channel3 evidence attached (products, retail prices, retailers)
    RECOMMENDED action, expected impact (an estimate, with its assumptions) and confidence
    APPROVED   a human with ``procurement:approve`` agreed           (or REJECTED)
    EXECUTED   the permitted action ran: product added to the catalog / price test applied
    MEASURED   outcomes recomputed from transactions and PayPal records

Money never moves from here. Buying test stock is a separate ``MERCHANT_PURCHASE``
approval request (bound by hash to the exact quantity, unit cost, payee and product)
that a human with ``payment:approve`` must decide, and the PayPal order is created
and captured by ``services/paypal/orders.py`` - never by an agent.

Every number in ``evidence`` comes from SQL or Channel3. Expected impact is labelled
``is_estimate`` and lists its assumptions; the attach rate is stated as an assumption,
not a measurement. An optional LLM pass may rewrite the *description* prose - it is
given the computed facts and cannot change them.
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from statistics import median
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import memory as agent_memory
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.logging import get_logger
from app.core.permissions import Permission
from app.db.models.audit import ActorType, AuditAction
from app.db.models.commerce import Product, Transaction, TransactionItem
from app.db.models.discovery import MerchantRecommendation, RecommendationKind, RecommendationStatus, SearchSource
from app.db.models.governance import ApprovalAction, ApprovalRequest, FinancialExecution
from app.integrations.groq import llm_service
from app.integrations.sponsors import get_channel3_catalog
from app.integrations.sponsors.base import SponsorError
from app.integrations.sponsors.channel3 import attribution_id
from app.integrations.sponsors.channel3_catalog import CatalogProduct, build_filters
from app.repositories.merchant import AuditLogRepository
from app.services.discovery.intent import SearchIntent
from app.services.discovery.ranking import rank_products
from app.services.discovery.service import ProductDiscoveryService, _throttle
from app.services.integrations.shelf import ATTACH_RATE
from app.services.supply.approvals import ApprovalService
from app.services.supply_intel.analysis import AssortmentAnalyzer
from app.services.supply_intel.pricing import PricingIntelligence

log = get_logger(__name__)

AGENT_LABEL = "Supply Intelligence Agent"
TEST_QTY_MIN, TEST_QTY_MAX = 6, 48
MIN_BUYERS_FOR_QUANTITY = 10
#: A decided recommendation is not re-proposed for the same slot within this window.
COOLDOWN = timedelta(days=14)
PURCHASE_POLICY_VERSION = "merchant-purchase-v1"


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _stage(status: str, note: str, actor: str = AGENT_LABEL) -> dict[str, Any]:
    return {"status": status, "at": _now().isoformat(), "actor": actor, "note": note}


def _snapshot(product: dict[str, Any]) -> dict[str, Any]:
    """What a recommendation keeps of a product: enough to show it, no short-lived offer link."""
    keep = ("id", "title", "brand", "image_url", "price", "currency", "retailer", "retailers", "offers_count",
            "in_stock", "category", "ratings", "key_features", "commission_rate", "ranking", "similarity")
    return {k: product.get(k) for k in keep if k in product}


class _Polished(BaseModel):
    items: list[dict[str, str]] = Field(default_factory=list)


def purchase_details(rec: MerchantRecommendation, *, quantity: int, unit_cost: Decimal, payee_email: str,
                     currency: str) -> dict[str, Any]:
    """The exact terms a MERCHANT_PURCHASE approval binds to (hashed by ApprovalService)."""
    product = (rec.products or [{}])[0]
    return {
        "recommendation_id": str(rec.id),
        "recommendation_reference": rec.reference,
        "channel3_product_id": product.get("id"),
        "product_title": product.get("title"),
        "quantity": int(quantity),
        "unit_cost": str(_q(Decimal(str(unit_cost)))),
        "total": str(_q(Decimal(str(unit_cost)) * int(quantity))),
        "currency": currency,
        "payee_email": payee_email.strip().lower(),
        "policy_version": PURCHASE_POLICY_VERSION,
    }


def recommendation_out(row: MerchantRecommendation) -> dict[str, Any]:
    reached = {s["status"] for s in row.lifecycle or []}
    stages = []
    for status in RecommendationStatus.LIFECYCLE:
        entry = next((s for s in reversed(row.lifecycle or []) if s["status"] == status), None)
        stages.append({"status": status, "reached": status in reached, "at": entry["at"] if entry else None,
                       "actor": entry["actor"] if entry else None, "note": entry["note"] if entry else None})
    return {
        "id": str(row.id),
        "reference": row.reference,
        "kind": row.kind,
        "kind_label": RecommendationKind.LABELS.get(row.kind, row.kind),
        "title": row.title,
        "description": row.description,
        "evidence": row.evidence or [],
        "recommended_action": row.recommended_action,
        "expected_impact": row.expected_impact or {},
        "confidence": float(row.confidence),
        "confidence_reasons": row.confidence_reasons or [],
        "requires_approval": row.requires_approval,
        "status": row.status,
        "stages": stages,
        "lifecycle": row.lifecycle or [],
        "anchor_product": {"id": str(row.anchor_product_id) if row.anchor_product_id else None,
                           "name": row.anchor_product_name},
        "category": row.category,
        "products": row.products or [],
        "suggested_test_quantity": row.suggested_test_quantity,
        "suggested_retail_price": str(row.suggested_retail_price) if row.suggested_retail_price is not None else None,
        "currency": row.currency,
        "narrative_source": row.narrative_source,
        "agent_run_id": str(row.agent_run_id) if row.agent_run_id else None,
        "decided_by": row.decided_by_label or None,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "decision_note": row.decision_note,
        "executed_at": row.executed_at.isoformat() if row.executed_at else None,
        "execution": row.execution or {},
        "measured_at": row.measured_at.isoformat() if row.measured_at else None,
        "measurement": row.measurement or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


class RecommendationService:
    def __init__(self, session: AsyncSession, merchant_id: uuid.UUID, *, user_id: uuid.UUID | None = None,
                 actor_label: str = "", merchant_name: str = "", agent_run_id: uuid.UUID | None = None,
                 request_id: str | None = None) -> None:
        self.session = session
        self.merchant_id = merchant_id
        self.user_id = user_id
        self.actor_label = actor_label or AGENT_LABEL
        self.merchant_name = merchant_name
        self.agent_run_id = agent_run_id
        self.request_id = request_id
        self.audit = AuditLogRepository(session)
        self.catalog = get_channel3_catalog()

    # ================================================================== read
    async def get(self, rec_id: uuid.UUID) -> MerchantRecommendation:
        row = (await self.session.execute(
            select(MerchantRecommendation).where(MerchantRecommendation.id == rec_id,
                                                 MerchantRecommendation.merchant_id == self.merchant_id)
        )).scalars().first()
        if row is None:
            raise NotFoundError("Recommendation not found.")
        return row

    async def list(self, *, status: str | None = None, kind: str | None = None, limit: int = 50) -> tuple[list[dict[str, Any]], dict[str, int]]:
        stmt = select(MerchantRecommendation).where(MerchantRecommendation.merchant_id == self.merchant_id,
                                                    MerchantRecommendation.status != RecommendationStatus.SUPERSEDED)
        if status:
            stmt = stmt.where(MerchantRecommendation.status == status)
        if kind:
            stmt = stmt.where(MerchantRecommendation.kind == kind)
        rows = (await self.session.execute(stmt.order_by(MerchantRecommendation.updated_at.desc()).limit(limit))).scalars().all()
        counts = dict((await self.session.execute(
            select(MerchantRecommendation.status, func.count()).where(MerchantRecommendation.merchant_id == self.merchant_id)
            .group_by(MerchantRecommendation.status)
        )).all())
        return [recommendation_out(r) for r in rows], {k: int(v) for k, v in counts.items()}

    # ================================================================== generate
    async def generate(self, *, days: int = 30, max_recommendations: int = 4, include_pricing: bool = True,
                       trace: Any = None) -> dict[str, Any]:
        analysis = await AssortmentAnalyzer(self.session, self.merchant_id).analyze(days=days)
        if not analysis.get("has_data"):
            return {"recommendations": [], "analysis": analysis, "notes": [analysis.get("note")]}
        produced: list[MerchantRecommendation] = []
        notes: list[str] = []
        seen_anchor_slots: set[str] = set()
        for candidate in analysis["expansion_candidates"]:
            if len(produced) >= max(1, max_recommendations - (1 if include_pricing else 0)):
                break
            if candidate["key"] in seen_anchor_slots:
                continue
            seen_anchor_slots.add(candidate["key"])
            try:
                rec = await self._assortment(candidate, analysis)
            except SponsorError as exc:
                if exc.status_code == 503:
                    raise
                notes.append(f"{candidate['slot']['label']}: {exc}")
                continue
            if rec is not None:
                produced.append(rec)
        if include_pricing:
            units = {r["product_id"]: r["units"] for r in analysis["top_products"]}
            try:
                pricing = await PricingIntelligence(self.session, self.merchant_id, user_id=self.user_id,
                                                    agent_run_id=self.agent_run_id).analyze(limit=2, units_by_product=units)
                for row in pricing["products"]:
                    if (row.get("opportunity") or {}).get("type") == "PRICE_TEST_UP":
                        rec = await self._pricing(row, analysis)
                        if rec is not None:
                            produced.append(rec)
                    elif row.get("note"):
                        notes.append(f"{row['name']}: {row['note']}")
            except SponsorError as exc:
                if exc.status_code == 503:
                    raise
                notes.append(f"Market price intelligence: {exc}")
        await self.session.flush()
        polished = await self._polish(produced, trace=trace)
        if produced:
            await self.audit.record(
                action=AuditAction.RECOMMENDATION_GENERATED, merchant_id=self.merchant_id, actor_id=self.user_id,
                actor_type=ActorType.AGENT, actor_label=AGENT_LABEL, resource="merchant_recommendation",
                resource_id=str(produced[0].id), agent_run_id=self.agent_run_id, request_id=self.request_id,
                description=f"Generated {len(produced)} supply recommendation(s) from sales data and Channel3.",
                metadata={"references": [r.reference for r in produced], "llm_narrative": polished},
            )
        await self.session.flush()
        return {
            "recommendations": [recommendation_out(r) for r in produced],
            "analysis": {k: analysis[k] for k in ("window", "summary", "categories", "growing_products", "data_quality")
                         if k in analysis},
            "notes": notes,
        }

    async def _next_reference(self) -> str:
        count = (await self.session.execute(
            select(func.count()).select_from(MerchantRecommendation).where(MerchantRecommendation.merchant_id == self.merchant_id)
        )).scalar_one()
        return f"REC-{int(count) + 1:05d}"

    async def _upsert(self, dedupe_key: str, fields: dict[str, Any], detected_note: str, analyzed_note: str) -> MerchantRecommendation | None:
        existing = (await self.session.execute(
            select(MerchantRecommendation).where(MerchantRecommendation.merchant_id == self.merchant_id,
                                                 MerchantRecommendation.dedupe_key == dedupe_key)
            .order_by(MerchantRecommendation.created_at.desc())
        )).scalars().first()
        if existing is not None and existing.status not in RecommendationStatus.OPEN:
            decided = existing.decided_at or existing.updated_at
            if decided and (decided if decided.tzinfo else decided.replace(tzinfo=UTC)) > _now() - COOLDOWN:
                return None  # a human already decided this one recently
        if existing is not None and existing.status in RecommendationStatus.OPEN:
            for key, value in fields.items():
                setattr(existing, key, value)
            existing.lifecycle = [*(existing.lifecycle or []),
                                  _stage(RecommendationStatus.ANALYZED, "Refreshed with the latest sales data and Channel3 listings."),
                                  _stage(RecommendationStatus.RECOMMENDED, "Action and impact recomputed.")]
            existing.status = RecommendationStatus.RECOMMENDED
            existing.agent_run_id = self.agent_run_id or existing.agent_run_id
            return existing
        row = MerchantRecommendation(
            merchant_id=self.merchant_id, reference=await self._next_reference(), dedupe_key=dedupe_key,
            requires_approval=True, agent_run_id=self.agent_run_id, execution={}, measurement={},
            lifecycle=[_stage(RecommendationStatus.DETECTED, detected_note),
                       _stage(RecommendationStatus.ANALYZED, analyzed_note),
                       _stage(RecommendationStatus.RECOMMENDED, "Action, expected impact and confidence computed; "
                                                                "waiting for a human decision.")],
            status=RecommendationStatus.RECOMMENDED, **fields,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def _channel3_products(self, query: str, *, category: str | None, max_price: Decimal | None,
                                 limit: int = 10) -> tuple[list[CatalogProduct], str | None]:
        filters = build_filters(max_price=max_price, category_ids=[category] if category else None)
        _throttle(self.merchant_id)
        page = await self.catalog.search(query, filters=filters, limit=limit, user_id=attribution_id(self.merchant_id))
        used_category = category
        if category and len(page.products) < 3:
            _throttle(self.merchant_id)
            filters.pop("category_ids", None)
            wider = await self.catalog.search(query, filters=filters, limit=limit, user_id=attribution_id(self.merchant_id))
            if len(wider.products) > len(page.products):
                page, used_category = wider, None
        discovery = ProductDiscoveryService(self.session, self.merchant_id, user_id=self.user_id, agent_run_id=self.agent_run_id)
        from app.db.models.discovery import ProductSearch

        self.session.add(ProductSearch(
            merchant_id=self.merchant_id, user_id=self.user_id, source=SearchSource.ASSORTMENT, query=query,
            intent={"category": used_category, "max_price": str(max_price) if max_price else None},
            request=page.request, result_count=len(page.products), product_ids=[p.id for p in page.products],
            mode=self.catalog.mode, duration_ms=page.duration_ms, agent_run_id=self.agent_run_id,
        ))
        await discovery._remember(page.products, SearchSource.ASSORTMENT)
        return page.products, used_category

    async def _assortment(self, candidate: dict[str, Any], analysis: dict[str, Any]) -> MerchantRecommendation | None:
        slot, anchor = candidate["slot"], candidate["anchor"]
        max_price = Decimal(slot["max_price"]) if slot.get("max_price") else None
        found, used_category = await self._channel3_products(slot["query"], category=slot.get("category"), max_price=max_price)
        usable = [p for p in found if p.best_offer and p.currency == self.catalog.currency and p.in_stock is not False]
        if not usable:
            return None
        intent = SearchIntent(raw=slot["query"], query=slot["query"], max_price=float(max_price) if max_price else None)
        ranked = rank_products(usable, intent, min_price=None, max_price=float(max_price) if max_price else None)[:3]
        prices = [Decimal(p["price"]) for p in ranked if p.get("price")]
        retail_reference = _q(Decimal(median(prices))) if prices else None
        buyers = int(anchor.get("buyers") or 0)
        monthly_buyers = Decimal(buyers) * Decimal(30) / Decimal(analysis["window"]["days"])
        quantity = None
        if buyers >= MIN_BUYERS_FOR_QUANTITY:
            quantity = max(TEST_QTY_MIN, min(TEST_QTY_MAX, math.ceil(monthly_buyers * ATTACH_RATE)))
        monthly_units = monthly_buyers * ATTACH_RATE
        revenue = _q(monthly_units * retail_reference) if retail_reference else None
        growth = anchor.get("units_growth_pct")
        quality = analysis.get("data_quality", {})

        confidence, reasons = Decimal("0.40"), ["Base: a complementary product, not yet tested with your customers"]
        if quality.get("sufficient"):
            confidence += Decimal("0.15")
            reasons.append(f"{quality.get('orders')} orders in the analysis window")
        if growth and growth > 10:
            confidence += Decimal("0.10")
            reasons.append(f"{anchor['name']} demand is rising ({growth:+.0f}%)")
        if len(ranked) >= 3:
            confidence += Decimal("0.10")
            reasons.append(f"{len(found)} live Channel3 listings in this category")
        online = next((s for s in candidate["signals"] if "online store" in s["label"]), None)
        if online:
            confidence += Decimal("0.05")
            reasons.append("Customers already buy this line online, where add-ons are easy to list")
        confidence = min(confidence, Decimal("0.90"))

        evidence = [*candidate["signals"],
                    {"label": "Comparable products on Channel3", "value": len(found), "source": "Channel3"},
                    {"label": "Median retail price of the top picks",
                     "value": f"{self.catalog.currency} {retail_reference}" if retail_reference else "-", "source": "Channel3"},
                    {"label": "Retailers listing the top picks",
                     "value": ", ".join(sorted({r for p in ranked for r in (p.get('retailers') or [])[:3]}))[:200] or "-",
                     "source": "Channel3"}]
        top = ranked[0]
        assumptions = [
            f"{buyers} customers bought {anchor['name']} in the last {analysis['window']['days']} days (measured).",
            f"{ATTACH_RATE * 100:.0f}% of them buy one {slot['label'].lower()} item a month (assumed, not measured).",
            f"Priced at the median retail price of the top picks ({self.catalog.currency} {retail_reference}) - a "
            "retail reference, not your wholesale cost." if retail_reference else "No retail price reference available.",
            "Margin is unknown until you have a supplier's wholesale price.",
        ]
        fields = {
            "kind": RecommendationKind.ASSORTMENT_EXPANSION,
            "title": f"Add {slot['label'].lower()} next to {anchor['name']}",
            "description": (f"{candidate['rationale']} Channel3 lists {len(found)} matching products; the strongest "
                            f"pick is {top['title']} ({top.get('retailer') or 'retailer'}, {self.catalog.currency} {top.get('price')})."),
            "evidence": evidence,
            "recommended_action": (f"Stock a test batch of {quantity} units of {top['title']} and list it beside "
                                   f"{anchor['name']} for 30 days." if quantity else
                                   f"List {top['title']} beside {anchor['name']} as a small test; there is not enough "
                                   "sales data to size a stock order."),
            "expected_impact": {"metric": "monthly_revenue", "value": str(revenue) if revenue is not None else None,
                                "currency": self.catalog.currency, "period": "month", "is_estimate": True,
                                "units_per_month": str(_q(monthly_units)), "assumptions": assumptions},
            "confidence": confidence.quantize(Decimal("0.001")),
            "confidence_reasons": reasons,
            "anchor_product_id": uuid.UUID(anchor["product_id"]),
            "anchor_product_name": anchor["name"][:160],
            "category": (used_category or slot["label"])[:120],
            "products": [_snapshot(p) for p in ranked],
            "suggested_test_quantity": quantity,
            "suggested_retail_price": retail_reference,
            "currency": self.catalog.currency,
            "narrative_source": "deterministic",
        }
        return await self._upsert(
            f"ASSORTMENT:{candidate['key']}", fields,
            detected_note=f"{anchor['name']}: {buyers} buyers" + (f", demand {growth:+.0f}%" if growth else "")
            + f" - customers need {slot['label'].lower()} you do not stock.",
            analyzed_note=f"Channel3 search '{slot['query']}' returned {len(found)} live products; top {len(ranked)} ranked.",
        )

    async def _pricing(self, row: dict[str, Any], analysis: dict[str, Any]) -> MerchantRecommendation | None:
        opp, stats = row["opportunity"], row["stats"]
        suggested = Decimal(opp["suggested_price"])
        change = opp.get("estimated_monthly_revenue_change")
        confidence = Decimal("0.45") + (Decimal("0.15") if stats["count"] >= 5 else Decimal("0")) \
            + (Decimal("0.10") if analysis.get("data_quality", {}).get("sufficient") else Decimal("0"))
        reasons = [f"{stats['count']} comparable listings in one Channel3 category",
                   "A price test is reversible and measured against your own sales"]
        evidence = [
            {"label": "Your selling price", "value": f"{row['currency']} {row['merchant_price']}", "source": "Your catalog"},
            {"label": "Market median (retail)", "value": f"{row['currency']} {stats['median']}", "source": "Channel3"},
            {"label": "Market range", "value": f"{stats['min']} - {stats['max']}", "source": "Channel3"},
            {"label": "Comparable listings", "value": stats["count"], "source": "Channel3"},
            {"label": "Gap to median", "value": f"{row['position']['difference_pct']}%", "source": "Computed"},
        ]
        if row.get("merchant_unit_cost"):
            evidence.append({"label": "Your unit cost (not a market price)", "value": f"{row['currency']} {row['merchant_unit_cost']}",
                             "source": "Your inventory"})
        fields = {
            "kind": RecommendationKind.PRICING_OPPORTUNITY,
            "title": f"Test {row['currency']} {suggested} for {row['name']}",
            "description": (f"{row['name']} sells for {row['currency']} {row['merchant_price']}, "
                            f"{abs(Decimal(row['position']['difference_pct']))}% below the median of {stats['count']} "
                            f"comparable retail listings ({row['currency']} {stats['median']}). A capped price test checks "
                            "whether customers accept a step toward the market."),
            "evidence": evidence,
            "recommended_action": (f"Raise {row['name']} from {row['merchant_price']} to {suggested} "
                                   f"(+{opp['step_pct']}%) for two weeks, then measure units and revenue against the "
                                   "two weeks before."),
            "expected_impact": {"metric": "monthly_revenue_change", "value": change, "currency": row["currency"],
                                "period": "month", "is_estimate": True, "assumptions": opp["assumptions"]},
            "confidence": min(confidence, Decimal("0.85")).quantize(Decimal("0.001")),
            "confidence_reasons": reasons,
            "anchor_product_id": uuid.UUID(row["product_id"]),
            "anchor_product_name": row["name"][:160],
            "category": ((row.get("comparable_category") or {}).get("title") or row["category"])[:120],
            "products": row["comparables"][:5],
            "suggested_test_quantity": None,
            "suggested_retail_price": suggested,
            "currency": row["currency"],
            "narrative_source": "deterministic",
        }
        return await self._upsert(
            f"PRICING:{row['product_id']}", fields,
            detected_note=f"{row['name']} priced {row['position']['difference_pct']}% vs the market median.",
            analyzed_note=f"{stats['count']} comparable Channel3 listings, median {stats['median']}.",
        )

    async def _polish(self, rows: list[MerchantRecommendation], *, trace: Any = None) -> bool:
        """Optional LLM rewrite of the description prose - facts in, prose out, numbers untouched."""
        if not rows or not llm_service.enabled:
            return False
        facts = [{"key": r.reference, "title": r.title, "description": r.description,
                  "evidence": r.evidence, "action": r.recommended_action} for r in rows]
        polished, result = await llm_service.structured(
            system=("You rewrite recommendation descriptions for a small-business owner in 2-3 clear sentences. "
                    "Use only the facts given; keep every number exactly as written; never add a statistic. "
                    "Return items as [{key, description}]."),
            user=str(facts), schema=_Polished, fallback=_Polished(), trace=trace,
            trace_name="supply_recommendation_narrative", max_tokens=1200,
        )
        if result.used_fallback:
            return False
        by_key = {i.get("key"): i.get("description", "") for i in polished.items}
        for row in rows:
            text = (by_key.get(row.reference) or "").strip()
            if 40 <= len(text) <= 900:
                row.description = text
                row.narrative_source = "llm"
        return True

    # ================================================================== alternatives
    async def alternatives(self, product_id: uuid.UUID, *, limit: int = 8) -> dict[str, Any]:
        """A merchant product -> its closest Channel3 equivalent -> similar products, compared to both."""
        product = (await self.session.execute(
            select(Product).where(Product.id == product_id, Product.merchant_id == self.merchant_id)
        )).scalars().first()
        if product is None:
            raise NotFoundError("Product not found.")
        price = Decimal(str(product.price))
        discovery = ProductDiscoveryService(self.session, self.merchant_id, user_id=self.user_id, agent_run_id=self.agent_run_id)
        channel3_id = (product.attributes or {}).get("channel3_product_id")
        if channel3_id:
            equivalent = await discovery._fetch(channel3_id)
        else:
            query = " ".join(product.name.replace("(", " ").replace(")", " ").split())
            _throttle(self.merchant_id)
            page = await self.catalog.search(query, filters=build_filters(min_price=price * Decimal("0.3"), max_price=price * 4),
                                             limit=5, user_id=attribution_id(self.merchant_id))
            if not page.products:
                return {"product": self._merchant_product(product), "equivalent": None, "alternatives": [],
                        "note": "Channel3 found no listing comparable to this product."}
            equivalent = page.products[0]
        similar = await discovery.similar(equivalent.id, limit=limit, source_product=equivalent, source=SearchSource.ALTERNATIVES)
        alternatives = []
        for item in similar["products"]:
            item_price = Decimal(item["price"]) if item.get("price") else None
            diff = _q(item_price - price) if item_price is not None else None
            alternatives.append({**item, "vs_your_price": {
                "difference": str(diff) if diff is not None else None,
                "difference_pct": str(_q(diff / price * 100)) if diff is not None and price else None,
            }})
        return {
            "product": self._merchant_product(product),
            "equivalent": {**equivalent.as_dict(), "match_note": "Closest Channel3 listing to your product, by name search."},
            "alternatives": alternatives,
            "fallback_used": similar.get("fallback_used", False),
            "note": "Prices are retail listings - compare them with your selling price, not your cost.",
        }

    @staticmethod
    def _merchant_product(product: Product) -> dict[str, Any]:
        return {"id": str(product.id), "name": product.name, "sku": product.sku, "category": product.category,
                "price": str(_q(Decimal(str(product.price)))), "cost_price": str(_q(Decimal(str(product.cost_price or 0)))),
                "image_url": product.image_url}

    async def save_alternative(self, product_id: uuid.UUID, channel3_product_id: str, *, note: str = "") -> dict[str, Any]:
        product = (await self.session.execute(
            select(Product).where(Product.id == product_id, Product.merchant_id == self.merchant_id)
        )).scalars().first()
        if product is None:
            raise NotFoundError("Product not found.")
        discovery = ProductDiscoveryService(self.session, self.merchant_id, user_id=self.user_id)
        alt = await discovery._fetch(channel3_product_id)
        price = _q(Decimal(str(product.price)))
        alt_price = alt.best_offer.price if alt.best_offer else None
        evidence = [{"label": "Your product", "value": f"{product.name} at {price}", "source": "Your catalog"},
                    {"label": "Alternative", "value": f"{alt.title} at {alt_price}" if alt_price else alt.title, "source": "Channel3"},
                    {"label": "Retailers", "value": ", ".join(alt.retailers[:4]) or "-", "source": "Channel3"},
                    {"label": "Availability", "value": "In stock" if alt.in_stock else "Not confirmed", "source": "Channel3"}]
        fields = {
            "kind": RecommendationKind.PRODUCT_ALTERNATIVE,
            "title": f"Consider {alt.title[:120]} as an alternative to {product.name}",
            "description": note or f"{alt.brand or 'A different brand'} listing in {alt.category_title or 'the same space'}, "
                                   f"saved by {self.actor_label} for review.",
            "evidence": evidence,
            "recommended_action": f"Trial {alt.title[:120]} alongside {product.name} and compare sell-through.",
            "expected_impact": {"metric": "assortment_coverage", "value": None, "is_estimate": True,
                                "assumptions": ["Impact depends on customer uptake; measured after execution."]},
            "confidence": Decimal("0.500"),
            "confidence_reasons": ["Saved manually from a Channel3 alternatives search"],
            "anchor_product_id": product.id,
            "anchor_product_name": product.name[:160],
            "category": alt.category_title[:120],
            "products": [_snapshot(alt.as_dict())],
            "suggested_test_quantity": None,
            "suggested_retail_price": alt_price,
            "currency": alt.currency,
            "narrative_source": "deterministic",
        }
        row = await self._upsert(f"ALTERNATIVE:{product.id}:{alt.id}", fields,
                                 detected_note=f"Alternative to {product.name} requested by {self.actor_label}.",
                                 analyzed_note=f"Channel3 product {alt.id} fetched fresh.")
        if row is None:
            raise ConflictError("This alternative was decided recently.")
        return recommendation_out(row)

    # ================================================================== decisions
    async def decide(self, rec_id: uuid.UUID, *, approve: bool, note: str = "") -> dict[str, Any]:
        if self.user_id is None:
            raise BadRequestError("Only a signed-in person can approve or reject a recommendation.")
        row = await self.get(rec_id)
        if row.status not in RecommendationStatus.OPEN:
            raise ConflictError(f"{row.reference} is {row.status.lower()} and cannot be decided again.")
        row.status = RecommendationStatus.APPROVED if approve else RecommendationStatus.REJECTED
        row.decided_by_id, row.decided_by_label = self.user_id, self.actor_label[:160]
        row.decided_at, row.decision_note = _now(), note[:1000]
        row.lifecycle = [*(row.lifecycle or []), _stage(row.status, note or ("Approved" if approve else "Rejected"), self.actor_label)]
        await self.session.flush()
        await self.audit.record(
            action=AuditAction.RECOMMENDATION_APPROVED if approve else AuditAction.RECOMMENDATION_REJECTED,
            merchant_id=self.merchant_id, actor_id=self.user_id, actor_label=self.actor_label,
            resource="merchant_recommendation", resource_id=str(row.id), request_id=self.request_id,
            description=f"{row.reference} {'approved' if approve else 'rejected'}: {row.title}",
            metadata={"note": note, "kind": row.kind},
        )
        agent_memory.record_approval(merchant_id=self.merchant_id, merchant_name=self.merchant_name or "the merchant",
                                     opportunity=row.title, approved=approve, decided_by=self.actor_label, note=note)
        return recommendation_out(row)

    async def execute(self, rec_id: uuid.UUID, *, retail_price: Decimal | None = None) -> dict[str, Any]:
        """Run the permitted, non-financial action of an approved recommendation."""
        if self.user_id is None:
            raise BadRequestError("Only a signed-in person can execute a recommendation.")
        row = await self.get(rec_id)
        if row.status != RecommendationStatus.APPROVED:
            raise ConflictError(f"{row.reference} is {row.status.lower()} - only an approved recommendation can be executed.")
        execution = dict(row.execution or {})
        if row.kind == RecommendationKind.PRICING_OPPORTUNITY:
            product = await self._own_product(row.anchor_product_id)
            new_price = _q(Decimal(str(retail_price or row.suggested_retail_price)))
            if new_price <= 0:
                raise BadRequestError("The new price must be positive.")
            execution.update(action="PRICE_TEST", product_id=str(product.id), old_price=str(_q(Decimal(str(product.price)))),
                             new_price=str(new_price))
            product.price = new_price
            note = f"Price of {product.name} changed {execution['old_price']} -> {new_price} (2-week test)."
        else:
            snap = (row.products or [{}])[0]
            if not snap.get("id"):
                raise ConflictError("This recommendation has no product to add.")
            existing = next((p for p in (await self.session.execute(
                select(Product).where(Product.merchant_id == self.merchant_id))).scalars().all()
                if (p.attributes or {}).get("channel3_product_id") == snap["id"]), None)
            price = _q(Decimal(str(retail_price or row.suggested_retail_price or snap.get("price") or 0)))
            if price <= 0:
                raise BadRequestError("Set a retail price for the new product.")
            if existing is None:
                existing = Product(
                    merchant_id=self.merchant_id, sku=f"C3-{snap['id']}"[:64], name=str(snap.get("title") or "New product")[:160],
                    category="retail", description=f"Added from Channel3 by {row.reference}.", price=price, cost_price=0,
                    is_active=True, tags=["channel3", "test-assortment"], image_url=snap.get("image_url") or None,
                    attributes={"source": "channel3", "channel3_product_id": snap["id"], "recommendation_id": str(row.id),
                                "channel": "online_store", "brand": snap.get("brand")},
                )
                self.session.add(existing)
                await self.session.flush()
            execution.update(action="ADDED_TO_CATALOG", catalog_product_id=str(existing.id), sku=existing.sku,
                             retail_price=str(price))
            note = f"{existing.name} added to your catalog at {price} ({existing.sku})."
        row.execution = execution
        row.status = RecommendationStatus.EXECUTED
        row.executed_at = _now()
        row.lifecycle = [*(row.lifecycle or []), _stage(RecommendationStatus.EXECUTED, note, self.actor_label)]
        await self.session.flush()
        await self.audit.record(
            action=AuditAction.RECOMMENDATION_EXECUTED, merchant_id=self.merchant_id, actor_id=self.user_id,
            actor_label=self.actor_label, resource="merchant_recommendation", resource_id=str(row.id),
            request_id=self.request_id, description=f"{row.reference} executed: {note}", metadata=execution,
        )
        return recommendation_out(row)

    async def _own_product(self, product_id: uuid.UUID | None) -> Product:
        product = (await self.session.execute(
            select(Product).where(Product.id == product_id, Product.merchant_id == self.merchant_id)
        )).scalars().first() if product_id else None
        if product is None:
            raise NotFoundError("The product this recommendation is about no longer exists.")
        return product

    # ================================================================== payments
    async def request_payment(self, rec_id: uuid.UUID, *, quantity: int, unit_cost: Decimal, payee_email: str,
                              currency: str | None = None, requested_by_agent: bool = False) -> ApprovalRequest:
        """Raise a MERCHANT_PURCHASE approval. Nothing is paid until a human approves and executes it."""
        row = await self.get(rec_id)
        if row.kind not in (RecommendationKind.ASSORTMENT_EXPANSION, RecommendationKind.PRODUCT_ALTERNATIVE):
            raise BadRequestError("Only product recommendations can lead to a stock purchase.")
        if row.status not in (RecommendationStatus.APPROVED, RecommendationStatus.EXECUTED, RecommendationStatus.MEASURED):
            raise ConflictError(f"Approve {row.reference} before requesting a purchase.")
        if not 1 <= int(quantity) <= 10_000:
            raise BadRequestError("Quantity must be between 1 and 10,000.")
        unit = Decimal(str(unit_cost))
        if unit <= 0 or unit > Decimal("100000"):
            raise BadRequestError("Enter the supplier's unit cost (greater than zero).")
        if "@" not in payee_email or len(payee_email) > 255:
            raise BadRequestError("Enter the supplier's PayPal email address.")
        details = purchase_details(row, quantity=quantity, unit_cost=unit, payee_email=payee_email,
                                   currency=(currency or row.currency or "USD").upper()[:3])
        total = Decimal(details["total"])
        flags = []
        if row.suggested_test_quantity and quantity > row.suggested_test_quantity * 2:
            flags.append(f"Quantity is more than twice the suggested test batch ({row.suggested_test_quantity}).")
        if row.suggested_retail_price and unit >= Decimal(str(row.suggested_retail_price)):
            flags.append("Unit cost is at or above the retail reference price - there would be no margin.")
        approval = await ApprovalService(self.session, self.merchant_id).request(
            action=ApprovalAction.MERCHANT_PURCHASE, resource_type="merchant_recommendation", resource_id=row.id,
            title=f"Buy {quantity} x {details['product_title'] or row.title}"[:255],
            summary=(f"Test stock for {row.reference} ({row.title}). Pay {details['payee_email']} "
                     f"{details['currency']} {total:,.2f} through PayPal Orders v2 after approval."),
            amount=total, currency=details["currency"], details=details, policy_version=PURCHASE_POLICY_VERSION,
            required_permission=str(Permission.PAYMENT_APPROVE), risk_flags=flags,
            requested_by_type=ActorType.AGENT if requested_by_agent else ActorType.USER,
            requested_by_id=self.user_id, requested_by_label=AGENT_LABEL if requested_by_agent else self.actor_label,
            correlation_id=row.reference,
        )
        row.execution = {**(row.execution or {}), "purchase_approval_id": str(approval.id),
                         "purchase_approval_reference": approval.reference}
        row.lifecycle = [*(row.lifecycle or []), _stage(row.status, f"Purchase approval {approval.reference} requested "
                                                                    f"({details['currency']} {total:,.2f}).", self.actor_label)]
        await self.session.flush()
        return approval

    # ================================================================== measure
    async def measure(self, rec_id: uuid.UUID) -> dict[str, Any]:
        row = await self.get(rec_id)
        if row.status not in (RecommendationStatus.EXECUTED, RecommendationStatus.MEASURED):
            raise ConflictError(f"{row.reference} has not been executed yet - there is nothing to measure.")
        executed = row.executed_at if row.executed_at and row.executed_at.tzinfo else (row.executed_at or _now()).replace(tzinfo=UTC)
        days = max(1, (_now() - executed).days + 1)
        result: dict[str, Any] = {"measured_at": _now().isoformat(), "days_since_execution": days}
        execution = row.execution or {}
        product_id = execution.get("catalog_product_id") or execution.get("product_id")
        since = executed.date()
        if product_id:
            pid = uuid.UUID(product_id)
            units, revenue, orders = await self._sales(pid, since, None)
            result.update(units_sold=units, revenue=str(_q(Decimal(str(revenue)))), orders=orders)
            if row.kind == RecommendationKind.PRICING_OPPORTUNITY:
                before_units, before_revenue, _ = await self._sales(pid, since - timedelta(days=days), since - timedelta(days=1))
                result.update(baseline_units=before_units, baseline_revenue=str(_q(Decimal(str(before_revenue)))),
                              baseline_window_days=days)
        expected = (row.expected_impact or {}).get("value")
        if expected and row.kind != RecommendationKind.PRICING_OPPORTUNITY:
            to_date = _q(Decimal(str(expected)) * Decimal(min(days, 30)) / Decimal(30))
            result["expected_revenue_to_date"] = str(to_date)
            if to_date > 0 and "revenue" in result:
                result["attainment_pct"] = str(_q(Decimal(result["revenue"]) / to_date * 100))
        exec_id = execution.get("purchase_execution_id")
        if exec_id:
            payment = await self.session.get(FinancialExecution, uuid.UUID(exec_id))
            if payment is not None and payment.merchant_id == self.merchant_id:
                result["payment"] = {"status": payment.status, "amount": str(payment.amount), "currency": payment.currency,
                                     "mode": payment.mode, "paypal_order_id": payment.paypal_order_id,
                                     "paypal_capture_id": payment.paypal_capture_id}
        if not product_id:
            verdict = "Executed, but no catalog product is linked yet - nothing to measure."
        elif result.get("units_sold", 0) == 0:
            verdict = f"No sales recorded in the {days} day(s) since execution."
        elif row.kind == RecommendationKind.PRICING_OPPORTUNITY:
            delta = Decimal(result["revenue"]) - Decimal(result["baseline_revenue"])
            verdict = (f"Revenue {'up' if delta >= 0 else 'down'} {abs(delta):,.2f} vs the {days} day(s) before the test "
                       f"({result['units_sold']} units vs {result['baseline_units']}).")
        else:
            verdict = (f"{result['units_sold']} units sold, revenue {result['revenue']} in {days} day(s)"
                       + (f" - {result['attainment_pct']}% of the estimate to date." if result.get("attainment_pct") else "."))
        result["verdict"] = verdict
        row.measurement = result
        row.measured_at = _now()
        row.status = RecommendationStatus.MEASURED
        row.lifecycle = [*(row.lifecycle or []), _stage(RecommendationStatus.MEASURED, verdict, "Measurement Agent")]
        await self.session.flush()
        await self.audit.record(
            action=AuditAction.RECOMMENDATION_MEASURED, merchant_id=self.merchant_id, actor_id=self.user_id,
            actor_label=self.actor_label, resource="merchant_recommendation", resource_id=str(row.id),
            request_id=self.request_id, description=f"{row.reference} measured: {verdict}"[:500],
        )
        return recommendation_out(row)

    async def _sales(self, product_id: uuid.UUID, start, end) -> tuple[float, float, int]:  # type: ignore[no-untyped-def]
        conditions = [TransactionItem.merchant_id == self.merchant_id, TransactionItem.product_id == product_id,
                      Transaction.business_date >= start]
        if end is not None:
            conditions.append(Transaction.business_date <= end)
        units, revenue, orders = (await self.session.execute(
            select(func.coalesce(func.sum(TransactionItem.quantity), 0), func.coalesce(func.sum(TransactionItem.line_total), 0),
                   func.count(distinct(TransactionItem.transaction_id)))
            .join(Transaction, Transaction.id == TransactionItem.transaction_id).where(*conditions)
        )).one()
        return float(units or 0), float(revenue or 0), int(orders or 0)

    # ================================================================== hooks
    async def on_payment_captured(self, rec_id: uuid.UUID, execution: FinancialExecution) -> None:
        """Called by the payment service and the webhook handler - idempotent."""
        row = (await self.session.execute(
            select(MerchantRecommendation).where(MerchantRecommendation.id == rec_id)
        )).scalars().first()
        if row is None:
            return
        info = dict(row.execution or {})
        if info.get("purchase_capture_id") == execution.paypal_capture_id and execution.paypal_capture_id:
            return
        info.update(purchase_execution_id=str(execution.id), purchase_status=execution.status,
                    purchase_capture_id=execution.paypal_capture_id, purchase_mode=execution.mode,
                    purchase_amount=str(execution.amount), purchase_currency=execution.currency)
        row.execution = info
        note = (f"PayPal capture {execution.paypal_capture_id} for {execution.currency} {Decimal(str(execution.amount)):,.2f} "
                f"({execution.mode}).")
        if row.status == RecommendationStatus.APPROVED:
            row.status = RecommendationStatus.EXECUTED
            row.executed_at = _now()
            row.lifecycle = [*(row.lifecycle or []), _stage(RecommendationStatus.EXECUTED, "Test stock paid. " + note, "PayPal")]
        else:
            row.lifecycle = [*(row.lifecycle or []), _stage(row.status, "Test stock paid. " + note, "PayPal")]
        await self.session.flush()


async def open_purchase_approval(session: AsyncSession, approval: ApprovalRequest) -> MerchantRecommendation:
    rec = (await session.execute(
        select(MerchantRecommendation).where(MerchantRecommendation.id == approval.resource_id,
                                             MerchantRecommendation.merchant_id == approval.merchant_id)
    )).scalars().first()
    if rec is None or rec.status in (RecommendationStatus.REJECTED, RecommendationStatus.SUPERSEDED):
        raise ConflictError("The recommendation behind this purchase was rejected or replaced - the approval no longer applies.")
    return rec


def live_purchase_details(rec: MerchantRecommendation, approval: ApprovalRequest) -> dict[str, Any]:
    """Recompute the bound terms from live state + the inputs the approval recorded."""
    d = approval.details or {}
    return purchase_details(rec, quantity=int(d.get("quantity") or 0), unit_cost=Decimal(str(d.get("unit_cost") or "0")),
                            payee_email=str(d.get("payee_email") or ""), currency=str(d.get("currency") or "USD"))


__all__ = [
    "PURCHASE_POLICY_VERSION",
    "RecommendationService",
    "live_purchase_details",
    "open_purchase_approval",
    "purchase_details",
    "recommendation_out",
]

