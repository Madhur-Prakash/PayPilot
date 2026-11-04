"""Human approvals for money-moving actions.

An approval is bound to the exact terms it authorises. ``details`` is the
canonical description of the action (supplier, unit price, quantity, total,
payee, policy version ...) and ``details_hash`` its SHA-256. Both at decision
time and at execution time the caller rebuilds ``details`` from *live* state; if
the hash differs, the approval is invalidated and a new one is required.

Rules enforced here, regardless of which endpoint or tool calls in:

* only a human can decide - agents may *request*, never approve;
* the decider must hold the action's permission, re-checked server side;
* this applies to Owners too - there is no bypass;
* an approval is consumed by exactly one execution;
* pending approvals expire.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ApprovalRequiredError,
    BadRequestError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.logging import get_logger
from app.db.models.audit import ActorType, AuditAction
from app.db.models.governance import ApprovalAction, ApprovalRequest, ApprovalStatus
from app.repositories.merchant import AuditLogRepository
from app.services.supply.policy import money, serialisable, sha256

log = get_logger(__name__)

DEFAULT_TTL = timedelta(hours=72)


def hash_details(details: dict[str, Any]) -> str:
    return sha256(serialisable(details))


class ApprovalService:
    def __init__(self, session: AsyncSession, merchant_id: uuid.UUID) -> None:
        self.session = session
        self.merchant_id = merchant_id
        self.audit = AuditLogRepository(session)

    # ------------------------------------------------------------------ read
    async def get(self, approval_id: uuid.UUID) -> ApprovalRequest:
        row = (
            await self.session.execute(
                select(ApprovalRequest).where(
                    ApprovalRequest.id == approval_id, ApprovalRequest.merchant_id == self.merchant_id
                )
            )
        ).scalars().first()
        if row is None:
            raise NotFoundError("Approval request not found.")
        return row

    async def open_for(self, *, resource_type: str, resource_id: uuid.UUID, action: str) -> ApprovalRequest | None:
        return (
            await self.session.execute(
                select(ApprovalRequest)
                .where(
                    ApprovalRequest.merchant_id == self.merchant_id,
                    ApprovalRequest.resource_type == resource_type,
                    ApprovalRequest.resource_id == resource_id,
                    ApprovalRequest.action == action,
                    ApprovalRequest.status.in_(ApprovalStatus.OPEN),
                )
                .order_by(ApprovalRequest.created_at.desc())
            )
        ).scalars().first()

    async def list(
        self, *, status: str | None = None, limit: int = 50, offset: int = 0
    ) -> tuple[list[ApprovalRequest], int, dict[str, int]]:
        conditions = [ApprovalRequest.merchant_id == self.merchant_id]
        if status:
            conditions.append(ApprovalRequest.status == status)
        rows = (
            await self.session.execute(
                select(ApprovalRequest)
                .where(*conditions)
                .order_by(ApprovalRequest.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
        total = (
            await self.session.execute(select(func.count()).select_from(ApprovalRequest).where(*conditions))
        ).scalar_one()
        counts = dict(
            (
                await self.session.execute(
                    select(ApprovalRequest.status, func.count())
                    .where(ApprovalRequest.merchant_id == self.merchant_id)
                    .group_by(ApprovalRequest.status)
                )
            ).all()
        )
        return list(rows), int(total), {k: int(v) for k, v in counts.items()}

    # ------------------------------------------------------------------ request
    async def _next_reference(self) -> str:
        count = (
            await self.session.execute(
                select(func.count()).select_from(ApprovalRequest).where(ApprovalRequest.merchant_id == self.merchant_id)
            )
        ).scalar_one()
        return f"APR-{int(count) + 1:05d}"

    async def request(
        self,
        *,
        action: str,
        resource_type: str,
        resource_id: uuid.UUID,
        title: str,
        summary: str,
        amount: Decimal,
        currency: str,
        details: dict[str, Any],
        policy_version: str,
        required_permission: str,
        risk_flags: list[str] | None = None,
        requested_by_type: str = ActorType.AGENT,
        requested_by_id: uuid.UUID | None = None,
        requested_by_label: str = "Buyer Agent",
        correlation_id: str = "",
        procurement_request_id: uuid.UUID | None = None,
        ttl: timedelta = DEFAULT_TTL,
    ) -> ApprovalRequest:
        # A newer request for the same thing supersedes the old one.
        previous = await self.open_for(resource_type=resource_type, resource_id=resource_id, action=action)
        if previous is not None:
            previous.status = ApprovalStatus.INVALIDATED
            previous.invalidated_reason = "Superseded by a newer approval request."

        canonical_details = serialisable(details)
        approval = ApprovalRequest(
            merchant_id=self.merchant_id,
            reference=await self._next_reference(),
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            title=title[:255],
            summary=summary,
            amount=money(amount),
            currency=currency,
            details=canonical_details,
            details_hash=hash_details(canonical_details),
            policy_version=policy_version,
            required_permission=required_permission,
            risk_flags=risk_flags or [],
            status=ApprovalStatus.PENDING,
            requested_by_type=requested_by_type,
            requested_by_id=requested_by_id,
            requested_by_label=requested_by_label[:160],
            expires_at=datetime.now(tz=UTC) + ttl,
            correlation_id=correlation_id,
            procurement_request_id=procurement_request_id,
        )
        self.session.add(approval)
        await self.session.flush()
        await self.audit.record(
            action=AuditAction.APPROVAL_REQUESTED,
            merchant_id=self.merchant_id,
            actor_id=requested_by_id,
            actor_type=requested_by_type,
            actor_label=requested_by_label,
            resource="approval",
            resource_id=str(approval.id),
            description=f"{approval.reference}: {title} ({currency} {money(amount):,.2f})",
            metadata={"action": action, "details_hash": approval.details_hash, "policy_version": policy_version},
        )
        return approval

    # ------------------------------------------------------------------ decide
    async def decide(
        self,
        approval_id: uuid.UUID,
        *,
        approve: bool,
        user_id: uuid.UUID,
        user_label: str,
        permissions: frozenset[str],
        live_details: dict[str, Any] | None,
        note: str = "",
        request_id: str | None = None,
    ) -> ApprovalRequest:
        approval = await self.get(approval_id)
        self._expire_if_due(approval)
        if approval.status != ApprovalStatus.PENDING:
            raise ConflictError(
                f"{approval.reference} is {approval.status.lower()} and cannot be decided.",
                details={"status": approval.status},
            )
        if approval.required_permission not in permissions:
            # Defence in depth: the endpoint already checked, this re-checks.
            raise PermissionDeniedError(
                "Your role cannot approve this action.",
                details={"required_permission": approval.required_permission},
            )
        if approve and live_details is not None and hash_details(live_details) != approval.details_hash:
            await self._invalidate(approval, "Terms changed after the request was raised.", user_id, user_label)
            raise ConflictError(
                f"{approval.reference} was invalidated: the underlying terms changed. A new approval is required.",
                details={"code": "APPROVAL_INVALIDATED"},
            )

        approval.status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
        approval.decided_by_id = user_id
        approval.decided_by_label = user_label[:160]
        approval.decided_at = datetime.now(tz=UTC)
        approval.decision_note = note
        await self.session.flush()
        await self.audit.record(
            action=AuditAction.APPROVAL_GRANTED if approve else AuditAction.APPROVAL_REJECTED,
            merchant_id=self.merchant_id,
            actor_id=user_id,
            actor_type=ActorType.USER,
            actor_label=user_label,
            resource="approval",
            resource_id=str(approval.id),
            description=f"{approval.reference} {'approved' if approve else 'rejected'}: {approval.title}",
            request_id=request_id,
            metadata={
                "action": approval.action,
                "amount": str(approval.amount),
                "currency": approval.currency,
                "details_hash": approval.details_hash,
                "policy_version": approval.policy_version,
                "note": note,
            },
        )
        return approval

    # ------------------------------------------------------------------ consume
    async def consume(
        self, approval_id: uuid.UUID, *, live_details: dict[str, Any], actor_id: uuid.UUID | None = None
    ) -> ApprovalRequest:
        """Bind one execution to one approval. Raises unless approved and unchanged."""
        approval = await self.get(approval_id)
        self._expire_if_due(approval)
        if approval.status == ApprovalStatus.EXECUTED:
            raise ConflictError(f"{approval.reference} has already been executed.")
        if approval.status != ApprovalStatus.APPROVED:
            raise ApprovalRequiredError(
                f"{approval.reference} is {approval.status.lower()} - a human approval is required first."
            )
        if hash_details(live_details) != approval.details_hash:
            await self._invalidate(approval, "Terms changed after approval.", actor_id, "system")
            raise ConflictError(
                f"{approval.reference} was invalidated: the terms changed after approval. Re-approval required.",
                details={"code": "APPROVAL_INVALIDATED"},
            )
        approval.status = ApprovalStatus.EXECUTED
        approval.executed_at = datetime.now(tz=UTC)
        await self.session.flush()
        return approval

    async def invalidate_open(self, *, resource_type: str, resource_id: uuid.UUID, reason: str) -> int:
        rows = (
            await self.session.execute(
                select(ApprovalRequest).where(
                    ApprovalRequest.merchant_id == self.merchant_id,
                    ApprovalRequest.resource_type == resource_type,
                    ApprovalRequest.resource_id == resource_id,
                    ApprovalRequest.status.in_(ApprovalStatus.OPEN),
                )
            )
        ).scalars().all()
        for row in rows:
            await self._invalidate(row, reason, None, "system")
        return len(rows)

    # ------------------------------------------------------------------ internals
    @staticmethod
    def _expire_if_due(approval: ApprovalRequest) -> None:
        if approval.status == ApprovalStatus.PENDING and approval.expires_at:
            expires = approval.expires_at if approval.expires_at.tzinfo else approval.expires_at.replace(tzinfo=UTC)
            if expires < datetime.now(tz=UTC):
                approval.status = ApprovalStatus.EXPIRED

    async def _invalidate(
        self, approval: ApprovalRequest, reason: str, actor_id: uuid.UUID | None, actor_label: str
    ) -> None:
        """Invalidate durably.

        The caller is usually about to raise, which rolls the request session
        back - so the invalidation is also written on its own short transaction,
        exactly like the security audit trail. Otherwise a stale approval could be
        retried and succeed after the terms were changed back.
        """
        approval.status = ApprovalStatus.INVALIDATED
        approval.invalidated_reason = reason
        try:
            from sqlalchemy import update

            import app.db.session as db_session
            from app.db.models.audit import AuditLog

            async with db_session.SessionLocal() as durable:
                await durable.execute(
                    update(ApprovalRequest)
                    .where(ApprovalRequest.id == approval.id)
                    .values(status=ApprovalStatus.INVALIDATED, invalidated_reason=reason)
                )
                durable.add(
                    AuditLog(
                        merchant_id=self.merchant_id,
                        actor_id=actor_id,
                        actor_type=ActorType.SYSTEM,
                        actor_label=actor_label[:160],
                        action=AuditAction.APPROVAL_INVALIDATED,
                        resource="approval",
                        resource_id=str(approval.id),
                        description=f"{approval.reference} invalidated: {reason}",
                        status="FAILURE",
                        metadata_json={"details_hash": approval.details_hash},
                    )
                )
                await durable.commit()
        except Exception as exc:  # never mask the original failure
            log.warning("approval_invalidation_persist_failed", detail=str(exc)[:200])
            await self.session.flush()


def describe_approval(approval: ApprovalRequest) -> dict[str, Any]:
    return {
        "approval_id": str(approval.id),
        "reference": approval.reference,
        "action": approval.action,
        "action_label": ApprovalAction.LABELS.get(approval.action, approval.action),
        "resource_type": approval.resource_type,
        "resource_id": str(approval.resource_id),
        "title": approval.title,
        "summary": approval.summary,
        "amount": str(approval.amount),
        "currency": approval.currency,
        "details": approval.details,
        "details_hash": approval.details_hash,
        "policy_version": approval.policy_version,
        "required_permission": approval.required_permission,
        "risk_flags": approval.risk_flags or [],
        "status": approval.status,
        "requested_by_type": approval.requested_by_type,
        "requested_by_label": approval.requested_by_label,
        "decided_by_label": approval.decided_by_label,
        "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
        "decision_note": approval.decision_note,
        "expires_at": approval.expires_at.isoformat() if approval.expires_at else None,
        "invalidated_reason": approval.invalidated_reason,
        "executed_at": approval.executed_at.isoformat() if approval.executed_at else None,
        "correlation_id": approval.correlation_id,
        "procurement_request_id": str(approval.procurement_request_id) if approval.procurement_request_id else None,
        "created_at": approval.created_at.isoformat() if approval.created_at else None,
    }


__all__ = ["ApprovalService", "BadRequestError", "describe_approval", "hash_details"]
