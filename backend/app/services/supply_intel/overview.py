"""The Supply Intelligence dashboard payload.

Assembled from the merchant's own data and what PayPilot has already stored -
**no Channel3 call happens on page load** (credits are spent only when the merchant or
an agent searches, compares or generates recommendations).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.discovery import DiscoveredProduct, MerchantRecommendation, ProductSearch, RecommendationKind, RecommendationStatus
from app.services.discovery.service import ProductDiscoveryService
from app.services.supply_intel.analysis import AssortmentAnalyzer
from app.services.supply_intel.recommendations import recommendation_out


async def supply_overview(session: AsyncSession, merchant_id: uuid.UUID, *, days: int = 30) -> dict[str, Any]:
    discovery = ProductDiscoveryService(session, merchant_id)
    analysis = await AssortmentAnalyzer(session, merchant_id).analyze(days=days)
    recs = (await session.execute(
        select(MerchantRecommendation).where(MerchantRecommendation.merchant_id == merchant_id,
                                             MerchantRecommendation.status != RecommendationStatus.SUPERSEDED)
        .order_by(MerchantRecommendation.updated_at.desc()).limit(30)
    )).scalars().all()
    counts = dict((await session.execute(
        select(MerchantRecommendation.status, func.count()).where(MerchantRecommendation.merchant_id == merchant_id)
        .group_by(MerchantRecommendation.status)
    )).all())
    discovered_total = (await session.execute(
        select(func.count()).select_from(DiscoveredProduct).where(DiscoveredProduct.merchant_id == merchant_id)
    )).scalar_one()
    searches_total = (await session.execute(
        select(func.count()).select_from(ProductSearch).where(ProductSearch.merchant_id == merchant_id)
    )).scalar_one()
    open_recs = [r for r in recs if r.status in RecommendationStatus.OPEN]
    pricing = [recommendation_out(r) for r in recs if r.kind == RecommendationKind.PRICING_OPPORTUNITY][:3]
    top_candidate = (analysis.get("expansion_candidates") or [None])[0]
    impact_open = sum(float((r.expected_impact or {}).get("value") or 0) for r in open_recs)
    return {
        "status": discovery.status(),
        "window": analysis.get("window"),
        "summary": analysis.get("summary"),
        "data_quality": analysis.get("data_quality"),
        "categories": analysis.get("categories", [])[:8],
        "growing_products": analysis.get("growing_products", []),
        "inventory": analysis.get("inventory", [])[:8],
        "pairs": analysis.get("pairs", [])[:5],
        "expansion_candidates": analysis.get("expansion_candidates", [])[:6],
        "top_opportunity": top_candidate,
        "recommendations": [recommendation_out(r) for r in recs[:12]],
        "pricing": pricing,
        "recently_discovered": await discovery.discovered(limit=12),
        "recent_searches": await discovery.history(limit=8),
        "kpis": {
            "open_recommendations": len(open_recs),
            "approved": int(counts.get(RecommendationStatus.APPROVED, 0)),
            "executed": int(counts.get(RecommendationStatus.EXECUTED, 0)) + int(counts.get(RecommendationStatus.MEASURED, 0)),
            "estimated_open_monthly_impact": round(impact_open, 2),
            "products_discovered": int(discovered_total),
            "searches": int(searches_total),
        },
    }


__all__ = ["supply_overview"]
