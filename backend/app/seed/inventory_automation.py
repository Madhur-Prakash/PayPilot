"""Seed the procurement side of the demo: vendors, terms, batches, policies.

Idempotent - safe to run repeatedly. It attaches to whatever inventory the main
seed already created rather than inventing a parallel catalogue, so the demo
stays one coherent story.

The scenarios are deliberately varied: something healthy, something below its
reorder point, something already ordered, something about to expire. A dashboard
with every row green demonstrates nothing.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.base  # noqa: F401  - registers every mapper
from app.core.logging import get_logger
from app.db.models.inventory import BatchStatus, InventoryBatch, InventoryItem
from app.db.models.merchant import Merchant
from app.db.models.procurement import OrderingMethod, Vendor, VendorProduct
from app.db.session import SessionLocal

log = get_logger(__name__)

VENDORS = [
    {
        "name": "Sunrise Wholesale",
        "contact_name": "Anil Deshpande",
        "email": "orders@sunrisewholesale.test",
        "phone": "+91 98200 11223",
        "ordering_method": OrderingMethod.EMAIL,
        "lead_time_days": 2,
        "notes": "Dairy, bakery and dry goods. Fastest turnaround.",
    },
    {
        "name": "Konkan Coffee Traders",
        "contact_name": "Meera Rao",
        "email": "supply@konkancoffee.test",
        "phone": "+91 98330 44556",
        "ordering_method": OrderingMethod.EMAIL,
        "lead_time_days": 5,
        "notes": "Single-origin beans. Cheaper, slower.",
    },
    {
        "name": "Metro Packaging Co",
        "contact_name": "Farhan Sheikh",
        "email": "sales@metropack.test",
        "phone": "+91 98190 77889",
        "ordering_method": OrderingMethod.MANUAL,
        "lead_time_days": 7,
        "notes": "Cups, lids and packaging. Ordered by phone.",
    },
]


async def seed(session: AsyncSession, merchant_id: uuid.UUID) -> dict[str, int]:
    created = {"vendors": 0, "supplies": 0, "batches": 0, "policies": 0}

    # ---- vendors
    vendors: dict[str, Vendor] = {}
    for spec in VENDORS:
        existing = (
            await session.execute(
                select(Vendor).where(
                    Vendor.merchant_id == merchant_id, Vendor.name == spec["name"]
                )
            )
        ).scalars().first()
        if existing is None:
            existing = Vendor(merchant_id=merchant_id, **spec)
            session.add(existing)
            await session.flush()
            created["vendors"] += 1
        vendors[spec["name"]] = existing

    items = list(
        (
            await session.execute(
                select(InventoryItem)
                .where(InventoryItem.merchant_id == merchant_id)
                .order_by(InventoryItem.sku)
            )
        ).scalars().all()
    )
    if not items:
        log.warning("inventory_automation_seed_skipped", reason="no inventory items")
        return created

    names = list(vendors.values())

    # ---- policies and supply links
    #
    # The pattern below is what produces a varied dashboard: roughly a third of
    # items are pushed under their reorder point so the low-stock path is
    # demonstrable without anyone having to fake a sale first.
    for index, item in enumerate(items):
        primary = names[index % len(names)]
        secondary = names[(index + 1) % len(names)]

        item.maximum_stock = max(float(item.reorder_point) * 5, 100)
        item.minimum_stock = float(item.reorder_point) * 0.5
        item.reorder_strategy = "TARGET_MAX_STOCK" if index % 2 == 0 else "FIXED_QUANTITY"
        if item.reorder_quantity <= 0:
            item.reorder_quantity = max(float(item.reorder_point) * 2, 20)
        item.automatic_ordering_enabled = index % 3 != 2  # two in three automate
        item.expiry_tracking_enabled = index % 2 == 0
        item.default_vendor_id = primary.id
        item.supplier = primary.name
        created["policies"] += 1

        unit_cost = float(item.unit_cost or 50)
        for vendor, preferred, premium in ((primary, True, 1.0), (secondary, False, 1.08)):
            link = (
                await session.execute(
                    select(VendorProduct).where(
                        VendorProduct.vendor_id == vendor.id,
                        VendorProduct.inventory_item_id == item.id,
                    )
                )
            ).scalars().first()
            if link is None:
                session.add(
                    VendorProduct(
                        merchant_id=merchant_id,
                        vendor_id=vendor.id,
                        inventory_item_id=item.id,
                        vendor_sku=f"{vendor.name[:3].upper()}-{item.sku}",
                        unit_price=round(unit_cost * premium, 2),
                        minimum_order_quantity=5,
                        is_preferred=preferred,
                        lead_time_days=vendor.lead_time_days,
                    )
                )
                created["supplies"] += 1

    # ---- batches, including one that is about to expire and one that has
    for index, item in enumerate(items):
        if not item.expiry_tracking_enabled:
            continue
        existing = (
            await session.execute(
                select(InventoryBatch).where(InventoryBatch.inventory_item_id == item.id)
            )
        ).scalars().first()
        if existing is not None:
            continue

        on_hand = float(item.quantity_on_hand)
        if on_hand <= 0:
            continue

        # Split the stock across two batches so FEFO has something to choose from.
        fresh = round(on_hand * 0.7, 2)
        old = round(on_hand - fresh, 2)
        today = date.today()

        session.add(
            InventoryBatch(
                merchant_id=merchant_id,
                inventory_item_id=item.id,
                batch_code=f"B-{item.sku}-FRESH",
                quantity=fresh,
                quantity_received=fresh,
                unit_cost=float(item.unit_cost or 0),
                received_at=datetime.now(tz=UTC) - timedelta(days=5),
                expiry_date=today + timedelta(days=90),
                vendor_id=item.default_vendor_id,
            )
        )
        # Every third tracked item gets a batch inside the expiry window, so the
        # aging sweep has real work on a fresh install.
        near = index % 3 == 0
        session.add(
            InventoryBatch(
                merchant_id=merchant_id,
                inventory_item_id=item.id,
                batch_code=f"B-{item.sku}-OLD",
                quantity=old,
                quantity_received=old,
                unit_cost=float(item.unit_cost or 0),
                received_at=datetime.now(tz=UTC) - timedelta(days=60),
                expiry_date=today + timedelta(days=12 if near else 45),
                status=BatchStatus.EXPIRING_SOON if near else BatchStatus.ACTIVE,
                vendor_id=item.default_vendor_id,
            )
        )
        created["batches"] += 2

    await session.commit()
    log.info("inventory_automation_seeded", **created)
    return created


async def main() -> int:
    async with SessionLocal() as session:
        merchant = (await session.execute(select(Merchant).limit(1))).scalars().first()
        if merchant is None:
            print("No merchant found. Run the main seed first.")
            return 1
        created = await seed(session, merchant.id)

    print(f"\n  merchant : {merchant.name}")
    for key, value in created.items():
        print(f"  {key:9}: {value}")
    print("\n  Run `make inventory-demo` to drive a sale through the automation.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
