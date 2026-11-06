"""Supply Intelligence, Product Discovery and the Growth Autopilot.

Discovery reads Channel3's live catalog (``products:read``); generating recommendations
needs ``growth:recommend``; approving, rejecting and executing them needs
``procurement:approve``; requesting a test-stock purchase creates an approval that only
``payment:approve`` can decide. Every route is merchant-scoped by the authenticated
membership and never returns the Channel3 key.

Without ``CHANNEL3_API_KEY`` the Channel3-backed routes answer **503
CHANNEL3_NOT_CONFIGURED** with setup steps - they never substitute invented products.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy import select

from app.agents.merchant_os import MerchantOS
from app.api.deps import DbSession, Principal, require_permission
from app.core.exceptions import (
    AppError,
    BadRequestError,
    IntegrationError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    ValidationError,
)
from app.core.permissions import Permission
from app.db.models.agent import AgentRun, AgentWorkflow
from app.db.models.commerce import Product
from app.integrations.sponsors.base import SponsorError, SponsorRequestError
from app.integrations.sponsors.channel3_catalog import SETUP_HINT
from app.schemas.common import APIResponse, SchemaBase
from app.services.discovery.conversation import ShoppingAssistant, conversation_out
from app.services.discovery.service import ProductDiscoveryService
from app.services.supply.approvals import describe_approval
from app.services.supply_intel.analysis import AssortmentAnalyzer
from app.services.supply_intel.overview import supply_overview
from app.services.supply_intel.pricing import PricingIntelligence
from app.services.supply_intel.recommendations import RecommendationService

router = APIRouter(tags=["supply-intelligence"])


def channel3_error(exc: SponsorError) -> AppError:
    """Map a Channel3 failure onto the right HTTP status, with a message safe to show."""
    if isinstance(exc, SponsorRequestError):
        return BadRequestError(str(exc))
    status = exc.status_code or 502
    if status == 503:
        return ServiceUnavailableError(str(exc), code="CHANNEL3_NOT_CONFIGURED", details={"setup": SETUP_HINT})
    if status == 404:
        return NotFoundError(str(exc))
    if status == 422:
        return ValidationError(str(exc))
    if status == 429:
        return RateLimitError(str(exc))
    return IntegrationError(str(exc), details={"upstream_status": status})


def _discovery(session: Any, principal: Principal) -> ProductDiscoveryService:
    return ProductDiscoveryService(session, principal.merchant_id, user_id=principal.user_id)


def _recs(session: Any, principal: Principal) -> RecommendationService:
    return RecommendationService(session, principal.merchant_id, user_id=principal.user_id, actor_label=principal.label,
                                 merchant_name=principal.merchant.name, request_id=principal.request_id)


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class SearchRequest(SchemaBase):
    query: str = Field(min_length=2, max_length=500, description="Natural language, e.g. 'office chairs under ₹15,000'.")
    min_price: float | None = Field(default=None, gt=0, le=1_000_000)
    max_price: float | None = Field(default=None, gt=0, le=1_000_000)
    brands: list[str] = Field(default_factory=list, max_length=5)
    category: str | None = Field(default=None, max_length=80, pattern=r"^[a-z0-9-]+$", description="A Channel3 category slug.")
    retailers: list[str] = Field(default_factory=list, max_length=5)
    include_out_of_stock: bool | None = None
    on_sale: bool | None = None
    limit: int = Field(default=12, ge=1, le=30)
    page_token: str | None = Field(default=None, max_length=500)
    mode: str = Field(default="default", pattern="^(default|agentic)$")


class CompareRequest(SchemaBase):
    product_ids: list[str] = Field(min_length=2, max_length=4)
    features: list[str] = Field(default_factory=list, max_length=8)


class SimilarRequest(SchemaBase):
    product_id: str = Field(min_length=1, max_length=64)
    limit: int = Field(default=12, ge=1, le=30)
    min_price: float | None = Field(default=None, gt=0)
    max_price: float | None = Field(default=None, gt=0)
    same_brand: bool | None = None


class EnrichRequest(SchemaBase):
    url: str = Field(min_length=10, max_length=2000)


class ShortlistRequest(SchemaBase):
    value: bool = True


class AssistantTurn(SchemaBase):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: uuid.UUID | None = None


class PricingRequest(SchemaBase):
    product_ids: list[uuid.UUID] = Field(default_factory=list, max_length=5)
    limit: int = Field(default=3, ge=1, le=5)


class AlternativesRequest(SchemaBase):
    product_id: uuid.UUID
    limit: int = Field(default=8, ge=1, le=20)


class SaveAlternativeRequest(SchemaBase):
    product_id: uuid.UUID
    channel3_product_id: str = Field(min_length=1, max_length=64)
    note: str = Field(default="", max_length=1000)


class GenerateRequest(SchemaBase):
    days: int = Field(default=30, ge=7, le=120)
    max_recommendations: int = Field(default=4, ge=1, le=6)
    include_pricing: bool = True


class DecisionRequest(SchemaBase):
    note: str = Field(default="", max_length=1000)


class ExecuteRequest(SchemaBase):
    retail_price: Decimal | None = Field(default=None, gt=0, le=Decimal("1000000"))


class PurchaseRequest(SchemaBase):
    quantity: int = Field(ge=1, le=10_000)
    unit_cost: Decimal = Field(gt=0, le=Decimal("100000"), description="The supplier's unit cost (not a retail price).")
    payee_email: str = Field(min_length=3, max_length=255, description="The supplier's PayPal email.")
    currency: str | None = Field(default=None, min_length=3, max_length=3)


class AutopilotRequest(SchemaBase):
    days: int = Field(default=30, ge=7, le=120)
    max_recommendations: int = Field(default=4, ge=1, le=6)


# --------------------------------------------------------------------------- #
# Product discovery
# --------------------------------------------------------------------------- #
@router.get("/supply/discovery/status", summary="Whether live Channel3 product discovery is configured")
async def discovery_status(
    session: DbSession, principal: Principal = Depends(require_permission(Permission.PRODUCTS_READ)),
) -> APIResponse[dict[str, Any]]:
    return APIResponse(data=_discovery(session, principal).status())


@router.post("/supply/search", summary="Natural-language product discovery (live Channel3 search, AI-ranked)")
async def search_products(
    body: SearchRequest, session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PRODUCTS_READ)),
) -> APIResponse[dict[str, Any]]:
    try:
        data = await _discovery(session, principal).search(
            body.query, min_price=body.min_price, max_price=body.max_price, brands=body.brands, category=body.category,
            retailers=body.retailers, include_out_of_stock=body.include_out_of_stock, on_sale=body.on_sale,
            limit=body.limit, page_token=body.page_token, mode=body.mode)
    except SponsorError as exc:
        await session.commit()  # keep the failed search in the history
        raise channel3_error(exc) from exc
    return APIResponse(data=data)


@router.post("/supply/compare", summary="Compare 2-4 products side by side with evidence-backed verdicts")
async def compare_products(
    body: CompareRequest, session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PRODUCTS_READ)),
) -> APIResponse[dict[str, Any]]:
    try:
        return APIResponse(data=await _discovery(session, principal).compare(body.product_ids, wanted=body.features))
    except SponsorError as exc:
        raise channel3_error(exc) from exc


@router.post("/supply/similar", summary="Similar products (Channel3 /v1/similar) with price differences")
async def similar_products(
    body: SimilarRequest, session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PRODUCTS_READ)),
) -> APIResponse[dict[str, Any]]:
    try:
        return APIResponse(data=await _discovery(session, principal).similar(
            body.product_id, limit=body.limit, min_price=body.min_price, max_price=body.max_price, same_brand=body.same_brand))
    except SponsorError as exc:
        raise channel3_error(exc) from exc


@router.post("/supply/enrich", summary="Structured product data from a product page URL (Channel3 /v1/lookup)")
async def enrich_product(
    body: EnrichRequest, session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PRODUCTS_READ)),
) -> APIResponse[dict[str, Any]]:
    try:
        return APIResponse(data=await _discovery(session, principal).enrich(body.url))
    except SponsorError as exc:
        await session.commit()
        raise channel3_error(exc) from exc


@router.get("/supply/products/{product_id}", summary="Product details (fresh from Channel3) and similar products")
async def product_details(
    product_id: str, session: DbSession, fresh: Annotated[bool, Query()] = False,
    principal: Principal = Depends(require_permission(Permission.PRODUCTS_READ)),
) -> APIResponse[dict[str, Any]]:
    try:
        return APIResponse(data=await _discovery(session, principal).product(product_id, fresh=fresh))
    except SponsorError as exc:
        raise channel3_error(exc) from exc


@router.post("/supply/products/{product_id}/shortlist", summary="Add or remove a product from the shortlist")
async def shortlist_product(
    product_id: str, body: ShortlistRequest, session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PRODUCTS_READ)),
) -> APIResponse[dict[str, Any]]:
    try:
        return APIResponse(data=await _discovery(session, principal).shortlist(product_id, value=body.value))
    except SponsorError as exc:
        raise channel3_error(exc) from exc


@router.get("/supply/searches", summary="Product search history")
async def search_history(
    session: DbSession, limit: Annotated[int, Query(ge=1, le=100)] = 30,
    principal: Principal = Depends(require_permission(Permission.PRODUCTS_READ)),
) -> APIResponse[list[dict[str, Any]]]:
    return APIResponse(data=await _discovery(session, principal).history(limit=limit))


@router.get("/supply/discovered", summary="Products discovered so far (snapshots; refreshed on view)")
async def discovered_products(
    session: DbSession, limit: Annotated[int, Query(ge=1, le=100)] = 24,
    shortlisted: Annotated[bool | None, Query()] = None,
    principal: Principal = Depends(require_permission(Permission.PRODUCTS_READ)),
) -> APIResponse[list[dict[str, Any]]]:
    return APIResponse(data=await _discovery(session, principal).discovered(limit=limit, shortlisted=shortlisted))


@router.get("/supply/comparisons", summary="Recent product comparisons")
async def comparisons(
    session: DbSession, principal: Principal = Depends(require_permission(Permission.PRODUCTS_READ)),
) -> APIResponse[list[dict[str, Any]]]:
    return APIResponse(data=await _discovery(session, principal).comparisons())


# --------------------------------------------------------------------------- #
# Conversational shopping agent
# --------------------------------------------------------------------------- #
@router.post("/supply/assistant", summary="One turn with the conversational shopping agent (Channel3 Conversations)")
async def assistant_turn(
    body: AssistantTurn, session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PRODUCTS_READ)),
) -> APIResponse[dict[str, Any]]:
    try:
        return APIResponse(data=await ShoppingAssistant(session, principal.merchant_id, user_id=principal.user_id).turn(
            body.message, conversation_id=body.conversation_id))
    except SponsorError as exc:
        raise channel3_error(exc) from exc


@router.get("/supply/assistant/conversations", summary="Shopping conversations")
async def assistant_conversations(
    session: DbSession, principal: Principal = Depends(require_permission(Permission.PRODUCTS_READ)),
) -> APIResponse[list[dict[str, Any]]]:
    return APIResponse(data=await ShoppingAssistant(session, principal.merchant_id).list())


@router.get("/supply/assistant/conversations/{conversation_id}", summary="One shopping conversation")
async def assistant_conversation(
    conversation_id: uuid.UUID, session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PRODUCTS_READ)),
) -> APIResponse[dict[str, Any]]:
    return APIResponse(data=conversation_out(await ShoppingAssistant(session, principal.merchant_id).get(conversation_id)))


# --------------------------------------------------------------------------- #
# Supply intelligence
# --------------------------------------------------------------------------- #
@router.get("/supply/intelligence", summary="Supply Intelligence dashboard (no Channel3 credits spent)")
async def intelligence_dashboard(
    session: DbSession, days: Annotated[int, Query(ge=7, le=120)] = 30,
    principal: Principal = Depends(require_permission(Permission.PRODUCTS_READ)),
) -> APIResponse[dict[str, Any]]:
    return APIResponse(data=await supply_overview(session, principal.merchant_id, days=days))


@router.get("/supply/assortment", summary="Assortment analysis from sales and inventory")
async def assortment(
    session: DbSession, days: Annotated[int, Query(ge=7, le=120)] = 30,
    principal: Principal = Depends(require_permission(Permission.PRODUCTS_READ)),
) -> APIResponse[dict[str, Any]]:
    return APIResponse(data=await AssortmentAnalyzer(session, principal.merchant_id).analyze(days=days))


@router.post("/supply/pricing", summary="Market price intelligence: your prices vs live retail listings")
async def market_pricing(
    body: PricingRequest, session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PRODUCTS_READ)),
) -> APIResponse[dict[str, Any]]:
    try:
        return APIResponse(data=await PricingIntelligence(session, principal.merchant_id, user_id=principal.user_id)
                           .analyze(product_ids=body.product_ids or None, limit=body.limit))
    except SponsorError as exc:
        raise channel3_error(exc) from exc


@router.get("/supply/catalog-products", summary="Your catalog, for picking a product to find alternatives for")
async def catalog_products(
    session: DbSession, principal: Principal = Depends(require_permission(Permission.PRODUCTS_READ)),
) -> APIResponse[list[dict[str, Any]]]:
    rows = (await session.execute(
        select(Product).where(Product.merchant_id == principal.merchant_id).order_by(Product.name)
    )).scalars().all()
    return APIResponse(data=[{"id": str(p.id), "name": p.name, "sku": p.sku, "category": p.category,
                              "price": format(Decimal(str(p.price)), ".2f"), "is_active": p.is_active,
                              "image_url": p.image_url, "source": (p.attributes or {}).get("source")} for p in rows])


@router.post("/supply/alternatives", summary="Alternatives to one of your products (Channel3 search + similar)")
async def product_alternatives(
    body: AlternativesRequest, session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PRODUCTS_READ)),
) -> APIResponse[dict[str, Any]]:
    try:
        return APIResponse(data=await _recs(session, principal).alternatives(body.product_id, limit=body.limit))
    except SponsorError as exc:
        raise channel3_error(exc) from exc


@router.post("/supply/alternatives/save", summary="Save an alternative as a recommendation for approval")
async def save_alternative(
    body: SaveAlternativeRequest, session: DbSession,
    principal: Principal = Depends(require_permission(Permission.GROWTH_RECOMMEND)),
) -> APIResponse[dict[str, Any]]:
    try:
        return APIResponse(data=await _recs(session, principal).save_alternative(
            body.product_id, body.channel3_product_id, note=body.note))
    except SponsorError as exc:
        raise channel3_error(exc) from exc


# --------------------------------------------------------------------------- #
# Recommendations
# --------------------------------------------------------------------------- #
@router.get("/supply/recommendations", summary="AI recommendations and their lifecycle")
async def list_recommendations(
    session: DbSession, status: Annotated[str | None, Query(max_length=16)] = None,
    kind: Annotated[str | None, Query(max_length=32)] = None,
    principal: Principal = Depends(require_permission(Permission.GROWTH_READ)),
) -> APIResponse[list[dict[str, Any]]]:
    items, counts = await _recs(session, principal).list(status=status, kind=kind)
    return APIResponse(data=items, meta={"status_counts": counts,
                                         "can_decide": principal.has(Permission.PROCUREMENT_APPROVE),
                                         "can_generate": principal.has(Permission.GROWTH_RECOMMEND),
                                         "can_request_purchase": principal.has(Permission.PROCUREMENT_CREATE),
                                         "can_pay": principal.has(Permission.PAYMENT_EXECUTE)})


@router.post("/supply/recommendations/generate", summary="Generate recommendations from sales data and Channel3")
async def generate_recommendations(
    body: GenerateRequest, session: DbSession,
    principal: Principal = Depends(require_permission(Permission.GROWTH_RECOMMEND)),
) -> APIResponse[dict[str, Any]]:
    try:
        return APIResponse(data=await _recs(session, principal).generate(
            days=body.days, max_recommendations=body.max_recommendations, include_pricing=body.include_pricing))
    except SponsorError as exc:
        raise channel3_error(exc) from exc


@router.get("/supply/recommendations/{rec_id}", summary="One recommendation with its evidence and lifecycle")
async def get_recommendation(
    rec_id: uuid.UUID, session: DbSession,
    principal: Principal = Depends(require_permission(Permission.GROWTH_READ)),
) -> APIResponse[dict[str, Any]]:
    from app.services.supply_intel.recommendations import recommendation_out

    return APIResponse(data=recommendation_out(await _recs(session, principal).get(rec_id)))


@router.post("/supply/recommendations/{rec_id}/approve", summary="Approve a recommendation (a human decision)")
async def approve_recommendation(
    rec_id: uuid.UUID, body: DecisionRequest, session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PROCUREMENT_APPROVE)),
) -> APIResponse[dict[str, Any]]:
    return APIResponse(data=await _recs(session, principal).decide(rec_id, approve=True, note=body.note))


@router.post("/supply/recommendations/{rec_id}/reject", summary="Reject a recommendation")
async def reject_recommendation(
    rec_id: uuid.UUID, body: DecisionRequest, session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PROCUREMENT_APPROVE)),
) -> APIResponse[dict[str, Any]]:
    return APIResponse(data=await _recs(session, principal).decide(rec_id, approve=False, note=body.note))


@router.post("/supply/recommendations/{rec_id}/execute",
             summary="Execute an approved recommendation (add to catalog / apply the price test - no money moves)")
async def execute_recommendation(
    rec_id: uuid.UUID, body: ExecuteRequest, session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PROCUREMENT_APPROVE)),
) -> APIResponse[dict[str, Any]]:
    return APIResponse(data=await _recs(session, principal).execute(rec_id, retail_price=body.retail_price))


@router.post("/supply/recommendations/{rec_id}/purchase",
             summary="Request approval to buy test stock through PayPal (creates an approval; pays nothing)")
async def request_purchase(
    rec_id: uuid.UUID, body: PurchaseRequest, session: DbSession,
    principal: Principal = Depends(require_permission(Permission.PROCUREMENT_CREATE)),
) -> APIResponse[dict[str, Any]]:
    approval = await _recs(session, principal).request_payment(
        rec_id, quantity=body.quantity, unit_cost=body.unit_cost, payee_email=body.payee_email, currency=body.currency)
    data = describe_approval(approval)
    data["can_decide"] = principal.has(approval.required_permission)
    return APIResponse(data=data)


@router.post("/supply/recommendations/{rec_id}/measure", summary="Measure an executed recommendation's results")
async def measure_recommendation(
    rec_id: uuid.UUID, session: DbSession,
    principal: Principal = Depends(require_permission(Permission.GROWTH_RECOMMEND)),
) -> APIResponse[dict[str, Any]]:
    return APIResponse(data=await _recs(session, principal).measure(rec_id))


# --------------------------------------------------------------------------- #
# Growth Autopilot
# --------------------------------------------------------------------------- #
@router.post("/growth/autopilot/run", summary="Run the Merchant Growth Autopilot up to the approval gate")
async def run_autopilot(
    body: AutopilotRequest, session: DbSession,
    principal: Principal = Depends(require_permission(Permission.GROWTH_RECOMMEND, Permission.AGENTS_RUN)),
) -> APIResponse[dict[str, Any]]:
    result = await MerchantOS(
        session, merchant_id=principal.merchant_id, merchant_name=principal.merchant.name, user_id=principal.user_id,
        permissions=principal.permissions, actor_label=principal.label,
    ).execute("Run the growth autopilot: analyse my business, find products to add and recommend what to do next.",
              agent="growth_strategy", params={"days": body.days, "max_recommendations": body.max_recommendations},
              workflow=AgentWorkflow.AUTOPILOT)
    return APIResponse(data=result)


@router.get("/growth/autopilot", summary="The latest autopilot run and the recommendation pipeline")
async def autopilot_state(
    session: DbSession, principal: Principal = Depends(require_permission(Permission.GROWTH_READ)),
) -> APIResponse[dict[str, Any]]:
    run = (await session.execute(
        select(AgentRun).where(AgentRun.merchant_id == principal.merchant_id, AgentRun.workflow == AgentWorkflow.AUTOPILOT)
        .order_by(AgentRun.created_at.desc()).limit(1)
    )).scalars().first()
    items, counts = await _recs(session, principal).list(limit=20)
    return APIResponse(data={
        "last_run": {"run_id": str(run.id), "status": run.status, "summary": run.summary,
                     "created_at": run.created_at.isoformat() if run.created_at else None,
                     "duration_ms": run.duration_ms} if run else None,
        "pipeline": counts, "recommendations": items,
    })
