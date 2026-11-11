"""The customer storefront: a PayPal checkout whose sale starts the rest of the loop.

Runs against the labelled PayPal simulator (no keys, no network). What matters here is
what a public, unauthenticated, payment-adjacent endpoint must get right:

* the server prices the cart and a client cannot say otherwise,
* a sale is recorded exactly once - whether the customer returns from PayPal, PayPal's
  verified webhook arrives first, or both arrive,
* stock moves through the stock engine, so a low-stock crossing still raises its event,
* one shop cannot capture another shop's order, and only demo merchants sell publicly,
* checkout attempts are rate limited.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.v1 import shop as shop_api
from app.db.models.automation import DomainEvent, EventType
from app.db.models.commerce import Transaction
from app.db.models.inventory import InventoryItem, InventoryMovement, MovementType
from app.db.models.merchant import Merchant
from app.integrations.paypal import get_paypal_gateway, sign_simulated_webhook
from app.seed.supply import BEAN_SKU, seed_supply_network
from app.services.intelligence.events import BusinessEvent
from app.services.supply.demand import InventoryIntelligence


@pytest.fixture(autouse=True)
def _fresh_limiter():
    shop_api._limiter.reset()
    yield
    shop_api._limiter.reset()


async def _make_shop(engine, *, demo: bool = True) -> dict:
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    async with factory() as s:
        merchant = Merchant(name="Shop Cafe", slug=f"shop-cafe-{uuid.uuid4().hex[:8]}", category="cafe",
                            city="Portland", is_demo=demo)
        s.add(merchant)
        await s.flush()
        await seed_supply_network(s, merchant)
        await s.commit()
        item = (await s.execute(select(InventoryItem).where(
            InventoryItem.merchant_id == merchant.id, InventoryItem.sku == BEAN_SKU))).scalars().one()
        return {"slug": merchant.slug, "merchant_id": merchant.id, "product_id": item.product_id, "item_id": item.id}


@pytest.fixture
async def shop(engine, seeded):
    return await _make_shop(engine)


@pytest.fixture
def db(engine):
    return async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)


async def _on_hand(db, item_id) -> float:
    async with db() as s:
        return float((await s.get(InventoryItem, item_id)).quantity_on_hand)


async def _buy(client, shop, quantity: int = 2, **body):
    return await client.post(f"/shop/{shop['slug']}/orders",
                             json={"items": [{"product_id": str(shop["product_id"]), "quantity": quantity}], **body})


class TestCatalog:
    async def test_the_catalog_is_public_and_shows_the_real_price_and_stock(self, client, shop):
        response = await client.get(f"/shop/{shop['slug']}")  # no Authorization header
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["mode"] == "SIMULATED" and "simulated" in data["note"].lower()
        bean = next(p for p in data["products"] if p["sku"] == BEAN_SKU)
        assert bean["price"] == "18.00" and bean["available"] == 42 and bean["in_stock"] is True

    async def test_only_demo_merchants_sell_publicly(self, client, engine):
        private = await _make_shop(engine, demo=False)
        assert (await client.get(f"/shop/{private['slug']}")).status_code == 404
        assert (await client.get("/shop/no-such-shop")).status_code == 404


class TestCheckout:
    async def test_a_paid_order_becomes_a_sale_and_moves_stock(self, client, shop, db):
        created = (await _buy(client, shop, 2)).json()["data"]
        assert created["total"] == "36.00" and created["mode"] == "SIMULATED"
        assert created["needs_payer_approval"] is False  # the simulator approves instantly

        captured = await client.post(f"/shop/{shop['slug']}/orders/{created['order_id']}/capture")
        assert captured.status_code == 200
        sale = captured.json()["data"]
        assert sale["recorded_now"] is True and sale["total"] == "36.00"
        assert sale["items"] == [{"name": "Premium Coffee Beans (12 oz)", "quantity": 2, "unit_price": "18.00"}]
        stock = sale["stock"][0]
        assert (stock["on_hand_before"], stock["on_hand_after"]) == (42.0, 40.0)

        async with db() as s:
            tx = (await s.execute(select(Transaction).where(
                Transaction.merchant_id == shop["merchant_id"], Transaction.order_ref == f"PP-{created['order_id']}"
            ))).scalars().one()
            assert tx.channel == "online_store" and tx.payment_method == "paypal" and float(tx.gross_amount) == 36.0
            assert tx.metadata_json["paypal_order_id"] == created["order_id"]
            movement = (await s.execute(select(InventoryMovement).where(
                InventoryMovement.inventory_item_id == shop["item_id"], InventoryMovement.reference_id == created["order_id"]
            ))).scalars().one()
            assert movement.movement_type == MovementType.SALE and movement.balance_after == 40
            event = (await s.execute(select(DomainEvent).where(
                DomainEvent.merchant_id == shop["merchant_id"], DomainEvent.event_type == BusinessEvent.ONLINE_SALE_CAPTURED
            ))).scalars().one()
            assert event.payload["order_id"] == created["order_id"]

    async def test_capturing_twice_records_one_sale(self, client, shop, db):
        order = (await _buy(client, shop, 3)).json()["data"]["order_id"]
        first = (await client.post(f"/shop/{shop['slug']}/orders/{order}/capture")).json()["data"]
        again = (await client.post(f"/shop/{shop['slug']}/orders/{order}/capture")).json()["data"]
        assert first["recorded_now"] is True and again["recorded_now"] is False
        assert await _on_hand(db, shop["item_id"]) == 39  # 42 - 3, once
        async with db() as s:
            count = (await s.execute(select(func.count()).select_from(Transaction).where(
                Transaction.order_ref == f"PP-{order}"))).scalar_one()
        assert count == 1

    async def test_the_client_cannot_set_the_price(self, client, shop):
        response = await client.post(f"/shop/{shop['slug']}/orders", json={
            "items": [{"product_id": str(shop["product_id"]), "quantity": 1, "price": "0.01", "unit_amount": "0.01"}],
            "total": "0.01"})
        assert response.status_code == 200 and response.json()["data"]["total"] == "18.00"

    @pytest.mark.parametrize("quantity", [0, 11, -1])
    async def test_quantities_are_bounded(self, client, shop, quantity):
        assert (await _buy(client, shop, quantity)).status_code == 422

    async def test_unknown_products_and_empty_carts_are_refused(self, client, shop):
        bad = await client.post(f"/shop/{shop['slug']}/orders",
                                json={"items": [{"product_id": str(uuid.uuid4()), "quantity": 1}]})
        assert bad.status_code == 400
        assert (await client.post(f"/shop/{shop['slug']}/orders", json={"items": []})).status_code == 422

    async def test_you_cannot_order_more_than_is_in_stock(self, client, shop, db):
        async with db() as s:
            item = await s.get(InventoryItem, shop["item_id"])
            item.quantity_on_hand = 3
            await s.commit()
        assert (await _buy(client, shop, 4)).status_code == 409
        assert (await _buy(client, shop, 3)).status_code == 200

    async def test_a_retried_click_returns_the_same_order(self, client, shop):
        one = (await _buy(client, shop, 1, client_key="same-click")).json()["data"]["order_id"]
        two = (await _buy(client, shop, 1, client_key="same-click")).json()["data"]["order_id"]
        assert one == two

    async def test_an_unknown_order_cannot_be_captured(self, client, shop):
        assert (await client.post(f"/shop/{shop['slug']}/orders/SIM-ORDER-NOPE12/capture")).status_code == 404

    async def test_one_shop_cannot_capture_another_shops_order(self, client, shop, engine, db):
        other = await _make_shop(engine)
        order = (await _buy(client, shop, 1)).json()["data"]["order_id"]
        assert (await client.post(f"/shop/{other['slug']}/orders/{order}/capture")).status_code == 404
        assert await _on_hand(db, other["item_id"]) == 42

    async def test_checkout_is_rate_limited(self, client, shop):
        codes = [(await _buy(client, shop, 1)).status_code for _ in range(22)]
        assert codes[:20] == [200] * 20 and codes[20:] == [429, 429]


class TestTheLoopContinues:
    async def test_a_sale_that_crosses_the_reorder_point_raises_the_low_stock_event(self, client, shop, db):
        async with db() as s:
            item = await s.get(InventoryItem, shop["item_id"])
            item.quantity_on_hand, item.reorder_point = 62, 60
            await s.commit()
        order = (await _buy(client, shop, 5)).json()["data"]["order_id"]
        stock = (await client.post(f"/shop/{shop['slug']}/orders/{order}/capture")).json()["data"]["stock"][0]
        assert stock["crossed_reorder_point"] is True and stock["on_hand_after"] == 57
        async with db() as s:
            low = (await s.execute(select(func.count()).select_from(DomainEvent).where(
                DomainEvent.merchant_id == shop["merchant_id"], DomainEvent.event_type == EventType.LOW_STOCK))).scalar_one()
        assert low == 1

    async def test_a_customer_who_already_paid_is_never_lost_to_a_stock_race(self, client, shop, db):
        order = (await _buy(client, shop, 5)).json()["data"]["order_id"]
        async with db() as s:  # someone else buys the shelf empty before this order is captured
            item = await s.get(InventoryItem, shop["item_id"])
            item.quantity_on_hand = 2
            await s.commit()
        sale = (await client.post(f"/shop/{shop['slug']}/orders/{order}/capture")).json()["data"]
        assert sale["recorded_now"] is True and sale["stock"][0]["oversold"] is True


class TestWebhookPath:
    @staticmethod
    def capture_event(merchant_id, order_id: str, capture_id: str) -> bytes:
        return json.dumps({
            "id": f"WH-{uuid.uuid4().hex[:12]}", "event_type": "PAYMENT.CAPTURE.COMPLETED", "resource_type": "capture",
            "resource": {"id": capture_id, "status": "COMPLETED", "custom_id": f"{merchant_id}|shop",
                         "supplementary_data": {"related_ids": {"order_id": order_id}}},
        }).encode()

    async def _webhook(self, client, body: bytes):
        return await client.post("/paypal/webhooks", content=body,
                                 headers={"content-type": "application/json", **sign_simulated_webhook(body)})

    async def test_the_webhook_records_a_sale_the_customer_never_returned_for(self, client, shop, db):
        order = (await _buy(client, shop, 2)).json()["data"]["order_id"]
        captured = await get_paypal_gateway().capture_order(order, request_id=f"test:{order}")  # paid, tab closed
        body = self.capture_event(shop["merchant_id"], order, captured.capture_ids[0])
        assert (await self._webhook(client, body)).json()["data"]["outcome"] == "verified"
        assert await _on_hand(db, shop["item_id"]) == 40

        # The customer's return then finds it already recorded - and stock does not move again.
        later = (await client.post(f"/shop/{shop['slug']}/orders/{order}/capture")).json()["data"]
        assert later["recorded_now"] is False and await _on_hand(db, shop["item_id"]) == 40

    async def test_a_webhook_after_the_return_changes_nothing(self, client, shop, db):
        order = (await _buy(client, shop, 2)).json()["data"]["order_id"]
        sale = (await client.post(f"/shop/{shop['slug']}/orders/{order}/capture")).json()["data"]
        assert (await self._webhook(client, self.capture_event(shop["merchant_id"], order, sale["capture_id"]))
                ).json()["data"]["outcome"] == "verified"
        assert await _on_hand(db, shop["item_id"]) == 40
        async with db() as s:
            count = (await s.execute(select(func.count()).select_from(Transaction).where(
                Transaction.order_ref == f"PP-{order}"))).scalar_one()
        assert count == 1

    async def test_an_unsigned_capture_webhook_records_nothing(self, client, shop, db):
        order = (await _buy(client, shop, 2)).json()["data"]["order_id"]
        body = self.capture_event(shop["merchant_id"], order, "SIM-CAPTURE-X")
        response = await client.post("/paypal/webhooks", content=body, headers={"content-type": "application/json"})
        assert response.status_code == 401 and await _on_hand(db, shop["item_id"]) == 42


class TestTradingDay:
    """A demo is seeded once and then lags the wall clock; a live sale must not push the story out of its windows."""

    async def test_a_live_sale_is_booked_onto_the_datasets_trading_day(self, client, shop, db):
        async with db() as s:  # the seeded history ends 6 days ago, as a hosted demo's does
            rows = (await s.execute(select(Transaction).where(Transaction.merchant_id == shop["merchant_id"]))).scalars().all()
            for row in rows:
                row.business_date = row.business_date - timedelta(days=6)
            await s.commit()
            anchor = max(r.business_date for r in rows)

        order = (await _buy(client, shop, 2)).json()["data"]["order_id"]
        assert (await client.post(f"/shop/{shop['slug']}/orders/{order}/capture")).status_code == 200

        async with db() as s:
            tx = (await s.execute(select(Transaction).where(Transaction.order_ref == f"PP-{order}"))).scalars().one()
            assert tx.business_date == anchor  # booked to the dataset's current day, not to "today"
            assert abs((tx.occurred_at.replace(tzinfo=None) - __import__("datetime").datetime.utcnow()).total_seconds()) < 120
            beans = next(r for r in await InventoryIntelligence(s, shop["merchant_id"]).scan() if r.sku == BEAN_SKU)
        # Without this, velocity collapses (0.14/day), cover jumps to ~285 days and the suggestion becomes 0.
        assert float(beans.velocity_recent) > 12 and float(beans.days_of_cover) < 4 and float(beans.suggested_quantity) > 0
