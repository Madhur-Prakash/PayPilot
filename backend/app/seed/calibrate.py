"""Measure the generated dataset without touching a database.

``python -m app.seed.calibrate`` prints the exact figures the dashboard will show,
so the demo story can be verified (and the generator retuned) in a second rather
than by seeding Postgres and clicking around.
"""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from app.db.models.commerce import DayPart
from app.seed.generators.dataset import (
    ANALYSIS_WINDOW,
    CUSTOMER_COUNT,
    HISTORY_DAYS,
    TransactionRecord,
    default_anchor,
    generate_customers,
    generate_transactions,
)


def _window_stats(
    transactions: list[TransactionRecord], start: date, end: date, *, daypart: str | None = None
) -> dict[str, Any]:
    rows = [
        t
        for t in transactions
        if start <= t.business_date <= end and (daypart is None or t.daypart == daypart)
    ]
    revenue = sum(t.net_amount for t in rows)
    orders = len(rows)
    per_customer: dict[str, int] = defaultdict(int)
    returning: set[str] = set()
    for t in rows:
        per_customer[t.customer_ref] += 1
        # `is_repeat` is the lifetime flag: this customer had ordered before.
        if t.is_repeat:
            returning.add(t.customer_ref)
    unique = len(per_customer)
    # Two defensible definitions; the product uses the lifetime one (see below).
    repeat_within_window = sum(1 for count in per_customer.values() if count >= 2)
    repeat_customers = len(returning)
    service = [t.service_minutes for t in rows if t.service_minutes]
    return {
        "revenue": round(revenue, 2),
        "orders": orders,
        "aov": round(revenue / orders, 2) if orders else 0.0,
        "unique_customers": unique,
        "repeat_customers": repeat_customers,
        "repeat_rate": round(repeat_customers / unique * 100, 2) if unique else 0.0,
        "repeat_within_window": repeat_within_window,
        "repeat_rate_window": round(repeat_within_window / unique * 100, 2) if unique else 0.0,
        "avg_service_minutes": round(sum(service) / len(service), 2) if service else 0.0,
        "items_per_order": round(sum(t.item_count for t in rows) / orders, 3) if orders else 0.0,
    }


def _pct(current: float, previous: float) -> float | None:
    if not previous:
        return None
    return round((current - previous) / abs(previous) * 100, 2)


def build(seed: int = 20240917, *, anchor: date | None = None) -> dict[str, Any]:
    rng = random.Random(seed)
    anchor = anchor or default_anchor()
    customers = generate_customers(rng, anchor=anchor, count=CUSTOMER_COUNT)
    transactions = generate_transactions(rng, customers, anchor=anchor, history_days=HISTORY_DAYS)

    cur_start = anchor - timedelta(days=ANALYSIS_WINDOW - 1)
    prev_end = cur_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=ANALYSIS_WINDOW - 1)

    current = _window_stats(transactions, cur_start, anchor)
    previous = _window_stats(transactions, prev_start, prev_end)

    dayparts = {}
    for part in DayPart.ALL:
        cur = _window_stats(transactions, cur_start, anchor, daypart=part)
        prev = _window_stats(transactions, prev_start, prev_end, daypart=part)
        dayparts[part] = {
            "current": cur,
            "previous": prev,
            "revenue_change_pct": _pct(cur["revenue"], prev["revenue"]),
            "repeat_customers_change_pct": _pct(
                float(cur["repeat_customers"]), float(prev["repeat_customers"])
            ),
            "service_change_pct": _pct(cur["avg_service_minutes"], prev["avg_service_minutes"]),
        }

    return {
        "anchor": anchor,
        "total_transactions": len(transactions),
        "total_customers": len(customers),
        "current": current,
        "previous": previous,
        "deltas": {
            "revenue": _pct(current["revenue"], previous["revenue"]),
            "orders": _pct(float(current["orders"]), float(previous["orders"])),
            "aov": _pct(current["aov"], previous["aov"]),
            "repeat_rate": _pct(current["repeat_rate"], previous["repeat_rate"]),
            "repeat_rate_window": _pct(
                current["repeat_rate_window"], previous["repeat_rate_window"]
            ),
            "avg_service_minutes": _pct(
                current["avg_service_minutes"], previous["avg_service_minutes"]
            ),
        },
        "dayparts": dayparts,
        "transactions": transactions,
        "customers": customers,
    }


TARGETS = {
    "revenue": -12.7,
    "orders": -4.2,
    "aov": -8.9,
    "repeat_rate": -18.4,
    "evening_revenue": -27.1,
}


def main() -> None:
    report = build()
    print(f"anchor date         : {report['anchor']}")
    print(f"customers           : {report['total_customers']}")
    print(f"transactions        : {report['total_transactions']}")
    print()
    print("HEADLINE (last 30d vs previous 30d)")
    print(f"{'metric':<22}{'current':>14}{'previous':>14}{'change %':>12}{'target':>10}")
    rows = [
        ("revenue", report["current"]["revenue"], report["previous"]["revenue"], "revenue"),
        ("orders", report["current"]["orders"], report["previous"]["orders"], "orders"),
        ("aov", report["current"]["aov"], report["previous"]["aov"], "aov"),
        (
            "repeat_rate %",
            report["current"]["repeat_rate"],
            report["previous"]["repeat_rate"],
            "repeat_rate",
        ),
    ]
    for label, cur, prev, target_key in rows:
        delta = report["deltas"][target_key]
        target = TARGETS.get(target_key)
        print(
            f"{label:<22}{cur:>14,.2f}{prev:>14,.2f}"
            f"{(delta if delta is not None else 0):>11.2f}%"
            f"{(f'{target:+.1f}%' if target else ''):>10}"
        )
    w = report["deltas"]["repeat_rate_window"]
    print(
        f"{'repeat_rate(win) %':<22}"
        f"{report['current']['repeat_rate_window']:>14,.2f}"
        f"{report['previous']['repeat_rate_window']:>14,.2f}"
        f"{(w if w is not None else 0):>11.2f}%"
    )
    svc = report["deltas"]["avg_service_minutes"]
    print(
        f"{'avg service mins':<22}"
        f"{report['current']['avg_service_minutes']:>14,.2f}"
        f"{report['previous']['avg_service_minutes']:>14,.2f}"
        f"{(svc if svc is not None else 0):>11.2f}%"
    )
    print()
    print("BY DAYPART (revenue change %)")
    for part, data in report["dayparts"].items():
        marker = "  <-- target -27.1%" if part == DayPart.EVENING else ""
        print(
            f"  {part:<12}{data['revenue_change_pct']:>9.2f}%   "
            f"repeat_customers {data['repeat_customers_change_pct']:>8.2f}%   "
            f"service {data['service_change_pct'] or 0:>7.2f}%{marker}"
        )


if __name__ == "__main__":
    main()
