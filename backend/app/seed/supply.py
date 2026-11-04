"""Seed the Supply Agents demo: the signature scenario, deterministic and labelled.

What it builds (idempotently - every block checks before writing):

* **Premium Coffee Beans (12 oz)** - the retail product whose online demand is
  rising: ~7 bags/day for the prior 14 days, exactly 12/day for the last 14, with
  42 bags on hand and a 3-day lead time. Inventory Intelligence turns that into
  "3.5 days of cover - reorder 150, needed within 3 days".
* **Three independent supplier agents**, each with its own private policy:
    - Summit Roastworks       premium & reliable, fast, moderate price, small concessions
    - Pacific Bean Exchange   cheapest list price, slow (9 days), only 90 bags in stock
    - Cascadia Coffee Collective  flexible, volume break at 150, waives shipping to close
* PayPal subscription records (a "Bean Club" plan, some with failed payments) and a
  simulated Transaction Search sync, all labelled SIMULATED.
* Supplier memories in the pgvector store.

Everything is fictional demo data. Order references for the online store use the
``JO-WEB-`` prefix; PayPal identifiers created in simulation use ``SIM-``.
"""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.commerce import DayPart, Product, Transaction, TransactionItem, TransactionStatus
from app.db.models.inventory import InventoryItem, StockStatus
from app.db.models.merchant import Merchant
from app.db.models.paypal import PayPalSubscriptionRecord
from app.db.models.procurement import OrderingMethod, Vendor, VendorProduct
from app.db.models.supply import PaymentTerms, SupplierAgent, SupplierAgentStatus, SupplierStrategy
from app.services.supply.policy import ratio
from app.services.supply.protocol import key_fingerprint

log = get_logger(__name__)

BEAN_SKU = "JO-BEAN-012"
BEAN_PRICE = Decimal("18.00")
BEAN_COST = Decimal("11.60")
BEAN_ON_HAND = Decimal("42")
#: Units sold per day, oldest first: the 14 days before the last 14, then the last 14.
PRIOR_14 = [7, 6, 8, 7, 7, 6, 8, 7, 7, 6, 8, 7, 7, 7]          # 98 units  = 7.00/day
RECENT_14 = [11, 13, 12, 12, 14, 10, 12, 13, 11, 12, 12, 13, 11, 12]  # 168 units = 12.00/day

SUPPLIERS: list[dict[str, Any]] = [
    {
        "vendor": {
            "name": "Summit Roastworks",
            "contact_name": "Rachel Okafor",
            "email": "orders@summitroastworks.test",
            "phone": "+1 (206) 555-0134",
            "lead_time_days": 2,
            "notes": "Specialty roaster. Roasts to order; ships next day.",
        },
        "agent": {
            "agent_key": "supplier.summit",
            "display_name": "Summit Roastworks",
            "tagline": "Premium and reliable - roasted to order, ships fast.",
            "strategy": SupplierStrategy.PREMIUM_RELIABLE,
            "region": "Seattle, WA",
            "quality_score": Decimal("0.9500"),
            "payment_terms": PaymentTerms.NET_30,
            "shipping_flat": Decimal("25.00"),
            "shipping_per_unit": Decimal("0"),
            "free_shipping_threshold": Decimal("1500.00"),
            "expedite_fee": Decimal("0"),
            "expedite_days": 1,
            "opening_markup": Decimal("0.0300"),
            "concession_rate": Decimal("0.2500"),
            "max_rounds": 3,
            "orders_completed": 24, "orders_on_time": 23,
            "units_ordered": Decimal("2400"), "units_received": Decimal("2400"),
            "invoices_received": 24, "invoice_discrepancies": 0,
        },
        "beans": {"unit_price": Decimal("11.20"), "floor_price": Decimal("10.30"), "moq": Decimal("50"),
                  "lead": Decimal("2"), "available": None, "breaks": []},
        "extra_sku": ("JO-COLD-001", Decimal("2.45"), Decimal("2.20")),
    },
    {
        "vendor": {
            "name": "Pacific Bean Exchange",
            "contact_name": "Victor Huang",
            "email": "sales@pacificbeanexchange.test",
            "phone": "+1 (510) 555-0162",
            "lead_time_days": 9,
            "notes": "Commodity importer. Lowest list prices, slow consolidated freight.",
        },
        "agent": {
            "agent_key": "supplier.pacific",
            "display_name": "Pacific Bean Exchange",
            "tagline": "Lowest list prices - limited stock, longer delivery.",
            "strategy": SupplierStrategy.LOW_PRICE_LIMITED,
            "region": "Oakland, CA",
            "quality_score": Decimal("0.8400"),
            "payment_terms": PaymentTerms.NET_15,
            "shipping_flat": Decimal("0"),
            "shipping_per_unit": Decimal("0.85"),
            "free_shipping_threshold": Decimal("0"),
            "expedite_fee": Decimal("0"),
            "expedite_days": 0,
            "opening_markup": Decimal("0"),
            "concession_rate": Decimal("0.1000"),
            "max_rounds": 3,
            "orders_completed": 10, "orders_on_time": 8,
            "units_ordered": Decimal("900"), "units_received": Decimal("880"),
            "invoices_received": 10, "invoice_discrepancies": 1,
        },
        "beans": {"unit_price": Decimal("9.40"), "floor_price": Decimal("9.10"), "moq": Decimal("30"),
                  "lead": Decimal("9"), "available": Decimal("90"), "breaks": []},
        "extra_sku": None,
    },
    {
        "vendor": {
            "name": "Cascadia Coffee Collective",
            "contact_name": "Priya Lindqvist",
            "email": "trade@cascadiacoffee.test",
            "phone": "+1 (503) 555-0109",
            "lead_time_days": 2,
            "notes": "Roaster co-op. Flexible on volume and terms.",
        },
        "agent": {
            "agent_key": "supplier.cascadia",
            "display_name": "Cascadia Coffee Collective",
            "tagline": "Flexible negotiator - volume breaks, will waive shipping to close.",
            "strategy": SupplierStrategy.FLEXIBLE_VOLUME,
            "region": "Portland, OR",
            "quality_score": Decimal("0.9000"),
            "payment_terms": PaymentTerms.NET_30,
            "shipping_flat": Decimal("40.00"),
            "shipping_per_unit": Decimal("0"),
            "free_shipping_threshold": Decimal("0"),
            "expedite_fee": Decimal("35.00"),
            "expedite_days": 1,
            "opening_markup": Decimal("0.0600"),
            "concession_rate": Decimal("0.4000"),
            "max_rounds": 3,
            "orders_completed": 15, "orders_on_time": 13,
            "units_ordered": Decimal("1900"), "units_received": Decimal("1880"),
            "invoices_received": 15, "invoice_discrepancies": 1,
        },
        "beans": {"unit_price": Decimal("10.90"), "floor_price": Decimal("9.70"), "moq": Decimal("60"),
                  "lead": Decimal("2"), "available": Decimal("600"),
                  "breaks": [{"min_quantity": "150", "discount_pct": "0.04"}]},
        "extra_sku": ("JO-CAPP-002", Decimal("2.05"), Decimal("1.85")),
    },
]


def _reliability(spec: dict[str, Any]) -> tuple[Decimal, Decimal]:
    """Same formula the reconciliation step uses, so seeded scores are consistent."""
    on_time = Decimal(spec["orders_on_time"]) / Decimal(spec["orders_completed"])
    fill = min(spec["units_received"] / spec["units_ordered"], Decimal("1"))
    accuracy = Decimal("1") - Decimal(spec["invoice_discrepancies"]) / Decimal(max(spec["invoices_received"], 1))
    return ratio(on_time), ratio(Decimal("0.5") * on_time + Decimal("0.3") * fill + Decimal("0.2") * accuracy)


async def _anchor(session: AsyncSession, merchant_id: Any) -> date:
    latest = (await session.execute(
        select(func.max(Transaction.business_date)).where(Transaction.merchant_id == merchant_id)
    )).scalar_one_or_none()
    return latest or datetime.now(tz=UTC).date()


async def seed_supply_network(session: AsyncSession, merchant: Merchant) -> dict[str, int]:
    created = {"products": 0, "orders": 0, "vendors": 0, "agents": 0, "supplies": 0, "subscriptions": 0}
    anchor = await _anchor(session, merchant.id)

    # ---- the product
    product = (await session.execute(
        select(Product).where(Product.merchant_id == merchant.id, Product.sku == BEAN_SKU)
    )).scalars().first()
    if product is None:
        product = Product(
            merchant_id=merchant.id, sku=BEAN_SKU, name="Premium Coffee Beans (12 oz)", category="retail",
            description="House espresso blend, whole bean, roasted in small batches. Sold online and in store.",
            price=BEAN_PRICE, cost_price=BEAN_COST, tags=["retail", "beans", "online"], prep_time_minutes=0,
            is_featured=True, attributes={"channel": "online_store", "seeded": True},
        )
        session.add(product)
        await session.flush()
        created["products"] += 1

    item = (await session.execute(
        select(InventoryItem).where(InventoryItem.merchant_id == merchant.id, InventoryItem.product_id == product.id)
    )).scalars().first()
    if item is None:
        item = InventoryItem(
            merchant_id=merchant.id, product_id=product.id, product_name=product.name, sku=BEAN_SKU, unit="bags",
            quantity_on_hand=BEAN_ON_HAND, reorder_point=Decimal("60"), reorder_quantity=Decimal("150"),
            lead_time_days=Decimal("3"), unit_cost=BEAN_COST, avg_daily_demand=Decimal("12"),
            days_of_cover=Decimal("3.5"), status=StockStatus.CRITICAL,
            recommendation="Demand up ~70%: 3.5 days of cover against a 3-day lead time. Source 150 bags.",
            supplier="Supplier agent network", is_tracked=True, automatic_ordering_enabled=False,
            maximum_stock=Decimal("250"), minimum_stock=Decimal("30"),
            metadata_json={"seeded": True, "scenario": "signature-demo"},
        )
        session.add(item)
        await session.flush()

    # ---- online-store sales: steady history, then the demand spike
    has_orders = (await session.execute(
        select(func.count()).select_from(Transaction).where(
            Transaction.merchant_id == merchant.id, Transaction.order_ref.like("JO-WEB-%")
        )
    )).scalar_one()
    if not has_orders:
        rng = random.Random(settings.seed_random_seed + 12)
        days = 180
        schedule: list[int] = [rng.randint(5, 8) for _ in range(days - 28)] + PRIOR_14 + RECENT_14
        seq = 0
        for offset, units in enumerate(schedule):
            day = anchor - timedelta(days=days - 1 - offset)
            remaining = units
            while remaining > 0:
                qty = 2 if remaining >= 2 and rng.random() < 0.35 else 1
                remaining -= qty
                seq += 1
                hour = rng.choice((9, 11, 13, 15, 19, 21))
                occurred = datetime.combine(day, time(hour, rng.randint(0, 59)), tzinfo=UTC)
                gross = BEAN_PRICE * qty
                txn = Transaction(
                    merchant_id=merchant.id, customer_id=None, order_ref=f"JO-WEB-{seq:06d}",
                    occurred_at=occurred, business_date=day,
                    daypart=DayPart.MORNING if hour < 12 else DayPart.AFTERNOON if hour < 17 else DayPart.EVENING if hour < 21 else DayPart.NIGHT,
                    hour_of_day=hour, day_of_week=day.weekday(),
                    gross_amount=gross, discount_amount=Decimal("0"), net_amount=gross,
                    cost_amount=BEAN_COST * qty, item_count=qty, payment_method="paypal", channel="online_store",
                    status=TransactionStatus.COMPLETED, is_repeat=False,
                    metadata_json={"seeded": True, "source": "online_store"},
                )
                session.add(txn)
                await session.flush()
                session.add(TransactionItem(
                    merchant_id=merchant.id, transaction_id=txn.id, product_id=product.id, product_name=product.name,
                    quantity=qty, unit_price=BEAN_PRICE, unit_cost=BEAN_COST, line_total=gross,
                ))
                created["orders"] += 1
        await session.flush()

    # ---- vendors + supplier agents
    payee_override = settings.paypal_sandbox_payee_email
    items_by_sku = {
        i.sku: i for i in (await session.execute(
            select(InventoryItem).where(InventoryItem.merchant_id == merchant.id)
        )).scalars().all()
    }
    for spec in SUPPLIERS:
        vendor = (await session.execute(
            select(Vendor).where(Vendor.merchant_id == merchant.id, Vendor.name == spec["vendor"]["name"])
        )).scalars().first()
        if vendor is None:
            vendor = Vendor(merchant_id=merchant.id, ordering_method=OrderingMethod.API, **spec["vendor"])
            session.add(vendor)
            await session.flush()
            created["vendors"] += 1

        agent = (await session.execute(
            select(SupplierAgent).where(SupplierAgent.merchant_id == merchant.id, SupplierAgent.vendor_id == vendor.id)
        )).scalars().first()
        if agent is None:
            a = dict(spec["agent"])
            on_time, reliability = _reliability(a)
            slug = a["agent_key"].split(".")[-1]
            agent = SupplierAgent(
                merchant_id=merchant.id, vendor_id=vendor.id, status=SupplierAgentStatus.ONLINE, is_simulated=True,
                currency="USD", tax_rate=Decimal("0"), on_time_rate=on_time, reliability_score=reliability,
                key_fingerprint=key_fingerprint(merchant.id, a["agent_key"]),
                paypal_email=payee_override or f"payments@{slug}.example.com",
                negotiations_total=a["orders_completed"] + 3, negotiations_won=a["orders_completed"],
                metadata_json={"seeded": True},
                **a,
            )
            session.add(agent)
            await session.flush()
            created["agents"] += 1

        links = [(BEAN_SKU, spec["beans"])]
        if spec["extra_sku"]:
            sku, price, floor = spec["extra_sku"]
            links.append((sku, {"unit_price": price, "floor_price": floor, "moq": Decimal("24"),
                                "lead": spec["beans"]["lead"], "available": None, "breaks": []}))
        for sku, terms in links:
            target = items_by_sku.get(sku)
            if target is None:
                continue
            link = (await session.execute(
                select(VendorProduct).where(VendorProduct.vendor_id == vendor.id, VendorProduct.inventory_item_id == target.id)
            )).scalars().first()
            if link is None:
                session.add(VendorProduct(
                    merchant_id=merchant.id, vendor_id=vendor.id, inventory_item_id=target.id,
                    vendor_sku=f"{vendor.name[:3].upper()}-{sku}", unit_price=terms["unit_price"],
                    floor_price=terms["floor_price"], minimum_order_quantity=terms["moq"],
                    lead_time_days=terms["lead"], available_quantity=terms["available"],
                    volume_breaks=terms["breaks"], is_preferred=False, automatic_ordering_enabled=False,
                ))
                created["supplies"] += 1
    await session.flush()

    # ---- PayPal subscriptions (simulated records)
    has_subs = (await session.execute(
        select(func.count()).select_from(PayPalSubscriptionRecord).where(PayPalSubscriptionRecord.merchant_id == merchant.id)
    )).scalar_one()
    if not has_subs:
        rng = random.Random(settings.seed_random_seed + 31)
        names = ["Riley Thompson", "Casey Nguyen", "Jamie Foster", "Quinn Ramirez", "Drew Sullivan", "Parker Hayes",
                 "Hayden Ortiz", "Rowan Mitchell", "Avery Collins", "Jordan Reyes", "Morgan Patel", "Taylor Brooks",
                 "Skyler Grant", "Emerson Clark", "Finley Ward", "Reese Morgan", "Sage Bennett", "Blake Turner"]
        for index, name in enumerate(names):
            failed = 2 if index in (3, 11) else 1 if index == 7 else 0
            started = datetime.combine(anchor - timedelta(days=rng.randint(40, 300)), time(10), tzinfo=UTC)
            session.add(PayPalSubscriptionRecord(
                merchant_id=merchant.id, paypal_subscription_id=f"SIM-SUB-{index + 1:04d}",
                plan_id="SIM-PLAN-BEANCLUB", plan_name="Bean Club - 2 bags monthly",
                status="SUSPENDED" if failed >= 2 and index == 11 else "ACTIVE",
                subscriber_name=name, subscriber_hash="", currency="USD", amount=Decimal("32.00"),
                interval="MONTH", failed_payments=failed,
                last_payment_at=datetime.combine(anchor - timedelta(days=rng.randint(1, 28)), time(9), tzinfo=UTC),
                next_billing_at=datetime.combine(anchor + timedelta(days=rng.randint(1, 28)), time(9), tzinfo=UTC),
                started_at=started, mode="SIMULATED", raw={"seeded": True},
            ))
            created["subscriptions"] += 1
        await session.flush()

    log.info("supply_network_seeded", **created)
    return created


async def seed_supply_extras(session: AsyncSession, merchant: Merchant) -> dict[str, Any]:
    """Opportunity refresh, simulated PayPal sync and supplier memories - after the core seed."""
    out: dict[str, Any] = {}
    from app.repositories.opportunity import OpportunityRepository
    from app.services.growth.supply_signals import supply_aware_opportunities

    repo = OpportunityRepository(session, merchant.id)
    stored = 0
    for opp in await supply_aware_opportunities(session, merchant.id):
        await repo.upsert(
            key=opp.key, title=opp.title, summary=opp.summary, kind=opp.kind,
            estimated_value_monthly=opp.estimated_value_monthly, confidence=opp.confidence, impact=opp.impact,
            effort=opp.effort, risk=opp.risk, priority_score=opp.priority_score, status="DETECTED",
            evidence=opp.evidence, hypothesis=opp.hypothesis, recommended_action=opp.recommended_action,
            reasoning=opp.reasoning, graph_path=opp.graph_path, target_segment=opp.target_segment, tags=opp.tags,
            requires_approval=opp.requires_approval, detected_at=datetime.now(tz=UTC),
        )
        stored += 1
    out["supply_opportunities"] = stored

    if settings.paypal_mode == "SIMULATED":
        from app.services.paypal.sync import TransactionSyncService

        out["paypal_sync"] = await TransactionSyncService(session, merchant.id).sync(days=90, actor_label="seed")

    # Memories are written on their own connection; make everything above durable
    # first (SQLite allows one writer at a time, and Postgres readers should see it).
    await session.commit()
    from app.integrations.vector_memory import MemoryKind, memory

    notes = [
        ("Summit Roastworks (supplier.summit) has delivered 23 of its last 24 orders on time. Premium "
         "pricing, rarely concedes more than a few percent.", MemoryKind.SUPPLIER, ("supplier.summit",)),
        ("Pacific Bean Exchange (supplier.pacific) quotes the lowest list prices but consolidates freight - "
         "deliveries took 9+ days and one invoice billed short-shipped bags.", MemoryKind.SUPPLIER, ("supplier.pacific",)),
        ("Cascadia Coffee Collective (supplier.cascadia) waives shipping and offers a 4% volume break at 150 bags; "
         "it closed the last two negotiations on the final round.", MemoryKind.SUPPLIER, ("supplier.cascadia",)),
        ("Premium Coffee Beans (JO-BEAN-012) sell mostly through the PayPal online store; demand rises after "
         "Bean Club newsletter sends.", MemoryKind.INVENTORY, ("jo-bean-012",)),
    ]
    written = 0
    for text, kind, tags in notes:
        written += int(await memory.remember(merchant.id, text, kind=kind, tags=tags, source="system",
                                             author_label="Seed"))
    out["memories"] = written
    return out
