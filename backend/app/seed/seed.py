"""Deterministic demo seeder.

    python -m app.seed.seed            # idempotent - skips if already seeded
    python -m app.seed.seed --reset    # wipe the demo tenant and rebuild
    python -m app.seed.seed --stats    # print what is currently in the database

Seeds the RBAC catalogue, the demo team, Juniper & Oak Coffee, and the full dataset:
products, customers, transactions, reviews, competitors, inventory, external
signals, two completed historical experiments and the opportunities detected
from it all.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.core.permissions import (
    ALL_PERMISSIONS,
    ALL_ROLES,
    PERMISSION_DESCRIPTIONS,
    ROLE_DESCRIPTIONS,
    Role,
    permissions_for_role,
)
from app.core.security import hash_password
from app.db.base import Base  # noqa: F401  (ensures full metadata)
from app.db.models.auth import CustomRole, User, UserStatus
from app.db.models.auth import Permission as PermissionModel
from app.db.models.auth import Role as RoleModel
from app.db.models.automation import ProcessedEvent
from app.db.models.commerce import Customer, Product, Transaction, TransactionItem
from app.db.models.competitor import Competitor, CompetitorReview
from app.db.models.growth import GrowthMetric
from app.db.models.inventory import InventoryItem
from app.db.models.merchant import MembershipStatus, Merchant, MerchantMembership
from app.db.models.review import Review
from app.db.models.signal import ExternalSignal
from app.db.session import ensure_extensions, session_scope
from app.integrations.embeddings import embedding_service
from app.seed.catalog import COMPETITORS, EXTERNAL_SIGNALS, MERCHANT_SLUG, PRODUCTS
from app.seed.experiments import seed_historical_experiments
from app.seed.generators.dataset import (
    CUSTOMER_COUNT,
    HISTORY_DAYS,
    CustomerRecord,
    TransactionRecord,
    default_anchor,
    generate_customers,
    generate_transactions,
)
from app.seed.generators.reviews import generate_competitor_reviews, generate_reviews
from app.seed.inventory_automation import seed as seed_inventory_automation
from app.seed.operations import (
    seed_agent_history,
    seed_automation_history,
    seed_custom_roles,
    seed_growth_metric_snapshots,
    seed_processed_events,
)
from app.seed.supply import seed_supply_extras, seed_supply_network

log = get_logger("app.seed")

BATCH_SIZE = 1000


# --------------------------------------------------------------------------- #
# RBAC catalogue
# --------------------------------------------------------------------------- #
async def seed_rbac(session: AsyncSession) -> None:
    """Mirror the in-code permission map into the database."""
    existing_permissions = {
        row[0]: row[1]
        for row in (await session.execute(select(PermissionModel.code, PermissionModel.id))).all()
    }
    for permission in ALL_PERMISSIONS:
        code = str(permission)
        if code in existing_permissions:
            continue
        resource, _, action = code.partition(":")
        model = PermissionModel(
            code=code,
            resource=resource,
            action=action,
            description=PERMISSION_DESCRIPTIONS.get(permission, ""),
        )
        session.add(model)
    await session.flush()

    permission_models = {
        row.code: row for row in (await session.execute(select(PermissionModel))).scalars().all()
    }
    # selectinload is required here: assigning to a lazy-loaded collection on an
    # async session triggers implicit IO and raises MissingGreenlet.
    existing_roles = {
        row.name: row
        for row in (
            await session.execute(select(RoleModel).options(selectinload(RoleModel.permissions)))
        )
        .scalars()
        .all()
    }
    for role in ALL_ROLES:
        granted = [
            permission_models[str(p)]
            for p in permissions_for_role(role)
            if str(p) in permission_models
        ]
        model = existing_roles.get(str(role))
        if model is None:
            # Pass the collection to the constructor so nothing has to be loaded first.
            session.add(
                RoleModel(
                    name=str(role),
                    description=ROLE_DESCRIPTIONS[role],
                    is_system=True,
                    permissions=granted,
                )
            )
        else:
            model.permissions = granted
    await session.flush()
    log.info("rbac_seeded", roles=len(ALL_ROLES), permissions=len(ALL_PERMISSIONS))


# --------------------------------------------------------------------------- #
# Team
# --------------------------------------------------------------------------- #
#: One account per role so the RBAC story is demonstrable, not just described.
DEMO_TEAM: tuple[tuple[str, str, Role], ...] = (
    ("Morgan Hayes", "owner@juniperoak.com", Role.OWNER),
    ("Jordan Ellis", "admin@juniperoak.com", Role.ADMIN),
    ("Avery Chen", "analyst@juniperoak.com", Role.ANALYST),
    ("Sam Rivera", "staff@juniperoak.com", Role.STAFF),
    ("Taylor Brooks", "viewer@juniperoak.com", Role.VIEWER),
)


async def seed_team(session: AsyncSession, merchant: Merchant) -> User:
    owner: User | None = None
    password_hash = hash_password(settings.demo_owner_password)

    for full_name, email, role in DEMO_TEAM:
        existing = (
            (await session.execute(select(User).where(User.email == email))).scalars().first()
        )
        if existing is None:
            existing = User(
                email=email,
                password_hash=password_hash,
                full_name=full_name,
                status=UserStatus.ACTIVE,
                email_verified=True,
            )
            session.add(existing)
            await session.flush()

        membership = (
            (
                await session.execute(
                    select(MerchantMembership).where(
                        MerchantMembership.user_id == existing.id,
                        MerchantMembership.merchant_id == merchant.id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if membership is None:
            session.add(
                MerchantMembership(
                    user_id=existing.id,
                    merchant_id=merchant.id,
                    role=str(role),
                    status=MembershipStatus.ACTIVE,
                    is_default=True,
                    joined_at=datetime.now(tz=UTC),
                )
            )
        if role == Role.OWNER:
            owner = existing

    await session.flush()
    log.info("team_seeded", members=len(DEMO_TEAM))
    assert owner is not None
    return owner


# --------------------------------------------------------------------------- #
# Merchant + catalogue
# --------------------------------------------------------------------------- #
async def seed_merchant(session: AsyncSession, anchor: date) -> Merchant:
    merchant = (
        (await session.execute(select(Merchant).where(Merchant.slug == MERCHANT_SLUG)))
        .scalars()
        .first()
    )
    if merchant is not None:
        return merchant

    merchant = Merchant(
        name=settings.demo_merchant_name,
        slug=MERCHANT_SLUG,
        legal_name="Juniper & Oak Coffee LLC",
        category="cafe",
        description=(
            "A neighborhood specialty coffee shop and online bean store, serving espresso, "
            "cold brew and all-day food, with a "
            "full year of transaction, review and inventory history."
        ),
        city="Portland",
        state="OR",
        country="United States",
        address="2140 SE Division St, Portland, OR 97202",
        timezone="America/Los_Angeles",
        currency="USD",
        locale="en-US",
        contact_email="hello@juniperoak.com",
        contact_phone="+1 (503) 555-0142",
        monthly_target_revenue=30000,
        opened_at=datetime.combine(
            anchor - timedelta(days=HISTORY_DAYS + 400), datetime.min.time(), tzinfo=UTC
        ),
        is_active=True,
        is_demo=True,
        data_source="SEEDED",
        settings_json={
            "dayparts": ["MORNING", "AFTERNOON", "EVENING", "NIGHT"],
            "analysis_window_days": 30,
        },
    )
    session.add(merchant)
    await session.flush()
    log.info("merchant_seeded", merchant_id=str(merchant.id), name=merchant.name)
    return merchant


async def seed_products(session: AsyncSession, merchant: Merchant) -> dict[str, Product]:
    existing = {
        p.sku: p
        for p in (await session.execute(select(Product).where(Product.merchant_id == merchant.id)))
        .scalars()
        .all()
    }
    for spec in PRODUCTS:
        if spec["sku"] in existing:
            continue
        product = Product(
            merchant_id=merchant.id,
            sku=spec["sku"],
            name=spec["name"],
            category=spec["category"],
            description=spec["description"],
            price=spec["price"],
            cost_price=spec["cost_price"],
            prep_time_minutes=spec["prep_time_minutes"],
            tags=list(spec.get("tags", [])),
            is_featured=bool(spec.get("is_featured")),
            attributes={"daypart_affinity": spec["daypart_affinity"]},
        )
        session.add(product)
        existing[spec["sku"]] = product
    await session.flush()
    log.info("products_seeded", count=len(existing))
    return existing


async def seed_inventory(
    session: AsyncSession, merchant: Merchant, products: dict[str, Product]
) -> None:
    have = {
        row.product_id
        for row in (
            await session.execute(
                select(InventoryItem).where(InventoryItem.merchant_id == merchant.id)
            )
        )
        .scalars()
        .all()
    }
    for spec in PRODUCTS:
        product = products[spec["sku"]]
        if product.id in have:
            continue
        session.add(
            InventoryItem(
                merchant_id=merchant.id,
                product_id=product.id,
                product_name=product.name,
                sku=product.sku,
                unit="units",
                quantity_on_hand=spec["stock"],
                reorder_point=spec["reorder_point"],
                reorder_quantity=spec["reorder_quantity"],
                lead_time_days=2 if spec["category"] == "beverages" else 3,
                unit_cost=spec["unit_cost"],
                supplier=spec["supplier"],
                last_counted_at=datetime.now(tz=UTC),
            )
        )
    await session.flush()
    log.info("inventory_seeded", items=len(PRODUCTS))


# --------------------------------------------------------------------------- #
# Customers / transactions
# --------------------------------------------------------------------------- #
async def seed_customers(
    session: AsyncSession, merchant: Merchant, records: list[CustomerRecord]
) -> dict[str, Customer]:
    models: dict[str, Customer] = {}
    for index, record in enumerate(records):
        customer = Customer(
            merchant_id=merchant.id,
            external_ref=record.external_ref,
            name=record.name,
            masked_phone=record.masked_phone,
            email=record.email,
            preferred_daypart=record.preferred_daypart,
            acquisition_channel=record.acquisition_channel,
            is_opted_in=record.is_opted_in,
            attributes={
                "loyalty_tier": record.loyalty_tier,
                "weekly_visits": record.weekly_visits,
                # Recorded honestly: this is generator metadata, not an inference.
                "seed_churned_on": str(record.churn_start) if record.churn_start else None,
            },
        )
        session.add(customer)
        models[record.external_ref] = customer
        if index % BATCH_SIZE == 0:
            await session.flush()
    await session.flush()
    log.info("customers_seeded", count=len(models))
    return models


async def seed_transactions(
    session: AsyncSession,
    merchant: Merchant,
    records: list[TransactionRecord],
    customers: dict[str, Customer],
    products: dict[str, Product],
) -> None:
    started = time.perf_counter()
    for index, record in enumerate(records, start=1):
        customer = customers.get(record.customer_ref)
        transaction = Transaction(
            merchant_id=merchant.id,
            customer_id=customer.id if customer else None,
            order_ref=record.order_ref,
            occurred_at=record.occurred_at,
            business_date=record.business_date,
            daypart=record.daypart,
            hour_of_day=record.hour_of_day,
            day_of_week=record.day_of_week,
            gross_amount=record.gross_amount,
            discount_amount=record.discount_amount,
            net_amount=record.net_amount,
            cost_amount=record.cost_amount,
            item_count=record.item_count,
            payment_method=record.payment_method,
            channel=record.channel,
            is_repeat=record.is_repeat,
            service_minutes=record.service_minutes,
        )
        session.add(transaction)
        await session.flush()

        for item in record.items:
            product = products[item.sku]
            session.add(
                TransactionItem(
                    merchant_id=merchant.id,
                    transaction_id=transaction.id,
                    product_id=product.id,
                    product_name=item.name,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    unit_cost=item.unit_cost,
                    line_total=item.line_total,
                )
            )
        if index % BATCH_SIZE == 0:
            await session.flush()
            log.info("transactions_progress", written=index, total=len(records))
    await session.flush()
    log.info(
        "transactions_seeded",
        count=len(records),
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )


# --------------------------------------------------------------------------- #
# Reviews
# --------------------------------------------------------------------------- #
async def seed_reviews(
    session: AsyncSession,
    merchant: Merchant,
    records: list[Any],
    customers: dict[str, Customer],
    products: dict[str, Product],
) -> None:
    # Embeddings are computed in one batch - far faster than per row.
    vectors = embedding_service.embed_batch([r.body for r in records])
    for index, (record, vector) in enumerate(zip(records, vectors, strict=False), start=1):
        customer = customers.get(record.customer_ref) if record.customer_ref else None
        product = products.get(record.product_sku) if record.product_sku else None
        session.add(
            Review(
                merchant_id=merchant.id,
                customer_id=customer.id if customer else None,
                product_id=product.id if product else None,
                source=record.source,
                author_name=record.author_name,
                rating=record.rating,
                title=record.title or None,
                body=record.body,
                sentiment=record.sentiment,
                sentiment_score=record.sentiment_score,
                primary_topic=record.primary_topic,
                topics=list(record.topics),
                daypart=record.daypart,
                review_date=record.review_date,
                reviewed_at=record.reviewed_at,
                is_verified_purchase=True,
                is_simulated=True,
                embedding=vector,
            )
        )
        if index % BATCH_SIZE == 0:
            await session.flush()
    await session.flush()
    log.info("reviews_seeded", count=len(records), embedding_provider=embedding_service.provider)


async def seed_competitors(
    session: AsyncSession, merchant: Merchant, corpora: dict[str, list[Any]]
) -> None:
    for spec in COMPETITORS:
        competitor = Competitor(
            merchant_id=merchant.id,
            name=spec["name"],
            slug=spec["slug"],
            category="cafe",
            distance_km=spec["distance_km"],
            price_tier=spec["price_tier"],
            avg_rating=spec["avg_rating"],
            perception_scores=spec["perception_scores"],
            strengths=list(spec["strengths"]),
            weaknesses=list(spec["weaknesses"]),
            notes=spec["notes"],
            data_source="SEEDED",
        )
        session.add(competitor)
        await session.flush()

        records = corpora.get(spec["slug"], [])
        vectors = embedding_service.embed_batch([r.body for r in records])
        for record, vector in zip(records, vectors, strict=False):
            session.add(
                CompetitorReview(
                    merchant_id=merchant.id,
                    competitor_id=competitor.id,
                    rating=record.rating,
                    body=record.body,
                    sentiment=record.sentiment,
                    sentiment_score=record.sentiment_score,
                    primary_topic=record.primary_topic,
                    topics=list(record.topics),
                    review_date=record.review_date,
                    reviewed_at=record.reviewed_at,
                    is_simulated=True,
                    embedding=vector,
                )
            )
        competitor.review_count = len(records)
        await session.flush()
    log.info("competitors_seeded", count=len(COMPETITORS))


async def seed_signals(
    session: AsyncSession, merchant: Merchant, products: dict[str, Product], anchor: date
) -> None:
    for spec in EXTERNAL_SIGNALS:
        observed = anchor - timedelta(days=spec["days_ago"])
        session.add(
            ExternalSignal(
                merchant_id=merchant.id,
                title=spec["title"],
                summary=spec["summary"],
                category=spec["category"],
                icon=spec["icon"],
                relevance=spec["relevance"],
                relevance_score=spec["relevance_score"],
                linked_category=spec["linked_category"],
                potential_impact=spec["potential_impact"],
                recommended_action=spec["recommended_action"],
                direction=spec["direction"],
                source_name=spec["source_name"],
                observed_on=observed,
                published_at=datetime.combine(observed, datetime.min.time(), tzinfo=UTC),
                is_simulated=True,
                tags=list(spec["tags"]),
                embedding=embedding_service.embed(f"{spec['title']} {spec['summary']}"),
            )
        )
    await session.flush()
    log.info("signals_seeded", count=len(EXTERNAL_SIGNALS))


# --------------------------------------------------------------------------- #
# Reset / stats
# --------------------------------------------------------------------------- #
#: Slugs of earlier demo tenants, removed on --reset so an old database converges.
LEGACY_SLUGS = ("sharma-cafe",)


async def reset_demo(session: AsyncSession) -> None:
    merchants = (
        (await session.execute(select(Merchant).where(Merchant.slug.in_((MERCHANT_SLUG, *LEGACY_SLUGS)))))
        .scalars()
        .all()
    )
    if not merchants:
        log.info("reset_skipped", reason="demo merchant not present")
        return
    for merchant in merchants:
        # ON DELETE CASCADE clears every tenant-scoped table.
        await session.execute(delete(Merchant).where(Merchant.id == merchant.id))
        log.info("demo_reset", merchant_id=str(merchant.id), slug=merchant.slug)
    await session.flush()


async def print_stats(session: AsyncSession) -> None:
    merchant = (
        (await session.execute(select(Merchant).where(Merchant.slug == MERCHANT_SLUG)))
        .scalars()
        .first()
    )
    if merchant is None:
        print("No demo merchant found. Run: python -m app.seed.seed")
        return

    async def count(model) -> int:
        stmt = select(func.count()).select_from(model)
        if hasattr(model, "merchant_id"):
            stmt = stmt.where(model.merchant_id == merchant.id)
        return int((await session.execute(stmt)).scalar_one() or 0)

    print(f"\n  Merchant : {merchant.name} ({merchant.slug})")
    for label, model in (
        ("products", Product),
        ("customers", Customer),
        ("transactions", Transaction),
        ("transaction items", TransactionItem),
        ("reviews", Review),
        ("competitors", Competitor),
        ("competitor reviews", CompetitorReview),
        ("inventory items", InventoryItem),
        ("external signals", ExternalSignal),
        ("growth metrics", GrowthMetric),
        ("custom roles", CustomRole),
        ("processed events", ProcessedEvent),
    ):
        print(f"  {label:<20}: {await count(model):,}")
    print()


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
async def run_seed(*, reset: bool = False) -> None:
    started = time.perf_counter()
    await ensure_extensions()

    async with session_scope() as session:
        if reset:
            await reset_demo(session)

        await seed_rbac(session)

        existing = (
            (await session.execute(select(Merchant).where(Merchant.slug == MERCHANT_SLUG)))
            .scalars()
            .first()
        )
        if existing is not None and not reset:
            transactions = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(Transaction)
                        .where(Transaction.merchant_id == existing.id)
                    )
                ).scalar_one()
                or 0
            )
            if transactions > 0:
                log.info(
                    "seed_skipped",
                    reason="demo data already present",
                    transactions=transactions,
                    hint="use --reset to rebuild",
                )
                # The narrative is already built, but the operational tables are
                # topped up regardless - they are idempotent, and they are how a
                # table added after the last full seed gets populated without
                # forcing a --reset of 14,000 transactions.
                owner = (
                    (await session.execute(select(User).where(User.email == DEMO_TEAM[0][1])))
                    .scalars()
                    .first()
                )
                created = await seed_inventory_automation(session, existing.id)
                log.info("inventory_automation_seeded", **created)
                await seed_custom_roles(
                    session, existing, created_by_id=owner.id if owner else None
                )
                await seed_growth_metric_snapshots(session, existing)
                await seed_agent_history(session, existing, user_id=owner.id if owner else None)
                await seed_automation_history(
                    session, existing, actor_id=owner.id if owner else None
                )
                await seed_processed_events(session, existing)
                await seed_supply_network(session, existing)
                # Make the network durable before the extras read it on their own session.
                await session.commit()
                async with session_scope() as extras_session:
                    await seed_supply_extras(extras_session, existing)
                await print_stats(session)
                return

        anchor = default_anchor()
        rng = random.Random(settings.seed_random_seed)

        log.info("seed_started", anchor=str(anchor), seed=settings.seed_random_seed)
        merchant = await seed_merchant(session, anchor)
        await seed_team(session, merchant)
        products = await seed_products(session, merchant)
        await seed_inventory(session, merchant, products)

        customer_records = generate_customers(rng, anchor=anchor, count=CUSTOMER_COUNT)
        transaction_records = generate_transactions(
            rng, customer_records, anchor=anchor, history_days=HISTORY_DAYS
        )
        review_records = generate_reviews(rng, customer_records, transaction_records)
        competitor_corpora = generate_competitor_reviews(rng, COMPETITORS, anchor=anchor)

        customers = await seed_customers(session, merchant, customer_records)
        await seed_transactions(session, merchant, transaction_records, customers, products)
        await seed_reviews(session, merchant, review_records, customers, products)
        await seed_competitors(session, merchant, competitor_corpora)
        await seed_signals(session, merchant, products, anchor)

    # Derived state runs in its own transaction so the bulk insert is already durable.
    async with session_scope() as session:
        merchant = (
            (await session.execute(select(Merchant).where(Merchant.slug == MERCHANT_SLUG)))
            .scalars()
            .first()
        )
        assert merchant is not None

        from app.repositories.customer import CustomerRepository
        from app.services.inventory.service import InventoryService

        anchor = default_anchor()
        await CustomerRepository(session, merchant.id).recompute_rollups(today=anchor)
        await InventoryService(session, merchant.id).refresh(today=anchor)
        log.info("rollups_computed")

    async with session_scope() as session:
        merchant = (
            (await session.execute(select(Merchant).where(Merchant.slug == MERCHANT_SLUG)))
            .scalars()
            .first()
        )
        assert merchant is not None
        owner = (
            (await session.execute(select(User).where(User.email == DEMO_TEAM[0][1])))
            .scalars()
            .first()
        )
        await seed_historical_experiments(
            session, merchant_id=merchant.id, owner_id=owner.id if owner else None
        )

    async with session_scope() as session:
        merchant = (
            (await session.execute(select(Merchant).where(Merchant.slug == MERCHANT_SLUG)))
            .scalars()
            .first()
        )
        assert merchant is not None
        from app.services.growth.detector import OpportunityDetector

        stored = await OpportunityDetector(session, merchant.id).detect_and_store(days=30)
        log.info("opportunities_seeded", count=len(stored))

    # The operational tables: metric snapshots, custom roles and the idempotency
    # ledger. Last, because the snapshots are computed from the ledger the steps
    # above have just finished writing.
    async with session_scope() as session:
        merchant = (
            (await session.execute(select(Merchant).where(Merchant.slug == MERCHANT_SLUG)))
            .scalars()
            .first()
        )
        assert merchant is not None
        owner = (
            (await session.execute(select(User).where(User.email == DEMO_TEAM[0][1])))
            .scalars()
            .first()
        )
        # Vendors, purchase orders, batches, automation runs and domain events.
        # Previously only reachable by running the module by hand, which is why a
        # fresh seed left six tables empty and the procurement pages blank.
        created = await seed_inventory_automation(session, merchant.id)
        log.info("inventory_automation_seeded", **created)

        await seed_custom_roles(session, merchant, created_by_id=owner.id if owner else None)
        await seed_growth_metric_snapshots(session, merchant)
        await seed_agent_history(session, merchant, user_id=owner.id if owner else None)
        # Drives the real procurement loop, so it must precede the two below:
        # it is what writes the movements, orders and domain events they read.
        await seed_automation_history(session, merchant, actor_id=owner.id if owner else None)
        await seed_processed_events(session, merchant)

    # Supply Agents: the signature demo (rising bean demand, three supplier agents,
    # PayPal subscriptions). After the legacy automation on purpose - it must not
    # pick the beans up and raise its own reorder.
    async with session_scope() as session:
        merchant = (
            (await session.execute(select(Merchant).where(Merchant.slug == MERCHANT_SLUG)))
            .scalars()
            .first()
        )
        assert merchant is not None
        await seed_supply_network(session, merchant)
    async with session_scope() as session:
        merchant = (
            (await session.execute(select(Merchant).where(Merchant.slug == MERCHANT_SLUG)))
            .scalars()
            .first()
        )
        assert merchant is not None
        extras = await seed_supply_extras(session, merchant)
        log.info("supply_extras_seeded", **{k: v for k, v in extras.items() if k != "paypal_sync"})

    async with session_scope() as session:
        await print_stats(session)

    log.info("seed_complete", duration_ms=round((time.perf_counter() - started) * 1000, 2))
    print(f"  Owner login: {settings.demo_owner_email} / {settings.demo_owner_password}")
    print("  Other roles: admin@ / analyst@ / staff@ / viewer@juniperoak.com (same password)\n")


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Seed the PayPilot demo dataset.")
    parser.add_argument("--reset", action="store_true", help="Wipe the demo tenant first.")
    parser.add_argument("--stats", action="store_true", help="Only print current row counts.")
    args = parser.parse_args()

    async def _run() -> None:
        if args.stats:
            async with session_scope() as session:
                await print_stats(session)
            return
        await run_seed(reset=args.reset)

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:  # pragma: no cover
        sys.exit(130)


if __name__ == "__main__":
    main()
