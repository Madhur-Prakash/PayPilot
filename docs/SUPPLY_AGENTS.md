# Supply Agents

[Back to docs](README.md)

An agent-to-agent procurement network inside PayPilot. A **Buyer Agent**
represents the merchant; independent **Supplier Agents** represent vendors, each
with its own private commercial policy. They negotiate through a typed, signed
protocol; a deterministic engine sets the limits and checks every offer; a person
approves the purchase and the payment; PayPal settles it; reconciliation feeds
the new cost back into growth analytics.

```
DETECT DEMAND -> STOCK NEED -> DISCOVER SUPPLIERS -> RFQ -> QUOTES -> NEGOTIATE
   -> VALIDATE -> EVALUATE -> RECOMMEND -> [HUMAN APPROVES] -> PURCHASE ORDER
   -> SUPPLIER INVOICE -> DELIVERY -> RECEIVE (partial ok) -> THREE-WAY MATCH
   -> [HUMAN APPROVES PAYMENT] -> PAYPAL ORDERS v2 -> RECONCILE
   -> INVENTORY REVALUED + PRODUCT MARGIN -> SUPPLIER LEARNING -> MEMORY
```

## Who decides what

| Decision | Made by | Code |
| --- | --- | --- |
| That and how much to buy | Inventory Intelligence (deterministic) | [`services/supply/demand.py`](../backend/app/services/supply/demand.py) |
| The merchant's limits | Financial engine (deterministic, `Decimal`) | [`services/supply/policy.py`](../backend/app/services/supply/policy.py) |
| A supplier's prices | That supplier agent's private policy | [`services/supply/supplier_agent.py`](../backend/app/services/supply/supplier_agent.py) |
| The buyer's counters | Buyer strategy (deterministic); an LLM may *propose*, the backend accepts only in-bounds proposals | [`services/supply/buyer_agent.py`](../backend/app/services/supply/buyer_agent.py) |
| Which offer wins | Deterministic scoring | [`services/supply/evaluation.py`](../backend/app/services/supply/evaluation.py) |
| Whether to buy / pay | A person with `procurement:approve` / `payment:approve` | [`services/supply/approvals.py`](../backend/app/services/supply/approvals.py) |

## Inventory Intelligence

For each tracked item, from persisted sales and stock:

* velocity = units/day over the last 14 days; demand change vs the 14 before;
* days of cover = available / velocity; stockout risk = cover <= lead time + 3;
* suggested quantity = velocity x (lead + 10-day review + 3 safety) - available -
  on order, rounded up to the pack size;
* required within = whole days of cover remaining.

Demo: Premium Coffee Beans sell **12/day** (was 7), **42** on hand, 3-day lead
time -> **3.5 days** of cover, suggest **150** bags, needed **within 3 days**.

## The deterministic financial engine

```
max landed unit cost = selling price x (1 - target margin)     $18.00 x 0.60 = $10.80
max budget           = max landed unit cost x quantity          $10.80 x 150  = $1,620.00
target unit cost     = max landed unit cost x (1 - 12%)         $9.50
landed cost          = unit price x qty + shipping + tax
```

Every offer - from a supplier, from the buyer, or proposed by an LLM - goes
through `validate_offer`:

* **INVALID** - non-positive values, a claimed total that does not equal the
  recomputed landed total, or more than the supplier holds;
* **OUT_OF_POLICY** - over the unit ceiling or budget, too slow, supplier below
  minimum reliability, partial quantity;
* **VALID** - inside policy; only these can win.

The policy is frozen onto the request with a content-hash version
(`pol-…`), and every approval records the version it was granted under.

## Supplier agents (demo network)

| Agent | Strategy | Behaviour |
| --- | --- | --- |
| Summit Roastworks (`supplier.summit`) | Premium & reliable | Opens list + 3%, concedes 25% of the gap per round, free shipping over $1,500, expedites at no charge |
| Pacific Bean Exchange (`supplier.pacific`) | Low price, limited stock | Lowest list price, only 90 bags, 9-day delivery, concedes 10%, never waives shipping, cannot expedite |
| Cascadia Coffee Collective (`supplier.cascadia`) | Flexible negotiator | 4% volume break at 150, concedes 40% (more under competitive pressure), waives shipping to close, closes on the final round |

Isolation is structural: a supplier engine is built from **its own two rows**
(agent + supply link) and receives only the public RFQ and the buyer's counters -
the types it is constructed from do not contain the merchant's budget, ceiling or
another supplier's terms. The buyer never quotes one supplier's price to another
(`competitive_pressure` is a boolean). `floor_price`, `opening_markup` and
`concession_rate` are never serialised by the API (asserted by a test).

## The agent protocol

[`services/supply/protocol.py`](../backend/app/services/supply/protocol.py)

Envelope: `message_id, conversation_id, tenant_id, sender, recipient,
message_type, schema_version, sent_at, correlation_id, nonce, idempotency_key,
payload, transport{scheme, algorithm, key_id, signature}`.

* **Signed per agent** - HMAC-SHA256 under a key derived from the protocol secret
  and the agent identity, over canonical JSON (the same rules as the n8n outbox).
  Supplier agents register a public key fingerprint; a row copied from another
  tenant or environment fails resolution.
* **One verification boundary** - `MessageBus.deliver` runs for in-process agents
  *and* for external agents posting to `POST /api/v1/agent-messages/inbound`:
  tenant -> identity -> signature -> freshness (5 min) -> schema (strict, extra
  fields forbidden) -> sender role (a supplier cannot issue a purchase order) ->
  replay (nonce and idempotency key, unique indexes).
* **Typed vocabulary** - `SUPPLIER_DISCOVERY, PROCUREMENT_REQUEST, RFQ_CREATED,
  RFQ_RESPONSE, QUOTE_SUBMITTED, COUNTEROFFER, OFFER_ACCEPTED, OFFER_REJECTED,
  NEGOTIATION_EXPIRED, PURCHASE_ORDER_CREATED, INVOICE_ISSUED, DELIVERY_UPDATE,
  GOODS_RECEIVED, INVOICE_MATCHED, PAYMENT_REQUESTED, PAYMENT_APPROVED,
  PAYMENT_COMPLETED, PAYMENT_FAILED, PROCUREMENT_CLOSED`.

## Negotiation

[`services/supply/negotiation.py`](../backend/app/services/supply/negotiation.py) - a
resumable state machine (`advance`), so the Negotiation Workspace can watch it
stage by stage; `run_to_recommendation` loops it; the LangGraph workflow
([`agents/procurement_graph.py`](../backend/app/agents/procurement_graph.py)) runs it
as `inventory_monitoring -> procurement_requirement -> sourcing -> negotiation* ->
approval_gate -> END`. Each stage is recorded as an agent step and every message
idempotency key is derived from the stage, so a re-run re-uses what exists.

Demo result (deterministic, no LLM): Cascadia **$1,455.00** landed (score 0.973),
Summit $1,570.71 (0.961), Pacific excluded (9 days, 90 bags) - **$248.77 saved**
against the best opening quote.

## Approvals

`approval_requests` stores the canonical terms and their SHA-256. Deciding and
executing both rebuild the terms from live rows; any difference invalidates the
approval - durably, on its own transaction, so a later retry cannot slip through.
Only people decide (agent tools `approve_purchase` / `pay_supplier_invoice`
always refuse); Owners are not exempt; pending approvals expire after 72 hours.

## Receiving, matching, payment, reconciliation

[`services/supply/lifecycle.py`](../backend/app/services/supply/lifecycle.py)

* **Receiving** wraps the existing inventory receive (stock movement, batch,
  ledger) and records a goods receipt (partial allowed, on-time flag), then
  re-runs matching.
* **Three-way match** - per line: billed vs received vs ordered, price variance vs
  `PROCUREMENT_PRICE_TOLERANCE_PCT`; shipping; total vs payable on goods received
  (± `PROCUREMENT_TOTAL_TOLERANCE_AMOUNT`). Billing ahead of delivery is flagged
  `BILLED_NOT_RECEIVED` and holds payment.
* **Payment** - a fully received, payable invoice raises a `SUPPLIER_PAYMENT`
  approval; once approved, execution creates a PayPal Orders v2 order with the
  supplier as payee (simulated: captured immediately; sandbox: payer approves in
  PayPal, then capture). One live execution per invoice - paying twice returns the
  same execution.
* **Reconciliation** - PO fully received, match payable, capture settled, paid ==
  invoiced -> inventory revalued at weighted-average landed cost, product
  `cost_price` updated, `PRODUCT_MARGIN_CHANGED` emitted, supplier performance
  recomputed (`0.5 on-time + 0.3 fill rate + 0.2 invoice accuracy`), memory written.

## Unified intelligence

Business events (`business.*`, written to the transactional outbox with
correlation ids): `REVENUE_ANOMALY_DETECTED, PRODUCT_DEMAND_INCREASED,
STOCKOUT_RISK_DETECTED, PROCUREMENT_REQUIRED, RFQ_STARTED, SUPPLIER_SELECTED,
PURCHASE_APPROVED, INVOICE_RECEIVED, GOODS_RECEIVED, PAYMENT_RECONCILED,
PRODUCT_MARGIN_CHANGED, CAMPAIGN_PERFORMANCE_UPDATED, EXPERIMENT_COMPLETED`.

* Demand up + stockout risk -> a growth opportunity *"Capture rising demand"*
  (value = extra units/day x 30 x price) whose action is "restock through the
  Supply Agents and hold promotions".
* Stockout risk -> other growth opportunities that would promote that product are
  down-weighted and annotated *"hold until restocked"*.
* Cheaper landed cost -> product margin rises in growth analytics.
* Reliability from reconciled orders -> future supplier scoring.

## Permissions

| Permission | Owner | Admin | Analyst | Staff | Viewer |
| --- | :-: | :-: | :-: | :-: | :-: |
| `procurement:read`, `supplier_invoice:read`, `approval:read`, `paypal:read`, `events:read` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `procurement:create`, `procurement:negotiate`, `paypal:sync` | ✓ | ✓ | ✓ | | |
| `procurement:approve`, `payment:approve`, `payment:execute`, `supplier_invoice:match`, `paypal:manage` | ✓ | ✓ | | | |
| `purchase_order:receive` | ✓ | ✓ | | ✓ | |

## API

| Method | Path |
| --- | --- |
| GET | `/suppliers`, `/suppliers/{id}` |
| GET | `/supply/demand`, `/supply/overview` |
| GET/POST | `/procurement` (POST with `auto_negotiate`) |
| POST | `/procurement/autopilot` (LangGraph workflow to the approval gate) |
| GET | `/procurement/{id}`, `/procurement/{id}/messages` |
| POST | `/procurement/{id}/advance`, `/procurement/{id}/negotiate`, `/procurement/{id}/approve` |
| POST | `/purchase-orders/{id}/goods-receipts`, `/purchase-orders/{id}/reconcile` |
| GET | `/goods-receipts`, `/supplier-invoices`, `/reconciliations`, `/purchase-orders/{id}/lifecycle` |
| POST | `/supplier-invoices/{id}/match`, `/approve-payment`, `/pay`; `/payments/{id}/capture` |
| GET/POST | `/approvals`, `/approvals/{id}`, `/approvals/{id}/decide`, `/approvals/{id}/execute` |
| GET/POST | `/agent-messages`, `/agent-messages/inbound` |
| GET | `/command-center`, `/events`, `/intelligence/signals` |
