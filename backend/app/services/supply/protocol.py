"""The agent-to-agent procurement protocol.

Agents never talk in free-form chat. Every message is a typed envelope::

    {message_id, conversation_id, tenant_id, sender, recipient, message_type,
     schema_version, sent_at, correlation_id, nonce, idempotency_key, payload}

signed with HMAC-SHA256 under a key derived *per agent* from the platform
protocol secret (reusing the same canonical-JSON rules as the n8n outbox, so a
signature survives a round trip through any JSON implementation).

``MessageBus.deliver`` is the single verification boundary. It runs for messages
produced in-process *and* for messages arriving over HTTP from an external agent,
and it rejects anything that fails any of:

1. tenant      - the envelope's tenant is the merchant this bus serves;
2. identity    - sender and recipient are registered, online agents of that tenant;
3. signature   - the HMAC verifies under the sender's key (constant-time compare);
4. freshness   - ``sent_at`` is within the allowed clock skew;
5. schema      - the message type is known and the payload validates strictly;
6. replay      - the nonce and the idempotency key have never been accepted
                 (enforced by unique indexes, so it holds under concurrency).

A duplicate delivery of the *same* message (same idempotency key, same payload)
is idempotent: the original row is returned. A different payload under a used
key is a replay attempt and is refused.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.db.models.governance import AgentKind, AgentMessage, AgentMessageType
from app.db.models.supply import SupplierAgent, SupplierAgentStatus
from app.services.inventory.events import canonical_json

log = get_logger(__name__)

SCHEMA_VERSION = "1.0"
SUPPORTED_SCHEMA_VERSIONS = frozenset({"1.0"})
MAX_CLOCK_SKEW = timedelta(minutes=5)
SYSTEM_AGENT_KEY = "system.paypilot"


class ProtocolError(AppError):
    status_code = 422
    code = "AGENT_PROTOCOL_VIOLATION"


class ReplayDetected(ProtocolError):
    status_code = 409
    code = "AGENT_MESSAGE_REPLAY"


class SignatureInvalid(ProtocolError):
    status_code = 401
    code = "AGENT_SIGNATURE_INVALID"


# --------------------------------------------------------------------------- #
# Identities and keys
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class AgentIdentity:
    key: str
    kind: str
    label: str = ""
    is_simulated: bool = True


def buyer_identity(merchant_id: uuid.UUID) -> AgentIdentity:
    return AgentIdentity(
        key=f"buyer.{str(merchant_id)[:8]}", kind=AgentKind.BUYER, label="Buyer Agent", is_simulated=False
    )


def system_identity() -> AgentIdentity:
    return AgentIdentity(key=SYSTEM_AGENT_KEY, kind=AgentKind.SYSTEM, label="PayPilot", is_simulated=False)


def supplier_identity(agent: SupplierAgent) -> AgentIdentity:
    return AgentIdentity(
        key=agent.agent_key, kind=AgentKind.SUPPLIER, label=agent.display_name, is_simulated=agent.is_simulated
    )


def agent_signing_key(merchant_id: uuid.UUID | str, agent_key: str) -> bytes:
    """Per-agent key. Compromising one agent's key does not let it speak as another."""
    return hmac.new(
        settings.agent_protocol_key, f"{merchant_id}:{agent_key}".encode(), hashlib.sha256
    ).digest()


def key_fingerprint(merchant_id: uuid.UUID | str, agent_key: str) -> str:
    return hashlib.sha256(agent_signing_key(merchant_id, agent_key)).hexdigest()[:32]


def key_id_for(merchant_id: uuid.UUID | str, agent_key: str) -> str:
    return f"{agent_key}#{key_fingerprint(merchant_id, agent_key)[:12]}"


def _signing_input(envelope: dict[str, Any]) -> bytes:
    fields = {k: envelope[k] for k in (
        "message_id", "conversation_id", "tenant_id", "sender", "recipient", "message_type",
        "schema_version", "sent_at", "correlation_id", "nonce", "idempotency_key", "payload",
    )}
    return canonical_json(fields)


def sign_envelope(envelope: dict[str, Any], *, merchant_id: uuid.UUID | str) -> str:
    key = agent_signing_key(merchant_id, envelope["sender"])
    return hmac.new(key, _signing_input(envelope), hashlib.sha256).hexdigest()


# --------------------------------------------------------------------------- #
# Typed payloads
# --------------------------------------------------------------------------- #
class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DiscoveryPayload(_Payload):
    rfq_reference: str
    sku: str
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    excluded: list[dict[str, Any]] = Field(default_factory=list)


class ProcurementRequestPayload(_Payload):
    procurement_reference: str
    sku: str
    product_name: str
    quantity: str
    trigger: str
    required_by: date | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)


class RFQPayload(_Payload):
    """What a supplier sees. Deliberately excludes the merchant's budget and ceiling."""

    rfq_reference: str
    sku: str
    product_name: str
    quantity: str
    unit: str
    currency: str
    required_by: date | None = None
    delivery_region: str = ""
    response_deadline: datetime | None = None


class QuotePayload(_Payload):
    rfq_reference: str
    round: int
    kind: str
    unit_price: str
    quantity: str
    shipping: str
    tax: str
    landed_total: str
    lead_time_days: int
    payment_terms: str
    valid_until: datetime | None = None
    note: str = ""


class CounterPayload(_Payload):
    rfq_reference: str
    round: int
    unit_price: str
    quantity: str
    request_free_shipping: bool = False
    request_expedite: bool = False
    competitive_pressure: bool = False
    note: str = ""


class DecisionPayload(_Payload):
    rfq_reference: str
    offer_id: str | None = None
    reason: str = ""
    conditional_on_approval: bool = False


class DeclinePayload(_Payload):
    rfq_reference: str
    reason: str


class PurchaseOrderPayload(_Payload):
    purchase_order_reference: str
    rfq_reference: str
    unit_price: str
    quantity: str
    total: str
    currency: str
    expected_delivery: date | None = None
    approval_reference: str


class InvoicePayload(_Payload):
    invoice_number: str
    purchase_order_reference: str
    currency: str
    subtotal: str
    shipping: str
    tax: str
    total: str
    due_date: date | None = None
    lines: list[dict[str, Any]] = Field(default_factory=list)


class DeliveryPayload(_Payload):
    purchase_order_reference: str
    status: str
    expected_delivery: date | None = None
    tracking_reference: str = ""
    note: str = ""


class ReceiptPayload(_Payload):
    purchase_order_reference: str
    receipt_reference: str
    quantity_received: str
    outstanding: str
    on_time: bool | None = None


class MatchPayload(_Payload):
    invoice_number: str
    status: str
    variance: str
    discrepancies: list[dict[str, Any]] = Field(default_factory=list)


class PaymentPayload(_Payload):
    invoice_number: str
    amount: str
    currency: str
    method: str = ""
    mode: str = ""
    approval_reference: str = ""
    paypal_reference: str = ""
    reason: str = ""


class ClosedPayload(_Payload):
    procurement_reference: str
    outcome: str
    final_total: str = ""
    savings: str = ""


PAYLOAD_SCHEMAS: dict[str, type[_Payload]] = {
    AgentMessageType.SUPPLIER_DISCOVERY: DiscoveryPayload,
    AgentMessageType.PROCUREMENT_REQUEST: ProcurementRequestPayload,
    AgentMessageType.RFQ_CREATED: RFQPayload,
    AgentMessageType.RFQ_RESPONSE: DeclinePayload,
    AgentMessageType.QUOTE_SUBMITTED: QuotePayload,
    AgentMessageType.COUNTEROFFER: CounterPayload,
    AgentMessageType.OFFER_ACCEPTED: DecisionPayload,
    AgentMessageType.OFFER_REJECTED: DecisionPayload,
    AgentMessageType.NEGOTIATION_EXPIRED: DecisionPayload,
    AgentMessageType.PURCHASE_ORDER_CREATED: PurchaseOrderPayload,
    AgentMessageType.INVOICE_ISSUED: InvoicePayload,
    AgentMessageType.DELIVERY_UPDATE: DeliveryPayload,
    AgentMessageType.GOODS_RECEIVED: ReceiptPayload,
    AgentMessageType.INVOICE_MATCHED: MatchPayload,
    AgentMessageType.PAYMENT_REQUESTED: PaymentPayload,
    AgentMessageType.PAYMENT_APPROVED: PaymentPayload,
    AgentMessageType.PAYMENT_COMPLETED: PaymentPayload,
    AgentMessageType.PAYMENT_FAILED: PaymentPayload,
    AgentMessageType.PROCUREMENT_CLOSED: ClosedPayload,
}

#: Who may send what. A supplier cannot, for example, issue a purchase order.
ALLOWED_SENDERS: dict[str, frozenset[str]] = {
    AgentMessageType.SUPPLIER_DISCOVERY: frozenset({AgentKind.BUYER}),
    AgentMessageType.PROCUREMENT_REQUEST: frozenset({AgentKind.SYSTEM}),
    AgentMessageType.RFQ_CREATED: frozenset({AgentKind.BUYER}),
    AgentMessageType.RFQ_RESPONSE: frozenset({AgentKind.SUPPLIER}),
    AgentMessageType.QUOTE_SUBMITTED: frozenset({AgentKind.SUPPLIER}),
    AgentMessageType.COUNTEROFFER: frozenset({AgentKind.BUYER, AgentKind.SUPPLIER}),
    AgentMessageType.OFFER_ACCEPTED: frozenset({AgentKind.BUYER, AgentKind.SUPPLIER}),
    AgentMessageType.OFFER_REJECTED: frozenset({AgentKind.BUYER, AgentKind.SUPPLIER}),
    AgentMessageType.NEGOTIATION_EXPIRED: frozenset({AgentKind.BUYER, AgentKind.SYSTEM}),
    AgentMessageType.PURCHASE_ORDER_CREATED: frozenset({AgentKind.BUYER}),
    AgentMessageType.INVOICE_ISSUED: frozenset({AgentKind.SUPPLIER}),
    AgentMessageType.DELIVERY_UPDATE: frozenset({AgentKind.SUPPLIER}),
    AgentMessageType.GOODS_RECEIVED: frozenset({AgentKind.BUYER, AgentKind.SYSTEM}),
    AgentMessageType.INVOICE_MATCHED: frozenset({AgentKind.SYSTEM}),
    AgentMessageType.PAYMENT_REQUESTED: frozenset({AgentKind.BUYER}),
    AgentMessageType.PAYMENT_APPROVED: frozenset({AgentKind.SYSTEM}),
    AgentMessageType.PAYMENT_COMPLETED: frozenset({AgentKind.SYSTEM}),
    AgentMessageType.PAYMENT_FAILED: frozenset({AgentKind.SYSTEM}),
    AgentMessageType.PROCUREMENT_CLOSED: frozenset({AgentKind.SYSTEM, AgentKind.BUYER}),
}


# --------------------------------------------------------------------------- #
# Bus
# --------------------------------------------------------------------------- #
def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class MessageBus:
    """Builds, signs, verifies and records protocol messages for one merchant."""

    def __init__(self, session: AsyncSession, merchant_id: uuid.UUID) -> None:
        self.session = session
        self.merchant_id = merchant_id

    # ------------------------------------------------------------------ registry
    async def resolve(self, agent_key: str) -> AgentIdentity | None:
        if agent_key == SYSTEM_AGENT_KEY:
            return system_identity()
        buyer = buyer_identity(self.merchant_id)
        if agent_key == buyer.key:
            return buyer
        agent = (
            await self.session.execute(
                select(SupplierAgent).where(
                    SupplierAgent.merchant_id == self.merchant_id,
                    SupplierAgent.agent_key == agent_key,
                )
            )
        ).scalars().first()
        if agent is None or agent.status == SupplierAgentStatus.SUSPENDED:
            return None
        # The registered fingerprint must match the key this deployment derives -
        # a supplier row copied from another tenant or environment is refused.
        if agent.key_fingerprint and agent.key_fingerprint != key_fingerprint(self.merchant_id, agent_key):
            return None
        return supplier_identity(agent)

    # ------------------------------------------------------------------ build
    def build(
        self,
        *,
        sender: AgentIdentity,
        recipient: AgentIdentity,
        message_type: str,
        payload: dict[str, Any],
        conversation_id: str,
        correlation_id: str,
        idempotency_key: str,
        sent_at: datetime | None = None,
    ) -> dict[str, Any]:
        envelope: dict[str, Any] = {
            "message_id": str(uuid.uuid4()),
            "conversation_id": conversation_id,
            "tenant_id": str(self.merchant_id),
            "sender": sender.key,
            "recipient": recipient.key,
            "message_type": message_type,
            "schema_version": SCHEMA_VERSION,
            "sent_at": _iso(sent_at or datetime.now(tz=UTC)),
            "correlation_id": correlation_id,
            "nonce": secrets.token_hex(16),
            "idempotency_key": idempotency_key,
            "payload": _jsonable(payload),
        }
        envelope["transport"] = {
            "scheme": "internal-hmac",
            "algorithm": "HMAC-SHA256",
            "key_id": key_id_for(self.merchant_id, sender.key),
            "signature": sign_envelope(envelope, merchant_id=self.merchant_id),
        }
        return envelope

    async def send(
        self,
        *,
        sender: AgentIdentity,
        recipient: AgentIdentity,
        message_type: str,
        payload: dict[str, Any],
        conversation_id: str,
        correlation_id: str,
        idempotency_key: str,
        procurement_request_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
        summary: str = "",
    ) -> AgentMessage:
        envelope = self.build(
            sender=sender,
            recipient=recipient,
            message_type=message_type,
            payload=payload,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        return await self.deliver(
            envelope,
            procurement_request_id=procurement_request_id,
            session_id=session_id,
            summary=summary,
        )

    # ------------------------------------------------------------------ verify + record
    async def deliver(
        self,
        envelope: dict[str, Any],
        *,
        procurement_request_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
        summary: str = "",
        now: datetime | None = None,
    ) -> AgentMessage:
        required = (
            "message_id", "conversation_id", "tenant_id", "sender", "recipient", "message_type",
            "schema_version", "sent_at", "correlation_id", "nonce", "idempotency_key", "payload",
            "transport",
        )
        missing = [key for key in required if key not in envelope]
        if missing:
            raise ProtocolError(f"Envelope is missing {', '.join(missing)}.")

        # 1. tenant
        if str(envelope["tenant_id"]) != str(self.merchant_id):
            raise ProtocolError("Message addressed to a different tenant.", status_code=403)

        # 2. identity
        sender = await self.resolve(str(envelope["sender"]))
        recipient = await self.resolve(str(envelope["recipient"]))
        if sender is None:
            raise SignatureInvalid("Unknown or unregistered sender identity.")
        if recipient is None:
            raise ProtocolError("Unknown recipient identity.")

        # 3. signature
        transport = envelope.get("transport") or {}
        signature = str(transport.get("signature", ""))
        expected = sign_envelope(envelope, merchant_id=self.merchant_id)
        if not signature or not hmac.compare_digest(signature, expected):
            log.warning("agent_message_bad_signature", sender=envelope.get("sender"))
            raise SignatureInvalid("Signature does not verify for the claimed sender.")
        if transport.get("key_id") != key_id_for(self.merchant_id, sender.key):
            raise SignatureInvalid("Key id does not belong to the sender.")

        # 4. freshness
        try:
            sent_at = _parse_time(str(envelope["sent_at"]))
        except ValueError:
            raise ProtocolError("Malformed sent_at.") from None
        current = now or datetime.now(tz=UTC)
        if abs(current - sent_at) > MAX_CLOCK_SKEW:
            raise ReplayDetected("Message timestamp is outside the allowed window.")

        # 5. schema
        message_type = str(envelope["message_type"])
        if envelope["schema_version"] not in SUPPORTED_SCHEMA_VERSIONS:
            raise ProtocolError(f"Unsupported schema version {envelope['schema_version']}.")
        schema = PAYLOAD_SCHEMAS.get(message_type)
        if schema is None:
            raise ProtocolError(f"Unknown message type {message_type}.")
        if sender.kind not in ALLOWED_SENDERS.get(message_type, frozenset()):
            raise ProtocolError(f"A {sender.kind.lower()} agent may not send {message_type}.", status_code=403)
        try:
            schema.model_validate(envelope["payload"])
        except ValidationError as exc:
            first = exc.errors()[0]
            raise ProtocolError(
                f"Payload does not match the {message_type} schema: "
                f"{'.'.join(str(p) for p in first['loc'])} {first['msg']}"
            ) from None

        # 6. replay / idempotency
        existing = (
            await self.session.execute(
                select(AgentMessage).where(
                    AgentMessage.merchant_id == self.merchant_id,
                    AgentMessage.idempotency_key == str(envelope["idempotency_key"]),
                )
            )
        ).scalars().first()
        if existing is not None:
            if canonical_json(existing.payload) == canonical_json(envelope["payload"]) and \
                    existing.message_type == message_type and existing.sender == sender.key:
                return existing
            raise ReplayDetected("Idempotency key already used for a different message.")

        message = AgentMessage(
            id=uuid.UUID(str(envelope["message_id"])),
            merchant_id=self.merchant_id,
            conversation_id=str(envelope["conversation_id"]),
            correlation_id=str(envelope["correlation_id"]),
            sender=sender.key,
            sender_kind=sender.kind,
            recipient=recipient.key,
            recipient_kind=recipient.kind,
            message_type=message_type,
            schema_version=str(envelope["schema_version"]),
            payload=envelope["payload"],
            transport=str(transport.get("scheme", "internal-hmac"))[:24],
            key_id=str(transport.get("key_id", ""))[:64],
            signature=signature,
            nonce=str(envelope["nonce"])[:48],
            idempotency_key=str(envelope["idempotency_key"])[:128],
            sent_at=sent_at,
            verified=True,
            procurement_request_id=procurement_request_id,
            session_id=session_id,
            summary=summary[:2000],
            is_simulated=sender.is_simulated or recipient.is_simulated,
        )
        nonce_used = (
            await self.session.execute(
                select(AgentMessage.id).where(
                    AgentMessage.sender == sender.key, AgentMessage.nonce == message.nonce
                )
            )
        ).first()
        if nonce_used is not None:
            raise ReplayDetected("Nonce has already been used by this sender.")
        self.session.add(message)
        try:
            await self.session.flush()
        except IntegrityError:
            # Lost a race with a concurrent delivery of the same nonce/key. The
            # unique index is the real guarantee; the request is rolled back.
            raise ReplayDetected("Nonce or idempotency key has already been accepted.") from None
        return message


def _jsonable(payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.supply.policy import serialisable

    return serialisable(payload)


def describe_message(message: AgentMessage) -> dict[str, Any]:
    return {
        "message_id": str(message.id),
        "conversation_id": message.conversation_id,
        "correlation_id": message.correlation_id,
        "sender": message.sender,
        "sender_kind": message.sender_kind,
        "recipient": message.recipient,
        "recipient_kind": message.recipient_kind,
        "message_type": message.message_type,
        "schema_version": message.schema_version,
        "payload": message.payload,
        "summary": message.summary,
        "sent_at": message.sent_at.isoformat() if message.sent_at else None,
        "verified": message.verified,
        "key_id": message.key_id,
        "signature_preview": f"{message.signature[:16]}…",
        "transport": message.transport,
        "is_simulated": message.is_simulated,
        "procurement_request_id": str(message.procurement_request_id) if message.procurement_request_id else None,
        "session_id": str(message.session_id) if message.session_id else None,
    }
