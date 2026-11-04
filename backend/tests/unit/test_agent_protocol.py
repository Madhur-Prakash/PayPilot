"""The agent-to-agent protocol's verification boundary.

Every check ``MessageBus.deliver`` makes is exercised against a real database:
signature, tenant, identity, freshness, schema, sender role and replay.
"""

from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.models.governance import AgentMessageType
from app.db.models.procurement import Vendor
from app.db.models.supply import SupplierAgent
from app.services.supply.protocol import (
    MessageBus,
    ProtocolError,
    ReplayDetected,
    SignatureInvalid,
    buyer_identity,
    key_fingerprint,
    supplier_identity,
)

RFQ = {
    "rfq_reference": "RFQ-T1",
    "sku": "JO-BEAN-012",
    "product_name": "Beans",
    "quantity": "150",
    "unit": "bags",
    "currency": "USD",
}


@pytest.fixture
async def supplier(session, seeded):
    merchant_id = seeded["merchant_id"]
    agent = (await session.execute(
        select(SupplierAgent).where(SupplierAgent.merchant_id == merchant_id, SupplierAgent.agent_key == "supplier.protocol")
    )).scalars().first()
    if agent is None:
        vendor = Vendor(merchant_id=merchant_id, name="Protocol Test Supplier")
        session.add(vendor)
        await session.flush()
        agent = SupplierAgent(merchant_id=merchant_id, vendor_id=vendor.id, agent_key="supplier.protocol",
                              display_name="Protocol Test Supplier",
                              key_fingerprint=key_fingerprint(merchant_id, "supplier.protocol"))
        session.add(agent)
        await session.flush()
    return agent


def build(bus: MessageBus, sender, recipient, message_type=AgentMessageType.RFQ_CREATED, payload=None, key=None, **kw):
    return bus.build(
        sender=sender, recipient=recipient, message_type=message_type, payload=payload or dict(RFQ),
        conversation_id="conv-test", correlation_id="PROC-TEST", idempotency_key=key or uuid.uuid4().hex, **kw,
    )


class TestVerification:
    async def test_a_signed_message_is_verified_and_recorded(self, session, seeded, supplier):
        bus = MessageBus(session, seeded["merchant_id"])
        envelope = build(bus, buyer_identity(seeded["merchant_id"]), supplier_identity(supplier))
        message = await bus.deliver(envelope)
        assert message.verified is True
        assert message.message_type == AgentMessageType.RFQ_CREATED
        assert message.signature == envelope["transport"]["signature"]

    async def test_a_tampered_payload_fails_the_signature(self, session, seeded, supplier):
        bus = MessageBus(session, seeded["merchant_id"])
        envelope = build(bus, buyer_identity(seeded["merchant_id"]), supplier_identity(supplier))
        envelope["payload"]["quantity"] = "15000"
        with pytest.raises(SignatureInvalid):
            await bus.deliver(envelope)

    async def test_a_message_for_another_tenant_is_refused(self, session, seeded, supplier):
        bus = MessageBus(session, seeded["merchant_id"])
        envelope = build(bus, buyer_identity(seeded["merchant_id"]), supplier_identity(supplier))
        other = MessageBus(session, seeded["other_merchant_id"])
        with pytest.raises(ProtocolError):
            await other.deliver(envelope)

    async def test_an_unregistered_sender_is_refused(self, session, seeded, supplier):
        bus = MessageBus(session, seeded["merchant_id"])
        envelope = build(bus, buyer_identity(seeded["merchant_id"]), supplier_identity(supplier))
        envelope["sender"] = "supplier.impostor"
        with pytest.raises(SignatureInvalid):
            await bus.deliver(envelope)

    async def test_a_stale_message_is_refused(self, session, seeded, supplier):
        bus = MessageBus(session, seeded["merchant_id"])
        envelope = build(bus, buyer_identity(seeded["merchant_id"]), supplier_identity(supplier),
                         sent_at=datetime.now(tz=UTC) - timedelta(hours=1))
        with pytest.raises(ReplayDetected):
            await bus.deliver(envelope)

    async def test_a_payload_that_breaks_the_schema_is_refused(self, session, seeded, supplier):
        bus = MessageBus(session, seeded["merchant_id"])
        payload = {**RFQ, "max_budget": "1620.00"}  # extra fields are forbidden
        envelope = build(bus, buyer_identity(seeded["merchant_id"]), supplier_identity(supplier), payload=payload)
        with pytest.raises(ProtocolError):
            await bus.deliver(envelope)

    async def test_a_supplier_cannot_issue_a_purchase_order(self, session, seeded, supplier):
        bus = MessageBus(session, seeded["merchant_id"])
        payload = {"purchase_order_reference": "PO-1", "rfq_reference": "RFQ-T1", "unit_price": "1",
                   "quantity": "150", "total": "150", "currency": "USD", "approval_reference": "APR-1"}
        envelope = build(bus, supplier_identity(supplier), buyer_identity(seeded["merchant_id"]),
                         message_type=AgentMessageType.PURCHASE_ORDER_CREATED, payload=payload)
        with pytest.raises(ProtocolError):
            await bus.deliver(envelope)


class TestReplay:
    async def test_redelivering_the_same_message_is_idempotent(self, session, seeded, supplier):
        bus = MessageBus(session, seeded["merchant_id"])
        envelope = build(bus, buyer_identity(seeded["merchant_id"]), supplier_identity(supplier))
        first = await bus.deliver(envelope)
        again = await bus.deliver(copy.deepcopy(envelope))
        assert again.id == first.id

    async def test_reusing_an_idempotency_key_for_a_different_message_is_a_replay(self, session, seeded, supplier):
        bus = MessageBus(session, seeded["merchant_id"])
        key = uuid.uuid4().hex
        await bus.deliver(build(bus, buyer_identity(seeded["merchant_id"]), supplier_identity(supplier), key=key))
        forged = build(bus, buyer_identity(seeded["merchant_id"]), supplier_identity(supplier), key=key,
                       payload={**RFQ, "quantity": "999"})
        with pytest.raises(ReplayDetected):
            await bus.deliver(forged)

    async def test_reusing_a_nonce_is_a_replay(self, session, seeded, supplier):
        bus = MessageBus(session, seeded["merchant_id"])
        first = build(bus, buyer_identity(seeded["merchant_id"]), supplier_identity(supplier))
        await bus.deliver(first)
        second = build(bus, buyer_identity(seeded["merchant_id"]), supplier_identity(supplier))
        second["nonce"] = first["nonce"]
        from app.services.supply.protocol import sign_envelope

        second["transport"]["signature"] = sign_envelope(second, merchant_id=seeded["merchant_id"])
        with pytest.raises(ReplayDetected):
            await bus.deliver(second)
