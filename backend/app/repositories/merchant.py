"""Merchant, membership and audit-log repositories."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import selectinload

from app.db.models.audit import ActorType, AuditLog
from app.db.models.merchant import MembershipStatus, Merchant, MerchantMembership
from app.repositories.base import BaseRepository


class MerchantRepository(BaseRepository[Merchant]):
    model = Merchant

    async def get_by_slug(self, slug: str) -> Merchant | None:
        stmt = select(Merchant).where(Merchant.slug == slug)
        return (await self.session.execute(stmt)).scalars().first()

    async def slug_exists(self, slug: str) -> bool:
        return (
            await self.session.execute(select(Merchant.id).where(Merchant.slug == slug))
        ).first() is not None


class MembershipRepository(BaseRepository[MerchantMembership]):
    model = MerchantMembership

    async def get_for_user_and_merchant(
        self, user_id: uuid.UUID, merchant_id: uuid.UUID
    ) -> MerchantMembership | None:
        """The single authorisation check behind every tenant-scoped request."""
        stmt = (
            select(MerchantMembership)
            .where(
                MerchantMembership.user_id == user_id,
                MerchantMembership.merchant_id == merchant_id,
                MerchantMembership.status == MembershipStatus.ACTIVE,
            )
            .options(selectinload(MerchantMembership.merchant))
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def list_for_user(self, user_id: uuid.UUID) -> list[MerchantMembership]:
        stmt = (
            select(MerchantMembership)
            .where(
                MerchantMembership.user_id == user_id,
                MerchantMembership.status == MembershipStatus.ACTIVE,
            )
            .options(selectinload(MerchantMembership.merchant))
            .order_by(desc(MerchantMembership.is_default), MerchantMembership.created_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def default_for_user(self, user_id: uuid.UUID) -> MerchantMembership | None:
        memberships = await self.list_for_user(user_id)
        return memberships[0] if memberships else None

    async def list_for_merchant(self, merchant_id: uuid.UUID) -> list[MerchantMembership]:
        stmt = (
            select(MerchantMembership)
            .where(MerchantMembership.merchant_id == merchant_id)
            .options(selectinload(MerchantMembership.user))
            .order_by(MerchantMembership.created_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_owners(self, merchant_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(MerchantMembership)
            .where(
                MerchantMembership.merchant_id == merchant_id,
                MerchantMembership.role == "OWNER",
                MerchantMembership.status == MembershipStatus.ACTIVE,
            )
        )
        return int((await self.session.execute(stmt)).scalar_one() or 0)


class AuditLogRepository(BaseRepository[AuditLog]):
    model = AuditLog

    async def record(
        self,
        *,
        action: str,
        merchant_id: uuid.UUID | None = None,
        actor_id: uuid.UUID | None = None,
        actor_type: str = ActorType.USER,
        actor_label: str = "",
        resource: str = "",
        resource_id: str | None = None,
        description: str = "",
        status: str = "SUCCESS",
        request_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        agent_run_id: uuid.UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            merchant_id=merchant_id,
            actor_id=actor_id,
            actor_type=actor_type,
            actor_label=actor_label[:160],
            action=action,
            resource=resource[:48],
            resource_id=str(resource_id)[:64] if resource_id else None,
            description=description,
            status=status,
            request_id=request_id,
            ip_address=ip_address,
            user_agent=(user_agent or "")[:256] or None,
            agent_run_id=agent_run_id,
            metadata_json=metadata or {},
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def list_for_merchant(
        self,
        merchant_id: uuid.UUID,
        *,
        limit: int = 50,
        offset: int = 0,
        action: str | None = None,
        since: datetime | None = None,
    ) -> list[AuditLog]:
        stmt = select(AuditLog).where(AuditLog.merchant_id == merchant_id)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        if since:
            stmt = stmt.where(AuditLog.created_at >= since)
        stmt = stmt.order_by(desc(AuditLog.created_at)).limit(limit).offset(offset)
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_for_merchant(self, merchant_id: uuid.UUID, *, action: str | None = None) -> int:
        stmt = select(func.count()).select_from(AuditLog).where(AuditLog.merchant_id == merchant_id)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        return int((await self.session.execute(stmt)).scalar_one() or 0)

    @staticmethod
    def now() -> datetime:
        return datetime.now(tz=UTC)
