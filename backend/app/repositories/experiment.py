"""Experiment repository."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import selectinload

from app.db.models.experiment import (
    Experiment,
    ExperimentResult,
    ExperimentStatus,
    ExperimentVariant,
    VariantRole,
)
from app.repositories.base import MerchantScopedRepository


class ExperimentRepository(MerchantScopedRepository[Experiment]):
    model = Experiment

    async def get_with_detail(self, experiment_id: uuid.UUID) -> Experiment | None:
        stmt = (
            self.scoped()
            .where(Experiment.id == experiment_id)
            .options(selectinload(Experiment.variants), selectinload(Experiment.results))
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def list_recent(
        self, *, limit: int = 25, offset: int = 0, status: str | None = None
    ) -> list[Experiment]:
        stmt = self.scoped().options(
            selectinload(Experiment.variants), selectinload(Experiment.results)
        )
        if status:
            stmt = stmt.where(Experiment.status == status)
        stmt = stmt.order_by(desc(Experiment.created_at)).limit(limit).offset(offset)
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_active(self) -> list[Experiment]:
        stmt = (
            self.scoped()
            .where(
                Experiment.status.in_(
                    [
                        ExperimentStatus.RUNNING,
                        ExperimentStatus.MEASURING,
                        ExperimentStatus.APPROVED,
                    ]
                )
            )
            .options(selectinload(Experiment.variants), selectinload(Experiment.results))
            .order_by(desc(Experiment.created_at))
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_by_status(self) -> dict[str, int]:
        stmt = (
            select(Experiment.status, func.count(Experiment.id))
            .where(Experiment.merchant_id == self.merchant_id)
            .group_by(Experiment.status)
        )
        rows = (await self.session.execute(stmt)).all()
        return {row[0]: int(row[1] or 0) for row in rows}

    # ------------------------------------------------------------------ variants
    async def add_variant(
        self,
        *,
        experiment: Experiment,
        key: str,
        name: str,
        role: str,
        customer_ids: list[uuid.UUID],
        description: str = "",
        offer_description: str = "",
        allocation_pct: float = 50.0,
        unit_cost: float = 0.0,
        audience_id: uuid.UUID | None = None,
    ) -> ExperimentVariant:
        variant = ExperimentVariant(
            merchant_id=self.merchant_id,
            experiment_id=experiment.id,
            key=key,
            name=name[:160],
            role=role,
            description=description,
            offer_description=offer_description,
            allocation_pct=allocation_pct,
            customer_ids=[str(cid) for cid in customer_ids],
            audience_size=len(customer_ids),
            unit_cost=unit_cost,
            audience_id=audience_id,
        )
        self.session.add(variant)
        await self.session.flush()
        return variant

    async def get_variants(self, experiment_id: uuid.UUID) -> list[ExperimentVariant]:
        stmt = (
            select(ExperimentVariant)
            .where(
                ExperimentVariant.merchant_id == self.merchant_id,
                ExperimentVariant.experiment_id == experiment_id,
            )
            .order_by(ExperimentVariant.role.desc())  # CONTROL before TEST
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def control_variant(self, experiment_id: uuid.UUID) -> ExperimentVariant | None:
        variants = await self.get_variants(experiment_id)
        return next((v for v in variants if v.role == VariantRole.CONTROL), None)

    async def test_variant(self, experiment_id: uuid.UUID) -> ExperimentVariant | None:
        variants = await self.get_variants(experiment_id)
        return next((v for v in variants if v.role == VariantRole.TEST), None)

    # ------------------------------------------------------------------ results
    async def upsert_result(
        self, *, experiment_id: uuid.UUID, variant_id: uuid.UUID, **values: Any
    ) -> ExperimentResult:
        stmt = select(ExperimentResult).where(
            ExperimentResult.merchant_id == self.merchant_id,
            ExperimentResult.experiment_id == experiment_id,
            ExperimentResult.variant_id == variant_id,
        )
        existing = (await self.session.execute(stmt)).scalars().first()
        if existing is not None:
            for field, value in values.items():
                setattr(existing, field, value)
            await self.session.flush()
            return existing
        result = ExperimentResult(
            merchant_id=self.merchant_id,
            experiment_id=experiment_id,
            variant_id=variant_id,
            **values,
        )
        self.session.add(result)
        await self.session.flush()
        return result

    async def get_results(self, experiment_id: uuid.UUID) -> list[ExperimentResult]:
        stmt = select(ExperimentResult).where(
            ExperimentResult.merchant_id == self.merchant_id,
            ExperimentResult.experiment_id == experiment_id,
        )
        return list((await self.session.execute(stmt)).scalars().all())
