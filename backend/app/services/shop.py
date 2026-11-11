"""The customer storefront: a real PayPal checkout that starts the loop.

Until this existed PayPal only appeared at the *end* of PayPilot's story - when the
merchant paid a supplier. The merchant's sales came from a seeded dataset. This is the
other end: a customer buys the shop's online beans with PayPal, and that sale is what
the rest of the product reacts to.

    customer pays with PayPal
      -> the sale is recorded as a transaction (channel ``online_store``)
      -> stock is decremented through the stock engine (SALE movement, ledger row)
      -> a low-stock event fires if the sale crosses the reorder point
      -> a business event reaches the Command Center
      -> reorder recommendations see the new cover; the agents take it from there

Design decisions worth knowing before changing this:

* **No new table.** PayPal remembers the cart: the order is created with ``items`` and
  ``custom_id = "<merchant id>|shop"`` and PayPal returns both on GET order. The sale is
  rebuilt from that, so there is no pending-order state to migrate, expire or clean up.
* **Two ways in, one result.** The browser return (``capture``) and PayPal's verified
  ``PAYMENT.CAPTURE.COMPLETED`` webhook both call :meth:`record_paid_order`, which is
  idempotent on ``order_ref = PP-<order id>`` and serialised per order, so whichever
  arrives second changes nothing - and a customer who closes the tab after paying is
  still recorded by the webhook.
* **The server prices the cart.** The browser sends product ids and quantities, never
  amounts; totals come from the catalog, quantised with the same ``money`` helper as
  every other figure.
* **Only a demo merchant sells publicly.** An unauthenticated checkout is enabled
  per merchant (``is_demo``), not globally.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError, ConflictError, IntegrationError, NotFoundError
from app.core.logging import get_logger
from app.db.models.commerce import DayPart, Product, Transaction, TransactionItem, TransactionStatus
from app.db.models.inventory import InventoryItem, MovementType
from app.db.models.merchant import Merchant
from app.integrations.paypal import get_paypal_gateway
from app.integrations.paypal.errors import PayPalError
from app.integrations.paypal.models import OrderItem, PayPalOrder
from app.services.intelligence.events import BusinessEvent, emit_business_event
from app.services.inventory.stock import InsufficientStock, StockEngine
from app.services.supply.policy import money

log = get_logger(__name__)

MAX_LINES = 5
MAX_QUANTITY = 10
SHOP_SUFFIX = "|shop"


async def get_shop_merchant(session: AsyncSession, slug: str) -> Merchant:
    merchant = (await session.execute(select(Merchant).where(Merchant.slug == slug))).scalars().first()
    # The same answer for "no such shop" and "not a public shop": a probe learns nothing.
    if merchant is None or not merchant.is_demo:
        raise NotFoundError("This shop does not exist.")
    return merchant


def _is_online(product: Product) -> bool:
    return (product.attributes or {}).get("channel") == "online_store" or "online" in (product.tags or [])


def _order_ref(order_id: str) -> str:
    return f"PP-{order_id}"[:48]


class ShopService:
    def __init__(self, session: AsyncSession, merchant: Merchant) -> None:
        self.session = session
        self.merchant = merchant

    # ------------------------------------------------------------------ catalog
    async def _online_products(self) -> list[Product]:
        rows = (await self.session.execute(
            select(Product).where(Product.merchant_id == self.merchant.id, Product.is_active.is_(True))
            .order_by(Product.name)
        )).scalars().all()
        return [p for p in rows if _is_online(p)]

    async def _stock(self, product_ids: list[uuid.UUID]) -> dict[uuid.UUID, InventoryItem]:
        if not product_ids:
            return {}
        rows = (await self.session.execute(
            select(InventoryItem).where(InventoryItem.merchant_id == self.merchant.id,
                                        InventoryItem.product_id.in_(product_ids))
        )).scalars().all()
        return {r.product_id: r for r in rows}

    async def catalog(self) -> dict[str, Any]:
        products = await self._online_products()
        stock = await self._stock([p.id for p in products])
        gateway = get_paypal_gateway()
        out = []
        for p in products:
            item = stock.get(p.id)
            available = max(int(item.available_quantity), 0) if item is not None else None
            out.append({
                "id": str(p.id), "sku": p.sku, "name": p.name, "description": p.description,
                "price": str(money(p.price)), "currency": self.merchant.currency, "image_url": p.image_url,
                "available": available, "in_stock": available is None or available > 0,
            })
        return {
            "merchant": {"name": self.merchant.name, "city": self.merchant.city, "slug": self.merchant.slug},
            "mode": gateway.mode, "currency": self.merchant.currency, "products": out,
            "max_quantity": MAX_QUANTITY,
            "note": ("Payments run on the PayPal sandbox - no real money moves." if gateway.mode == "SANDBOX"
                     else "PayPal is simulated here - no real money moves." if gateway.mode == "SIMULATED"
                     else "Live PayPal payments."),
        }

    # ------------------------------------------------------------------ create
    async def create_order(self, lines: list[tuple[uuid.UUID, int]], *, client_key: str | None) -> dict[str, Any]:
        merged: dict[uuid.UUID, int] = {}
        for product_id, quantity in lines:
            merged[product_id] = merged.get(product_id, 0) + int(quantity)
        if not merged or len(merged) > MAX_LINES or any(not 1 <= q <= MAX_QUANTITY for q in merged.values()):
            raise BadRequestError(f"Order 1-{MAX_LINES} products, 1-{MAX_QUANTITY} of each.")

        products = {p.id: p for p in await self._online_products()}
        stock = await self._stock(list(merged))
        order_items: list[OrderItem] = []
        total = Decimal("0")
        for product_id, quantity in merged.items():
            product = products.get(product_id)
            if product is None:
                raise BadRequestError("One of those products is not sold online.")
            item = stock.get(product_id)
            if item is not None and quantity > item.available_quantity:
                raise ConflictError(f"Only {max(int(item.available_quantity), 0)} of {product.name} left.")
            unit = money(product.price)
            total += unit * quantity
            order_items.append(OrderItem(name=product.name[:127], quantity=quantity, unit_amount=unit, sku=product.sku[:127]))
        total = money(total)

        gateway = get_paypal_gateway()
        # A client-supplied key makes a retried click return the same PayPal order.
        key = (client_key or uuid.uuid4().hex)[:64]
        try:
            order = await gateway.create_order(
                intent="CAPTURE", amount=total, currency=self.merchant.currency,
                reference_id=f"SHOP-{key[:12]}", description=f"{self.merchant.name} online order"[:127],
                request_id=f"shop-order:{self.merchant.id}:{key}", custom_id=f"{self.merchant.id}{SHOP_SUFFIX}",
                items=order_items,
                return_url=f"{settings.frontend_url}/shop/return?shop={self.merchant.slug}",
                cancel_url=f"{settings.frontend_url}/shop?cancelled=1",
            )
        except PayPalError as exc:
            log.warning("shop_order_failed", error=exc.message, debug_id=getattr(exc, "debug_id", ""))
            raise IntegrationError(f"PayPal could not create the order: {exc.message}") from exc
        return {
            "order_id": order.id, "status": order.status, "approve_url": order.approve_url or None,
            # Simulated payers approve instantly; a real one is sent to PayPal first.
            "needs_payer_approval": order.status != "APPROVED", "mode": gateway.mode,
            "total": str(total), "currency": self.merchant.currency,
            "items": [{"name": i.name, "quantity": i.quantity, "unit_price": str(i.unit_amount)} for i in order_items],
        }

    # ------------------------------------------------------------------ capture
    async def capture(self, order_id: str) -> dict[str, Any]:
        gateway = get_paypal_gateway()
        try:
            order = await gateway.get_order(order_id)
        except PayPalError as exc:
            raise NotFoundError("That order was not found.") from exc
        self._ensure_ours(order)

        existing = await self._existing(order_id)
        if existing is not None:
            return await self._summary(existing, recorded_now=False, capture_id=None, order=order)

        if order.status == "COMPLETED":  # already captured elsewhere (the webhook got there first)
            capture_id = order.capture_ids[0] if order.capture_ids else ""
        elif order.status == "APPROVED":
            try:
                captured = await gateway.capture_order(order_id, request_id=f"shop-capture:{order_id}")
            except PayPalError as exc:
                raise IntegrationError(f"PayPal could not capture the payment: {exc.message}") from exc
            if captured.status != "COMPLETED" or not captured.capture_ids:
                raise ConflictError("PayPal did not complete the payment.")
            capture_id = captured.capture_ids[0]
            order = captured if captured.raw.get("purchase_units", [{}])[0].get("items") else order
        else:
            raise ConflictError("The payment has not been approved in PayPal yet.")
        return await self.record_paid_order(order, capture_id, source="return")

    def _ensure_ours(self, order: PayPalOrder) -> None:
        unit = (order.raw.get("purchase_units") or [{}])[0]
        if str(unit.get("custom_id") or "") != f"{self.merchant.id}{SHOP_SUFFIX}":
            raise NotFoundError("That order was not found.")

    async def _existing(self, order_id: str) -> Transaction | None:
        return (await self.session.execute(
            select(Transaction).where(Transaction.merchant_id == self.merchant.id,
                                      Transaction.order_ref == _order_ref(order_id))
        )).scalars().first()

    # ------------------------------------------------------------------ record
    async def record_paid_order(self, order: PayPalOrder, capture_id: str, *, source: str) -> dict[str, Any]:
        """Turn a paid PayPal order into a sale. Idempotent; the browser and the webhook both call it."""
        self._ensure_ours(order)
        if self.session.bind is not None and settings.is_postgres:
            # Serialise per order, so the browser return and the webhook cannot both insert.
            key = int.from_bytes(hashlib.blake2b(order.id.encode(), digest_size=8).digest(), "big", signed=True)
            await self.session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": key})
        existing = await self._existing(order.id)
        if existing is not None:
            return await self._summary(existing, recorded_now=False, capture_id=capture_id, order=order)

        unit = (order.raw.get("purchase_units") or [{}])[0]
        raw_items = unit.get("items") or []
        if not raw_items:
            raise BadRequestError("The PayPal order has no line items to record.")
        by_sku = {p.sku: p for p in await self._online_products()}
        stock = await self._stock([p.id for p in by_sku.values()])

        lines: list[tuple[Product, int, Decimal]] = []
        for raw in raw_items:
            product = by_sku.get(str(raw.get("sku") or ""))
            if product is None:
                continue
            lines.append((product, int(raw.get("quantity") or 1), money((raw.get("unit_amount") or {}).get("value") or product.price)))
        if not lines:
            raise BadRequestError("None of the order's products are sold by this shop.")

        gross = sum((price * qty for _, qty, price in lines), Decimal("0"))
        paid = money(order.amount.value) if order.amount is not None else money(gross)
        cost = sum((money(p.cost_price) * qty for p, qty, _ in lines), Decimal("0"))
        now = datetime.now(tz=UTC)
        try:
            local = now.astimezone(ZoneInfo(self.merchant.timezone))
        except Exception:  # an unknown zone name must not lose a paid sale
            local = now
        business_date = await self._trading_day(local.date())

        tx = Transaction(
            merchant_id=self.merchant.id, customer_id=None, order_ref=_order_ref(order.id), occurred_at=now,
            business_date=business_date, daypart=DayPart.from_hour(local.hour), hour_of_day=local.hour,
            day_of_week=business_date.weekday(), gross_amount=paid, discount_amount=0, net_amount=paid,
            cost_amount=money(cost), item_count=sum(q for _, q, _ in lines), payment_method="paypal",
            channel="online_store", status=TransactionStatus.COMPLETED, is_repeat=False,
            metadata_json={"source": "online_store", "paypal_order_id": order.id, "paypal_capture_id": capture_id,
                           "paypal_mode": get_paypal_gateway().mode, "recorded_by": source},
        )
        for product, qty, price in lines:
            tx.items.append(TransactionItem(
                merchant_id=self.merchant.id, product_id=product.id, product_name=product.name, quantity=qty,
                unit_price=price, unit_cost=money(product.cost_price), line_total=money(price * qty), discount_amount=0,
            ))
        self.session.add(tx)
        await self.session.flush()

        engine = StockEngine(self.session, self.merchant.id)
        movements: list[dict[str, Any]] = []
        for product, qty, _ in lines:
            item = stock.get(product.id)
            if item is None:
                continue
            kwargs: dict[str, Any] = {
                "item_id": item.id, "movement_type": MovementType.SALE, "quantity": qty,
                "correlation_id": f"SHOP-{order.id}"[:48], "note": f"Online sale paid with PayPal ({order.id})",
                "reference_type": "PAYPAL_ORDER", "reference_id": order.id, "actor_type": "SYSTEM",
                "source": "paypal_shop", "metadata": {"paypal_capture_id": capture_id},
            }
            oversold = False
            try:
                change = await engine.apply(**kwargs)
            except InsufficientStock:
                # The customer has already paid: record the sale, flag the shortfall, do not lose it.
                change = await engine.apply(**kwargs, allow_negative=True)
                oversold = True
            movements.append({
                "sku": product.sku, "name": product.name, "quantity": qty, "on_hand_before": change.balance_before,
                "on_hand_after": change.balance_after, "status": change.status_after, "oversold": oversold,
                "crossed_reorder_point": change.crossed_reorder_point,
            })

        await emit_business_event(
            self.session, merchant_id=self.merchant.id, event_type=BusinessEvent.ONLINE_SALE_CAPTURED,
            correlation_id=f"SHOP-{order.id}"[:48], entity_type="transaction", entity_id=tx.id, source="paypal_shop",
            payload={"order_id": order.id, "capture_id": capture_id, "total": str(paid), "currency": self.merchant.currency,
                     "mode": get_paypal_gateway().mode, "stock": movements, "recorded_by": source},
        )
        await self.session.flush()
        log.info("shop_sale_recorded", order_id=order.id, total=str(paid), source=source, merchant_id=str(self.merchant.id))
        return await self._summary(tx, recorded_now=True, capture_id=capture_id, order=order, movements=movements)

    async def _trading_day(self, today: date) -> date:
        """The business day a live sale belongs to.

        Every analytics window (demand velocity, cover, growth comparisons) is anchored on the
        latest ``business_date`` in the merchant's data, because a demo is seeded once and then
        lags the wall clock. A live sale dated *today* would jump that anchor past the seeded
        history and push the whole story out of its windows - one purchase would turn "demand
        +71%, 3.5 days of cover" into "no recent sales". So a demo merchant books a live sale onto
        the dataset's current trading day; ``occurred_at`` keeps the real moment.
        """
        latest = (await self.session.execute(
            select(func.max(Transaction.business_date)).where(Transaction.merchant_id == self.merchant.id)
        )).scalar_one_or_none()
        return min(today, latest) if latest is not None else today

    async def _summary(self, tx: Transaction, *, recorded_now: bool, capture_id: str | None, order: PayPalOrder,
                       movements: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        await self.session.refresh(tx, attribute_names=["items"])
        meta = tx.metadata_json or {}
        return {
            "recorded_now": recorded_now, "order_ref": tx.order_ref, "paypal_order_id": order.id,
            "capture_id": capture_id or meta.get("paypal_capture_id"), "mode": meta.get("paypal_mode"),
            "total": str(money(tx.gross_amount)), "currency": self.merchant.currency,
            "items": [{"name": i.product_name, "quantity": i.quantity, "unit_price": str(money(i.unit_price))} for i in tx.items],
            "stock": movements or [], "paid_at": tx.occurred_at.isoformat(),
        }
