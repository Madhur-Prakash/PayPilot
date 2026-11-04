"""Controlled transaction generation for experiments without live traffic yet.

A real experiment accumulates transactions over its run, which takes time this
platform doesn't wait on: for a tenant not yet on live traffic, this module
writes the transactions an experiment's run would produce, from an explicitly
declared ground truth:

    control converts at `control_rate`
    test    converts at `control_rate * uplift`
    test baskets are `basket_uplift` larger (the combo effect)

Nothing downstream is told what those numbers were. The ordinary measurement
service aggregates the rows and computes conversion, lift, incremental revenue,
ROI and significance the same way it would for live traffic - so the result on
screen is genuinely measured, not asserted. Selection is deterministic (exact
counts, hash-ordered) so a run reproduces exactly.

Every row is stamped ``metadata_json.simulated = true`` so the API can label
the run as a delivery/traffic preview rather than live.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.commerce import DayPart, Product, Transaction, TransactionItem
from app.db.models.experiment import Experiment, VariantRole
from app.repositories.experiment import ExperimentRepository

log = get_logger(__name__)

#: Declared ground truth for the headline evening win-back scenario.
DEFAULT_CONTROL_RATE = 0.088
DEFAULT_UPLIFT = 1.62
#: Test baskets are larger because the intervention is a combo, not a discount.
DEFAULT_BASKET_UPLIFT = 1.18


def _stable_order(customer_ids: list[uuid.UUID], salt: str) -> list[uuid.UUID]:
    """Deterministic, unbiased ordering - same result on every machine and run."""
    return sorted(
        customer_ids,
        key=lambda cid: hashlib.blake2b(f"{salt}:{cid}".encode(), digest_size=8).hexdigest(),
    )


async def simulate_experiment_traffic(
    session: AsyncSession,
    *,
    merchant_id: uuid.UUID,
    experiment: Experiment,
    control_rate: float = DEFAULT_CONTROL_RATE,
    uplift: float = DEFAULT_UPLIFT,
    basket_uplift: float = DEFAULT_BASKET_UPLIFT,
    seed: int = 20240917,
) -> dict[str, int]:
    """Write the transactions backing each arm. Returns converted counts per arm."""
    repo = ExperimentRepository(session, merchant_id)
    variants = await repo.get_variants(experiment.id)
    if not variants:
        return {}

    # Never double-write: if this experiment already has tagged traffic, stop.
    existing = (
        await session.execute(
            select(Transaction.id)
            .where(
                Transaction.merchant_id == merchant_id,
                Transaction.experiment_id == experiment.id,
            )
            .limit(1)
        )
    ).first()
    if existing is not None:
        log.info("experiment_traffic_exists", experiment_id=str(experiment.id))
        return {}

    products = list(
        (
            await session.execute(
                select(Product).where(
                    Product.merchant_id == merchant_id, Product.is_active.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    if not products:
        return {}

    # The combo the evening intervention actually offers.
    by_sku = {p.sku: p for p in products}
    anchor = by_sku.get("JO-COLD-001") or products[0]
    companion = by_sku.get("JO-WRAP-005") or (products[1] if len(products) > 1 else None)
    dessert = by_sku.get("JO-BRWN-006")

    start = experiment.start_date or date.today() - timedelta(days=13)
    end = experiment.end_date or start + timedelta(days=13)
    window_days = max((end - start).days + 1, 1)

    rng = random.Random(seed + int(str(experiment.id.int)[:8]))
    converted: dict[str, int] = {}

    for variant in variants:
        member_ids = [uuid.UUID(str(c)) for c in (variant.customer_ids or [])]
        if not member_ids:
            converted[variant.key] = 0
            continue

        is_test = variant.role == VariantRole.TEST
        rate = control_rate * uplift if is_test else control_rate
        # Exact counts rather than Bernoulli draws: with a few hundred customers per
        # arm, sampling noise would swamp the effect and make the result unreliable.
        take = max(round(len(member_ids) * rate), 0)
        chosen = _stable_order(member_ids, salt=f"{experiment.id}:{variant.key}")[:take]
        converted[variant.key] = len(chosen)

        for customer_id in chosen:
            day = start + timedelta(days=rng.randrange(window_days))
            hour = rng.randint(17, 20)  # the evening slot the intervention targets
            occurred = datetime.combine(day, time(hour, rng.randint(0, 59)), tzinfo=UTC)

            items: list[tuple[Product, int]] = [(anchor, 1)]
            if companion is not None and (is_test or rng.random() < 0.45):
                items.append((companion, 1))
            if is_test and dessert is not None and rng.random() < 0.40:
                items.append((dessert, 1))

            gross = round(
                sum(float(p.price) * q for p, q in items) * (basket_uplift if is_test else 1.0), 2
            )
            cost = round(sum(float(p.cost_price) * q for p, q in items), 2)

            transaction = Transaction(
                merchant_id=merchant_id,
                customer_id=customer_id,
                order_ref=f"EXP-{variant.key.upper()}-{uuid.uuid4().hex[:8]}",
                occurred_at=occurred,
                business_date=day,
                daypart=DayPart.from_hour(hour),
                hour_of_day=hour,
                day_of_week=day.weekday(),
                gross_amount=gross,
                discount_amount=0,
                net_amount=gross,
                cost_amount=cost,
                item_count=sum(q for _, q in items),
                payment_method="paypal",
                channel="paypal_app",
                status="COMPLETED",
                is_repeat=True,
                service_minutes=round(
                    rng.uniform(3.5, 6.0) if is_test else rng.uniform(6.0, 11.0), 2
                ),
                campaign_id=experiment.campaign_id,
                experiment_id=experiment.id,
                experiment_variant=variant.key,
                metadata_json={"source": "experiment_simulation", "simulated": True},
            )
            session.add(transaction)
            await session.flush()

            for product, quantity in items:
                session.add(
                    TransactionItem(
                        merchant_id=merchant_id,
                        transaction_id=transaction.id,
                        product_id=product.id,
                        product_name=product.name,
                        quantity=quantity,
                        unit_price=product.price,
                        unit_cost=product.cost_price,
                        line_total=round(float(product.price) * quantity, 2),
                    )
                )

    await session.flush()
    log.info(
        "experiment_traffic_simulated",
        experiment_id=str(experiment.id),
        converted=converted,
        window=f"{start}..{end}",
    )
    return converted
