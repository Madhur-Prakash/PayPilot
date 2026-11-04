"""The signature demo, end to end, through the real API.

Rising demand -> stockout risk -> RFQ -> three independent supplier agents ->
multi-round negotiation -> deterministic recommendation -> an Analyst is denied ->
an Owner approves -> purchase order + supplier invoice -> partial receipt flags a
discrepancy -> full receipt matches -> payment approval -> PayPal payment
(simulated) -> reconciliation -> inventory revalued, margin up, supplier learning.

Runs with no LLM key and no PayPal credentials, which is the point: the
deterministic core is the product, and it is the same every run.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.inventory import InventoryItem
from app.db.models.merchant import Merchant
from app.db.models.supply import NegotiationOffer, SupplierAgent
from app.seed.supply import BEAN_SKU, seed_supply_network


@pytest.fixture(scope="module")
async def network(engine, seeded) -> dict:
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        merchant = await s.get(Merchant, seeded["merchant_id"])
        await seed_supply_network(s, merchant)
        await s.commit()
        item = (await s.execute(
            select(InventoryItem).where(InventoryItem.merchant_id == merchant.id, InventoryItem.sku == BEAN_SKU)
        )).scalars().first()
        return {"item_id": str(item.id), "factory": factory}


async def _reset_item(network) -> None:
    """Each lifecycle test starts from the seeded stock position."""
    async with network["factory"]() as s:
        await s.execute(update(InventoryItem).where(InventoryItem.sku == BEAN_SKU)
                        .values(quantity_on_hand=Decimal("42"), unit_cost=Decimal("11.60")))
        await s.commit()


class TestInventoryIntelligence:
    async def test_the_beans_are_flagged_with_the_brief_numbers(self, client, analyst_headers, network):
        response = await client.get("/supply/demand", headers=analyst_headers)
        assert response.status_code == 200
        beans = next(r for r in response.json()["data"] if r["sku"] == BEAN_SKU)
        assert Decimal(beans["velocity_recent"]) == Decimal("12.00")
        assert Decimal(beans["velocity_prior"]) == Decimal("7.00")
        assert beans["stockout_risk"] is True
        assert Decimal(beans["suggested_quantity"]) == Decimal("150")
        assert beans["required_within_days"] == 3


class TestSignatureScenario:
    async def test_the_full_procurement_lifecycle(
        self, client, analyst_headers, owner_headers, viewer_headers, staff_headers, network
    ):
        await _reset_item(network)
        # ---- an Analyst sources and negotiates (moves no money)
        created = await client.post("/procurement", headers=analyst_headers,
                                    json={"inventory_item_id": network["item_id"], "auto_negotiate": True})
        assert created.status_code == 201, created.text
        request = created.json()["data"]
        assert request["status"] == "AWAITING_APPROVAL"
        assert Decimal(request["policy"]["max_unit_cost"]) == Decimal("10.8000")
        assert Decimal(request["policy"]["max_budget"]) == Decimal("1620.00")
        assert len(request["sessions"]) == 3
        winner = request["recommendation"]["winner"]
        assert winner["supplier_name"] == "Cascadia Coffee Collective"
        assert Decimal(request["final_landed_total"]) <= Decimal("1620.00")
        assert Decimal(request["savings_amount"]) > 0
        ineligible = {r["supplier_name"] for r in request["recommendation"]["ineligible"]}
        assert "Pacific Bean Exchange" in ineligible
        # Every offer was validated by the backend, and the conversation is signed.
        for session in request["sessions"]:
            for offer in session["offers"]:
                assert offer["validation_status"] in ("VALID", "OUT_OF_POLICY")
                assert offer["terms_hash"]
        messages = (await client.get(f"/procurement/{request['procurement_request_id']}/messages",
                                     headers=viewer_headers)).json()["data"]
        types = {m["message_type"] for m in messages}
        assert {"PROCUREMENT_REQUEST", "SUPPLIER_DISCOVERY", "RFQ_CREATED", "QUOTE_SUBMITTED", "COUNTEROFFER"} <= types
        assert all(m["verified"] for m in messages)

        # ---- the Analyst tries to approve and is denied; so is a Viewer
        rid = request["procurement_request_id"]
        denied = await client.post(f"/procurement/{rid}/approve", headers=analyst_headers, json={"approve": True})
        assert denied.status_code == 403
        approval_id = request["approval"]["approval_id"]
        denied_inbox = await client.post(f"/approvals/{approval_id}/decide", headers=analyst_headers, json={"approve": True})
        assert denied_inbox.status_code == 403
        assert (await client.post(f"/approvals/{approval_id}/decide", headers=viewer_headers,
                                  json={"approve": True})).status_code == 403

        # ---- the Owner approves through the inbox (bound to the exact terms)
        approved = await client.post(f"/approvals/{approval_id}/decide", headers=owner_headers,
                                     json={"approve": True, "note": "Go"})
        assert approved.status_code == 200, approved.text
        assert approved.json()["data"]["status"] == "EXECUTED"
        detail = (await client.get(f"/procurement/{rid}", headers=owner_headers)).json()["data"]
        assert detail["status"] == "ORDERED"
        order = detail["purchase_order"]
        assert order and len(detail["invoices"]) == 1
        line_id = order["lines"][0]["line_id"]
        invoice_id = detail["invoices"][0]["supplier_invoice_id"]

        # ---- partial receipt: the invoice bills goods not yet received
        partial = await client.post(f"/purchase-orders/{order['purchase_order_id']}/goods-receipts",
                                    headers=staff_headers, json={"lines": [{"line_id": line_id, "quantity": 100}]})
        assert partial.status_code == 201, partial.text
        assert partial.json()["data"]["is_partial"] is True
        detail = (await client.get(f"/procurement/{rid}", headers=owner_headers)).json()["data"]
        assert detail["invoices"][0]["status"] == "DISCREPANCY"
        assert detail["invoices"][0]["match"]["discrepancies"][0]["code"] == "BILLED_NOT_RECEIVED"
        # Paying now is impossible - nothing has been approved for payment.
        assert (await client.post(f"/supplier-invoices/{invoice_id}/pay", headers=owner_headers)).status_code == 409

        # ---- the rest arrives; matching clears and payment approval is requested
        rest = await client.post(f"/purchase-orders/{order['purchase_order_id']}/goods-receipts",
                                 headers=staff_headers, json={"lines": [{"line_id": line_id, "quantity": 50}]})
        assert rest.status_code == 201
        detail = (await client.get(f"/procurement/{rid}", headers=owner_headers)).json()["data"]
        invoice = detail["invoices"][0]
        assert invoice["status"] == "PAYMENT_APPROVAL_PENDING"
        assert detail["status"] == "PAYMENT_PENDING"

        assert (await client.post(f"/supplier-invoices/{invoice_id}/approve-payment", headers=analyst_headers,
                                  json={"approve": True})).status_code == 403
        ok = await client.post(f"/supplier-invoices/{invoice_id}/approve-payment", headers=owner_headers,
                               json={"approve": True})
        assert ok.status_code == 200, ok.text

        # ---- PayPal payment (simulated, labelled) and automatic reconciliation
        paid = await client.post(f"/supplier-invoices/{invoice_id}/pay", headers=owner_headers)
        assert paid.status_code == 200, paid.text
        execution = paid.json()["data"]
        assert execution["mode"] == "SIMULATED"
        assert execution["paypal_order_id"].startswith("SIM-ORDER-")
        assert execution["paypal_capture_id"].startswith("SIM-CAPTURE-")
        # Paying twice returns the same execution - never a second payment.
        again = await client.post(f"/supplier-invoices/{invoice_id}/pay", headers=owner_headers)
        assert again.json()["data"]["execution_id"] == execution["execution_id"]

        detail = (await client.get(f"/procurement/{rid}", headers=owner_headers)).json()["data"]
        assert detail["status"] == "RECONCILED"
        rec = detail["reconciliation"]
        assert Decimal(rec["paid_amount"]) == Decimal(rec["invoice_total"])
        assert Decimal(rec["new_unit_cost"]) < Decimal(rec["previous_unit_cost"])
        assert Decimal(rec["new_margin_pct"]) > Decimal(rec["previous_margin_pct"])

        # ---- unified intelligence: margin event + supplier learning + command center
        events = (await client.get("/events", headers=owner_headers)).json()["data"]
        kinds = {e["event_type"] for e in events}
        assert {"business.procurement_required", "business.supplier_selected", "business.purchase_approved",
                "business.goods_received", "business.payment_reconciled", "business.product_margin_changed"} <= kinds
        async with network["factory"]() as s:
            cascadia = (await s.execute(select(SupplierAgent).where(SupplierAgent.agent_key == "supplier.cascadia"))).scalars().first()
            assert cascadia.orders_completed == 16
        center = (await client.get("/command-center", headers=owner_headers)).json()["data"]
        assert Decimal(center["procurement"]["savings"]) > 0
        assert center["margins"]

        # ---- the Gantt shows every stage the system really recorded, chained in order
        timeline = (await client.get("/supply/timeline", headers=owner_headers)).json()["data"]
        parent = next(t for t in timeline["tasks"] if t["id"] == rid)
        by_name = {c["name"]: c for c in parent["children"]}
        assert {"RFQ & negotiation", "Human approval"} <= set(by_name)
        po_task = next(c for n, c in by_name.items() if n.startswith("PO ") and "delivery" in n)
        assert po_task["percentDone"] == 100 and po_task["state"] == "done"      # 100 + 50 of 150, both receipts
        receipts = [c for c in parent["children"] if c["milestone"]]
        assert len(receipts) == 2                                                  # partial, then the rest
        assert any(n.startswith("Invoice ") and c["state"] == "done" for n, c in by_name.items())
        pay = next(c for n, c in by_name.items() if n.startswith("PayPal payment"))
        assert "Simulated" in pay["name"] and pay["state"] == "done"
        ids = {c["id"] for c in parent["children"]}
        chain = [d for d in timeline["dependencies"] if d["from"] in ids]
        assert len(chain) == 4 and all(d["to"] in ids for d in chain)              # nego>approval>PO>invoice>payment


class TestApprovalBinding:
    async def test_changing_the_terms_invalidates_the_approval(self, client, analyst_headers, owner_headers, network):
        await _reset_item(network)
        created = await client.post("/procurement", headers=analyst_headers,
                                    json={"inventory_item_id": network["item_id"], "auto_negotiate": True,
                                          "note": "binding test"})
        if created.status_code == 409:  # an earlier test left one open
            pytest.skip("procurement already open for this item")
        request = created.json()["data"]
        async with network["factory"]() as s:
            await s.execute(update(NegotiationOffer).where(
                NegotiationOffer.id == request["recommended_offer_id"]).values(unit_price=Decimal("1.00")))
            await s.commit()
        response = await client.post(f"/procurement/{request['procurement_request_id']}/approve",
                                     headers=owner_headers, json={"approve": True})
        assert response.status_code == 409
        approval = (await client.get(f"/approvals/{request['approval']['approval_id']}",
                                     headers=owner_headers)).json()["data"]
        assert approval["status"] == "INVALIDATED"

    async def test_an_agent_tool_cannot_approve(self, engine, seeded, network):
        from app.tools import registry
        from app.tools.base import ToolContext

        async with network["factory"]() as s:
            ctx = ToolContext(session=s, merchant_id=seeded["merchant_id"],
                              permissions=frozenset({"procurement:read", "procurement:approve"}))
            result = await registry.execute("approve_purchase", ctx, {"reference": "PR-00001"})
        assert result.ok is False
        assert "cannot approve" in (result.error or "")


class TestIsolation:
    async def test_another_tenant_cannot_see_procurement(self, client, outsider_headers, analyst_headers, network):
        listing = (await client.get("/procurement", headers=analyst_headers)).json()["data"]["items"]
        if not listing:
            pytest.skip("no procurement yet")
        rid = listing[0]["procurement_request_id"]
        response = await client.get(f"/procurement/{rid}", headers=outsider_headers)
        assert response.status_code == 404

    async def test_supplier_floor_prices_never_leave_the_backend(self, client, owner_headers, network):
        suppliers = (await client.get("/suppliers", headers=owner_headers)).json()["data"]
        text = str(suppliers)
        assert "floor_price" not in text and "concession_rate" not in text and "opening_markup" not in text
