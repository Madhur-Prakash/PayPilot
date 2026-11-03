"""The inventory event outbox.

Events are written inside the same transaction as the change that produced them,
then delivered to n8n by :func:`dispatch_pending`. That ordering is the whole
point: a stock decrement and its event either both land or neither does, so a
reorder can never be silently lost because a webhook timed out.

Delivery is at-least-once. Consumers are expected to be idempotent - see
:class:`~app.db.models.automation.ProcessedEvent` and ``claim_event``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.automation import DeliveryStatus, DomainEvent, ProcessedEvent

log = get_logger(__name__)

#: Backoff between delivery attempts. Short, because a reorder that waits an hour
#: is a reorder that arrived too late to matter.
_RETRY_DELAYS = (timedelta(seconds=30), timedelta(minutes=2), timedelta(minutes=10))
_MAX_ATTEMPTS = len(_RETRY_DELAYS) + 1


def new_correlation_id(prefix: str = "INV") -> str:
    """A readable id that ties one automated chain together end to end."""
    return f"{prefix}-{datetime.now(tz=UTC):%Y%m%d}-{uuid.uuid4().hex[:10]}"


def canonical_json(payload: Any) -> bytes:
    """Serialise so an independent implementation can reproduce these exact bytes.

    The signature has to survive a round trip through n8n, where the body is
    parsed into a JavaScript object before anything can look at it. Signing
    whatever ``json.dumps`` happened to emit would not survive that: Python
    writes an integral float as ``13.0`` and JavaScript writes ``13``, so the
    two sides would hash different text and every event would look forged.

    So the wire form is pinned instead - sorted keys, no spaces, no ASCII
    escaping, and integral floats narrowed to ints. Re-serialising the parsed
    object under the same rules gives byte-identical output in either language.
    """

    def narrow(value: Any) -> Any:
        if isinstance(value, bool):
            return value
        if isinstance(value, float) and value.is_integer():
            # 13.0 and 13 are the same quantity; only one of them round-trips.
            return int(value)
        if isinstance(value, dict):
            return {str(k): narrow(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [narrow(v) for v in value]
        return value

    return json.dumps(
        narrow(payload),
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sign(body: bytes) -> str:
    """HMAC-SHA256 of the raw body, hex encoded.

    n8n verifies this before acting on anything, so a leaked webhook URL alone is
    not enough to drive the automation.
    """
    secret = settings.n8n_webhook_secret.encode("utf-8")
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


def verify(body: bytes, signature: str | None) -> bool:
    """Constant-time check of an inbound signature. Fails closed."""
    if not settings.n8n_webhook_secret or not signature:
        return False
    expected = sign(body)
    candidate = signature.split("=", 1)[-1].strip()
    return hmac.compare_digest(expected, candidate)


async def emit(
    session: AsyncSession,
    *,
    merchant_id: uuid.UUID,
    event_type: str,
    correlation_id: str,
    entity_type: str = "",
    entity_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
    source: str = "backend",
) -> DomainEvent:
    """Record an event. Caller owns the transaction; this never commits.

    Nothing is sent here on purpose - see the module docstring.
    """
    event = DomainEvent(
        merchant_id=merchant_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        correlation_id=correlation_id,
        source=source,
        payload=payload or {},
        delivery_status=DeliveryStatus.PENDING,
        next_attempt_at=datetime.now(tz=UTC),
    )
    session.add(event)
    await session.flush()
    return event


async def claim_event(
    session: AsyncSession,
    *,
    merchant_id: uuid.UUID,
    scope: str,
    event_key: str,
    result_ref: str = "",
) -> bool:
    """Claim an event for one consumer. ``False`` means it was already handled.

    The unique index does the work: a duplicate delivery loses the race at the
    database rather than in application logic, which is what makes this safe
    under concurrency rather than merely usually correct.
    """
    session.add(
        ProcessedEvent(
            merchant_id=merchant_id,
            scope=scope,
            event_key=event_key,
            result_ref=result_ref,
        )
    )
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        log.info("event_already_processed", scope=scope, event_key=event_key)
        return False
    return True


def envelope(event: DomainEvent) -> dict[str, Any]:
    """The wire format n8n receives. Documented in n8n/README.md."""
    return {
        "event_id": str(event.id),
        "event_type": event.event_type,
        "merchant_id": str(event.merchant_id),
        "entity_type": event.entity_type,
        "entity_id": str(event.entity_id) if event.entity_id else None,
        "correlation_id": event.correlation_id,
        "source": event.source,
        "timestamp": event.created_at.isoformat() if event.created_at else None,
        "payload": event.payload or {},
    }


#: How long a claimed event is reserved for. Long enough to cover the HTTP
#: timeout below, short enough that a crashed worker's events are retried soon.
_LEASE = timedelta(seconds=90)

_TIMEOUT = httpx.Timeout(20.0)


async def _skip_unconfigured(session: AsyncSession, limit: int) -> dict[str, int]:
    """Nothing is listening, so stop the queue growing without bound."""
    rows = list(
        (
            await session.execute(
                select(DomainEvent)
                .where(DomainEvent.delivery_status == DeliveryStatus.PENDING)
                .limit(limit)
            )
        ).scalars().all()
    )
    for event in rows:
        event.delivery_status = DeliveryStatus.SKIPPED
        event.last_error = "No N8N_INVENTORY_WEBHOOK_URL configured."
    if rows:
        await session.commit()
    return {"delivered": 0, "failed": 0, "skipped": len(rows)}


async def _claim_batch(
    session: AsyncSession, limit: int
) -> list[tuple[uuid.UUID, bytes, str, str, int]]:
    """Reserve a batch of due events, in one short transaction.

    Claiming and sending have to be separate. The delivery loop makes HTTP calls
    that can take tens of seconds, and holding row locks across them would park a
    transaction on the database for the duration. So this marks the batch as
    in-flight by pushing ``next_attempt_at`` beyond the lease and commits
    immediately; the sending happens with nothing held.

    ``SKIP LOCKED`` is what makes more than one web worker safe: each relay tick
    takes a disjoint batch instead of every worker grabbing the same rows and
    delivering them all over again.
    """
    now = datetime.now(tz=UTC)
    stmt = (
        select(DomainEvent)
        .where(
            DomainEvent.delivery_status == DeliveryStatus.PENDING,
            (DomainEvent.next_attempt_at.is_(None)) | (DomainEvent.next_attempt_at <= now),
        )
        .order_by(DomainEvent.created_at)
        .limit(limit)
    )
    # SQLite, which the tests run on, has no row locking and errors on the clause.
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)

    events = list((await session.execute(stmt)).scalars().all())
    if not events:
        return []

    claimed = []
    for event in events:
        event.attempts += 1
        event.next_attempt_at = now + _LEASE
        claimed.append(
            (
                event.id,
                canonical_json(envelope(event)),
                event.correlation_id,
                event.event_type,
                event.attempts,
            )
        )
    await session.commit()
    return claimed


async def _settle(
    session: AsyncSession,
    event_id: uuid.UUID,
    *,
    error: str | None,
    attempts: int,
) -> None:
    """Record the outcome of one delivery."""
    event = await session.get(DomainEvent, event_id)
    if event is None:
        return

    if error is None:
        event.delivery_status = DeliveryStatus.DELIVERED
        event.delivered_at = datetime.now(tz=UTC)
        event.last_error = ""
        event.next_attempt_at = None
    elif attempts >= _MAX_ATTEMPTS:
        event.delivery_status = DeliveryStatus.FAILED
        event.last_error = error
        event.next_attempt_at = None
    else:
        # Back to PENDING with the normal backoff, replacing the lease.
        event.last_error = error
        event.next_attempt_at = datetime.now(tz=UTC) + _RETRY_DELAYS[attempts - 1]
    await session.commit()


async def dispatch_pending(session: AsyncSession, *, limit: int = 50) -> dict[str, int]:
    """Deliver due events to n8n. Safe to call repeatedly and concurrently.

    Runs outside the producing transaction, so a slow or dead n8n slows nothing
    down but this loop.
    """
    if not settings.n8n_inventory_webhook_url:
        return await _skip_unconfigured(session, limit)

    claimed = await _claim_batch(session, limit)
    if not claimed:
        return {"delivered": 0, "failed": 0, "skipped": 0}

    delivered = failed = 0
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for event_id, body, correlation_id, event_type, attempts in claimed:
            error: str | None = None
            try:
                response = await client.post(
                    settings.n8n_inventory_webhook_url,
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-Signature": f"sha256={sign(body)}",
                        "X-Event-Id": str(event_id),
                        "X-Correlation-Id": correlation_id,
                    },
                )
                response.raise_for_status()
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"[:400]

            await _settle(session, event_id, error=error, attempts=attempts)

            if error is None:
                delivered += 1
            elif attempts >= _MAX_ATTEMPTS:
                failed += 1
                log.error(
                    "event_delivery_exhausted",
                    event_id=str(event_id),
                    event_type=event_type,
                    attempts=attempts,
                    error=error,
                )
            else:
                log.warning(
                    "event_delivery_retry",
                    event_id=str(event_id),
                    attempt=attempts,
                    error=error,
                )

    return {"delivered": delivered, "failed": failed, "skipped": 0}
