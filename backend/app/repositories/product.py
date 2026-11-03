"""Product and inventory repositories."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import and_, func, select

from app.db.models.commerce import Product, Transaction, TransactionItem, TransactionStatus
from app.db.models.inventory import InventoryItem, InventoryMovement, StockStatus
from app.repositories.base import MerchantScopedRepository


class ProductRepository(MerchantScopedRepository[Product]):
    model = Product

    async def list_active(self) -> list[Product]:
        stmt = self.scoped().where(Product.is_active.is_(True)).order_by(Product.name)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_by_sku(self, sku: str) -> Product | None:
        stmt = self.scoped().where(Product.sku == sku)
        return (await self.session.execute(stmt)).scalars().first()

    async def by_id_map(self) -> dict[uuid.UUID, Product]:
        products = list((await self.session.execute(self.scoped())).scalars().all())
        return {product.id: product for product in products}

    async def category_revenue(self, start: date, end: date) -> list[dict[str, Any]]:
        stmt = (
            select(
                Product.category,
                func.coalesce(func.sum(TransactionItem.line_total), 0),
                func.coalesce(func.sum(TransactionItem.quantity), 0),
                func.count(func.distinct(TransactionItem.transaction_id)),
            )
            .join(TransactionItem, TransactionItem.product_id == Product.id)
            .join(Transaction, Transaction.id == TransactionItem.transaction_id)
            .where(
                Transaction.merchant_id == self.merchant_id,
                Transaction.status == TransactionStatus.COMPLETED,
                Transaction.business_date >= start,
                Transaction.business_date <= end,
            )
            .group_by(Product.category)
            .order_by(func.coalesce(func.sum(TransactionItem.line_total), 0).desc())
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            {
                "category": row[0],
                "revenue": round(float(row[1] or 0), 2),
                "units": int(row[2] or 0),
                "orders": int(row[3] or 0),
            }
            for row in rows
        ]

    async def revenue_share_by_category(self, start: date, end: date) -> dict[str, float]:
        rows = await self.category_revenue(start, end)
        total = sum(row["revenue"] for row in rows)
        if not total:
            return {}
        return {row["category"]: round(row["revenue"] / total * 100, 2) for row in rows}


class InventoryRepository(MerchantScopedRepository[InventoryItem]):
    model = InventoryItem

    async def list_items(self) -> list[InventoryItem]:
        stmt = (
            self.scoped()
            .where(InventoryItem.is_tracked.is_(True))
            .order_by(InventoryItem.product_name)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_by_product(self, product_id: uuid.UUID) -> InventoryItem | None:
        stmt = self.scoped().where(InventoryItem.product_id == product_id)
        return (await self.session.execute(stmt)).scalars().first()

    async def daily_demand(
        self, *, days: int = 14, today: date | None = None
    ) -> dict[uuid.UUID, float]:
        """Average units sold per day per product over the trailing window."""
        anchor = today or date.today()
        start = anchor - timedelta(days=days - 1)
        stmt = (
            select(
                TransactionItem.product_id,
                func.coalesce(func.sum(TransactionItem.quantity), 0),
            )
            .join(Transaction, Transaction.id == TransactionItem.transaction_id)
            .where(
                and_(
                    Transaction.merchant_id == self.merchant_id,
                    Transaction.status == TransactionStatus.COMPLETED,
                    Transaction.business_date >= start,
                    Transaction.business_date <= anchor,
                )
            )
            .group_by(TransactionItem.product_id)
        )
        rows = (await self.session.execute(stmt)).all()
        return {row[0]: round(float(row[1] or 0) / days, 3) for row in rows}

    async def record_movement(
        self,
        *,
        item: InventoryItem,
        movement_type: str,
        quantity: float,
        note: str = "",
        actor_type: str = "SYSTEM",
        actor_id: uuid.UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> InventoryMovement:
        movement = InventoryMovement(
            merchant_id=self.merchant_id,
            inventory_item_id=item.id,
            movement_type=movement_type,
            quantity=quantity,
            balance_after=float(item.quantity_on_hand or 0),
            note=note,
            actor_type=actor_type,
            actor_id=actor_id,
            quantity_units=int(quantity),
            metadata_json=metadata or {},
        )
        self.session.add(movement)
        await self.session.flush()
        return movement

    async def at_risk(self) -> list[InventoryItem]:
        stmt = self.scoped().where(
            InventoryItem.status.in_(
                [StockStatus.LOW, StockStatus.CRITICAL, StockStatus.OUT_OF_STOCK]
            )
        )
        return list((await self.session.execute(stmt)).scalars().all())
