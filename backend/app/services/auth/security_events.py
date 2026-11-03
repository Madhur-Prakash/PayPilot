"""Durable security auditing.

A denied request raises, and the request-scoped session is then rolled back - which
would take the audit row with it. Exactly the events worth keeping (permission
denials, cross-tenant attempts, failed logins) are the ones that would vanish.

These helpers write through an *independent* session that is committed
immediately, so the record survives the rollback of the request that produced it.
Failures here are swallowed: auditing must never convert a 403 into a 500.
"""

from __future__ import annotations

import uuid
from datetime import UTC
from typing import Any

from app.core.logging import get_logger
from app.db.models.audit import ActorType
from app.db.session import session_scope
from app.repositories.merchant import AuditLogRepository

log = get_logger(__name__)


async def record_security_event(
    *,
    action: str,
    merchant_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    actor_type: str = ActorType.USER,
    actor_label: str = "",
    resource: str = "",
    resource_id: str | None = None,
    description: str = "",
    request_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    try:
        async with session_scope() as session:
            await AuditLogRepository(session).record(
                action=action,
                merchant_id=merchant_id,
                actor_id=actor_id,
                actor_type=actor_type,
                actor_label=actor_label,
                resource=resource,
                resource_id=resource_id,
                description=description,
                status="FAILURE",
                request_id=request_id,
                ip_address=ip_address,
                user_agent=user_agent,
                metadata=metadata,
            )
    except Exception as exc:  # pragma: no cover - never break the request
        log.warning("security_audit_failed", action=action, detail=str(exc)[:200])


async def revoke_token_family(family_id: str, *, reason: str) -> int:
    """Revoke an entire refresh-token rotation chain, durably.

    Reuse of an already-rotated token is treated as a compromise, and the request
    that carried it is rejected. The rejection rolls back the request session, so
    revoking in that session would undo the very thing the detection exists to do
    - the attacker's successor token would stay valid.
    """
    from app.repositories.user import RefreshTokenRepository

    try:
        async with session_scope() as session:
            return await RefreshTokenRepository(session).revoke_family(family_id, reason=reason)
    except Exception as exc:  # pragma: no cover
        log.error("token_family_revoke_failed", detail=str(exc)[:200])
        return 0


async def record_failed_login(*, user_id: uuid.UUID, max_attempts: int = 8) -> None:
    """Increment the lockout counter in its own transaction.

    The login request itself raises InvalidCredentialsError and rolls back, so
    without this the counter would reset on every attempt and the soft lock would
    never engage.
    """
    from datetime import datetime, timedelta

    from app.db.models.auth import User

    try:
        async with session_scope() as session:
            user = await session.get(User, user_id)
            if user is None:
                return
            user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
            if user.failed_login_attempts >= max_attempts:
                user.locked_until = datetime.now(tz=UTC) + timedelta(minutes=15)
    except Exception as exc:  # pragma: no cover
        log.warning("failed_login_record_failed", detail=str(exc)[:200])
