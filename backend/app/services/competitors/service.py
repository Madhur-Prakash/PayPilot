"""Competitor intelligence.

Competitor data is representative baseline data. Nothing here scrapes or
integrates with a competitor platform yet, and the response says so explicitly
via ``ProvenanceMeta`` so the UI can badge it.

The merchant's own perception scores are *derived from its real review corpus*,
so the comparison is between a computed score and a baseline benchmark - which
is stated in the summary rather than glossed over.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.review import ReviewTopic
from app.repositories.review import CompetitorRepository, ReviewRepository
from app.schemas.growth import (
    CompetitorIntelligence,
    CompetitorOut,
    PerceptionComparison,
    TopicStat,
)
from app.services.analytics.service import AnalyticsService

log = get_logger(__name__)

#: Dimensions compared side by side. Each maps to review topics.
PERCEPTION_DIMENSIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    "speed": ("Speed", (ReviewTopic.WAITING_TIME,)),
    "service": ("Service", (ReviewTopic.SERVICE, ReviewTopic.STAFF)),
    "quality": ("Quality", (ReviewTopic.QUALITY,)),
    "taste": ("Taste", (ReviewTopic.TASTE,)),
    "price": ("Price perception", (ReviewTopic.PRICE,)),
    "packaging": ("Packaging", (ReviewTopic.PACKAGING,)),
    "ambience": ("Ambience", (ReviewTopic.AMBIENCE,)),
}


class CompetitorService:
    def __init__(self, session: AsyncSession, merchant_id: uuid.UUID) -> None:
        self.session = session
        self.merchant_id = merchant_id
        self.repo = CompetitorRepository(session, merchant_id)
        self.reviews = ReviewRepository(session, merchant_id)
        self.analytics = AnalyticsService(session, merchant_id)

    async def intelligence(self, *, merchant_name: str, days: int = 90) -> CompetitorIntelligence:
        period = await self.analytics.resolve_period(days=days)
        merchant_scores = await self._merchant_scores(period.current.start, period.current.end)
        merchant_sentiment = await self.reviews.sentiment_breakdown(
            period.current.start, period.current.end
        )
        competitors = await self.repo.list_active()

        comparisons: list[PerceptionComparison] = []
        for key, (label, _) in PERCEPTION_DIMENSIONS.items():
            merchant_score = merchant_scores.get(key)
            rival_scores = [
                float(c.perception_scores.get(key, 0) or 0)
                for c in competitors
                if c.perception_scores.get(key) is not None
            ]
            if merchant_score is None or not rival_scores:
                continue
            rival_avg = round(sum(rival_scores) / len(rival_scores), 1)
            leader = merchant_name
            best_rival = max(
                competitors,
                key=lambda c: float(c.perception_scores.get(key, 0) or 0),
                default=None,
            )
            if best_rival and float(best_rival.perception_scores.get(key, 0) or 0) > merchant_score:
                leader = best_rival.name
            comparisons.append(
                PerceptionComparison(
                    dimension=key,
                    label=label,
                    merchant_score=round(merchant_score, 1),
                    competitor_avg_score=rival_avg,
                    gap=round(merchant_score - rival_avg, 1),
                    leader=leader,
                    is_merchant_ahead=merchant_score >= rival_avg,
                )
            )

        biggest_gap = min(comparisons, key=lambda c: c.gap, default=None)
        topic_share = await self._competitor_topic_share(period.current.start, period.current.end)

        summary = self._summarise(merchant_name, biggest_gap, comparisons)

        return CompetitorIntelligence(
            merchant_name=merchant_name,
            merchant_scores={k: round(v, 1) for k, v in merchant_scores.items()},
            merchant_avg_rating=merchant_sentiment["avg_rating"],
            competitors=[CompetitorOut.model_validate(c) for c in competitors],
            comparisons=sorted(comparisons, key=lambda c: c.gap),
            biggest_gap=biggest_gap,
            topic_share=topic_share,
            summary=summary,
            generated_at=datetime.now(tz=UTC),
        )

    async def _merchant_scores(self, start, end) -> dict[str, float]:
        """Convert the merchant's own reviews into 0-100 perception scores.

        A dimension's score is the average rating of reviews on its topics,
        rescaled from 1-5 to 0-100 so it is comparable to the baseline benchmarks.
        """
        stats = await self.reviews.topic_stats(start, end)
        by_topic = {row["topic"]: row for row in stats}

        scores: dict[str, float] = {}
        for key, (_, topics) in PERCEPTION_DIMENSIONS.items():
            rows = [by_topic[t] for t in topics if t in by_topic and by_topic[t]["count"] > 0]
            if not rows:
                continue
            total = sum(row["count"] for row in rows)
            weighted = sum(row["avg_rating"] * row["count"] for row in rows) / total
            scores[key] = round(((weighted - 1) / 4) * 100, 1)
        return scores

    async def _competitor_topic_share(self, start, end) -> list[TopicStat]:
        rows = await self.repo.topic_stats(start, end)
        return [
            TopicStat(
                topic=row["topic"],
                label=ReviewTopic.LABELS.get(row["topic"], row["topic"].title()),
                count=row["count"],
                share_pct=row["share_pct"],
                avg_rating=row["avg_rating"],
                negative_count=row["negative_count"],
                positive_count=row["positive_count"],
                negative_share_pct=row["negative_share_pct"],
            )
            for row in rows
        ]

    @staticmethod
    def _summarise(
        merchant_name: str,
        biggest_gap: PerceptionComparison | None,
        comparisons: list[PerceptionComparison],
    ) -> str:
        if biggest_gap is None:
            return "Not enough review coverage yet to compare against nearby competitors."
        ahead = [c.label for c in comparisons if c.is_merchant_ahead]
        parts = [
            f"{merchant_name} trails nearby competitors most on {biggest_gap.label.lower()} "
            f"({biggest_gap.merchant_score:.0f} versus {biggest_gap.competitor_avg_score:.0f} "
            f"on a 0-100 perception scale)."
        ]
        if ahead:
            parts.append(f"It leads on {', '.join(ahead[:3]).lower()}.")
        parts.append(
            "Merchant scores are computed from its own review corpus; competitor scores are "
            "benchmark data, not yet sourced from a live competitor integration."
        )
        return " ".join(parts)

    async def summary_for_agent(self, *, merchant_name: str, days: int = 90) -> dict:
        intelligence = await self.intelligence(merchant_name=merchant_name, days=days)
        return {
            "merchant_avg_rating": intelligence.merchant_avg_rating,
            "biggest_gap": (
                {
                    "dimension": intelligence.biggest_gap.label,
                    "merchant_score": intelligence.biggest_gap.merchant_score,
                    "competitor_avg": intelligence.biggest_gap.competitor_avg_score,
                    "gap": intelligence.biggest_gap.gap,
                    "leader": intelligence.biggest_gap.leader,
                }
                if intelligence.biggest_gap
                else None
            ),
            "dimensions": [
                {
                    "dimension": c.label,
                    "merchant": c.merchant_score,
                    "competitor_avg": c.competitor_avg_score,
                    "gap": c.gap,
                }
                for c in intelligence.comparisons
            ],
            "competitors": [
                {
                    "name": c.name,
                    "distance_km": c.distance_km,
                    "avg_rating": c.avg_rating,
                    "strengths": c.strengths,
                    "weaknesses": c.weaknesses,
                }
                for c in intelligence.competitors
            ],
            "data_source": "SEEDED - representative competitor data, no platform integration",
        }
