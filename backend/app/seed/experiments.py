"""Historical experiments for the demo.

Two completed experiments give the merchant a track record on day one, so the
Experiments screen is not empty and the Measurement agent has something real to
read back.

Importantly these are *measured the same way live ones are*: synthetic
transactions are written for both arms, tagged with the experiment and variant,
and then the ordinary measurement service aggregates them. No result is typed in
by hand, which is why the numbers on screen always reconcile with the ledger.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.campaign import AudienceRole, CampaignActionType, CampaignStatus
from app.db.models.commerce import Customer, DayPart, Product, Transaction, TransactionItem
from app.db.models.experiment import ExperimentStatus, VariantRole
from app.repositories.campaign import CampaignRepository
from app.repositories.experiment import ExperimentRepository
from app.seed.generators.dataset import default_anchor
from app.services.campaigns.service import CampaignService
from app.services.experiments.service import ExperimentService

log = get_logger(__name__)


#: (key, name, hypothesis, offer, control conversion, test conversion, basket uplift)
HISTORICAL: tuple[dict, ...] = (
    {
        "key": "weekend-brunch-combo",
        "name": "Weekend Brunch Combo",
        "hypothesis": (
            "Pairing a sandwich with a hot beverage at a combo price will lift weekend "
            "morning conversion without discounting either item on its own."
        ),
        "offer": "Veg Sandwich + Cappuccino combo at Rs 229 (saves Rs 39).",
        "daypart": DayPart.MORNING,
        "audience_dayparts": [DayPart.MORNING, DayPart.AFTERNOON],
        "days_ago_start": 96,
        "duration": 14,
        "control_conversion": 0.094,
        "test_conversion": 0.139,
        "basket_uplift": 1.14,
        "unit_cost": 34.0,
        "anchor_sku": "SC-VSAN-004",
        "companion_sku": "SC-CAPP-002",
    },
    {
        "key": "loyalty-chai-pass",
        "name": "Loyalty Chai Pass",
        "hypothesis": (
            "A pre-paid chai pass for regulars will increase visit frequency among "
            "customers who already order chai at least twice a week."
        ),
        "offer": "10 Masala Chai for Rs 449, valid 30 days.",
        "daypart": DayPart.AFTERNOON,
        "audience_dayparts": [DayPart.AFTERNOON],
        "days_ago_start": 58,
        "duration": 14,
        "control_conversion": 0.151,
        "test_conversion": 0.124,
        "basket_uplift": 0.96,
        "unit_cost": 45.0,
        "anchor_sku": "SC-CHAI-003",
        "companion_sku": None,
    },
)


async def seed_historical_experiments(
    session: AsyncSession, *, merchant_id: uuid.UUID, owner_id: uuid.UUID | None
) -> int:
    repo = ExperimentRepository(session, merchant_id)
    if await repo.count() > 0:
        log.info("historical_experiments_skipped", reason="already present")
        return 0

    anchor = default_anchor()
    rng = random.Random(settings.seed_random_seed + 7)

    products = {
        p.sku: p
        for p in (await session.execute(select(Product).where(Product.merchant_id == merchant_id)))
        .scalars()
        .all()
    }
    customers = list(
        (await session.execute(select(Customer).where(Customer.merchant_id == merchant_id)))
        .scalars()
        .all()
    )
    if not customers or not products:
        log.warning("historical_experiments_skipped", reason="no customers or products")
        return 0

    campaigns = CampaignService(session, merchant_id)
    experiments = ExperimentService(session, merchant_id)
    created = 0

    for spec in HISTORICAL:
        start = anchor - timedelta(days=spec["days_ago_start"])
        end = start + timedelta(days=spec["duration"] - 1)

        # ---- eligible audience: customers whose habit matches the slot ----
        pool = [c for c in customers if c.preferred_daypart == spec["daypart"]]
        if len(pool) < 60:
            pool = customers[:400]
        pool = sorted(pool, key=lambda c: c.external_ref)

        campaign = await campaigns.create(
            name=spec["name"],
            objective=spec["hypothesis"],
            offer_type="COMBO",
            offer_description=spec["offer"],
            message=spec["offer"],
            channel="paypal_app",
            start_date=start,
            end_date=end,
            estimated_impact=0,
            created_by_id=owner_id,
            actor_label="Seed",
        )
        await CampaignRepository(session, merchant_id).add_audience(
            campaign=campaign,
            name=f"{spec['name']} audience",
            role=AudienceRole.FULL,
            customer_ids=[c.id for c in pool],
            definition={"dayparts": [spec["daypart"]], "seeded": True},
        )
        if owner_id:
            await campaigns.approve(
                campaign.id, approve=True, user_id=owner_id, actor_label="Seed", note="Historical"
            )
            await campaigns.execute(campaign.id, user_id=owner_id, actor_label="Seed")
        campaign.status = CampaignStatus.COMPLETED
        campaign.completed_at = datetime.combine(end, time(21, 0), tzinfo=UTC)

        experiment = await experiments.create(
            name=spec["name"],
            hypothesis=spec["hypothesis"],
            success_metric="conversion_rate",
            success_threshold_pct=10.0,
            duration_days=spec["duration"],
            start_date=start,
            campaign_id=campaign.id,
            control_split_pct=50.0,
            test_offer_description=spec["offer"],
            unit_cost=spec["unit_cost"],
            audience={
                "active_dayparts": spec["audience_dayparts"],
                "active_within_days": 180,
                "opted_in_only": False,
                "limit": 5000,
            },
            created_by_id=owner_id,
        )
        if owner_id:
            await experiments.approve(
                experiment.id, approve=True, user_id=owner_id, actor_label="Seed", note="Historical"
            )

        variants = await repo.get_variants(experiment.id)
        for variant in variants:
            conversion = (
                spec["control_conversion"]
                if variant.role == VariantRole.CONTROL
                else spec["test_conversion"]
            )
            uplift = 1.0 if variant.role == VariantRole.CONTROL else spec["basket_uplift"]
            await _write_variant_transactions(
                session,
                merchant_id=merchant_id,
                experiment_id=experiment.id,
                variant_key=variant.key,
                customer_ids=[uuid.UUID(str(c)) for c in (variant.customer_ids or [])],
                start=start,
                end=end,
                conversion=conversion,
                basket_uplift=uplift,
                products=products,
                anchor_sku=spec["anchor_sku"],
                companion_sku=spec["companion_sku"],
                rng=rng,
            )

        # Measure it exactly the way a live experiment is measured.
        summary = await experiments.measure(
            experiment.id, window_start=start, window_end=end, user_id=owner_id
        )
        experiment.status = ExperimentStatus.COMPLETED
        experiment.completed_at = datetime.combine(end, time(21, 0), tzinfo=UTC)
        experiment.learning = _learning_for(spec, summary)
        await session.flush()

        await CampaignRepository(session, merchant_id).log_action(
            campaign=campaign,
            action_type=CampaignActionType.COMPLETED,
            description=f"Campaign completed. Experiment decision: {summary.decision}.",
            actor_type="SYSTEM",
            actor_label="Seed",
        )
        created += 1
        log.info(
            "historical_experiment_seeded",
            name=spec["name"],
            decision=summary.decision,
            lift=summary.conversion_lift_pct,
        )

    return created


def _learning_for(spec: dict, summary) -> str:
    if summary.decision == "SCALE":
        return (
            f"Bundling drove a {summary.conversion_lift_pct:+.0f}% conversion lift in the "
            f"{spec['daypart'].lower()} slot at Rs {summary.incremental_revenue:,.0f} incremental "
            "revenue. Combo framing works better than a straight discount for this base - keep "
            "the held-out control in future tests so the lift stays attributable."
        )
    if summary.decision == "STOP":
        return (
            "The pre-paid pass did not move behaviour enough to justify the upfront discount. "
            "Regulars were already visiting at the target frequency, so there was little headroom "
            "to buy. Target lapsing customers rather than active ones next time."
        )
    return (
        f"Result was inconclusive at {summary.conversion_lift_pct:+.1f}% lift. The audience was "
        "too small to separate signal from noise - size future tests for the effect worth detecting."
    )


async def _write_variant_transactions(
    session: AsyncSession,
    *,
    merchant_id: uuid.UUID,
    experiment_id: uuid.UUID,
    variant_key: str,
    customer_ids: list[uuid.UUID],
    start: date,
    end: date,
    conversion: float,
    basket_uplift: float,
    products: dict[str, Product],
    anchor_sku: str,
    companion_sku: str | None,
    rng: random.Random,
) -> None:
    """Write the transactions that back an experiment arm.

    These are tagged with ``experiment_id`` / ``experiment_variant`` so the
    measurement query picks up exactly this arm and nothing else.
    """
    window_days = max((end - start).days + 1, 1)
    anchor_product = products.get(anchor_sku)
    companion = products.get(companion_sku) if companion_sku else None
    if anchor_product is None:
        return

    # Exact counts, deterministically ordered. With a few hundred customers per arm,
    # Bernoulli sampling noise would completely swamp the effect being demonstrated.
    ordered = sorted(
        customer_ids,
        key=lambda cid: hashlib.blake2b(
            f"{experiment_id}:{variant_key}:{cid}".encode(), digest_size=8
        ).hexdigest(),
    )
    converters = ordered[: max(int(round(len(ordered) * conversion)), 0)]
    for customer_id in converters:
        day = start + timedelta(days=rng.randrange(window_days))
        hour = rng.randint(8, 20)
        occurred = datetime.combine(day, time(hour, rng.randint(0, 59)), tzinfo=UTC)

        items: list[tuple[Product, int]] = [(anchor_product, 1)]
        if companion is not None and rng.random() < (0.55 * basket_uplift):
            items.append((companion, 1))

        gross = round(sum(float(p.price) * q for p, q in items) * basket_uplift, 2)
        cost = round(sum(float(p.cost_price) * q for p, q in items), 2)

        transaction = Transaction(
            merchant_id=merchant_id,
            customer_id=customer_id,
            order_ref=f"EXP-{variant_key.upper()}-{uuid.uuid4().hex[:8]}",
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
            payment_method="paypal_upi",
            channel="paypal_app",
            is_repeat=True,
            service_minutes=round(rng.uniform(4.0, 8.5), 2),
            experiment_id=experiment_id,
            experiment_variant=variant_key,
            metadata_json={"source": "seeded_experiment", "simulated": True},
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
