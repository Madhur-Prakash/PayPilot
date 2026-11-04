"""Customer repository, including server-side segment materialisation."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import and_, case, func, select

from app.db.models.commerce import Customer, CustomerSegment, Transaction, TransactionStatus
from app.repositories.base import MerchantScopedRepository


class CustomerRepository(MerchantScopedRepository[Customer]):
    model = Customer

    async def list_by_ids(self, customer_ids: list[uuid.UUID]) -> list[Customer]:
        if not customer_ids:
            return []
        stmt = self.scoped().where(Customer.id.in_(customer_ids))
        return list((await self.session.execute(stmt)).scalars().all())

    async def segment_counts(self) -> dict[str, int]:
        stmt = (
            select(Customer.segment, func.count(Customer.id))
            .where(Customer.merchant_id == self.merchant_id)
            .group_by(Customer.segment)
        )
        rows = (await self.session.execute(stmt)).all()
        return {row[0]: int(row[1] or 0) for row in rows}

    async def daypart_counts(self) -> dict[str, int]:
        stmt = (
            select(Customer.preferred_daypart, func.count(Customer.id))
            .where(Customer.merchant_id == self.merchant_id)
            .group_by(Customer.preferred_daypart)
        )
        rows = (await self.session.execute(stmt)).all()
        return {row[0]: int(row[1] or 0) for row in rows}

    async def total_customers(self) -> int:
        return await self.count()

    async def churn_risk_count(self, *, threshold_days: int = 30) -> int:
        return await self.count(
            Customer.recency_days.is_not(None), Customer.recency_days > threshold_days
        )

    # ------------------------------------------------------------------ segments
    async def resolve_segment(
        self,
        *,
        dayparts: list[str] | None = None,
        segments: list[str] | None = None,
        min_orders: int | None = None,
        max_orders: int | None = None,
        min_recency_days: int | None = None,
        max_recency_days: int | None = None,
        min_total_spend: float | None = None,
        product_ids: list[uuid.UUID] | None = None,
        active_dayparts: list[str] | None = None,
        active_within_days: int | None = None,
        opted_in_only: bool = True,
        limit: int = 5000,
    ) -> list[Customer]:
        """Materialise an audience from a validated filter.

        The filter is applied in SQL against this merchant's customers only - a
        caller can never widen the scope by passing ids from another tenant.
        """
        conditions: list[Any] = [Customer.merchant_id == self.merchant_id]
        if dayparts:
            conditions.append(Customer.preferred_daypart.in_(dayparts))
        if segments:
            conditions.append(Customer.segment.in_(segments))
        if min_orders is not None:
            conditions.append(Customer.total_orders >= min_orders)
        if max_orders is not None:
            conditions.append(Customer.total_orders <= max_orders)
        if min_recency_days is not None:
            conditions.append(Customer.recency_days >= min_recency_days)
        if max_recency_days is not None:
            conditions.append(Customer.recency_days <= max_recency_days)
        if min_total_spend is not None:
            conditions.append(Customer.total_spend >= min_total_spend)
        if opted_in_only:
            conditions.append(Customer.is_opted_in.is_(True))

        stmt = select(Customer).where(and_(*conditions))

        if active_dayparts:
            # Behavioural membership: customers who actually *transacted* in these slots.
            # This is the right audience for a win-back - it includes people who have
            # since drifted to another slot, whom `preferred_daypart` would miss.
            behaviour = select(Transaction.customer_id).where(
                Transaction.merchant_id == self.merchant_id,
                Transaction.status == TransactionStatus.COMPLETED,
                Transaction.daypart.in_(active_dayparts),
                Transaction.customer_id.is_not(None),
            )
            if active_within_days is not None:
                cutoff = date.today() - timedelta(days=active_within_days)
                behaviour = behaviour.where(Transaction.business_date >= cutoff)
            stmt = stmt.where(Customer.id.in_(behaviour))

        if product_ids:
            from app.db.models.commerce import TransactionItem

            buyers = (
                select(Transaction.customer_id)
                .join(TransactionItem, TransactionItem.transaction_id == Transaction.id)
                .where(
                    Transaction.merchant_id == self.merchant_id,
                    TransactionItem.product_id.in_(product_ids),
                    Transaction.customer_id.is_not(None),
                )
            )
            stmt = stmt.where(Customer.id.in_(buyers))

        # Deterministic ordering keeps demo runs reproducible.
        stmt = stmt.order_by(Customer.total_spend.desc(), Customer.external_ref).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def paypal_acquired_stats(
        self, *, dayparts: list[str] | None = None
    ) -> dict[str, float]:
        """Real, historical grounding for "the PayPal surface" - customers whose
        first order came through PayPal Checkout on the merchant's online store
        (``acquisition_channel='paypal_checkout'``), optionally narrowed to the
        daypart an opportunity concerns.

        This is not a PayPal audience feed - PayPal does not share its consumer
        base, and nothing here pretends it does. It is the merchant's *own*
        history: how many customers with this profile PayPal Checkout has already
        brought in, which is what sizes PayPal-powered levers (cashback via
        Payouts, Pay Later messaging, checkout promotions) honestly.
        """
        conditions: list[Any] = [
            Customer.merchant_id == self.merchant_id,
            Customer.acquisition_channel.in_(("paypal_checkout", "paypal_app")),
        ]
        if dayparts:
            conditions.append(Customer.preferred_daypart.in_(dayparts))
        stmt = select(
            func.count(Customer.id),
            func.coalesce(func.avg(Customer.avg_order_value), 0),
            func.coalesce(func.avg(Customer.total_orders), 0),
            func.sum(case((Customer.total_orders >= 2, 1), else_=0)),
        ).where(and_(*conditions))
        row = (await self.session.execute(stmt)).one()
        size = int(row[0] or 0)
        repeat = int(row[3] or 0)
        return {
            "size": size,
            "avg_order_value": round(float(row[1] or 0), 2),
            "avg_orders": round(float(row[2] or 0), 2),
            "repeat_rate_pct": round((repeat / size) * 100, 1) if size else 0.0,
        }

    async def high_propensity_share(self, customer_ids: list[uuid.UUID]) -> float:
        """Fraction of this audience that already orders regularly (>=3 past
        orders) without needing this campaign to exist - the real number behind
        the "don't discount" check: customers who would likely buy anyway."""
        if not customer_ids:
            return 0.0
        stmt = select(
            func.count(Customer.id),
            func.sum(case((Customer.total_orders >= 3, 1), else_=0)),
        ).where(Customer.merchant_id == self.merchant_id, Customer.id.in_(customer_ids))
        row = (await self.session.execute(stmt)).one()
        size = int(row[0] or 0)
        high = int(row[1] or 0)
        return round((high / size) * 100, 1) if size else 0.0

    async def segment_stats(self, customer_ids: list[uuid.UUID]) -> dict[str, float]:
        if not customer_ids:
            return {"size": 0, "total_spend": 0.0, "avg_order_value": 0.0, "avg_orders": 0.0}
        stmt = select(
            func.count(Customer.id),
            func.coalesce(func.sum(Customer.total_spend), 0),
            func.coalesce(func.avg(Customer.avg_order_value), 0),
            func.coalesce(func.avg(Customer.total_orders), 0),
        ).where(Customer.merchant_id == self.merchant_id, Customer.id.in_(customer_ids))
        row = (await self.session.execute(stmt)).one()
        return {
            "size": int(row[0] or 0),
            "total_spend": round(float(row[1] or 0), 2),
            "avg_order_value": round(float(row[2] or 0), 2),
            "avg_orders": round(float(row[3] or 0), 2),
        }

    # ------------------------------------------------------------------ rollups
    async def recompute_rollups(self, *, today: date | None = None) -> int:
        """Refresh per-customer totals from transactions.

        Run by the seeder and after simulated campaigns so ``segment`` /
        ``recency_days`` always agree with the transaction ledger.
        """
        anchor = today or date.today()
        stmt = (
            select(
                Transaction.customer_id,
                func.count(Transaction.id),
                func.coalesce(func.sum(Transaction.net_amount), 0),
                func.min(Transaction.occurred_at),
                func.max(Transaction.occurred_at),
                func.max(Transaction.business_date),
            )
            .where(
                Transaction.merchant_id == self.merchant_id,
                Transaction.status == TransactionStatus.COMPLETED,
                Transaction.customer_id.is_not(None),
            )
            .group_by(Transaction.customer_id)
        )
        rows = (await self.session.execute(stmt)).all()
        rollups = {
            row[0]: {
                "orders": int(row[1] or 0),
                "spend": float(row[2] or 0),
                "first": row[3],
                "last": row[4],
                "last_date": row[5],
            }
            for row in rows
        }

        customers = list((await self.session.execute(self.scoped())).scalars().all())
        for customer in customers:
            data = rollups.get(customer.id)
            if not data:
                customer.total_orders = 0
                customer.total_spend = 0
                customer.avg_order_value = 0
                customer.recency_days = None
                customer.segment = CustomerSegment.NEW
                continue
            orders = data["orders"]
            customer.total_orders = orders
            customer.total_spend = round(data["spend"], 2)
            customer.avg_order_value = round(data["spend"] / orders, 2) if orders else 0
            customer.first_order_at = data["first"]
            customer.last_order_at = data["last"]
            recency = (anchor - data["last_date"]).days if data["last_date"] else None
            customer.recency_days = recency
            customer.segment = _classify(orders, recency)

        await self.session.flush()
        return len(customers)


def _classify(orders: int, recency_days: int | None) -> str:
    """RFM-lite segmentation used consistently across the product."""
    if recency_days is None:
        return CustomerSegment.NEW
    if recency_days > 60:
        return CustomerSegment.CHURNED
    if recency_days > 30:
        return CustomerSegment.AT_RISK
    if orders >= 8:
        return CustomerSegment.LOYAL
    if orders >= 2:
        return CustomerSegment.REPEAT
    return CustomerSegment.NEW
