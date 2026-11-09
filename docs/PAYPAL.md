# PayPal integration

[Back to docs](README.md)

PayPal is the merchant's system of record and the only rail money moves on - see
[PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md#2-why-paypal-is-central-not-decoration) for where it is used, how it
helps and what is unique. It is an operating component of PayPilot, not a logo: merchant transactions
feed growth analytics, supplier invoices are settled with PayPal Orders v2,
customers are invoiced with PayPal Invoicing, rewards go out through Payouts,
subscription failures arrive by webhook, and every payment is reconciled against
the purchase order and goods receipt it pays for.

## Modes - never blurred

| Mode | When | What you see |
| --- | --- | --- |
| `SANDBOX` | `PAYPAL_CLIENT_ID` + `PAYPAL_CLIENT_SECRET` set, `PAYPAL_ENVIRONMENT=sandbox` | Real calls to `api-m.sandbox.paypal.com` |
| `LIVE` | credentials set, `PAYPAL_ENVIRONMENT=live` | Real calls to `api-m.paypal.com` |
| `SIMULATED` | no credentials (the default) | A deterministic in-process simulator; every id starts `SIM-`; every row and badge says *Simulated* |

The mode is persisted on every transaction, webhook, invoice, subscription and
payment row. A simulated payment can never be mistaken for a real one.

## APIs used

All calls go through [`app/integrations/paypal/client.py`](../backend/app/integrations/paypal/client.py)
(real) or [`simulator.py`](../backend/app/integrations/paypal/simulator.py), behind one
gateway interface ([`gateway.py`](../backend/app/integrations/paypal/gateway.py)).

| API | Endpoint(s) | Used for |
| --- | --- | --- |
| OAuth 2.0 | `POST /v1/oauth2/token` | Client-credentials token, cached until 60s before expiry, refreshed under a lock, retried once on 401 |
| Transaction Search | `GET /v1/reporting/transactions` | Transaction intelligence: gross/net, fees, refunds, failures, AOV, repeat payers |
| Orders v2 | `POST /v2/checkout/orders`, `GET …/{id}`, `POST …/{id}/capture`, `POST …/{id}/authorize` | Supplier invoice settlement (payee = supplier) |
| Payments v2 | `POST /v2/payments/authorizations/{id}/capture`, `…/void` | Authorization holds captured after matching (supported by the client; the demo uses direct capture) |
| Invoicing v2 | `POST /v2/invoicing/invoices`, `GET …/{id}`, `POST …/send`, `…/remind`, `…/cancel`, `POST /v2/invoicing/generate-next-invoice-number` | Merchant -> customer invoices (win-back offers, wholesale orders) |
| Payouts | `POST /v1/payments/payouts`, `GET …/{batch_id}` | Cashback rewards only |
| Catalog + Subscriptions | `POST /v1/catalogs/products`, `POST/GET /v1/billing/plans`, `GET /v1/billing/subscriptions/{id}`, `…/suspend`, `…/activate`, `…/cancel`, `…/revise` | Subscription plans, lifecycle, failed-payment recovery |
| Webhooks | `POST /v1/notifications/verify-webhook-signature` | Verifying every inbound event before it is trusted |

### Why these choices

* **Supplier invoices are paid with Orders v2, never Payouts.** Orders v2 with a
  `payee` is a buyer-approved payment to a business for a specific invoice
  (`invoice_id`, `custom_id` carry our references). Payouts are disbursements and
  are reserved for cashback rewards.
* **Authorization is a hold, not escrow.** The client supports intent
  `AUTHORIZE` + capture-after-match; nothing in the product calls it escrow.
* **Invoicing is merchant -> customer.** A simulated supplier has no PayPal
  account to invoice from; supplier invoices are recorded from the supplier
  agent's `INVOICE_ISSUED` message and paid with Orders v2.

## Reliability

* `PayPal-Request-Id` on every POST that supports it - derived from the business
  action (e.g. `supplier-invoice:{invoice}:{approval}:{attempt}:create`), so a
  retried request can never move money twice. Payouts use the approval id as
  `sender_batch_id`.
* Bounded retries with backoff on 429/5xx/transport errors; `Retry-After` honoured.
* `paypal-debug-id` captured on every response and error, stored on the execution.
* Money is `Decimal` end to end and serialised in PayPal's string format
  (2 dp; 0 dp for JPY/HUF/TWD). Currencies are never summed together.
* Secrets never logged; errors carry PayPal's error name, message and debug id only.

## Transaction sync

[`app/services/paypal/sync.py`](../backend/app/services/paypal/sync.py)

* Transaction Search allows **at most 31 days per call** - the range is split into
  consecutive <=31-day windows and each window is paginated.
* Incremental: resumes from `paypal_sync_checkpoints.synced_until`, re-reading a
  6-hour overlap because reporting data can lag.
* Idempotent: rows upsert on `(merchant_id, paypal_transaction_id)`.
* Payer emails are reduced to a SHA-256 hash - enough to count repeat payers.

## Webhooks

`POST /api/v1/paypal/webhooks` ([`webhooks.py`](../backend/app/services/paypal/webhooks.py))

1. **Verify first** - the raw body is embedded byte-for-byte in the
   verify-webhook-signature request (re-serialising can break verification).
   No `PAYPAL_WEBHOOK_ID` -> reject. A simulator signature is refused by the real client.
2. **Replay guard** - `event_id` is unique; a redelivery returns `duplicate`.
3. **Idempotent handlers** - capture completed/denied/reversed/refunded, order
   approved, payout batch success/denied, invoice paid/cancelled, subscription
   activated/suspended/cancelled/payment-failed.
4. **Failures recorded** - a handler error marks the event `FAILED` (re-processable
   from Finance -> Webhooks); unverified events are stored as `REJECTED` and never acted on.

## Approval gates

| Money movement | Approval action | Permission to approve | Permission to execute |
| --- | --- | --- | --- |
| Pay a supplier invoice | `SUPPLIER_PAYMENT` | `payment:approve` | `payment:execute` |
| Send cashback payouts | `CASHBACK_PAYOUT` | `payment:approve` | `payment:execute` |
| Buy from a supplier (creates the PO) | `PROCUREMENT_PURCHASE` | `procurement:approve` | - |

Approvals bind to a SHA-256 of the exact terms (amount, payee, match, policy
version) and are re-verified at execution. Owners are not exempt.

## Using the sandbox

1. developer.paypal.com -> Apps & Credentials -> create a REST app (Sandbox).
2. Set `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_ENVIRONMENT=sandbox`.
3. Optional: set `PAYPAL_SANDBOX_PAYEE_EMAIL` to a sandbox **business** account
   and re-seed - supplier agents will use it as their payee.
4. Webhooks: register `https://<your-backend>/api/v1/paypal/webhooks` for the
   events above (needs a public URL, e.g. a tunnel) and set `PAYPAL_WEBHOOK_ID`.
5. Supplier payment in the sandbox: approve the purchase and the payment in
   PayPilot, click **Pay with PayPal**, open **Approve in PayPal** (log in with a
   sandbox *personal* account), then click **Capture**. Reconciliation runs
   automatically once captured.

## Agent Toolkit and MCP

PayPal publishes its Agent Toolkit as a remote **MCP server** (46 tools: invoicing,
subscriptions, catalog, shipment tracking, orders, disputes, reporting - and tools that move
money). PayPilot connects to it, **read-only**, through its own tool registry
(`paypal_mcp_read`, permission `paypal:read`), so tenant scoping, RBAC, logging and tracing
still apply and an agent can never use it to bypass the approval gates:

* Transport is HTTP+SSE (`GET /sse`, then POST to the announced per-session endpoint) with the
  same cached OAuth token every REST call uses - verified against the live sandbox.
* A tool is callable only if its name starts with `list_`, `get_`, `show_` or `search_`, has no
  state-changing fragment, and is not annotated `readOnlyHint: false`. That is decided in code
  **before any network request**. 16 of the 46 tools pass; the 30 that create orders, pay,
  refund, send invoices or accept disputes are refused for every role, the Owner included.
* Money-moving PayPal operations stay on the approval-gated REST path
  (`services/paypal/finance.py`); `approve_purchase` and `pay_supplier_invoice` exist only to
  refuse and point at the human approval path.
* **Known PayPal-side issue (observed 2026-11-04):** every sandbox tool call returns
  `PAYPAL_API_SETUP_ERROR: Unsupported cache mode: default` inside a successful MCP reply.
  PayPilot reports it as an error instead of presenting it as data.

See [SPONSORS.md](SPONSORS.md#paypal-agent-toolkit-over-mcp) for the full account.

## Known limitations

* **Verified live against the sandbox:** OAuth, and the Orders v2 supplier payment (create -> buyer
  approval -> capture) on the official Server SDK. **Exercised against the simulator and mocked PayPal
  responses only:** Transaction Search, Invoicing, Payouts, Subscriptions and webhook verification
  (`tests/unit/test_paypal_client.py`, `tests/api/test_paypal_api.py`); run the sandbox steps above to
  verify them live. Real webhooks are rejected until `PAYPAL_WEBHOOK_ID` is set.
* Transaction Search data can lag several hours behind real time.
* The simulator keeps order/invoice state in memory; restart the API and simulated
  PayPal objects are forgotten (PayPilot's own rows persist).
* Customer messaging for campaigns uses PayPilot's own email adapter; PayPal does
  not deliver marketing messages and nothing claims it does.
