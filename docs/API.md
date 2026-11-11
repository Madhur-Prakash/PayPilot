<div align="center">

# API reference

Every PayPilot endpoint with the permission it requires, the response envelope, error codes and the role matrix.

[![Docs index](https://img.shields.io/badge/-Docs_index-0b2a6f?style=flat-square)](README.md)
[![Security](https://img.shields.io/badge/-Security-dc2626?style=flat-square)](SECURITY.md)
[![API portal](https://img.shields.io/badge/-API_portal_and_SDKs-0f766e?style=flat-square)](APIMATIC.md)
[![OpenAPI](https://img.shields.io/badge/OpenAPI-3.0.3-6BA539?style=flat-square&logo=openapiinitiative&logoColor=white)](openapi.json)
[![Swagger](https://img.shields.io/badge/Swagger-hosted-85EA2D?style=flat-square&logo=swagger&logoColor=black)](https://paypilot-api-bjn2.onrender.com/docs)

</div>

---

## Contents

- [Basics](#basics)
- [Conventions](#conventions)
- [Error codes](#error-codes)
- [Authentication flow](#authentication-flow)
- [Endpoints](#endpoints)
- [Permission matrix](#permission-matrix)

---

## Basics

| | |
| --- | --- |
| Base URL | `http://localhost:8000/api/v1` locally; `https://paypilot-api-bjn2.onrender.com/api/v1` hosted |
| Interactive docs | `/docs` (Swagger UI), `/redoc`, `/openapi.json` |
| Exported spec | [`docs/openapi.json`](openapi.json), regenerated with `python scripts/export_openapi.py` |
| Size | 200 documented operations in 18 tag groups, plus hidden webhook callbacks and a WebSocket |
| SDKs | Python and TypeScript, generated with APIMatic; see [API portal and SDKs](APIMATIC.md) |
| Postman | [`postman/PayPilot.postman_collection.json`](../postman/PayPilot.postman_collection.json), 59 requests |

Paths in the tables below omit the `/api/v1` prefix.

---

## Conventions

**Success envelope.** Every successful response:

```json
{ "success": true, "data": { }, "meta": { } }
```

**Pagination.** List endpoints that page return `data.items` and `data.pagination`:

```json
{ "items": [ ], "pagination": { "page": 1, "page_size": 25, "total": 112, "total_pages": 5, "has_next": true, "has_previous": false } }
```

**Error envelope.** Every failure, never with a stack trace in production:

```json
{
  "success": false,
  "error": { "code": "PERMISSION_DENIED", "message": "...", "details": { } },
  "request_id": "8f2c..."
}
```

**Request ids.** Send `X-Request-ID` to correlate; the API generates one otherwise and returns it on every
response. The same id appears in every log line for the request.

**Authentication.** `Authorization: Bearer <access_token>`. The refresh token lives in an `HttpOnly` cookie scoped to
`/api/v1/auth`; send credentials with refresh requests.

**Merchant scope.** The merchant is resolved from your membership. `?merchant_id=` and the `X-Merchant-ID` header
are honoured **only** for merchants you belong to; anything else is `403 MERCHANT_SCOPE_VIOLATION` and audited.

**Rate limits.** `RATE_LIMIT_REQUESTS` per caller per `RATE_LIMIT_WINDOW_SECONDS` (300 per 60 seconds by default).
Responses carry `X-RateLimit-Limit` and `X-RateLimit-Remaining`; `429` carries `Retry-After`.

**Money.** Amounts are decimal strings or numbers with two decimal places in the merchant's currency. Every PayPal
record carries `mode`: `SANDBOX`, `LIVE` or `SIMULATED`.

---

## Error codes

| Code | HTTP | Meaning |
| --- | --- | --- |
| `BAD_REQUEST` | 400 | Malformed request or unsafe input (for example a non-https Kernel URL) |
| `AUTHENTICATION_FAILED` | 401 | Missing or invalid credentials, or an invalid webhook signature |
| `INVALID_CREDENTIALS` | 401 | Wrong email or password (same response for an unknown email) |
| `TOKEN_EXPIRED`, `INVALID_TOKEN` | 401 | Refresh the session or sign in again |
| `ACCOUNT_INACTIVE`, `ACCOUNT_LOCKED` | 403 | Deactivated account, or locked for 15 minutes after 8 failed sign-ins |
| `PERMISSION_DENIED` | 403 | The role lacks the permission. Audited |
| `MERCHANT_SCOPE_VIOLATION` | 403 | A merchant you are not a member of. Audited |
| `NOT_FOUND` | 404 | Absent, or belongs to another tenant |
| `CONFLICT` | 409 | Already exists or invalid state transition |
| `APPROVAL_REQUIRED` | 409 | A money-moving action with no valid approval on record, for every role |
| `VALIDATION_ERROR` | 422 | Field errors in `details` |
| `RATE_LIMITED` | 429 | `Retry-After` header set |
| `INTERNAL_ERROR` | 500 | Unexpected failure; correlate with `request_id` |
| `INTEGRATION_ERROR` | 502 | An upstream integration failed (PayPal, Channel3, ...) |
| `LLM_ERROR`, `LLM_SCHEMA_ERROR` | 502 | Upstream model failure; agent workflows fall back instead of surfacing this |
| `SERVICE_UNAVAILABLE`, `CHANNEL3_NOT_CONFIGURED` | 503 | A required integration is not configured; `details.setup` explains how |
| `LLM_TIMEOUT` | 504 | Upstream model timeout |

---

## Authentication flow

```bash
# Sign in: returns an access token and sets the refresh cookie
curl -s -c cookies.txt -X POST localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"owner@juniperoak.com","password":"Autopilot@2024"}'
# data.tokens.access_token, data.user (user, active_merchant, role, permissions, memberships)

# Call the API
curl -s localhost:8000/api/v1/auth/me -H "Authorization: Bearer $TOKEN"

# Rotate the session (single use; replaying an old refresh token revokes the whole family)
curl -s -b cookies.txt -c cookies.txt -X POST localhost:8000/api/v1/auth/refresh
```

Details: [Security: tokens](SECURITY.md#tokens).

---

## Endpoints

Generated from the route declarations in [`backend/app/api`](../backend/app/api): the permission column is the
`require_permission(...)` dependency on each route. Where a route lists two permissions, both are required.

### Health, merchants, users and settings

| Method | Path | Permission | Summary |
| --- | --- | --- | --- |
| GET | `/health` | public | Health check |
| GET | `/health/live` | public | Liveness probe (hidden from schema) |
| GET | `/merchants/current` | `dashboard:read` | Active merchant |
| GET | `/merchants/mine` | `dashboard:read` | Merchants I can access |
| GET | `/roles` | `dashboard:read` | Roles and their permissions |
| POST | `/roles` | `users:manage` | Create a custom role |
| DELETE | `/roles/{role_id}` | `users:manage` | Delete a custom role |
| GET | `/permissions` | `dashboard:read` | Permission catalogue |
| GET | `/users` | `users:manage` | Team members |
| POST | `/users/invite` | `users:manage` | Invite a team member |
| POST | `/settings/email/test` | `settings:manage` | Send a test email |
| POST | `/users/role` | `users:manage` | Change a member's role |
| GET | `/audit-logs` | `audit:read` | Audit log |
| GET | `/settings` | `settings:manage` | Merchant settings and integration status |

### Authentication

| Method | Path | Permission | Summary |
| --- | --- | --- | --- |
| POST | `/auth/register` | public | Register a new account |
| POST | `/auth/login` | public | Sign in |
| POST | `/auth/refresh` | refresh cookie | Rotate the session |
| POST | `/auth/logout` | refresh cookie | Sign out |
| POST | `/auth/logout-all` | refresh cookie | Sign out everywhere |
| GET | `/auth/me` | authenticated | Current user |
| PATCH | `/auth/me` | authenticated | Update profile |
| POST | `/auth/change-password` | authenticated | Change password |
| POST | `/auth/forgot-password` | public | Request a password reset |
| POST | `/auth/reset-password` | reset token | Complete a password reset |
| GET | `/auth/session` | authenticated | Access token metadata (hidden from schema) |

### Dashboard and analytics

| Method | Path | Permission | Summary |
| --- | --- | --- | --- |
| GET | `/dashboard/overview` | `dashboard:read` | Growth Command Center |
| GET | `/growth/graph` | `growth:read` | Interactive growth graph |
| GET | `/customers/metrics` | `customers:read` | Customer health |
| GET | `/customers` | `customers:read` | List customers |
| POST | `/customers/segment/preview` | `customers:read` | Preview a customer segment |
| GET | `/products/analytics` | `products:read` | Product analytics |

### Command Center and business events

| Method | Path | Permission | Summary |
| --- | --- | --- | --- |
| GET | `/command-center` | `dashboard:read` | The merchant's whole operating picture |
| GET | `/events` | `events:read` | Cross-module business events |
| GET | `/intelligence/signals` | `growth:read` | Inventory and margin signals that shape growth recommendations |

### Growth: opportunities, reviews, competitors, signals

| Method | Path | Permission | Summary |
| --- | --- | --- | --- |
| GET | `/opportunities` | `growth:read` | Opportunity Radar |
| POST | `/opportunities/detect` | `growth:read` | Run opportunity detection |
| GET | `/opportunities/{opportunity_id}` | `growth:read` | Opportunity detail |
| PATCH | `/opportunities/{opportunity_id}/status` | `growth:recommend` | Update opportunity status |
| GET | `/opportunities/{opportunity_id}/missions` | `growth:read` | Generate a Growth Mission for an opportunity |
| GET | `/growth/arbitrage` | `growth:read` | Growth arbitrage |
| GET | `/growth/allocation` | `growth:read` | Growth budget allocation |
| GET | `/reviews/intelligence` | `reviews:read` | Review intelligence |
| GET | `/reviews` | `reviews:read` | List reviews |
| POST | `/reviews/search` | `reviews:read` | Semantic review search |
| GET | `/competitors/intelligence` | `competitors:read` | Competitor intelligence |
| GET | `/competitors` | `competitors:read` | List competitors |
| GET | `/signals` | `signals:read` | Contextual market signals |
| POST | `/signals/{signal_id}/dismiss` | `signals:read` | Dismiss a signal |
| GET | `/inventory` | `inventory:read` | Inventory intelligence |
| POST | `/inventory/{item_id}/action` | `inventory:write` | Record an inventory decision |
| POST | `/opportunities` | `growth:recommend` | Add an opportunity by hand |

### Campaigns and experiments

| Method | Path | Permission | Summary |
| --- | --- | --- | --- |
| GET | `/campaigns` | `campaign:read` | List campaigns |
| POST | `/campaigns` | `campaign:create` | Create a campaign |
| GET | `/campaigns/{campaign_id}` | `campaign:read` | Campaign detail |
| POST | `/campaigns/{campaign_id}/approve` | `campaign:approve` | Approve or reject a campaign |
| POST | `/campaigns/{campaign_id}/execute` | `campaign:execute` | Execute an approved campaign |
| GET | `/experiments` | `experiment:read` | List experiments |
| POST | `/experiments` | `experiment:create` | Create an experiment |
| GET | `/experiments/{experiment_id}` | `experiment:read` | Experiment detail |
| POST | `/experiments/{experiment_id}/approve` | `experiment:approve` | Approve and launch an experiment |
| POST | `/experiments/{experiment_id}/measure` | `experiment:measure` | Measure an experiment |
| GET | `/experiments/{experiment_id}/summary` | `experiment:read` | Experiment results |

### Agents

| Method | Path | Permission | Summary |
| --- | --- | --- | --- |
| POST | `/agents/ask` | `agents:run` | Ask the Growth Scientist |
| POST | `/agents/investigate` | `growth:recommend` | Run a full investigation |
| POST | `/agents/opportunities/{opportunity_id}/approve` | `campaign:execute` and `experiment:approve` | Approve a recommendation and execute it |
| POST | `/agents/experiments/{experiment_id}/measure` | `experiment:measure` | Measurement and learning agent |
| GET | `/agents/runs` | `agents:view` | Agent activity feed |
| GET | `/agents/runs/{run_id}` | `agents:view` | Agent trace |
| GET | `/agents/tools` | `agents:view` | Tool catalogue |
| POST | `/agents/execute` | `agents:run` | Ask the Merchant OS (Orchestrator -> specialist agent -> approval gate) |
| GET | `/agents/catalogue` | `agents:view` | The Merchant OS agents, what each does, and its tools |
| GET | `/agents/activity` | `agents:view` | Agent activity |

### Inventory, vendors, purchase orders and automation

| Method | Path | Permission | Summary |
| --- | --- | --- | --- |
| GET | `/inventory/items` | `inventory:read` | List inventory |
| GET | `/inventory/items/{item_id}` | `inventory:read` | Inventory item detail |
| POST | `/inventory/items/{item_id}/adjust` | `inventory:write` | Adjust stock |
| PATCH | `/inventory/items/{item_id}/policy` | `inventory:configure` | Configure reorder policy |
| POST | `/inventory/import/preview` | `inventory:configure` | Preview a bulk inventory import |
| POST | `/inventory/import/commit` | `inventory:configure` | Commit a bulk inventory import |
| GET | `/inventory/ledger` | `inventory:ledger_read` | Stock movement ledger |
| GET | `/vendors` | `vendor:read` | List vendors |
| POST | `/vendors` | `vendor:manage` | Create a vendor |
| POST | `/vendors/{vendor_id}/supplies` | `vendor:manage` | Link a vendor to an item |
| GET | `/purchase-orders` | `purchase_order:read` | List purchase orders |
| POST | `/purchase-orders/{order_id}/approve` | `purchase_order:approve` | Approve or reject an order |
| POST | `/purchase-orders/{order_id}/receive` | `purchase_order:receive` | Record goods received |
| GET | `/inventory/automation` | `automation:view` | Automation runs |
| GET | `/inventory/trace/{correlation_id}` | `automation:view` | One automation chain |
| POST | `/inventory/items/{item_id}/reorder` | `purchase_order:create` | Force a replenishment run |
| POST | `/inventory/automation/dispatch` | `automation:manage` | Flush the event outbox |
| POST | `/webhooks/n8n/inventory-event` | HMAC signature | Where n8n asks the backend to act on an event it routed (hidden from schema) |
| POST | `/webhooks/n8n/event` | HMAC signature | Where n8n asks the backend to act on an event it routed (hidden from schema) |
| WS | `/inventory/stream` | access token (query) | Live inventory for one merchant |
| GET | `/inventory/book` | `inventory:ledger_read` | Inventory book |
| GET | `/inventory/book/export` | `inventory:reports_export` | Export the inventory book to Excel |

### Supply Agents: procurement, receiving, invoices, payment

| Method | Path | Permission | Summary |
| --- | --- | --- | --- |
| GET | `/suppliers` | `vendor:read` | Supplier agent network |
| GET | `/suppliers/{supplier_agent_id}` | `vendor:read` | Supplier agent profile |
| GET | `/supply/demand` | `inventory:read` | Demand, stockout risk and reorder recommendations |
| GET | `/supply/timeline` | `procurement:read` | Procurement timeline for the Gantt (tasks + dependencies) |
| GET | `/supply/overview` | `procurement:read` | Supply command center |
| GET | `/procurement` | `procurement:read` | Procurement requests and RFQs |
| POST | `/procurement` | `procurement:create` | Raise a procurement request (and RFQ) |
| POST | `/procurement/autopilot` | `procurement:create` and `procurement:negotiate` | Run the LangGraph procurement workflow to the approval gate |
| GET | `/procurement/{request_id}` | `procurement:read` | Procurement detail |
| POST | `/procurement/{request_id}/advance` | `procurement:negotiate` | Advance the negotiation by one stage |
| POST | `/procurement/{request_id}/negotiate` | `procurement:negotiate` | Run the negotiation to a recommendation |
| POST | `/procurement/{request_id}/approve` | `procurement:approve` | Approve or reject the recommended purchase |
| GET | `/procurement/{request_id}/messages` | `procurement:read` | Agent-to-agent conversation (verified envelopes) |
| POST | `/purchase-orders/{order_id}/goods-receipts` | `purchase_order:receive` | Book a (partial) goods receipt and re-run matching |
| POST | `/purchase-orders/{order_id}/delivery-delay` | `procurement:negotiate` | Supplier agent reports a delivery delay (signed DELIVERY_UPDATE; reschedules the timeline) |
| GET | `/goods-receipts` | `purchase_order:read` | Goods receipts |
| GET | `/purchase-orders/{order_id}/lifecycle` | `purchase_order:read` | Purchase order lifecycle |
| GET | `/supplier-invoices` | `supplier_invoice:read` | Supplier invoices |
| POST | `/supplier-invoices/{invoice_id}/match` | `supplier_invoice:match` | Run three-way matching |
| POST | `/supplier-invoices/{invoice_id}/approve-payment` | `payment:approve` | Approve or reject paying an invoice |
| POST | `/supplier-invoices/{invoice_id}/pay` | `payment:execute` | Execute the approved PayPal payment |
| POST | `/payments/{execution_id}/capture` | `payment:execute` | Capture a payer-approved PayPal order |
| GET | `/reconciliations` | `supplier_invoice:read` | Procurement reconciliations |
| POST | `/purchase-orders/{order_id}/reconcile` | `supplier_invoice:match` | Reconcile PO, receipt, invoice and payment |
| GET | `/agent-messages` | `agents:view` | All agent-to-agent messages |
| POST | `/agent-messages/inbound` | `procurement:negotiate` + agent signature | Deliver a signed envelope from an external agent |

### Supply Intelligence and product discovery

| Method | Path | Permission | Summary |
| --- | --- | --- | --- |
| GET | `/supply/discovery/status` | `products:read` | Whether live Channel3 product discovery is configured |
| POST | `/supply/search` | `products:read` | Natural-language product discovery (live Channel3 search, AI-ranked) |
| POST | `/supply/compare` | `products:read` | Compare 2-4 products side by side with evidence-backed verdicts |
| POST | `/supply/similar` | `products:read` | Similar products (Channel3 /v1/similar) with price differences |
| POST | `/supply/enrich` | `products:read` | Structured product data from a product page URL (Channel3 /v1/lookup) |
| GET | `/supply/products/{product_id}` | `products:read` | Product details (fresh from Channel3) and similar products |
| POST | `/supply/products/{product_id}/shortlist` | `products:read` | Add or remove a product from the shortlist |
| GET | `/supply/searches` | `products:read` | Product search history |
| GET | `/supply/discovered` | `products:read` | Products discovered so far (snapshots; refreshed on view) |
| GET | `/supply/comparisons` | `products:read` | Recent product comparisons |
| POST | `/supply/assistant` | `products:read` | One turn with the conversational shopping agent (Channel3 Conversations) |
| GET | `/supply/assistant/conversations` | `products:read` | Shopping conversations |
| GET | `/supply/assistant/conversations/{conversation_id}` | `products:read` | One shopping conversation |
| GET | `/supply/intelligence` | `products:read` | Supply Intelligence dashboard (no Channel3 credits spent) |
| GET | `/supply/assortment` | `products:read` | Assortment analysis from sales and inventory |
| POST | `/supply/pricing` | `products:read` | Market price intelligence |
| GET | `/supply/catalog-products` | `products:read` | Your catalog, for picking a product to find alternatives for |
| POST | `/supply/alternatives` | `products:read` | Alternatives to one of your products (Channel3 search + similar) |
| POST | `/supply/alternatives/save` | `growth:recommend` | Save an alternative as a recommendation for approval |
| GET | `/supply/recommendations` | `growth:read` | AI recommendations and their lifecycle |
| POST | `/supply/recommendations/generate` | `growth:recommend` | Generate recommendations from sales data and Channel3 |
| GET | `/supply/recommendations/{rec_id}` | `growth:read` | One recommendation with its evidence and lifecycle |
| POST | `/supply/recommendations/{rec_id}/approve` | `procurement:approve` | Approve a recommendation (a human decision) |
| POST | `/supply/recommendations/{rec_id}/reject` | `procurement:approve` | Reject a recommendation |
| POST | `/supply/recommendations/{rec_id}/execute` | `procurement:approve` | Execute an approved recommendation (add to catalog / apply the price test - no money moves) |
| POST | `/supply/recommendations/{rec_id}/purchase` | `procurement:create` | Request approval to buy test stock through PayPal (creates an approval; pays nothing) |
| POST | `/supply/recommendations/{rec_id}/measure` | `growth:recommend` | Measure an executed recommendation's results |
| POST | `/growth/autopilot/run` | `growth:recommend` and `agents:run` | Run the Merchant Growth Autopilot up to the approval gate |
| GET | `/growth/autopilot` | `growth:read` | The latest autopilot run and the recommendation pipeline |

### Approvals and the payments ledger

| Method | Path | Permission | Summary |
| --- | --- | --- | --- |
| GET | `/approvals` | `approval:read` | Approval inbox |
| GET | `/approvals/{approval_id}` | `approval:read` | Approval detail |
| POST | `/approvals/{approval_id}/decide` | `approval:read` + the approval's required permission | Approve or reject (dispatches to the owning service) |
| POST | `/approvals/{approval_id}/execute` | `payment:execute` | Execute an approved cashback payout |
| GET | `/payments` | `paypal:read` | Financial executions (every PayPal money movement) |

### PayPal

| Method | Path | Permission | Summary |
| --- | --- | --- | --- |
| GET | `/paypal/status` | `paypal:read` | PayPal connection status (no secrets) |
| POST | `/paypal/sync` | `paypal:sync` | Synchronise transactions from PayPal (incremental) |
| GET | `/paypal/transactions` | `paypal:read` | Synced PayPal transactions |
| GET | `/paypal/intelligence` | `paypal:read` | Transaction intelligence over synced PayPal data |
| POST | `/paypal/webhooks` | PayPal signature | PayPal webhook receiver (verified, idempotent) |
| GET | `/paypal/webhooks/events` | `paypal:read` | Received webhook events |
| POST | `/paypal/webhooks/simulate` | `paypal:manage` | Send a signed simulated webhook through the real pipeline |
| POST | `/paypal/webhooks/{webhook_event_id}/reprocess` | `paypal:manage` | Re-run a failed webhook handler |
| GET | `/paypal/invoices` | `paypal:read` | PayPal invoices sent to customers |
| POST | `/paypal/invoices` | `paypal:manage` | Create (and send) a PayPal invoice |
| POST | `/paypal/invoices/{record_id}/action` | `paypal:manage` | Remind, cancel or refresh an invoice |
| POST | `/paypal/payouts/cashback` | `paypal:manage` | Request a cashback payout batch (creates an approval) |
| GET | `/paypal/payouts` | `paypal:read` | Payout executions |
| POST | `/paypal/payouts/{execution_id}/refresh` | `paypal:manage` | Refresh a payout batch status from PayPal |
| GET | `/paypal/subscriptions` | `paypal:read` | Subscriptions and failed-payment recovery |
| GET | `/paypal/subscriptions/radar` | `paypal:read` | Subscription revenue radar (billing periods, retries, recovery) |
| GET | `/paypal/plans` | `paypal:read` | Subscription plans |
| POST | `/paypal/plans` | `paypal:manage` | Create a subscription plan |
| POST | `/paypal/subscriptions/{record_id}/action` | `paypal:manage` | Suspend, activate, recover or cancel |

### Payments for approved purchases

| Method | Path | Permission | Summary |
| --- | --- | --- | --- |
| POST | `/payments/orders` | `payment:execute` | Create the PayPal order for an approved purchase (human only, idempotent) |
| POST | `/payments/capture` | `payment:execute` | Capture a payer-approved PayPal order |
| GET | `/payments/orders/{execution_id}` | `paypal:read` | Order details, refreshed from PayPal |
| GET | `/payments/history` | `paypal:read` | Payment history, status counts and open approvals |
| POST | `/payments/webhooks/paypal` | PayPal signature | PayPal webhook receiver (verified, idempotent) - alias of /paypal/webhooks |

### Online store (public)

| Method | Path | Permission | Summary |
| --- | --- | --- | --- |
| GET | `/shop/{slug}` | public | The online store's catalog (public) |
| POST | `/shop/{slug}/orders` | public, rate limited | Start a PayPal checkout (public) |
| POST | `/shop/{slug}/orders/{order_id}/capture` | public | Capture an approved PayPal order and record the sale (public) |

### Agent memory

| Method | Path | Permission | Summary |
| --- | --- | --- | --- |
| GET | `/memory/status` | `memory:read` | Is agent memory configured and reachable |
| GET | `/memory/search` | `memory:read` | Search what the agents have learned about this merchant |
| GET | `/memory/recent` | `memory:read` | The most recent memories for this merchant |
| POST | `/memory/remember` | `memory:write` | Teach the agents something |
| DELETE | `/memory` | `memory:admin` | Erase this merchant's agent memory |

### Integrations

| Method | Path | Permission | Summary |
| --- | --- | --- | --- |
| GET | `/integrations/status` | `dashboard:read` | Every integration, what it is used for, and whether it is live |
| POST | `/integrations/market/benchmark` | `procurement:read` | Market price reference for a product (Channel3) |
| GET | `/integrations/shelf` | `growth:read` | Gear shelf |
| GET | `/integrations/market/procurement/{procurement_id}` | `procurement:read` | Market reference for one procurement request |
| GET | `/integrations/search` | `dashboard:read` | Search the evidence behind decisions (Elasticsearch) |
| POST | `/integrations/search/reindex` | `settings:manage` | Index this merchant's evidence into Elasticsearch |
| POST | `/integrations/kernel/sessions` | `procurement:negotiate` | Open a cloud browser on a supplier's public page (Kernel) |
| DELETE | `/integrations/kernel/sessions/{session_id}` | `procurement:negotiate` | Close a supplier-portal browser session |
| GET | `/integrations/zapier` | `events:read` | Zapier delivery state |
| POST | `/integrations/zapier/test` | `settings:manage` | Send a signed test event to the Zapier Catch Hook |
| GET | `/integrations/paypal-mcp/tools` | `paypal:read` | PayPal MCP tools, flagged callable or blocked |
| POST | `/integrations/paypal-mcp/call` | `paypal:read` | Call one read-only PayPal MCP tool |
| GET | `/integrations/studio/datasets` | `dashboard:read` | Computed datasets for AG Studio dashboards |
| GET | `/integrations/studio/ai` | `dashboard:read` | Whether Studio's AI assistant is available, and on which model |
| POST | `/integrations/studio/ai/turn` | `dashboard:read` | Run one AG Studio agent turn on PayPilot's LLM |

### Voice

| Method | Path | Permission | Summary |
| --- | --- | --- | --- |
| GET | `/voice/session` | `agents:run` | Start a voice session |
| GET | `/voice/assistant-config` | `settings:manage` | Vapi assistant configuration |
| POST | `/voice/sync` | `settings:manage` | Push this backend's tools and prompt onto the live Vapi assistant |
| POST | `/voice/server` | Vapi secret | Vapi server URL (hidden from schema) |
| POST | `/voice/webhook` | Vapi secret | Vapi server URL, alias (hidden from schema) |
| POST | `/voice/tool` | voice session token | Run one voice tool directly |

Notes on the less obvious rows:

* `POST /approvals/{id}/decide` checks `approval:read` at the route and then the approval's own required permission
  (`procurement:approve` or `payment:approve`) in the service, after re-hashing the terms.
* `POST /opportunities/detect` and `POST /signals/{id}/dismiss` need only read permissions because they recompute or
  hide; they never act.
* `POST /inventory/{id}/action` records a decision a person took; the system never places an order from it.
* Inventory endpoints include stock value and unit cost only for callers with `inventory:value_read`; without it
  they return counts and omit money rather than refusing.
* `WS /inventory/stream` takes the access token as a query parameter because browsers cannot set headers on a
  WebSocket; every frame is filtered against the caller's permissions.

---

## Permission matrix

Generated from [`core/permissions.py`](../backend/app/core/permissions.py). Owner holds 51 permissions, Admin 50,
Analyst 32, Staff 24, Viewer 21.

| Permission | Description | Owner | Admin | Analyst | Staff | Viewer |
| --- | --- | :-: | :-: | :-: | :-: | :-: |
| `dashboard:read` | View the growth command center and KPIs | x | x | x | x | x |
| `growth:read` | View growth metrics, the growth graph and opportunities | x | x | x | x | x |
| `growth:recommend` | Ask the Growth Scientist to investigate and recommend | x | x | x |  |  |
| `customers:read` | View customers, cohorts and segments | x | x | x | x | x |
| `products:read` | View product performance | x | x | x | x | x |
| `reviews:read` | View review intelligence | x | x | x | x | x |
| `competitors:read` | View competitor intelligence | x | x | x | x | x |
| `signals:read` | View contextual external market signals | x | x | x | x | x |
| `campaign:read` | View campaigns | x | x | x | x | x |
| `campaign:create` | Create campaigns and audiences | x | x | x |  |  |
| `campaign:approve` | Approve a campaign for execution | x | x |  |  |  |
| `campaign:execute` | Execute an approved campaign | x | x |  |  |  |
| `experiment:read` | View experiments and results | x | x | x | x | x |
| `experiment:create` | Create experiments and variants | x | x | x |  |  |
| `experiment:approve` | Approve and launch an experiment | x | x |  |  |  |
| `experiment:measure` | Run measurement and record the learning outcome | x | x | x |  |  |
| `inventory:read` | View inventory intelligence | x | x | x | x | x |
| `inventory:write` | Record inventory actions such as a reorder decision | x | x |  | x |  |
| `inventory:value_read` | See stock valuation and cost, not just counts | x | x | x |  |  |
| `inventory:configure` | Set reorder points, strategies and automatic ordering | x | x |  |  |  |
| `inventory:ledger_read` | Read the immutable stock movement ledger | x | x | x | x | x |
| `inventory:reports_export` | Export inventory books and reports to Excel | x | x | x |  |  |
| `memory:read` | Search what the agents have learned about this merchant | x | x | x | x | x |
| `memory:write` | Teach the agents something they should remember | x | x | x |  |  |
| `memory:admin` | Erase this merchant's agent memory | x | x |  |  |  |
| `vendor:read` | View suppliers and their terms | x | x | x | x | x |
| `vendor:manage` | Add and edit suppliers, prices and lead times | x | x |  |  |  |
| `purchase_order:read` | View purchase orders | x | x | x | x | x |
| `purchase_order:create` | Raise a purchase order | x | x |  |  |  |
| `purchase_order:approve` | Approve or reject a purchase order | x | x |  |  |  |
| `purchase_order:receive` | Record goods received against an order | x | x |  | x |  |
| `procurement:read` | View procurement requests, RFQs, negotiations and quotes | x | x | x | x | x |
| `procurement:create` | Raise a procurement request and send an RFQ to supplier agents | x | x | x |  |  |
| `procurement:negotiate` | Run buyer-agent negotiation rounds within policy | x | x | x |  |  |
| `procurement:approve` | Approve a negotiated purchase (creates the purchase order) | x | x |  |  |  |
| `supplier_invoice:read` | View supplier invoices, matches and reconciliations | x | x | x | x | x |
| `supplier_invoice:match` | Run three-way matching and reconciliation | x | x |  |  |  |
| `payment:approve` | Approve a payment to a supplier or a cashback payout | x | x |  |  |  |
| `payment:execute` | Execute an approved PayPal payment | x | x |  |  |  |
| `paypal:read` | View PayPal transactions, invoices, payouts and subscriptions | x | x | x | x | x |
| `paypal:sync` | Synchronise transactions from PayPal | x | x | x |  |  |
| `paypal:manage` | Create PayPal invoices, plans and payout requests | x | x |  |  |  |
| `approval:read` | View the approval inbox and decision history | x | x | x | x | x |
| `events:read` | View cross-module business events | x | x | x | x | x |
| `automation:view` | View automation runs and their traces | x | x | x | x | x |
| `automation:manage` | Retry, pause or resume inventory automation | x | x |  |  |  |
| `agents:view` | View agent runs, steps and traces | x | x | x | x | x |
| `agents:run` | Start an agent run | x | x | x | x |  |
| `settings:manage` | Manage merchant settings | x | x |  |  |  |
| `users:manage` | Invite users and change roles | x |  |  |  |  |
| `audit:read` | Read the audit log | x | x |  |  |  |

The separation that matters: **an Analyst can investigate, propose, source and negotiate, but cannot approve or
execute anything that moves money.** Staff sits outside the Viewer-Analyst-Admin-Owner chain because it can
receive goods and write inventory, which an Analyst cannot. Owners can also create custom roles
(`POST /roles`) from the same permission catalogue.

---

<div align="center">

[Previous: API portal and SDKs](APIMATIC.md) | [Docs index](README.md) | [Next: Security](SECURITY.md)

</div>
