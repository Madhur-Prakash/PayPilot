"""Agent tools for Product Discovery, Supply Intelligence, pricing and merchant payments.

Same contract as every tool: typed arguments, a permission check against the human the
agent works for, merchant scope, logging, tracing and a recorded call. Channel3 data is
fetched live; without ``CHANNEL3_API_KEY`` the tools fail with a clear configuration
error rather than inventing products.

``request_purchase_payment`` is the only tool that touches money, and it cannot move
any: it raises a ``MERCHANT_PURCHASE`` approval request for a human to decide. Creating
and capturing the PayPal order happen only through authenticated endpoints that require
``payment:execute``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.core.exceptions import AppError, BadRequestError, IntegrationError, ServiceUnavailableError
from app.core.permissions import Permission
from app.integrations.sponsors.base import SponsorError, SponsorRequestError
from app.services.discovery.service import ProductDiscoveryService
from app.services.paypal.orders import MerchantPaymentService
from app.services.supply_intel.analysis import AssortmentAnalyzer
from app.services.supply_intel.pricing import PricingIntelligence
from app.services.supply_intel.recommendations import RecommendationService
from app.tools.base import ToolContext, registry


def _sponsor(exc: SponsorError) -> AppError:
    if isinstance(exc, SponsorRequestError):
        return BadRequestError(str(exc))
    if exc.status_code == 503:
        return ServiceUnavailableError(str(exc))
    return IntegrationError(str(exc))


def _run_id(ctx: ToolContext) -> uuid.UUID | None:
    return ctx.run.id if ctx.run is not None else None


def _card(product: dict[str, Any]) -> dict[str, Any]:
    """The compact product shape handed to a model and stored in the trace."""
    ranking = product.get("ranking") or {}
    return {
        "id": product.get("id"), "title": product.get("title"), "brand": product.get("brand"),
        "price": product.get("price"), "currency": product.get("currency"), "retailer": product.get("retailer"),
        "in_stock": product.get("in_stock"), "image_url": product.get("image_url"), "url": product.get("url"),
        "category": (product.get("category") or {}).get("title"), "score": ranking.get("score"),
        "reasons": (ranking.get("reasons") or (product.get("similarity") or {}).get("reasons") or [])[:4],
        "ratings": product.get("ratings"),
    }


class DiscoverArgs(BaseModel):
    query: str = Field(min_length=2, max_length=300, description="What the merchant is looking for, in their words "
                       "(budget, brand, use case included), e.g. 'wireless earbuds under $80 for students'.")
    max_results: int = Field(default=8, ge=1, le=20)


class ProductIdArgs(BaseModel):
    product_id: str = Field(min_length=1, max_length=64, description="A Channel3 product id from a previous search.")


class SimilarArgs(ProductIdArgs):
    limit: int = Field(default=6, ge=1, le=12)
    max_price: float | None = Field(default=None, gt=0, description="Only alternatives at or below this price.")


class CompareArgs(BaseModel):
    product_ids: list[str] = Field(min_length=2, max_length=4, description="2-4 Channel3 product ids.")
    features: list[str] = Field(default_factory=list, description="Features that matter, e.g. ['noise cancelling'].")


class DaysArgs(BaseModel):
    days: int = Field(default=30, ge=7, le=120)


class PricingArgs(BaseModel):
    limit: int = Field(default=2, ge=1, le=4, description="How many retail products to price-check.")


class GenerateArgs(BaseModel):
    days: int = Field(default=30, ge=7, le=120)
    max_recommendations: int = Field(default=4, ge=1, le=6)


class ListRecsArgs(BaseModel):
    status: str | None = Field(default=None, description="DETECTED, ANALYZED, RECOMMENDED, APPROVED, EXECUTED, MEASURED, REJECTED")


class PaymentsArgs(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)


class PurchaseRequestArgs(BaseModel):
    recommendation_id: uuid.UUID
    quantity: int = Field(ge=1, le=10000)
    unit_cost: float = Field(gt=0, description="The supplier's unit cost - not a retail price.")
    payee_email: str = Field(min_length=3, max_length=255, description="The supplier's PayPal email.")


@registry.register(
    "discover_products",
    description="Search Channel3's live catalog from a natural-language request. Extracts budget, brand, category "
    "and use case, converts it to a Channel3 search, and returns ranked products with images, prices, retailers "
    "and the reasons for each score.",
    args_model=DiscoverArgs,
    permission=Permission.PRODUCTS_READ,
)
async def discover_products(ctx: ToolContext, args: DiscoverArgs) -> tuple[dict[str, Any], str]:
    try:
        result = await ProductDiscoveryService(ctx.session, ctx.merchant_id, user_id=ctx.user_id,
                                               agent_run_id=_run_id(ctx)).search(
            args.query, limit=args.max_results, source="agent", trace=ctx.trace)
    except SponsorError as exc:
        raise _sponsor(exc) from exc
    cards = [_card(p) for p in result["products"]]
    data = {"search_id": result["search_id"], "intent": result["intent"], "applied_filters": result["applied_filters"],
            "budget": result["budget"], "notes": result["notes"], "products": cards}
    top = cards[0] if cards else None
    summary = (f"{len(cards)} live Channel3 products for '{args.query}'"
               + (f"; top: {top['title']} ({top['currency']} {top['price']} at {top['retailer']})." if top else "."))
    return data, summary


@registry.register(
    "get_product_details",
    description="Fresh Channel3 details for one product: offers per retailer, variants, specifications, availability.",
    args_model=ProductIdArgs,
    permission=Permission.PRODUCTS_READ,
)
async def get_product_details(ctx: ToolContext, args: ProductIdArgs) -> tuple[dict[str, Any], str]:
    try:
        result = await ProductDiscoveryService(ctx.session, ctx.merchant_id, user_id=ctx.user_id,
                                               agent_run_id=_run_id(ctx)).product(args.product_id, with_similar=False)
    except SponsorError as exc:
        raise _sponsor(exc) from exc
    p = result["product"]
    return {"product": {**_card(p), "offers": p["offers"][:6], "key_features": p["key_features"][:8],
                        "structured_attributes": p["structured_attributes"], "variants": p["variants"]}}, \
        f"{p['title']}: {p['offers_count']} offers from {p['currency']} {p['min_price']}."


@registry.register(
    "find_similar_products",
    description="Channel3 'more like this' for a product id, with why each is similar and the price difference.",
    args_model=SimilarArgs,
    permission=Permission.PRODUCTS_READ,
)
async def find_similar_products(ctx: ToolContext, args: SimilarArgs) -> tuple[dict[str, Any], str]:
    try:
        result = await ProductDiscoveryService(ctx.session, ctx.merchant_id, user_id=ctx.user_id,
                                               agent_run_id=_run_id(ctx)).similar(args.product_id, limit=args.limit,
                                                                                  max_price=args.max_price)
    except SponsorError as exc:
        raise _sponsor(exc) from exc
    cards = [{**_card(p), "price_difference": p["similarity"]["price_difference"]} for p in result["products"]]
    return {"source": _card(result["source"]), "products": cards, "note": result.get("note")}, \
        f"{len(cards)} alternatives to {result['source']['title']}."


@registry.register(
    "compare_products",
    description="Side-by-side comparison of 2-4 Channel3 products: better value, more suitable specifications, fit "
    "for the merchant's customers and the best alternative - each with evidence. Missing specs stay 'not listed'.",
    args_model=CompareArgs,
    permission=Permission.PRODUCTS_READ,
)
async def compare_products(ctx: ToolContext, args: CompareArgs) -> tuple[dict[str, Any], str]:
    try:
        result = await ProductDiscoveryService(ctx.session, ctx.merchant_id, user_id=ctx.user_id,
                                               agent_run_id=_run_id(ctx)).compare(args.product_ids, wanted=args.features,
                                                                                  trace=ctx.trace)
    except SponsorError as exc:
        raise _sponsor(exc) from exc
    verdicts = {k: {"product_id": v.get("product_id"), "title": v.get("title"), "reason": v.get("reason")}
                for k, v in result["verdicts"].items() if v}
    return {"comparison_id": result["comparison_id"], "verdicts": verdicts, "overall": result["overall"],
            "narrative": result["narrative"], "products": [_card(p) for p in result["products"]]}, result["narrative"][:400]


@registry.register(
    "analyze_assortment",
    description="The merchant's assortment from their own sales and inventory: category performance and growth, "
    "top and growing products, basket pairs, inventory turnover, and complementary expansion candidates.",
    args_model=DaysArgs,
    permission=Permission.PRODUCTS_READ,
)
async def analyze_assortment(ctx: ToolContext, args: DaysArgs) -> tuple[dict[str, Any], str]:
    analysis = await AssortmentAnalyzer(ctx.session, ctx.merchant_id).analyze(days=args.days)
    if not analysis.get("has_data"):
        return analysis, analysis.get("note", "No sales data.")
    data = {k: analysis[k] for k in ("window", "summary", "categories", "growing_products", "data_quality")}
    data["top_products"] = analysis["top_products"][:6]
    data["inventory"] = analysis["inventory"][:6]
    data["expansion_candidates"] = [{"key": c["key"], "anchor": c["anchor"]["name"], "slot": c["slot"]["label"],
                                     "query": c["slot"]["query"], "rationale": c["rationale"], "score": c["score"]}
                                    for c in analysis["expansion_candidates"][:6]]
    top = analysis["top_products"][0] if analysis["top_products"] else None
    best = analysis["expansion_candidates"][0] if analysis["expansion_candidates"] else None
    return data, (f"{analysis['summary']['orders']} orders, {len(analysis['categories'])} categories"
                  + (f"; best seller {top['name']}" if top else "")
                  + (f"; top expansion: {best['slot']['label']} next to {best['anchor']['name']}." if best else "."))


@registry.register(
    "get_market_price_intelligence",
    description="Compare the merchant's retail selling prices with comparable live Channel3 listings (median, range, "
    "gap, suggested price test). Retail prices only - never a procurement cost or limit.",
    args_model=PricingArgs,
    permission=Permission.PRODUCTS_READ,
)
async def get_market_price_intelligence(ctx: ToolContext, args: PricingArgs) -> tuple[dict[str, Any], str]:
    try:
        result = await PricingIntelligence(ctx.session, ctx.merchant_id, user_id=ctx.user_id,
                                           agent_run_id=_run_id(ctx)).analyze(limit=args.limit)
    except SponsorError as exc:
        raise _sponsor(exc) from exc
    lines = []
    for row in result["products"]:
        if row.get("stats"):
            lines.append(f"{row['name']} {row['merchant_price']} vs median {row['stats']['median']} of "
                         f"{row['stats']['count']} listings ({row['position']['difference_pct']}%, verdict: "
                         f"{row['position']['verdict']})")
        elif row.get("note"):
            lines.append(f"{row['name']}: {row['note']}")
    for row in result["products"]:
        row["comparables"] = row["comparables"][:5]
    return result, ("; ".join(lines) or "No consistent market prices found.")


@registry.register(
    "generate_supply_recommendations",
    description="Run Supply Intelligence: analyse sales and inventory, search Channel3 for complementary products and "
    "market prices, and store explainable recommendations (evidence, estimated impact, confidence) that wait for a "
    "human approval.",
    args_model=GenerateArgs,
    permission=Permission.GROWTH_RECOMMEND,
)
async def generate_supply_recommendations(ctx: ToolContext, args: GenerateArgs) -> tuple[dict[str, Any], str]:
    try:
        result = await RecommendationService(ctx.session, ctx.merchant_id, user_id=ctx.user_id,
                                             merchant_name=ctx.merchant_name, agent_run_id=_run_id(ctx)).generate(
            days=args.days, max_recommendations=args.max_recommendations, trace=ctx.trace)
    except SponsorError as exc:
        raise _sponsor(exc) from exc
    recs = [{"id": r["id"], "reference": r["reference"], "kind": r["kind"], "title": r["title"],
             "expected_impact": r["expected_impact"].get("value"), "confidence": r["confidence"], "status": r["status"]}
            for r in result["recommendations"]]
    return {"recommendations": recs, "notes": result["notes"], "analysis": result.get("analysis", {}).get("summary")}, \
        f"{len(recs)} recommendation(s) ready for approval" + (f": {recs[0]['title']}." if recs else ".")


@registry.register(
    "list_supply_recommendations",
    description="Supply Intelligence recommendations and where each is in its lifecycle.",
    args_model=ListRecsArgs,
    permission=Permission.GROWTH_READ,
)
async def list_supply_recommendations(ctx: ToolContext, args: ListRecsArgs) -> tuple[dict[str, Any], str]:
    items, counts = await RecommendationService(ctx.session, ctx.merchant_id).list(status=args.status, limit=20)
    compact = [{"id": r["id"], "reference": r["reference"], "title": r["title"], "status": r["status"],
                "kind": r["kind"], "expected_impact": r["expected_impact"].get("value"), "confidence": r["confidence"]}
               for r in items]
    return {"recommendations": compact, "counts": counts}, f"{len(compact)} recommendation(s); {counts}."


@registry.register(
    "get_payment_history",
    description="PayPal payment executions (orders, captures, payouts), their status and mode, plus open approvals.",
    args_model=PaymentsArgs,
    permission=Permission.PAYPAL_READ,
)
async def get_payment_history(ctx: ToolContext, args: PaymentsArgs) -> tuple[dict[str, Any], str]:
    data = await MerchantPaymentService(ctx.session, ctx.merchant_id, actor_id=ctx.user_id,
                                        actor_label="PayPal Transaction Agent").history(limit=args.limit)
    data["items"] = data["items"][: args.limit]
    stats = data["stats"]
    return data, (f"{stats['total']} payment(s): {stats['by_status']}; {len(data['approvals'])} approval(s) open; "
                  f"mode {data['mode']}.")


@registry.register(
    "request_purchase_payment",
    description="Ask a human to approve buying test stock for an APPROVED recommendation (PayPal Orders v2). This only "
    "creates an approval request - it never creates, approves or captures a payment.",
    args_model=PurchaseRequestArgs,
    permission=Permission.PROCUREMENT_CREATE,
    requires_approval=True,
)
async def request_purchase_payment(ctx: ToolContext, args: PurchaseRequestArgs) -> tuple[dict[str, Any], str]:
    approval = await RecommendationService(ctx.session, ctx.merchant_id, user_id=ctx.user_id,
                                           actor_label="PayPal Transaction Agent", agent_run_id=_run_id(ctx)).request_payment(
        args.recommendation_id, quantity=args.quantity, unit_cost=Decimal(str(args.unit_cost)),
        payee_email=args.payee_email, requested_by_agent=True)
    return {"approval_id": str(approval.id), "reference": approval.reference, "status": approval.status,
            "amount": str(approval.amount), "currency": approval.currency,
            "required_permission": approval.required_permission}, \
        (f"Approval {approval.reference} requested for {approval.currency} {approval.amount}. A person with "
         "payment:approve must decide it; nothing has been paid.")
