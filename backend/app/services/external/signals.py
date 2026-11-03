"""Contextual external signals.

A signal is only shown when it can be tied to this merchant's actual exposure -
the share of revenue coming from the affected category. Relevance is recomputed
from live product mix rather than stored as a fixed label, so a signal about
coffee prices ranks differently for a cafe than for a sandwich shop.

This is deliberately not a news feed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.signal import SignalRelevance
from app.integrations.external_search import external_search
from app.repositories.opportunity import SignalRepository
from app.repositories.product import ProductRepository
from app.schemas.growth import SignalFeed, SignalOut
from app.services.analytics.service import AnalyticsService

log = get_logger(__name__)

#: Revenue share at or above which an exposed category makes a signal high-relevance.
HIGH_EXPOSURE_PCT = 25.0
MEDIUM_EXPOSURE_PCT = 10.0


class SignalService:
    def __init__(self, session: AsyncSession, merchant_id: uuid.UUID) -> None:
        self.session = session
        self.merchant_id = merchant_id
        self.repo = SignalRepository(session, merchant_id)
        self.products = ProductRepository(session, merchant_id)
        self.analytics = AnalyticsService(session, merchant_id)

    async def feed(self, *, days: int = 30, limit: int = 10) -> SignalFeed:
        period = await self.analytics.resolve_period(days=days)
        exposure = await self.products.revenue_share_by_category(
            period.current.start, period.current.end
        )
        signals = await self.repo.list_relevant(limit=limit)

        out: list[SignalOut] = []
        for signal in signals:
            share = exposure.get(signal.linked_category or "", None)
            if share is not None:
                signal.exposure_pct = share
                signal.exposure_note = (
                    f"{signal.linked_category.title()} is {share:.0f}% of your revenue this period."
                )
                signal.relevance = _relevance_for(share)
                signal.relevance_score = round(min(0.35 + share / 100, 0.98), 3)
            elif not signal.exposure_note:
                signal.exposure_note = "General market context for your category."
            out.append(SignalOut.model_validate(signal))
        await self.session.flush()

        out.sort(key=lambda s: s.relevance_score, reverse=True)
        return SignalFeed(
            signals=out,
            high_relevance_count=sum(1 for s in out if s.relevance == SignalRelevance.HIGH),
            generated_at=datetime.now(tz=UTC),
        )

    async def refresh_from_web(self, *, query: str, limit: int = 4) -> int:
        """Pull live external context when a provider is configured.

        Returns the number of signals added. With the default ``seed`` provider
        this is a no-op, which is why the core flow never depends on the network.
        """
        results = await external_search.search(query, limit=limit)
        if not results:
            return 0
        added = 0
        for result in results:
            await self.repo.create(
                title=result.title[:240],
                summary=result.summary[:2000],
                category="TREND",
                icon="globe",
                relevance=SignalRelevance.MEDIUM,
                relevance_score=round(min(max(result.score, 0.1), 0.95), 3),
                source_name=result.source_name[:120],
                source_url=result.url,
                observed_on=date.today(),
                published_at=datetime.now(tz=UTC),
                is_simulated=False,
                exposure_note="Sourced from live web search.",
            )
            added += 1
        log.info("signals_refreshed", added=added, query=query[:80])
        return added

    async def summary_for_agent(self, *, days: int = 30) -> dict:
        feed = await self.feed(days=days, limit=6)
        return {
            "high_relevance_count": feed.high_relevance_count,
            "signals": [
                {
                    "title": s.title,
                    "category": s.category,
                    "relevance": s.relevance,
                    "exposure_pct": s.exposure_pct,
                    "exposure_note": s.exposure_note,
                    "potential_impact": s.potential_impact,
                    "recommended_action": s.recommended_action,
                    "source": s.source_name,
                    "simulated": s.is_simulated,
                }
                for s in feed.signals[:4]
            ],
        }


def _relevance_for(share_pct: float) -> str:
    if share_pct >= HIGH_EXPOSURE_PCT:
        return SignalRelevance.HIGH
    if share_pct >= MEDIUM_EXPOSURE_PCT:
        return SignalRelevance.MEDIUM
    return SignalRelevance.LOW
