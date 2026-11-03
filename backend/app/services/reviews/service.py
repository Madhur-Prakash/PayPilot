"""Review intelligence.

Topic volume alone is misleading when order volume is moving: if a slot loses a
third of its orders, its complaint count can fall while the experience gets
materially worse. So this service reports complaints **per 100 orders** alongside
raw counts, and that normalised rate is what drives the "emerging complaint" flag.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.commerce import DayPart
from app.db.models.review import ReviewTopic
from app.repositories.review import ReviewRepository
from app.repositories.transaction import TransactionRepository, _pct_change
from app.schemas.analytics import PeriodInfo
from app.schemas.common import TrendPoint
from app.schemas.growth import (
    ReviewIntelligence,
    ReviewOut,
    ReviewSearchHit,
    SentimentBreakdown,
    TopicStat,
)
from app.services.analytics.service import AnalyticsService

log = get_logger(__name__)

#: Minimum negative volume before a topic can be called an emerging complaint.
MIN_EMERGING_VOLUME = 4
#: Minimum rise in the normalised complaint rate to qualify.
MIN_EMERGING_RATE_CHANGE_PCT = 20.0


def _trend(change: float | None) -> str:
    if change is None:
        return "FLAT"
    if change > 5:
        return "UP"
    if change < -5:
        return "DOWN"
    return "FLAT"


class ReviewService:
    def __init__(self, session: AsyncSession, merchant_id: uuid.UUID) -> None:
        self.session = session
        self.merchant_id = merchant_id
        self.repo = ReviewRepository(session, merchant_id)
        self.transactions = TransactionRepository(session, merchant_id)
        self.analytics = AnalyticsService(session, merchant_id)

    async def intelligence(self, *, days: int = 30) -> ReviewIntelligence:
        period = await self.analytics.resolve_period(days=days)
        current_stats = await self.repo.topic_stats(period.current.start, period.current.end)
        previous_stats = await self.repo.topic_stats(period.previous.start, period.previous.end)
        prev_by_topic = {row["topic"]: row for row in previous_stats}

        # Normalise by order volume so a shrinking slot cannot hide a worsening one.
        current_orders = await self.transactions.count_orders(
            period.current.start, period.current.end
        )
        previous_orders = await self.transactions.count_orders(
            period.previous.start, period.previous.end
        )

        topics: list[TopicStat] = []
        for row in current_stats:
            prior = prev_by_topic.get(row["topic"], {})
            prior_count = int(prior.get("count", 0) or 0)
            prior_negative = int(prior.get("negative_count", 0) or 0)

            count_change = _pct_change(float(row["count"]), float(prior_count))
            rate_now = (row["negative_count"] / current_orders * 100) if current_orders else 0.0
            rate_before = (prior_negative / previous_orders * 100) if previous_orders else 0.0
            rate_change = _pct_change(rate_now, rate_before)

            is_emerging = bool(
                row["negative_count"] >= MIN_EMERGING_VOLUME
                and rate_change is not None
                and rate_change >= MIN_EMERGING_RATE_CHANGE_PCT
            )
            topics.append(
                TopicStat(
                    topic=row["topic"],
                    label=ReviewTopic.LABELS.get(row["topic"], row["topic"].title()),
                    count=row["count"],
                    share_pct=row["share_pct"],
                    avg_rating=row["avg_rating"],
                    negative_count=row["negative_count"],
                    positive_count=row["positive_count"],
                    negative_share_pct=row["negative_share_pct"],
                    previous_count=prior_count,
                    change_pct=rate_change if rate_change is not None else count_change,
                    trend=_trend(rate_change if rate_change is not None else count_change),
                    is_emerging_complaint=is_emerging,
                    sample_review_ids=await self.repo.sample_ids_for_topic(
                        row["topic"], period.current.start, period.current.end
                    ),
                )
            )

        sentiment_now = await self.repo.sentiment_breakdown(
            period.current.start, period.current.end
        )
        sentiment_before = await self.repo.sentiment_breakdown(
            period.previous.start, period.previous.end
        )

        emerging = sorted(
            [t for t in topics if t.is_emerging_complaint],
            key=lambda t: (t.change_pct or 0),
            reverse=True,
        )
        positive_themes = sorted(
            [t for t in topics if t.positive_count >= 5 and t.avg_rating >= 4.0],
            key=lambda t: t.positive_count,
            reverse=True,
        )[:5]

        rating_rows = await self.repo.daily_rating_trend(period.current.start, period.current.end)
        rating_trend = [
            TrendPoint(
                date=row["date"], value=row["avg_rating"], secondary_value=float(row["count"])
            )
            for row in rating_rows
        ]
        negative_trend = [
            TrendPoint(date=row["date"], value=float(row["negative"])) for row in rating_rows
        ]

        by_daypart: list[TopicStat] = []
        for part in DayPart.ALL:
            slot_now = await self.repo.topic_stats(
                period.current.start, period.current.end, daypart=part
            )
            slot_before = await self.repo.topic_stats(
                period.previous.start, period.previous.end, daypart=part
            )
            negatives_now = sum(row["negative_count"] for row in slot_now)
            negatives_before = sum(row["negative_count"] for row in slot_before)
            total_now = sum(row["count"] for row in slot_now)
            if total_now == 0:
                continue
            by_daypart.append(
                TopicStat(
                    topic=part,
                    label=part.title(),
                    count=total_now,
                    share_pct=round((negatives_now / total_now) * 100, 2),
                    avg_rating=round(
                        sum(row["avg_rating"] * row["count"] for row in slot_now) / total_now, 2
                    ),
                    negative_count=negatives_now,
                    positive_count=sum(row["positive_count"] for row in slot_now),
                    negative_share_pct=round((negatives_now / total_now) * 100, 2),
                    previous_count=sum(row["count"] for row in slot_before),
                    change_pct=_pct_change(float(negatives_now), float(negatives_before)),
                    trend=_trend(_pct_change(float(negatives_now), float(negatives_before))),
                )
            )

        recent = await self.repo.list_recent(limit=12)
        total_reviews = await self.repo.count()

        return ReviewIntelligence(
            total_reviews=total_reviews,
            period_reviews=sentiment_now["total"],
            sentiment=SentimentBreakdown(
                positive=sentiment_now["positive"],
                neutral=sentiment_now["neutral"],
                negative=sentiment_now["negative"],
                positive_pct=sentiment_now["positive_pct"],
                neutral_pct=sentiment_now["neutral_pct"],
                negative_pct=sentiment_now["negative_pct"],
                avg_rating=sentiment_now["avg_rating"],
                previous_avg_rating=sentiment_before["avg_rating"],
                avg_rating_change=round(
                    sentiment_now["avg_rating"] - sentiment_before["avg_rating"], 2
                ),
            ),
            topics=topics,
            emerging_complaints=emerging[:4],
            positive_themes=positive_themes,
            rating_trend=rating_trend,
            negative_topic_trend=negative_trend,
            by_daypart=by_daypart,
            recent_reviews=[ReviewOut.model_validate(review) for review in recent],
            generated_at=datetime.now(tz=UTC),
        )

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        topic: str | None = None,
        sentiment: str | None = None,
    ) -> list[ReviewSearchHit]:
        hits = await self.repo.semantic_search(query, limit=limit, topic=topic, sentiment=sentiment)
        log.info("review_semantic_search", query=query[:80], results=len(hits))
        return [
            ReviewSearchHit(review=ReviewOut.model_validate(review), similarity=score)
            for review, score in hits
        ]

    async def summary_for_agent(self, period: PeriodInfo) -> dict:
        """Compact structured review facts for the agents to reason over."""
        intelligence = await self.intelligence(days=period.days)
        return {
            "total_reviews_period": intelligence.period_reviews,
            "avg_rating": intelligence.sentiment.avg_rating,
            "avg_rating_change": intelligence.sentiment.avg_rating_change,
            "negative_share_pct": intelligence.sentiment.negative_pct,
            "emerging_complaints": [
                {
                    "topic": t.topic,
                    "label": t.label,
                    "negative_reviews": t.negative_count,
                    "rate_change_pct": t.change_pct,
                }
                for t in intelligence.emerging_complaints
            ],
            "positive_themes": [
                {"topic": t.topic, "label": t.label, "positive_reviews": t.positive_count}
                for t in intelligence.positive_themes
            ],
            "by_daypart_negative_share": [
                {
                    "daypart": t.topic,
                    "negative_share_pct": t.negative_share_pct,
                    "change_pct": t.change_pct,
                }
                for t in intelligence.by_daypart
            ],
        }
