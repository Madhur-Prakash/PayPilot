"""Transaction repository - the deterministic analytics engine.

Every financial figure in the product is produced here in SQL. No LLM ever sees a
raw transaction, and no LLM ever computes a number (spec section 17).

Aggregations stay dialect-portable (no ``date_trunc``, no window functions) so the
same queries run on Postgres in production and SQLite in the test suite.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, and_, case, distinct, func, select

from app.db.models.commerce import (
    Customer,
    DayPart,
    Product,
    Transaction,
    TransactionItem,
    TransactionStatus,
)
from app.repositories.base import MerchantScopedRepository


def _f(value: Any) -> float:
    """Numeric/Decimal -> float, treating NULL as 0."""
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _pct_change(current: float, previous: float) -> float | None:
    """Percentage change, or None when there is no baseline to compare against."""
    if previous == 0:
        return None
    return round(((current - previous) / abs(previous)) * 100, 2)


@dataclass(slots=True)
class SalesAggregate:
    revenue: float = 0.0
    orders: int = 0
    aov: float = 0.0
    unique_customers: int = 0
    new_customers: int = 0
    repeat_customers: int = 0
    repeat_orders: int = 0
    repeat_rate: float = 0.0
    gross_margin: float = 0.0
    gross_margin_pct: float = 0.0
    discount_total: float = 0.0
    avg_service_minutes: float | None = None
    items_sold: int = 0


class TransactionRepository(MerchantScopedRepository[Transaction]):
    model = Transaction

    # ------------------------------------------------------------------ helpers
    def _window(
        self,
        start: date,
        end: date,
        *,
        daypart: str | None = None,
        customer_ids: list[uuid.UUID] | None = None,
        experiment_id: uuid.UUID | None = None,
        variant_key: str | None = None,
    ) -> list[Any]:
        conditions: list[Any] = [
            Transaction.merchant_id == self.merchant_id,
            Transaction.business_date >= start,
            Transaction.business_date <= end,
            Transaction.status == TransactionStatus.COMPLETED,
        ]
        if daypart:
            conditions.append(Transaction.daypart == daypart)
        if customer_ids is not None:
            if not customer_ids:
                # An empty audience must aggregate to zero, not to "no filter".
                conditions.append(Transaction.customer_id.is_(None))
                conditions.append(Transaction.customer_id.is_not(None))
            else:
                conditions.append(Transaction.customer_id.in_(customer_ids))
        if experiment_id:
            conditions.append(Transaction.experiment_id == experiment_id)
        if variant_key:
            conditions.append(Transaction.experiment_variant == variant_key)
        return conditions

    # ------------------------------------------------------------------ summary
    async def sales_summary(
        self,
        start: date,
        end: date,
        *,
        daypart: str | None = None,
        customer_ids: list[uuid.UUID] | None = None,
    ) -> SalesAggregate:
        """Headline figures for a window. One query, all deterministic."""
        conditions = self._window(start, end, daypart=daypart, customer_ids=customer_ids)

        stmt = select(
            func.coalesce(func.sum(Transaction.net_amount), 0),
            func.count(Transaction.id),
            func.count(distinct(Transaction.customer_id)),
            func.coalesce(func.sum(Transaction.cost_amount), 0),
            func.coalesce(func.sum(Transaction.discount_amount), 0),
            func.avg(Transaction.service_minutes),
            func.coalesce(func.sum(Transaction.item_count), 0),
            func.coalesce(func.sum(case((Transaction.is_repeat.is_(True), 1), else_=0)), 0),
        ).where(and_(*conditions))

        row = (await self.session.execute(stmt)).one()
        revenue = _f(row[0])
        orders = int(row[1] or 0)
        unique_customers = int(row[2] or 0)
        cost = _f(row[3])
        discount = _f(row[4])
        service_minutes = _f(row[5]) if row[5] is not None else None
        items = int(row[6] or 0)
        repeat_orders = int(row[7] or 0)
        repeat_customers = await self.repeat_customer_count(
            start, end, daypart=daypart, customer_ids=customer_ids
        )

        margin = revenue - cost
        return SalesAggregate(
            revenue=round(revenue, 2),
            orders=orders,
            aov=round(revenue / orders, 2) if orders else 0.0,
            unique_customers=unique_customers,
            new_customers=max(unique_customers - repeat_customers, 0),
            repeat_customers=repeat_customers,
            repeat_orders=repeat_orders,
            repeat_rate=round((repeat_customers / unique_customers) * 100, 2)
            if unique_customers
            else 0.0,
            gross_margin=round(margin, 2),
            gross_margin_pct=round((margin / revenue) * 100, 2) if revenue else 0.0,
            discount_total=round(discount, 2),
            avg_service_minutes=round(service_minutes, 2) if service_minutes is not None else None,
            items_sold=items,
        )

    async def repeat_customer_count(
        self,
        start: date,
        end: date,
        *,
        daypart: str | None = None,
        customer_ids: list[uuid.UUID] | None = None,
        min_orders: int = 2,
    ) -> int:
        """Customers who transacted at least ``min_orders`` times inside the window.

        This is the product's definition of a repeat customer: a *returning visitor
        within the period*, not merely someone who has ever ordered before. With a
        long tail of occasional visitors the lifetime flag saturates near 100% and
        stops being a useful signal, whereas this moves when regulars stop coming.
        """
        conditions = self._window(start, end, daypart=daypart, customer_ids=customer_ids)
        conditions.append(Transaction.customer_id.is_not(None))
        inner = (
            select(Transaction.customer_id)
            .where(and_(*conditions))
            .group_by(Transaction.customer_id)
            .having(func.count(Transaction.id) >= min_orders)
            .subquery()
        )
        stmt = select(func.count()).select_from(inner)
        return int((await self.session.execute(stmt)).scalar_one() or 0)

    # ------------------------------------------------------------------ trends
    async def daily_trend(
        self, start: date, end: date, *, daypart: str | None = None
    ) -> list[dict[str, Any]]:
        """Revenue / orders / customers per business date, gap-filled."""
        conditions = self._window(start, end, daypart=daypart)
        stmt = (
            select(
                Transaction.business_date,
                func.coalesce(func.sum(Transaction.net_amount), 0),
                func.count(Transaction.id),
                func.count(distinct(Transaction.customer_id)),
            )
            .where(and_(*conditions))
            .group_by(Transaction.business_date)
            .order_by(Transaction.business_date)
        )
        rows = (await self.session.execute(stmt)).all()
        by_date = {
            row[0]: {
                "revenue": round(_f(row[1]), 2),
                "orders": int(row[2] or 0),
                "customers": int(row[3] or 0),
            }
            for row in rows
        }

        points: list[dict[str, Any]] = []
        cursor = start
        while cursor <= end:
            entry = by_date.get(cursor, {"revenue": 0.0, "orders": 0, "customers": 0})
            points.append({"date": cursor, **entry})
            cursor += timedelta(days=1)
        return points

    async def daypart_breakdown(self, start: date, end: date) -> list[dict[str, Any]]:
        conditions = self._window(start, end)
        stmt = (
            select(
                Transaction.daypart,
                func.coalesce(func.sum(Transaction.net_amount), 0),
                func.count(Transaction.id),
                func.count(distinct(Transaction.customer_id)),
                func.avg(Transaction.service_minutes),
            )
            .where(and_(*conditions))
            .group_by(Transaction.daypart)
        )
        rows = (await self.session.execute(stmt)).all()
        found = {
            row[0]: {
                "daypart": row[0],
                "revenue": round(_f(row[1]), 2),
                "orders": int(row[2] or 0),
                "unique_customers": int(row[3] or 0),
                "avg_service_minutes": round(_f(row[4]), 2) if row[4] is not None else None,
                "repeat_customers": await self.repeat_customer_count(start, end, daypart=row[0]),
            }
            for row in rows
        }
        result = []
        for part in DayPart.ALL:
            entry = found.get(
                part,
                {
                    "daypart": part,
                    "revenue": 0.0,
                    "orders": 0,
                    "unique_customers": 0,
                    "avg_service_minutes": None,
                    "repeat_customers": 0,
                },
            )
            entry["aov"] = round(entry["revenue"] / entry["orders"], 2) if entry["orders"] else 0.0
            result.append(entry)
        return result

    async def hourly_distribution(self, start: date, end: date) -> list[dict[str, Any]]:
        conditions = self._window(start, end)
        stmt = (
            select(
                Transaction.hour_of_day,
                func.coalesce(func.sum(Transaction.net_amount), 0),
                func.count(Transaction.id),
            )
            .where(and_(*conditions))
            .group_by(Transaction.hour_of_day)
            .order_by(Transaction.hour_of_day)
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            {"hour": int(row[0]), "revenue": round(_f(row[1]), 2), "orders": int(row[2] or 0)}
            for row in rows
        ]

    # ------------------------------------------------------------------ products
    async def product_performance(self, start: date, end: date) -> list[dict[str, Any]]:
        """Units, revenue and margin per product, plus how many orders contained it."""
        stmt = (
            select(
                TransactionItem.product_id,
                Product.name,
                Product.sku,
                Product.category,
                Product.price,
                func.coalesce(func.sum(TransactionItem.quantity), 0),
                func.coalesce(func.sum(TransactionItem.line_total), 0),
                func.coalesce(
                    func.sum(
                        TransactionItem.line_total
                        - (TransactionItem.unit_cost * TransactionItem.quantity)
                    ),
                    0,
                ),
                func.count(distinct(TransactionItem.transaction_id)),
            )
            .join(Transaction, Transaction.id == TransactionItem.transaction_id)
            .join(Product, Product.id == TransactionItem.product_id)
            .where(and_(*self._window(start, end)))
            .group_by(
                TransactionItem.product_id,
                Product.name,
                Product.sku,
                Product.category,
                Product.price,
            )
            .order_by(func.coalesce(func.sum(TransactionItem.line_total), 0).desc())
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            {
                "product_id": row[0],
                "name": row[1],
                "sku": row[2],
                "category": row[3],
                "price": round(_f(row[4]), 2),
                "units_sold": int(row[5] or 0),
                "revenue": round(_f(row[6]), 2),
                "gross_margin": round(_f(row[7]), 2),
                "orders": int(row[8] or 0),
            }
            for row in rows
        ]

    async def product_pairs(
        self, start: date, end: date, *, limit: int = 10, min_support: int = 8
    ) -> list[dict[str, Any]]:
        """Co-occurrence of product pairs within a single order (market-basket)."""
        a = TransactionItem.__table__.alias("item_a")
        b = TransactionItem.__table__.alias("item_b")
        pa = Product.__table__.alias("prod_a")
        pb = Product.__table__.alias("prod_b")

        stmt = (
            select(
                a.c.product_id,
                pa.c.name,
                b.c.product_id,
                pb.c.name,
                func.count(distinct(a.c.transaction_id)),
                func.coalesce(func.sum(a.c.line_total + b.c.line_total), 0),
            )
            .select_from(
                a.join(
                    b,
                    and_(a.c.transaction_id == b.c.transaction_id, a.c.product_id < b.c.product_id),
                )
                .join(Transaction, Transaction.id == a.c.transaction_id)
                .join(pa, pa.c.id == a.c.product_id)
                .join(pb, pb.c.id == b.c.product_id)
            )
            .where(and_(*self._window(start, end)))
            .group_by(a.c.product_id, pa.c.name, b.c.product_id, pb.c.name)
            .having(func.count(distinct(a.c.transaction_id)) >= min_support)
            .order_by(func.count(distinct(a.c.transaction_id)).desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()

        total_orders = await self.count_orders(start, end)
        product_orders = {
            row["product_id"]: row["orders"] for row in await self.product_performance(start, end)
        }

        pairs: list[dict[str, Any]] = []
        for row in rows:
            co = int(row[4] or 0)
            orders_a = product_orders.get(row[0], 0)
            support = (co / total_orders * 100) if total_orders else 0.0
            confidence = (co / orders_a * 100) if orders_a else 0.0
            expected = (
                (orders_a / total_orders) * (product_orders.get(row[2], 0) / total_orders)
                if total_orders
                else 0
            )
            lift = (co / total_orders / expected) if expected else 0.0
            pairs.append(
                {
                    "product_a_id": row[0],
                    "product_a_name": row[1],
                    "product_b_id": row[2],
                    "product_b_name": row[3],
                    "co_occurrences": co,
                    "support_pct": round(support, 2),
                    "confidence_pct": round(confidence, 2),
                    "lift": round(lift, 2),
                    "combined_revenue": round(_f(row[5]), 2),
                }
            )
        return pairs

    async def count_orders(self, start: date, end: date) -> int:
        stmt = select(func.count(Transaction.id)).where(and_(*self._window(start, end)))
        return int((await self.session.execute(stmt)).scalar_one() or 0)

    # ------------------------------------------------------------------ customers
    async def customer_activity(
        self, start: date, end: date, *, daypart: str | None = None
    ) -> list[dict[str, Any]]:
        conditions = self._window(start, end, daypart=daypart)
        conditions.append(Transaction.customer_id.is_not(None))
        stmt = (
            select(
                Transaction.customer_id,
                func.count(Transaction.id),
                func.coalesce(func.sum(Transaction.net_amount), 0),
                func.min(Transaction.business_date),
                func.max(Transaction.business_date),
            )
            .where(and_(*conditions))
            .group_by(Transaction.customer_id)
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            {
                "customer_id": row[0],
                "orders": int(row[1] or 0),
                "revenue": round(_f(row[2]), 2),
                "first_date": row[3],
                "last_date": row[4],
            }
            for row in rows
        ]

    async def active_customer_ids(
        self, start: date, end: date, *, daypart: str | None = None
    ) -> set[uuid.UUID]:
        conditions = self._window(start, end, daypart=daypart)
        conditions.append(Transaction.customer_id.is_not(None))
        stmt = select(distinct(Transaction.customer_id)).where(and_(*conditions))
        return {row[0] for row in (await self.session.execute(stmt)).all() if row[0]}

    async def retention_between(
        self, base_start: date, base_end: date, follow_start: date, follow_end: date
    ) -> dict[str, Any]:
        """Share of customers active in the base window who returned in the next one."""
        base = await self.active_customer_ids(base_start, base_end)
        follow = await self.active_customer_ids(follow_start, follow_end)
        retained = base & follow
        return {
            "base_customers": len(base),
            "retained_customers": len(retained),
            "retention_pct": round((len(retained) / len(base)) * 100, 2) if base else 0.0,
        }

    async def cohort_retention(
        self, *, months: int = 6, today: date | None = None
    ) -> list[dict[str, Any]]:
        """Monthly acquisition cohorts and their month-over-month return rate.

        Computed in Python from (customer, month) pairs so the query stays portable.
        """
        anchor = today or date.today()
        window_start = (anchor.replace(day=1) - timedelta(days=31 * months)).replace(day=1)

        stmt = select(Transaction.customer_id, Transaction.business_date).where(
            Transaction.merchant_id == self.merchant_id,
            Transaction.status == TransactionStatus.COMPLETED,
            Transaction.customer_id.is_not(None),
            Transaction.business_date >= window_start,
            Transaction.business_date <= anchor,
        )
        rows = (await self.session.execute(stmt)).all()

        months_active: dict[uuid.UUID, set[tuple[int, int]]] = defaultdict(set)
        for customer_id, business_date in rows:
            months_active[customer_id].add((business_date.year, business_date.month))

        cohorts: dict[tuple[int, int], list[uuid.UUID]] = defaultdict(list)
        for customer_id, active in months_active.items():
            cohorts[min(active)].append(customer_id)

        def month_index(base: tuple[int, int], other: tuple[int, int]) -> int:
            return (other[0] - base[0]) * 12 + (other[1] - base[1])

        results: list[dict[str, Any]] = []
        for cohort_month in sorted(cohorts):
            members = cohorts[cohort_month]
            size = len(members)
            if size == 0:
                continue
            for index in range(0, months):
                retained = sum(
                    1
                    for member in members
                    if any(month_index(cohort_month, m) == index for m in months_active[member])
                )
                if index > 0 and retained == 0:
                    continue
                results.append(
                    {
                        "cohort_month": f"{cohort_month[0]:04d}-{cohort_month[1]:02d}",
                        "cohort_size": size,
                        "month_index": index,
                        "retained": retained,
                        "retention_pct": round((retained / size) * 100, 2),
                    }
                )
        return results

    # ------------------------------------------------------------------ experiments
    async def experiment_aggregate(
        self,
        *,
        experiment_id: uuid.UUID,
        variant_key: str,
        customer_ids: list[uuid.UUID],
        start: date,
        end: date,
    ) -> dict[str, Any]:
        """Measured outcome for one variant. The only source of experiment numbers."""
        conditions = self._window(
            start,
            end,
            customer_ids=customer_ids,
            experiment_id=experiment_id,
            variant_key=variant_key,
        )
        stmt = select(
            func.count(distinct(Transaction.customer_id)),
            func.count(Transaction.id),
            func.coalesce(func.sum(Transaction.net_amount), 0),
            func.coalesce(func.sum(Transaction.cost_amount), 0),
        ).where(and_(*conditions))
        row = (await self.session.execute(stmt)).one()
        revenue = _f(row[2])
        cost = _f(row[3])
        return {
            "converted_customers": int(row[0] or 0),
            "orders": int(row[1] or 0),
            "revenue": round(revenue, 2),
            "gross_margin": round(revenue - cost, 2),
        }

    async def first_transaction_date(self) -> date | None:
        stmt = select(func.min(Transaction.business_date)).where(
            Transaction.merchant_id == self.merchant_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def last_transaction_date(self) -> date | None:
        stmt = select(func.max(Transaction.business_date)).where(
            Transaction.merchant_id == self.merchant_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def customers_by_daypart(self, start: date, end: date, daypart: str) -> list[uuid.UUID]:
        conditions = self._window(start, end, daypart=daypart)
        conditions.append(Transaction.customer_id.is_not(None))
        stmt = select(distinct(Transaction.customer_id)).where(and_(*conditions))
        return [row[0] for row in (await self.session.execute(stmt)).all() if row[0]]

    def scoped_customers(self) -> Select[Any]:
        return select(Customer).where(Customer.merchant_id == self.merchant_id)
