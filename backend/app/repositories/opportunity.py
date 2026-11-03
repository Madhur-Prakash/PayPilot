"""Growth opportunity, growth metric and external signal repositories."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import desc, func, select

from app.db.models.growth import GrowthMetric, GrowthOpportunity, OpportunityStatus
from app.db.models.signal import ExternalSignal
from app.repositories.base import MerchantScopedRepository


class OpportunityRepository(MerchantScopedRepository[GrowthOpportunity]):
    model = GrowthOpportunity

    async def get_by_key(self, key: str) -> GrowthOpportunity | None:
        stmt = self.scoped().where(GrowthOpportunity.key == key)
        return (await self.session.execute(stmt)).scalars().first()

    async def list_open(self, *, limit: int = 20) -> list[GrowthOpportunity]:
        stmt = (
            self.scoped()
            .where(GrowthOpportunity.status.in_(list(OpportunityStatus.OPEN)))
            .order_by(desc(GrowthOpportunity.priority_score))
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_all_ranked(
        self, *, limit: int = 50, status: str | None = None
    ) -> list[GrowthOpportunity]:
        stmt = self.scoped()
        if status:
            stmt = stmt.where(GrowthOpportunity.status == status)
        stmt = stmt.order_by(desc(GrowthOpportunity.priority_score)).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def top(self) -> GrowthOpportunity | None:
        results = await self.list_open(limit=1)
        return results[0] if results else None

    async def total_open_value(self) -> float:
        stmt = select(func.coalesce(func.sum(GrowthOpportunity.estimated_value_monthly), 0)).where(
            GrowthOpportunity.merchant_id == self.merchant_id,
            GrowthOpportunity.status.in_(list(OpportunityStatus.OPEN)),
        )
        return round(float((await self.session.execute(stmt)).scalar_one() or 0), 2)

    async def upsert(self, *, key: str, **values: Any) -> GrowthOpportunity:
        """Detection is idempotent: re-running updates the row rather than duplicating it.

        Human-driven state (an opportunity already approved, running or measured) is
        never rolled back to DETECTED by a later detection pass.
        """
        existing = await self.get_by_key(key)
        if existing is None:
            return await self.create(key=key, **values)

        protected = {
            OpportunityStatus.APPROVAL_REQUIRED,
            OpportunityStatus.RUNNING,
            OpportunityStatus.MEASURING,
            OpportunityStatus.SCALED,
            OpportunityStatus.STOPPED,
            OpportunityStatus.DISMISSED,
        }
        if existing.status in protected:
            values.pop("status", None)
        for field, value in values.items():
            setattr(existing, field, value)
        await self.session.flush()
        return existing

    async def set_status(self, opportunity: GrowthOpportunity, status: str) -> GrowthOpportunity:
        opportunity.status = status
        await self.session.flush()
        return opportunity

    async def count_by_status(self) -> dict[str, int]:
        stmt = (
            select(GrowthOpportunity.status, func.count(GrowthOpportunity.id))
            .where(GrowthOpportunity.merchant_id == self.merchant_id)
            .group_by(GrowthOpportunity.status)
        )
        rows = (await self.session.execute(stmt)).all()
        return {row[0]: int(row[1] or 0) for row in rows}


class GrowthMetricRepository(MerchantScopedRepository[GrowthMetric]):
    model = GrowthMetric

    async def upsert_snapshot(
        self,
        *,
        metric_key: str,
        label: str,
        period_start: date,
        period_end: date,
        value: float,
        dimension: str = "overall",
        dimension_value: str = "all",
        **extra: Any,
    ) -> GrowthMetric:
        stmt = self.scoped().where(
            GrowthMetric.metric_key == metric_key,
            GrowthMetric.period_start == period_start,
            GrowthMetric.period_end == period_end,
            GrowthMetric.dimension == dimension,
            GrowthMetric.dimension_value == dimension_value,
        )
        existing = (await self.session.execute(stmt)).scalars().first()
        payload = {
            "label": label,
            "value": value,
            "computed_at": datetime.now(tz=UTC),
            **extra,
        }
        if existing is not None:
            for field, val in payload.items():
                setattr(existing, field, val)
            await self.session.flush()
            return existing
        return await self.create(
            metric_key=metric_key,
            period_start=period_start,
            period_end=period_end,
            dimension=dimension,
            dimension_value=dimension_value,
            **payload,
        )

    async def latest_for_key(self, metric_key: str) -> GrowthMetric | None:
        stmt = (
            self.scoped()
            .where(GrowthMetric.metric_key == metric_key, GrowthMetric.dimension == "overall")
            .order_by(desc(GrowthMetric.period_end))
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def history(self, metric_key: str, *, limit: int = 12) -> list[GrowthMetric]:
        stmt = (
            self.scoped()
            .where(GrowthMetric.metric_key == metric_key)
            .order_by(desc(GrowthMetric.period_end))
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())


class SignalRepository(MerchantScopedRepository[ExternalSignal]):
    model = ExternalSignal

    async def list_relevant(self, *, limit: int = 10) -> list[ExternalSignal]:
        stmt = (
            self.scoped()
            .where(ExternalSignal.is_dismissed.is_(False))
            .order_by(desc(ExternalSignal.relevance_score), desc(ExternalSignal.observed_on))
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def high_relevance_count(self) -> int:
        return await self.count(
            ExternalSignal.relevance == "HIGH", ExternalSignal.is_dismissed.is_(False)
        )

    async def dismiss(self, signal: ExternalSignal) -> ExternalSignal:
        signal.is_dismissed = True
        await self.session.flush()
        return signal

    async def for_category(self, category: str) -> list[ExternalSignal]:
        stmt = self.scoped().where(ExternalSignal.linked_category == category)
        return list((await self.session.execute(stmt)).scalars().all())
