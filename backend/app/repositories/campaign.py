"""Campaign repository."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import selectinload

from app.db.models.campaign import (
    Campaign,
    CampaignAction,
    CampaignAudience,
    CampaignStatus,
)
from app.repositories.base import MerchantScopedRepository


class CampaignRepository(MerchantScopedRepository[Campaign]):
    model = Campaign

    async def get_with_detail(self, campaign_id: uuid.UUID) -> Campaign | None:
        stmt = (
            self.scoped()
            .where(Campaign.id == campaign_id)
            .options(selectinload(Campaign.audiences), selectinload(Campaign.actions))
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def list_recent(
        self, *, limit: int = 25, offset: int = 0, status: str | None = None
    ) -> list[Campaign]:
        stmt = self.scoped().options(selectinload(Campaign.audiences))
        if status:
            stmt = stmt.where(Campaign.status == status)
        stmt = stmt.order_by(desc(Campaign.created_at)).limit(limit).offset(offset)
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_by_status(self) -> dict[str, int]:
        stmt = (
            select(Campaign.status, func.count(Campaign.id))
            .where(Campaign.merchant_id == self.merchant_id)
            .group_by(Campaign.status)
        )
        rows = (await self.session.execute(stmt)).all()
        return {row[0]: int(row[1] or 0) for row in rows}

    async def active_count(self) -> int:
        return await self.count(
            Campaign.status.in_([CampaignStatus.RUNNING, CampaignStatus.SCHEDULED])
        )

    # ------------------------------------------------------------------ children
    async def add_audience(
        self,
        *,
        campaign: Campaign,
        name: str,
        role: str,
        customer_ids: list[uuid.UUID],
        definition: dict[str, Any] | None = None,
    ) -> CampaignAudience:
        audience = CampaignAudience(
            merchant_id=self.merchant_id,
            campaign_id=campaign.id,
            name=name[:200],
            role=role,
            customer_ids=[str(cid) for cid in customer_ids],
            size=len(customer_ids),
            definition=definition or {},
        )
        self.session.add(audience)
        await self.session.flush()
        return audience

    async def get_audience(self, campaign_id: uuid.UUID, role: str) -> CampaignAudience | None:
        stmt = select(CampaignAudience).where(
            CampaignAudience.merchant_id == self.merchant_id,
            CampaignAudience.campaign_id == campaign_id,
            CampaignAudience.role == role,
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def log_action(
        self,
        *,
        campaign: Campaign,
        action_type: str,
        description: str = "",
        actor_type: str = "AGENT",
        actor_id: uuid.UUID | None = None,
        actor_label: str = "",
        agent_run_id: uuid.UUID | None = None,
        payload: dict[str, Any] | None = None,
    ) -> CampaignAction:
        action = CampaignAction(
            merchant_id=self.merchant_id,
            campaign_id=campaign.id,
            action_type=action_type,
            description=description,
            actor_type=actor_type,
            actor_id=actor_id,
            actor_label=actor_label[:96],
            agent_run_id=agent_run_id,
            payload=payload or {},
        )
        self.session.add(action)
        await self.session.flush()
        return action

    async def list_actions(self, campaign_id: uuid.UUID) -> list[CampaignAction]:
        stmt = (
            select(CampaignAction)
            .where(
                CampaignAction.merchant_id == self.merchant_id,
                CampaignAction.campaign_id == campaign_id,
            )
            .order_by(CampaignAction.created_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())
