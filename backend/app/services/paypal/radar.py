"""Subscription revenue radar: every PayPal subscriber on one timeline.

One row per subscription, one bar per billing period. Paid periods, the period
whose charge failed, PayPal's automatic retries, a suspension and a recovery all
land on the row as events, and upcoming periods are projected so the merchant can
see which renewals are safe and which revenue is about to slip. The frontend draws
it with Bryntum Scheduler.

Everything is derived from ``PayPalSubscriptionRecord`` - the billing anchor is
``next_billing_at``, stepped back one interval at a time to ``started_at`` - plus
the lifecycle history ``subscription_action`` stamps into ``raw["events"]``.
Nothing here invents a payment the record does not imply.
"""

from __future__ import annotations

import calendar
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.db.models.paypal import PayPalSubscriptionRecord

#: PayPal retries a failed subscription charge on a schedule; the radar draws one
#: retry marker per failed attempt, this many days apart.
RETRY_SPACING_DAYS = 3
MAX_PERIODS_BACK = 24


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def add_interval(value: datetime, interval: str, steps: int) -> datetime:
    """Step a billing date by whole intervals, clamping to the end of short months."""
    unit = (interval or "MONTH").upper()
    if unit == "DAY":
        return value + timedelta(days=steps)
    if unit == "WEEK":
        return value + timedelta(weeks=steps)
    months = steps * (12 if unit == "YEAR" else 1)
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def risk_of(row: PayPalSubscriptionRecord) -> str:
    if row.status == "CANCELLED":
        return "cancelled"
    if row.status == "SUSPENDED":
        return "suspended"
    if row.failed_payments > 0:
        return "at_risk"
    return "healthy"


def _history(row: PayPalSubscriptionRecord) -> list[dict[str, Any]]:
    events = (row.raw or {}).get("events") or []
    return [e for e in events if isinstance(e, dict) and e.get("at")]


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _money(value: Decimal) -> str:
    return format(Decimal(value).quantize(Decimal("0.01")), "f")


def _show(value: Decimal, currency: str) -> str:
    """Display form for bar labels: $32.00, or 32.00 EUR for other currencies."""
    amount = f"{Decimal(value).quantize(Decimal('0.01')):,}"
    return f"${amount}" if currency == "USD" else f"{amount} {currency}"


def build_radar(
    rows: Sequence[PayPalSubscriptionRecord],
    *,
    now: datetime | None = None,
    days_back: int = 120,
    days_ahead: int = 60,
) -> dict[str, Any]:
    now = _aware(now) or datetime.now(tz=UTC)
    window_start = now - timedelta(days=days_back)
    window_end = now + timedelta(days=days_ahead)
    next_30 = now + timedelta(days=30)

    resources: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    collected = Decimal("0")
    projected_safe = Decimal("0")
    projected_at_risk = Decimal("0")
    recovered = 0
    renewals_7 = 0

    for row in rows:
        rid = str(row.id)
        risk = risk_of(row)
        amount = Decimal(row.amount or 0)
        next_bill = _aware(row.next_billing_at) or add_interval(now, row.interval, 1)
        started = _aware(row.started_at) or add_interval(next_bill, row.interval, -MAX_PERIODS_BACK)
        history = _history(row)
        shown = _show(amount, row.currency)
        recovered_at = max(
            (_aware(datetime.fromisoformat(e["at"])) for e in history if e.get("type") in ("recover", "activate")),
            default=None,
        )
        suspended_at = max(
            (_aware(datetime.fromisoformat(e["at"])) for e in history if e.get("type") == "suspend"),
            default=None,
        )
        cancelled_at = max(
            (_aware(datetime.fromisoformat(e["at"])) for e in history if e.get("type") == "cancel"),
            default=None,
        )
        if recovered_at:
            recovered += 1
        if risk in ("healthy", "at_risk") and now <= next_bill <= now + timedelta(days=7):
            renewals_7 += 1

        resources.append({
            "id": rid,
            "name": row.subscriber_name or row.paypal_subscription_id,
            "plan": row.plan_name,
            "status": row.status,
            "risk": risk,
            "amount": _money(amount),
            "currency": row.currency,
            "interval": row.interval,
            "failed_payments": row.failed_payments,
            "next_billing_at": _iso(next_bill),
            "paypal_subscription_id": row.paypal_subscription_id,
            "mode": row.mode,
        })

        # ---- past periods, newest first: the current one is [next_bill - 1, next_bill)
        current_start = add_interval(next_bill, row.interval, -1)
        failed_current = row.failed_payments > 0 and recovered_at is None
        for step in range(1, MAX_PERIODS_BACK + 1):
            start = add_interval(next_bill, row.interval, -step)
            end = add_interval(next_bill, row.interval, -step + 1)
            if end <= window_start or start < started - timedelta(days=1):
                break
            is_current = step == 1
            if is_current and (failed_current or row.status == "SUSPENDED") and not recovered_at:
                kind, label = "failed", f"Charge failed · {shown}"
            else:
                kind, label = "paid", f"Paid · {shown}"
                if start >= window_start:
                    collected += amount
            events.append({
                "id": f"{rid}:p{step}",
                "resourceId": rid,
                "startDate": _iso(start),
                "endDate": _iso(end),
                "name": label,
                "kind": kind,
                "amount": _money(amount),
            })

        # ---- PayPal's automatic retries after the failed charge
        if row.failed_payments > 0 and not recovered_at:
            for attempt in range(1, row.failed_payments + 1):
                at = current_start + timedelta(days=RETRY_SPACING_DAYS * attempt)
                events.append({
                    "id": f"{rid}:r{attempt}",
                    "resourceId": rid,
                    "startDate": _iso(at),
                    "endDate": _iso(at),
                    "name": f"Retry {attempt} failed",
                    "kind": "retry",
                    "amount": _money(amount),
                })
        if row.status == "SUSPENDED":
            at = suspended_at or current_start + timedelta(days=RETRY_SPACING_DAYS * (row.failed_payments + 1))
            events.append({
                "id": f"{rid}:s", "resourceId": rid, "startDate": _iso(at), "endDate": _iso(at),
                "name": "Suspended by PayPal" if suspended_at is None else "Paused", "kind": "suspended",
                "amount": _money(amount),
            })
        if recovered_at:
            events.append({
                "id": f"{rid}:rec", "resourceId": rid, "startDate": _iso(recovered_at), "endDate": _iso(recovered_at),
                "name": "Recovered", "kind": "recovered", "amount": _money(amount),
            })
        if cancelled_at or row.status == "CANCELLED":
            at = cancelled_at or now
            events.append({
                "id": f"{rid}:c", "resourceId": rid, "startDate": _iso(at), "endDate": _iso(at),
                "name": "Cancelled", "kind": "cancelled", "amount": _money(amount),
            })
            continue

        # ---- upcoming renewals
        for step in range(0, 24):
            start = add_interval(next_bill, row.interval, step)
            if start >= window_end:
                break
            end = add_interval(next_bill, row.interval, step + 1)
            if risk == "suspended":
                kind, label = "paused", f"Paused · {shown} at stake"
            elif risk == "at_risk" and step == 0:
                kind, label = "at_risk", f"Renewal at risk · {shown}"
            else:
                kind, label = "scheduled", f"Renews · {shown}"
            if start < next_30:
                if kind == "scheduled":
                    projected_safe += amount
                else:
                    projected_at_risk += amount
            events.append({
                "id": f"{rid}:n{step}",
                "resourceId": rid,
                "startDate": _iso(start),
                "endDate": _iso(end),
                "name": label,
                "kind": kind,
                "amount": _money(amount),
            })

    order = {"suspended": 0, "at_risk": 1, "healthy": 2, "cancelled": 3}
    resources.sort(key=lambda r: (order.get(r["risk"], 9), r["next_billing_at"]))
    active = [r for r in rows if r.status == "ACTIVE"]
    return {
        "window": {"start": _iso(window_start), "end": _iso(window_end), "now": _iso(now)},
        "resources": resources,
        "events": events,
        "summary": {
            "subscribers": len(rows),
            "active": len(active),
            "monthly_recurring_revenue": _money(sum((Decimal(r.amount) for r in active), Decimal("0"))),
            "at_risk_revenue": _money(
                sum((Decimal(r.amount) for r in rows if risk_of(r) in ("at_risk", "suspended")), Decimal("0"))
            ),
            "at_risk": sum(1 for r in rows if risk_of(r) in ("at_risk", "suspended")),
            "collected_in_window": _money(collected),
            "projected_next_30_days": _money(projected_safe),
            "at_risk_next_30_days": _money(projected_at_risk),
            "renewals_next_7_days": renewals_7,
            "recovered": recovered,
            "currency": rows[0].currency if rows else "USD",
        },
    }


__all__ = ["add_interval", "build_radar", "risk_of"]
