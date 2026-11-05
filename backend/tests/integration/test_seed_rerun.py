"""Re-running the seed must not disturb the supply-agent demo.

The API container re-runs ``python -m app.seed.seed`` on every start, which tops up
existing data. That top-up used to switch automatic ordering on for the coffee
beans and force-reorder them, so n8n restocked the beans and the "3.5 days of
cover" scenario the supply agents are demonstrated on disappeared after a restart.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.inventory import InventoryItem
from app.db.models.merchant import Merchant
from app.db.models.procurement import PurchaseOrderLine
from app.seed.inventory_automation import is_agent_managed
from app.seed.inventory_automation import seed as seed_inventory_automation
from app.seed.operations import seed_automation_history
from app.seed.supply import BEAN_ON_HAND, BEAN_SKU, seed_supply_network


async def test_the_top_up_leaves_the_agent_managed_beans_alone(engine, seeded):
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    async with factory() as s:
        merchant = Merchant(name="Seed Rerun Cafe", slug="seed-rerun-cafe", category="cafe", city="Portland")
        s.add(merchant)
        await s.flush()
        await seed_supply_network(s, merchant)
        await s.commit()

        # What every API start does on an already-seeded database - twice.
        for _ in range(2):
            await seed_inventory_automation(s, merchant.id)
            await seed_automation_history(s, merchant, actor_id=None)
            await s.commit()

        beans = (await s.execute(
            select(InventoryItem).where(InventoryItem.merchant_id == merchant.id, InventoryItem.sku == BEAN_SKU)
        )).scalars().one()
        assert is_agent_managed(beans)
        assert beans.automatic_ordering_enabled is False
        assert Decimal(beans.quantity_on_hand) == Decimal(BEAN_ON_HAND)
        orders = (await s.execute(
            select(func.count()).select_from(PurchaseOrderLine).where(PurchaseOrderLine.inventory_item_id == beans.id)
        )).scalar_one()
        assert orders == 0
