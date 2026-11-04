"""Deterministic dataset generator for the Juniper & Oak Coffee demo.

Pure functions, no database. Given a seed it always produces the identical
customers / transactions / reviews, which is what makes the demo repeatable and
lets the numbers be verified without a running Postgres.

The dataset is built so the business story is *discoverable*, never asserted:

  * the last 30 days decline versus the 30 before them,
  * the decline is concentrated in the EVENING slot,
  * it is driven by loyal evening regulars visiting less often,
  * evening baskets also shrink (the combo attach rate collapses),
  * service times in the evening drift up across the same window,
  * waiting-time complaints rise in step.

No code anywhere says "the answer is waiting time". The analytics layer surfaces
the correlations; the agent reasons over them.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from app.db.models.commerce import DayPart
from app.seed.catalog import FIRST_NAMES, LAST_NAMES, PRODUCTS

# --------------------------------------------------------------------------- #
# Tuning constants
# --------------------------------------------------------------------------- #
HISTORY_DAYS = 180
ANALYSIS_WINDOW = 30
CUSTOMER_COUNT = 1700

#: Loyalty tiers: (share of base, visits per week, basket size bias).
#:
#: The shape matters. A cafe's repeat rate is only realistic when a small core of
#: near-daily regulars sits on top of a long tail of infrequent visitors - that is
#: what produces a ~31% within-window repeat rate rather than the ~85% you get from
#: a small, uniformly-loyal base.
LOYALTY_TIERS: dict[str, tuple[float, float, float]] = {
    "CORE": (0.055, 3.97, 1.14),
    "REGULAR": (0.035, 1.17, 1.04),
    "OCCASIONAL": (0.150, 0.20, 0.96),
    "RARE": (0.760, 0.047, 0.90),
}

#: Share of the customer base whose habitual slot is each daypart.
DAYPART_MIX: dict[str, float] = {
    DayPart.MORNING: 0.24,
    DayPart.AFTERNOON: 0.30,
    DayPart.EVENING: 0.36,
    DayPart.NIGHT: 0.10,
}

#: Chance a visit happens outside the customer's habitual slot.
SPILLOVER_PROB = 0.18

#: Monday=0. Weekend lifts footfall.
DOW_FACTOR: tuple[float, ...] = (0.92, 0.94, 0.97, 1.02, 1.14, 1.24, 1.10)

# --- the decline -------------------------------------------------------------
#: Share of habitual EVENING regulars who stop coming during the current window.
#: Real churn, not a uniform dip: they drop out on a specific day and mostly do
#: not come back. This is what makes "recover lost evening repeat customers" a
#: genuine, recoverable opportunity rather than a rounding change.
EVENING_REGULAR_CHURN_PROB = 0.37
#: Residual visit rate for a churned customer (they have not vanished entirely).
CHURNED_RESIDUAL_RATE = 0.06
#: Evening regulars who do not churn still visit somewhat less.
EVENING_REGULAR_DECAY = 0.90
#: Evening non-regulars decline more mildly.
EVENING_CASUAL_DECAY = 0.80
#: Other dayparts drift slightly up (the business is not uniformly down).
OTHER_DAYPART_LIFT = 1.075
#: Evening basket shrink - the combo attach collapse that drives AOV down.
EVENING_COMBO_ATTACH_DECAY = 0.28
#: Mild attach softening elsewhere.
OTHER_COMBO_ATTACH_DECAY = 0.90

#: Evening service time drift (minutes added by the end of the window).
EVENING_SERVICE_DRIFT_MINUTES = 6.4

REVIEW_COUNT = 2450
COMPETITOR_REVIEWS_PER_RIVAL = 165

DAYPART_HOURS: dict[str, tuple[int, int]] = {
    DayPart.MORNING: (7, 11),
    DayPart.AFTERNOON: (12, 16),
    DayPart.EVENING: (17, 20),
    DayPart.NIGHT: (21, 23),
}


#: The demo anchors on the most recent completed Sunday rather than "yesterday".
#: Pinning the weekday keeps the day-of-week composition of the two comparison
#: windows identical, so the seeded figures are byte-identical whenever the demo
#: is rebuilt instead of drifting as the real calendar moves.
ANCHOR_WEEKDAY = 6  # Sunday


def default_anchor(today: date | None = None) -> date:
    """Most recent completed ANCHOR_WEEKDAY on or before yesterday."""
    reference = (today or date.today()) - timedelta(days=1)
    return reference - timedelta(days=(reference.weekday() - ANCHOR_WEEKDAY) % 7)


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class CustomerRecord:
    external_ref: str
    name: str
    masked_phone: str
    email: str | None
    preferred_daypart: str
    loyalty_tier: str
    weekly_visits: float
    basket_bias: float
    acquisition_channel: str
    joined_on: date
    is_opted_in: bool
    #: Day this customer stopped being a regular (None = never churned).
    churn_start: date | None = None


@dataclass(slots=True)
class ItemRecord:
    sku: str
    name: str
    quantity: int
    unit_price: float
    unit_cost: float
    line_total: float


@dataclass(slots=True)
class TransactionRecord:
    order_ref: str
    customer_ref: str
    occurred_at: datetime
    business_date: date
    daypart: str
    hour_of_day: int
    day_of_week: int
    gross_amount: float
    discount_amount: float
    net_amount: float
    cost_amount: float
    item_count: int
    payment_method: str
    channel: str
    is_repeat: bool
    service_minutes: float
    items: list[ItemRecord] = field(default_factory=list)
    experiment_key: str | None = None
    experiment_variant: str | None = None


@dataclass(slots=True)
class ReviewRecord:
    author_name: str
    customer_ref: str | None
    rating: int
    title: str
    body: str
    sentiment: str
    sentiment_score: float
    primary_topic: str
    topics: list[str]
    daypart: str
    reviewed_at: datetime
    review_date: date
    product_sku: str | None
    source: str


@dataclass(slots=True)
class Dataset:
    anchor: date
    start: date
    customers: list[CustomerRecord]
    transactions: list[TransactionRecord]
    reviews: list[ReviewRecord]
    competitor_reviews: dict[str, list[ReviewRecord]]

    @property
    def current_window(self) -> tuple[date, date]:
        return (self.anchor - timedelta(days=ANALYSIS_WINDOW - 1), self.anchor)

    @property
    def previous_window(self) -> tuple[date, date]:
        start, _ = self.current_window
        prev_end = start - timedelta(days=1)
        return (prev_end - timedelta(days=ANALYSIS_WINDOW - 1), prev_end)


# --------------------------------------------------------------------------- #
# Customers
# --------------------------------------------------------------------------- #
def generate_customers(
    rng: random.Random, *, anchor: date, count: int = CUSTOMER_COUNT
) -> list[CustomerRecord]:
    tiers: list[str] = []
    for tier, (share, _, _) in LOYALTY_TIERS.items():
        tiers.extend([tier] * round(share * count))
    while len(tiers) < count:
        tiers.append("OCCASIONAL")
    tiers = tiers[:count]
    rng.shuffle(tiers)

    dayparts: list[str] = []
    for part, share in DAYPART_MIX.items():
        dayparts.extend([part] * round(share * count))
    while len(dayparts) < count:
        dayparts.append(DayPart.AFTERNOON)
    dayparts = dayparts[:count]
    rng.shuffle(dayparts)

    channels = ("walk_in", "paypal_checkout", "referral", "delivery_app")
    channel_weights = (0.52, 0.30, 0.11, 0.07)

    customers: list[CustomerRecord] = []
    for index in range(count):
        tier = tiers[index]
        _, weekly, basket_bias = LOYALTY_TIERS[tier]
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        # Tenure must reach well beyond the history window, otherwise a large share of
        # the base "joins" during the comparison windows and manufactures fake growth
        # that masks the real decline.
        tenure_days = (
            rng.randint(150, 1100) if tier in ("CORE", "REGULAR") else rng.randint(15, 1000)
        )
        customers.append(
            CustomerRecord(
                external_ref=f"JO-CUST-{index + 1:04d}",
                name=f"{first} {last}",
                masked_phone=f"+1 (503) 555-{rng.randint(1000, 9999)}",
                email=(
                    f"{first.lower()}.{last.lower()}{rng.randint(1, 99)}@example.com"
                    if rng.random() < 0.42
                    else None
                ),
                preferred_daypart=dayparts[index],
                loyalty_tier=tier,
                # Per-customer jitter so the base is not artificially uniform.
                weekly_visits=round(weekly * rng.uniform(0.75, 1.28), 3),
                basket_bias=round(basket_bias * rng.uniform(0.92, 1.10), 3),
                acquisition_channel=rng.choices(channels, weights=channel_weights)[0],
                joined_on=anchor - timedelta(days=tenure_days),
                is_opted_in=rng.random() < 0.88,
            )
        )

    _assign_evening_churn(rng, customers, anchor=anchor)
    return customers


def _assign_evening_churn(
    rng: random.Random, customers: list[CustomerRecord], *, anchor: date
) -> None:
    """Churn a share of evening regulars at staggered points in the current window.

    Staggering matters: a cliff on one day would look like an outage, whereas a
    steady bleed across the month is what an eroding experience actually looks like.
    """
    window_start = anchor - timedelta(days=ANALYSIS_WINDOW - 1)
    for customer in customers:
        if customer.preferred_daypart != DayPart.EVENING:
            continue
        if customer.loyalty_tier not in ("CORE", "REGULAR"):
            continue
        if rng.random() >= EVENING_REGULAR_CHURN_PROB:
            continue
        # The erosion starts just before the current window and continues into it, so
        # these customers still look healthy in the comparison period and are clearly
        # missing from the current one.
        offset = int(rng.triangular(-12, 14, -3))
        customer.churn_start = window_start + timedelta(days=offset)


# --------------------------------------------------------------------------- #
# Transactions
# --------------------------------------------------------------------------- #
def _decline_progress(day_offset_from_window_start: int) -> float:
    """0.0 at the start of the current window, 1.0 at its end (smooth ramp)."""
    if day_offset_from_window_start < 0:
        return 0.0
    ratio = min(day_offset_from_window_start / max(ANALYSIS_WINDOW - 1, 1), 1.0)
    # Ease-in: the slide accelerates rather than switching on abruptly.
    return ratio**1.35


def _visit_multiplier(customer: CustomerRecord, day: date, progress: float) -> float:
    """How this customer's visit rate is scaled on a given day of the decline."""
    if customer.churn_start is not None and day >= customer.churn_start:
        return CHURNED_RESIDUAL_RATE
    if progress <= 0:
        return 1.0
    if customer.preferred_daypart == DayPart.EVENING:
        if customer.loyalty_tier in ("CORE", "REGULAR"):
            return 1.0 + (EVENING_REGULAR_DECAY - 1.0) * progress
        return 1.0 + (EVENING_CASUAL_DECAY - 1.0) * progress
    return 1.0 + (OTHER_DAYPART_LIFT - 1.0) * progress


def _pick_daypart(rng: random.Random, customer: CustomerRecord) -> str:
    if rng.random() < SPILLOVER_PROB:
        options = [p for p in DayPart.ALL if p != customer.preferred_daypart]
        return rng.choice(options)
    return customer.preferred_daypart


def _build_basket(
    rng: random.Random,
    *,
    daypart: str,
    customer: CustomerRecord,
    progress: float,
) -> list[ItemRecord]:
    """Choose items for one order.

    Basket size is driven by the customer's bias and the slot. In the current
    window the evening combo attach rate decays, which is what pulls AOV down.
    """
    weights: list[float] = []
    for product in PRODUCTS:
        affinity = product["daypart_affinity"].get(daypart, 1.0)
        weights.append(max(product["base_popularity"] * affinity, 0.01))

    anchor_product = rng.choices(PRODUCTS, weights=weights, k=1)[0]
    basket: list[dict[str, Any]] = [anchor_product]

    # Attach probability for a second (and rarely third) item.
    attach_base = 0.62 if daypart == DayPart.EVENING else 0.46
    attach_base *= customer.basket_bias

    decay = EVENING_COMBO_ATTACH_DECAY if daypart == DayPart.EVENING else OTHER_COMBO_ATTACH_DECAY
    attach = attach_base * (1.0 + (decay - 1.0) * progress)

    if rng.random() < attach:
        companions = [p for p in PRODUCTS if p["sku"] != anchor_product["sku"]]
        comp_weights = [
            max(
                p["base_popularity"]
                * p["daypart_affinity"].get(daypart, 1.0)
                * (1.55 if p.get("evening_combo") and daypart == DayPart.EVENING else 1.0),
                0.01,
            )
            for p in companions
        ]
        basket.append(rng.choices(companions, weights=comp_weights, k=1)[0])

        if rng.random() < attach * 0.30:
            extras = [p for p in companions if p["sku"] not in {b["sku"] for b in basket}]
            if extras:
                basket.append(rng.choice(extras))

    items: list[ItemRecord] = []
    for product in basket:
        quantity = 2 if rng.random() < 0.13 else 1
        line_total = round(product["price"] * quantity, 2)
        items.append(
            ItemRecord(
                sku=product["sku"],
                name=product["name"],
                quantity=quantity,
                unit_price=product["price"],
                unit_cost=product["cost_price"],
                line_total=line_total,
            )
        )
    return items


def _service_minutes(
    rng: random.Random, *, daypart: str, progress: float, item_count: int
) -> float:
    """Time from order to handover.

    Evening service degrades across the current window - the signal that the
    review corpus independently corroborates.
    """
    base = {
        DayPart.MORNING: 4.2,
        DayPart.AFTERNOON: 5.6,
        DayPart.EVENING: 7.1,
        DayPart.NIGHT: 5.0,
    }[daypart]
    base += (item_count - 1) * 1.4
    if daypart == DayPart.EVENING:
        base += EVENING_SERVICE_DRIFT_MINUTES * progress
    return round(max(base + rng.gauss(0, 1.1), 1.5), 2)


def generate_transactions(
    rng: random.Random,
    customers: list[CustomerRecord],
    *,
    anchor: date,
    history_days: int = HISTORY_DAYS,
) -> list[TransactionRecord]:
    start = anchor - timedelta(days=history_days - 1)
    window_start = anchor - timedelta(days=ANALYSIS_WINDOW - 1)

    lifetime_orders: dict[str, int] = {c.external_ref: 0 for c in customers}
    transactions: list[TransactionRecord] = []
    order_seq = 0

    day = start
    while day <= anchor:
        progress = _decline_progress((day - window_start).days)
        dow = day.weekday()
        dow_factor = DOW_FACTOR[dow]
        # Very mild organic drift. Kept small: anything larger confounds the
        # period-over-period comparison the whole product is built on.
        seasonal = 1.0 + 0.012 * ((day - start).days / max(history_days, 1))

        for customer in customers:
            if day < customer.joined_on:
                continue
            daily_p = (customer.weekly_visits / 7.0) * dow_factor * seasonal
            daily_p *= _visit_multiplier(customer, day, progress)
            if rng.random() >= min(daily_p, 0.95):
                continue

            daypart = _pick_daypart(rng, customer)
            hour_lo, hour_hi = DAYPART_HOURS[daypart]
            hour = rng.randint(hour_lo, hour_hi)
            minute = rng.randint(0, 59)
            occurred_at = datetime.combine(day, time(hour, minute), tzinfo=UTC)

            items = _build_basket(rng, daypart=daypart, customer=customer, progress=progress)
            gross = round(sum(item.line_total for item in items), 2)
            cost = round(sum(item.unit_cost * item.quantity for item in items), 2)

            # Occasional promo discounts, more common off-peak.
            discount = 0.0
            if rng.random() < (0.10 if daypart == DayPart.EVENING else 0.07):
                discount = round(gross * rng.choice((0.05, 0.10, 0.15)), 2)
            net = round(gross - discount, 2)

            item_count = sum(item.quantity for item in items)
            order_seq += 1
            is_repeat = lifetime_orders[customer.external_ref] > 0
            lifetime_orders[customer.external_ref] += 1

            transactions.append(
                TransactionRecord(
                    order_ref=f"JO-ORD-{order_seq:06d}",
                    customer_ref=customer.external_ref,
                    occurred_at=occurred_at,
                    business_date=day,
                    daypart=daypart,
                    hour_of_day=hour,
                    day_of_week=dow,
                    gross_amount=gross,
                    discount_amount=discount,
                    net_amount=net,
                    cost_amount=cost,
                    item_count=item_count,
                    payment_method=rng.choices(
                        ("card", "paypal", "venmo", "cash"),
                        weights=(0.46, 0.30, 0.12, 0.12),
                    )[0],
                    channel=rng.choices(
                        ("in_store", "online_order", "delivery"), weights=(0.72, 0.19, 0.09)
                    )[0],
                    is_repeat=is_repeat,
                    service_minutes=_service_minutes(
                        rng, daypart=daypart, progress=progress, item_count=item_count
                    ),
                    items=items,
                )
            )
        day += timedelta(days=1)

    return transactions
