---
title: Supplier agent protocol
---

Supplier agents - PayPilot's own or yours - talk to the buyer through typed,
signed messages. External agents post them to:

```
POST /api/v1/agent-messages/inbound
```

## The envelope

`message_id, conversation_id, tenant_id, sender, recipient, message_type,
schema_version, sent_at, correlation_id, nonce, idempotency_key, payload,
transport{scheme, algorithm, key_id, signature}`

* **Signature:** HMAC-SHA256 over the envelope's canonical JSON (sorted keys, no
  spaces, integral floats written as integers, no ASCII escaping) under the key
  PayPilot derives for your agent identity.
* **Message types:** `RFQ_RESPONSE`, `QUOTE_SUBMITTED`, `COUNTEROFFER`,
  `OFFER_ACCEPTED`, `OFFER_REJECTED`, `INVOICE_ISSUED`, `DELIVERY_UPDATE` and the rest
  of the procurement vocabulary. A supplier cannot send buyer-only types (for example,
  a purchase order).

## What is checked, in order

1. **Tenant** - the message belongs to the merchant it is addressed to.
2. **Identity** - the sender is a registered agent with a matching key fingerprint.
3. **Signature** - HMAC verified in constant time.
4. **Freshness** - `sent_at` within 5 minutes.
5. **Schema** - the payload matches its type exactly; extra fields are rejected.
6. **Sender role** - the sender may send this type.
7. **Replay** - `nonce` and `idempotency_key` are unique. Re-sending an identical
   message is idempotent; a different message with a used key is refused.

Rejections are `401` (identity/signature), `403` (role), `409` (replay) or `422`
(schema).

## Offers are data, not decisions

Every quote and counteroffer is validated by the backend against the procurement's
policy - price ceiling, landed total, delivery window, quantity - and labelled
*inside policy* or with the exact rule it breaks. Agents never set limits, approve
or pay.
