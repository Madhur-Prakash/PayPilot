"""Transaction synchronisation and transaction intelligence.

Sync is incremental and safe to repeat:

* it resumes from the stored checkpoint (``paypal_sync_checkpoints``), re-reading a
  small overlap because Transaction Search data can arrive up to a few hours late;
* the gateway splits the range into <= 31-day windows (PayPal's per-call limit) and
  pages through each;
* rows upsert on ``(merchant_id, paypal_transaction_id)``, so an overlap updates
  rather than duplicates;
* currencies are never mixed - analytics group by currency.

Intelligence (totals, refund rate, fees, repeat payers, daily series) is computed
in SQL/Decimal from the synced rows. Nothing here is estimated by a model.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.audit import ActorType, AuditAction
from app.db.models.paypal import PayPalSyncCheckpoint, PayPalTransactionRecord
from app.integrations.paypal import (
    PayPalAPIError,
    PayPalTransaction,
    get_paypal_gateway,
    split_windows,
)
from app.repositories.merchant import AuditLogRepository
from app.services.supply.policy import ZERO, D, money, pct

log = get_logger(__name__)

RESOURCE = "transactions"
DEFAULT_BACKFILL = timedelta(days=90)
#: Re-read this much before the checkpoint - PayPal reporting can lag.
OVERLAP = timedelta(hours=6)
MAX_BACKFILL = timedelta(days=3 * 365)


def payer_hash(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest() if email else ""


class TransactionSyncService:
    def __init__(self, session: AsyncSession, merchant_id: uuid.UUID) -> None:
        self.session = session
        self.merchant_id = merchant_id

    async def checkpoint(self) -> PayPalSyncCheckpoint:
        row = (
            await self.session.execute(
                select(PayPalSyncCheckpoint).where(
                    PayPalSyncCheckpoint.merchant_id == self.merchant_id,
                    PayPalSyncCheckpoint.resource == RESOURCE,
                )
            )
        ).scalars().first()
        if row is None:
            row = PayPalSyncCheckpoint(merchant_id=self.merchant_id, resource=RESOURCE)
            self.session.add(row)
            await self.session.flush()
        return row

    async def sync(
        self,
        *,
        days: int | None = None,
        until: datetime | None = None,
        actor_id: uuid.UUID | None = None,
        actor_label: str = "system",
    ) -> dict[str, Any]:
        gateway = get_paypal_gateway()
        checkpoint = await self.checkpoint()
        end = (until or datetime.now(tz=UTC)).replace(microsecond=0)
        if days is not None:
            start = end - timedelta(days=max(1, min(days, MAX_BACKFILL.days)))
        elif checkpoint.synced_until is not None:
            last = checkpoint.synced_until if checkpoint.synced_until.tzinfo else checkpoint.synced_until.replace(tzinfo=UTC)
            start = last - OVERLAP
        else:
            start = end - DEFAULT_BACKFILL

        inserted = updated = 0
        windows = len(split_windows(start, end))
        try:
            async for txn in gateway.iter_transactions(start=start, end=end, page_size=200):
                created = await self._upsert(txn, gateway.mode)
                inserted += int(created)
                updated += int(not created)
            checkpoint.synced_until = end
            checkpoint.last_status = "OK"
            checkpoint.last_error = ""
        except PayPalAPIError as exc:
            checkpoint.last_status = "FAILED"
            checkpoint.last_error = f"{exc.message} (debug_id {exc.debug_id})"[:2000]
            log.warning("paypal_sync_failed", detail=exc.message, debug_id=exc.debug_id)
        checkpoint.last_run_at = datetime.now(tz=UTC)
        checkpoint.items_last_run = inserted + updated
        checkpoint.items_total = int(
            (
                await self.session.execute(
                    select(func.count()).select_from(PayPalTransactionRecord).where(
                        PayPalTransactionRecord.merchant_id == self.merchant_id
                    )
                )
            ).scalar_one()
        )
        checkpoint.mode = gateway.mode
        await self.session.flush()

        await AuditLogRepository(self.session).record(
            action=AuditAction.PAYPAL_SYNC,
            merchant_id=self.merchant_id,
            actor_id=actor_id,
            actor_type=ActorType.USER if actor_id else ActorType.SYSTEM,
            actor_label=actor_label,
            resource="paypal",
            resource_id=RESOURCE,
            description=f"Synced {inserted} new and {updated} updated PayPal transactions ({gateway.mode}).",
            status="SUCCESS" if checkpoint.last_status == "OK" else "FAILURE",
            metadata={"start": start.isoformat(), "end": end.isoformat(), "windows": windows},
        )
        return {
            "mode": gateway.mode,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "windows": windows,
            "inserted": inserted,
            "updated": updated,
            "status": checkpoint.last_status,
            "error": checkpoint.last_error,
            "total_synced": checkpoint.items_total,
        }

    async def _upsert(self, txn: PayPalTransaction, mode: str) -> bool:
        row = (
            await self.session.execute(
                select(PayPalTransactionRecord).where(
                    PayPalTransactionRecord.merchant_id == self.merchant_id,
                    PayPalTransactionRecord.paypal_transaction_id == txn.transaction_id,
                )
            )
        ).scalars().first()
        created = row is None
        if row is None:
            row = PayPalTransactionRecord(merchant_id=self.merchant_id, paypal_transaction_id=txn.transaction_id)
            self.session.add(row)
        row.event_code = txn.event_code
        row.status_code = txn.status
        row.category = txn.category
        row.currency = txn.gross.currency_code
        row.gross_amount = money(txn.gross.value)
        row.fee_amount = money(txn.fee.value if txn.fee else 0)
        row.net_amount = money(txn.net)
        row.initiated_at = txn.initiated_at
        row.updated_at_paypal = txn.updated_at
        row.invoice_id = txn.invoice_id[:127]
        row.custom_field = txn.custom_field[:255]
        row.payer_hash = payer_hash(txn.payer_email)
        row.payer_name = txn.payer_name[:160]
        row.item_count = txn.item_count
        row.mode = mode
        row.synced_at = datetime.now(tz=UTC)
        # Keep the raw record minus payer PII beyond the hash.
        raw = dict(txn.raw or {})
        raw.pop("payer_info", None)
        row.raw = raw
        await self.session.flush()
        return created


# --------------------------------------------------------------------------- #
# Transaction intelligence
# --------------------------------------------------------------------------- #
async def transaction_intelligence(
    session: AsyncSession, merchant_id: uuid.UUID, *, days: int = 30
) -> dict[str, Any]:
    """Deterministic analytics over synced PayPal transactions, per currency."""
    latest = (
        await session.execute(
            select(func.max(PayPalTransactionRecord.initiated_at)).where(
                PayPalTransactionRecord.merchant_id == merchant_id
            )
        )
    ).scalar_one_or_none()
    if latest is None:
        return {"has_data": False, "currencies": {}, "days": days}
    anchor = latest if latest.tzinfo else latest.replace(tzinfo=UTC)
    start = anchor - timedelta(days=days)
    prev_start = start - timedelta(days=days)

    rows = (
        await session.execute(
            select(PayPalTransactionRecord).where(
                PayPalTransactionRecord.merchant_id == merchant_id,
                PayPalTransactionRecord.initiated_at >= prev_start,
            )
        )
    ).scalars().all()

    by_currency: dict[str, dict[str, Any]] = {}
    for currency in sorted({r.currency for r in rows}):
        current = [r for r in rows if r.currency == currency and _aware(r.initiated_at) >= start]
        previous = [r for r in rows if r.currency == currency and _aware(r.initiated_at) < start]
        by_currency[currency] = _summarise(current, previous, start, anchor)
    modes = sorted({r.mode for r in rows})
    return {
        "has_data": True,
        "days": days,
        "period_start": start.isoformat(),
        "period_end": anchor.isoformat(),
        "modes": modes,
        "is_simulated": modes == ["SIMULATED"],
        "currencies": by_currency,
    }


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _summarise(current: list[PayPalTransactionRecord], previous: list[PayPalTransactionRecord],
               start: datetime, end: datetime) -> dict[str, Any]:
    def stats(rows: list[PayPalTransactionRecord]) -> dict[str, Decimal | int]:
        payments = [r for r in rows if r.category == "PAYMENT" and r.status_code in ("S", "")]
        failed = [r for r in rows if r.category == "PAYMENT" and r.status_code == "D"]
        refunds = [r for r in rows if r.category == "REFUND"]
        gross = sum((D(r.gross_amount) for r in payments), ZERO)
        refunded = -sum((D(r.gross_amount) for r in refunds), ZERO)
        fees = -sum((D(r.fee_amount) for r in payments), ZERO)
        payers: dict[str, int] = defaultdict(int)
        for r in payments:
            if r.payer_hash:
                payers[r.payer_hash] += 1
        repeat = sum(1 for count in payers.values() if count > 1)
        return {
            "payments": len(payments),
            "failed": len(failed),
            "refunds": len(refunds),
            "gross": money(gross),
            "refunded": money(refunded),
            "fees": money(fees),
            "net": money(gross - refunded - fees),
            "unique_payers": len(payers),
            "repeat_payers": repeat,
        }

    now, before = stats(current), stats(previous)
    aov = money(D(now["gross"]) / now["payments"]) if now["payments"] else ZERO
    daily: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for r in current:
        if r.category == "PAYMENT":
            daily[_aware(r.initiated_at).date().isoformat()] += D(r.gross_amount)
    series = []
    day = start.date()
    while day <= end.date():
        key = day.isoformat()
        series.append({"date": key, "gross": str(money(daily.get(key, ZERO)))})
        day += timedelta(days=1)
    attempts = int(now["payments"]) + int(now["failed"])
    return {
        "transactions": int(now["payments"]),
        "gross_revenue": str(now["gross"]),
        "net_revenue": str(now["net"]),
        "fees": str(now["fees"]),
        "refunded": str(now["refunded"]),
        "refund_count": int(now["refunds"]),
        "refund_rate_pct": str(pct(now["refunded"], now["gross"])),
        "payment_failure_rate_pct": str(pct(now["failed"], attempts)) if attempts else "0.00",
        "average_order_value": str(aov),
        "unique_payers": int(now["unique_payers"]),
        "repeat_payers": int(now["repeat_payers"]),
        "repeat_payer_rate_pct": str(pct(now["repeat_payers"], now["unique_payers"])),
        "gross_change_pct": str(pct(D(now["gross"]) - D(before["gross"]), before["gross"])) if before["gross"] else None,
        "previous_gross_revenue": str(before["gross"]),
        "daily": series,
    }
