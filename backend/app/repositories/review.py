"""Review and competitor repositories, including pgvector similarity search."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import Float, and_, case, cast, desc, func, or_, select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.competitor import Competitor, CompetitorReview
from app.db.models.review import Review, Sentiment
from app.integrations.embeddings import cosine_similarity, embedding_service
from app.repositories.base import MerchantScopedRepository

log = get_logger(__name__)


class ReviewRepository(MerchantScopedRepository[Review]):
    model = Review

    # ------------------------------------------------------------------ listing
    @staticmethod
    def _filters(
        *,
        topic: str | None = None,
        sentiment: str | None = None,
        daypart: str | None = None,
        rating: int | None = None,
        q: str | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[Any]:
        """One source of truth for list and count, so a page total can never
        disagree with the rows on the page."""
        conditions: list[Any] = []
        if topic:
            conditions.append(Review.primary_topic == topic)
        if sentiment:
            conditions.append(Review.sentiment == sentiment)
        if daypart:
            conditions.append(Review.daypart == daypart)
        if rating is not None:
            conditions.append(Review.rating == rating)
        if q:
            term = f"%{q.strip()}%"
            conditions.append(
                or_(
                    Review.body.ilike(term),
                    Review.title.ilike(term),
                    Review.author_name.ilike(term),
                )
            )
        if start:
            conditions.append(Review.review_date >= start)
        if end:
            conditions.append(Review.review_date <= end)
        return conditions

    async def list_recent(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        topic: str | None = None,
        sentiment: str | None = None,
        daypart: str | None = None,
        rating: int | None = None,
        q: str | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[Review]:
        conditions = self._filters(
            topic=topic,
            sentiment=sentiment,
            daypart=daypart,
            rating=rating,
            q=q,
            start=start,
            end=end,
        )
        stmt = self.scoped()
        for condition in conditions:
            stmt = stmt.where(condition)
        stmt = stmt.order_by(desc(Review.reviewed_at)).limit(limit).offset(offset)
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_filtered(
        self,
        *,
        topic: str | None = None,
        sentiment: str | None = None,
        daypart: str | None = None,
        rating: int | None = None,
        q: str | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> int:
        return await self.count(
            *self._filters(
                topic=topic,
                sentiment=sentiment,
                daypart=daypart,
                rating=rating,
                q=q,
                start=start,
                end=end,
            )
        )

    async def rating_breakdown(
        self,
        *,
        topic: str | None = None,
        sentiment: str | None = None,
        daypart: str | None = None,
        q: str | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> dict[int, int]:
        """Counts per star, honouring every filter except rating itself.

        Faceted counts: picking a star narrows the list, it does not change what
        the other stars would return.
        """
        stmt = select(Review.rating, func.count(Review.id)).where(
            Review.merchant_id == self.merchant_id
        )
        for condition in self._filters(
            topic=topic, sentiment=sentiment, daypart=daypart, q=q, start=start, end=end
        ):
            stmt = stmt.where(condition)
        rows = (await self.session.execute(stmt.group_by(Review.rating))).all()
        counts = {int(row[0]): int(row[1]) for row in rows}
        return {star: counts.get(star, 0) for star in range(1, 6)}

    # ------------------------------------------------------------------ aggregates
    async def topic_stats(
        self, start: date, end: date, *, daypart: str | None = None
    ) -> list[dict[str, Any]]:
        """Volume, rating and negative share per topic for a window."""
        conditions = [
            Review.merchant_id == self.merchant_id,
            Review.review_date >= start,
            Review.review_date <= end,
        ]
        if daypart:
            conditions.append(Review.daypart == daypart)

        stmt = (
            select(
                Review.primary_topic,
                func.count(Review.id),
                func.avg(cast(Review.rating, Float)),
                func.sum(case((Review.sentiment == Sentiment.NEGATIVE, 1), else_=0)),
                func.sum(case((Review.sentiment == Sentiment.POSITIVE, 1), else_=0)),
            )
            .where(and_(*conditions))
            .group_by(Review.primary_topic)
            .order_by(func.count(Review.id).desc())
        )
        rows = (await self.session.execute(stmt)).all()
        total = sum(int(row[1] or 0) for row in rows)
        return [
            {
                "topic": row[0],
                "count": int(row[1] or 0),
                "avg_rating": round(float(row[2] or 0), 2),
                "negative_count": int(row[3] or 0),
                "positive_count": int(row[4] or 0),
                "share_pct": round((int(row[1] or 0) / total) * 100, 2) if total else 0.0,
                "negative_share_pct": round((int(row[3] or 0) / int(row[1] or 1)) * 100, 2),
            }
            for row in rows
        ]

    async def sentiment_breakdown(self, start: date, end: date) -> dict[str, Any]:
        stmt = select(
            func.count(Review.id),
            func.sum(case((Review.sentiment == Sentiment.POSITIVE, 1), else_=0)),
            func.sum(case((Review.sentiment == Sentiment.NEUTRAL, 1), else_=0)),
            func.sum(case((Review.sentiment == Sentiment.NEGATIVE, 1), else_=0)),
            func.avg(cast(Review.rating, Float)),
        ).where(
            Review.merchant_id == self.merchant_id,
            Review.review_date >= start,
            Review.review_date <= end,
        )
        row = (await self.session.execute(stmt)).one()
        total = int(row[0] or 0)
        positive, neutral, negative = int(row[1] or 0), int(row[2] or 0), int(row[3] or 0)
        return {
            "total": total,
            "positive": positive,
            "neutral": neutral,
            "negative": negative,
            "positive_pct": round((positive / total) * 100, 2) if total else 0.0,
            "neutral_pct": round((neutral / total) * 100, 2) if total else 0.0,
            "negative_pct": round((negative / total) * 100, 2) if total else 0.0,
            "avg_rating": round(float(row[4] or 0), 2),
        }

    async def daily_rating_trend(self, start: date, end: date) -> list[dict[str, Any]]:
        stmt = (
            select(
                Review.review_date,
                func.avg(cast(Review.rating, Float)),
                func.count(Review.id),
                func.sum(case((Review.sentiment == Sentiment.NEGATIVE, 1), else_=0)),
            )
            .where(
                Review.merchant_id == self.merchant_id,
                Review.review_date >= start,
                Review.review_date <= end,
            )
            .group_by(Review.review_date)
            .order_by(Review.review_date)
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            {
                "date": row[0],
                "avg_rating": round(float(row[1] or 0), 2),
                "count": int(row[2] or 0),
                "negative": int(row[3] or 0),
            }
            for row in rows
        ]

    async def topic_daily_trend(self, topic: str, start: date, end: date) -> list[dict[str, Any]]:
        stmt = (
            select(Review.review_date, func.count(Review.id))
            .where(
                Review.merchant_id == self.merchant_id,
                Review.primary_topic == topic,
                Review.review_date >= start,
                Review.review_date <= end,
            )
            .group_by(Review.review_date)
            .order_by(Review.review_date)
        )
        rows = (await self.session.execute(stmt)).all()
        return [{"date": row[0], "count": int(row[1] or 0)} for row in rows]

    async def sample_ids_for_topic(
        self, topic: str, start: date, end: date, *, limit: int = 3
    ) -> list[uuid.UUID]:
        stmt = (
            select(Review.id)
            .where(
                Review.merchant_id == self.merchant_id,
                Review.primary_topic == topic,
                Review.review_date >= start,
                Review.review_date <= end,
            )
            .order_by(desc(Review.reviewed_at))
            .limit(limit)
        )
        return [row[0] for row in (await self.session.execute(stmt)).all()]

    # ------------------------------------------------------------------ vector search
    async def semantic_search(
        self,
        query: str,
        *,
        limit: int = 10,
        topic: str | None = None,
        sentiment: str | None = None,
    ) -> list[tuple[Review, float]]:
        """pgvector cosine search, with an in-Python fallback on other dialects."""
        vector = embedding_service.embed(query)

        if settings.is_postgres:
            try:
                stmt = self.scoped()
                if topic:
                    stmt = stmt.where(Review.primary_topic == topic)
                if sentiment:
                    stmt = stmt.where(Review.sentiment == sentiment)
                distance = Review.embedding.cosine_distance(vector)  # type: ignore[attr-defined]
                stmt = (
                    stmt.where(Review.embedding.is_not(None))
                    .add_columns(distance)
                    .order_by(distance)
                    .limit(limit)
                )
                rows = (await self.session.execute(stmt)).all()
                return [(row[0], round(1.0 - float(row[1] or 0), 4)) for row in rows]
            except Exception as exc:
                log.warning("pgvector_search_failed", detail=str(exc)[:200], fallback="python")

        stmt = self.scoped().where(Review.embedding.is_not(None))
        if topic:
            stmt = stmt.where(Review.primary_topic == topic)
        if sentiment:
            stmt = stmt.where(Review.sentiment == sentiment)
        reviews = list((await self.session.execute(stmt.limit(2000))).scalars().all())
        scored = [
            (review, round(cosine_similarity(vector, review.embedding or []), 4))
            for review in reviews
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:limit]


class CompetitorRepository(MerchantScopedRepository[Competitor]):
    model = Competitor

    async def list_active(self) -> list[Competitor]:
        stmt = self.scoped().where(Competitor.is_active.is_(True)).order_by(Competitor.name)
        return list((await self.session.execute(stmt)).scalars().all())

    async def topic_stats(self, start: date, end: date) -> list[dict[str, Any]]:
        stmt = (
            select(
                CompetitorReview.primary_topic,
                func.count(CompetitorReview.id),
                func.avg(cast(CompetitorReview.rating, Float)),
                func.sum(case((CompetitorReview.sentiment == Sentiment.NEGATIVE, 1), else_=0)),
                func.sum(case((CompetitorReview.sentiment == Sentiment.POSITIVE, 1), else_=0)),
            )
            .where(
                CompetitorReview.merchant_id == self.merchant_id,
                CompetitorReview.review_date >= start,
                CompetitorReview.review_date <= end,
            )
            .group_by(CompetitorReview.primary_topic)
            .order_by(func.count(CompetitorReview.id).desc())
        )
        rows = (await self.session.execute(stmt)).all()
        total = sum(int(row[1] or 0) for row in rows)
        return [
            {
                "topic": row[0],
                "count": int(row[1] or 0),
                "avg_rating": round(float(row[2] or 0), 2),
                "negative_count": int(row[3] or 0),
                "positive_count": int(row[4] or 0),
                "share_pct": round((int(row[1] or 0) / total) * 100, 2) if total else 0.0,
                "negative_share_pct": round((int(row[3] or 0) / int(row[1] or 1)) * 100, 2),
            }
            for row in rows
        ]

    async def review_count(self) -> int:
        stmt = select(func.count(CompetitorReview.id)).where(
            CompetitorReview.merchant_id == self.merchant_id
        )
        return int((await self.session.execute(stmt)).scalar_one() or 0)
