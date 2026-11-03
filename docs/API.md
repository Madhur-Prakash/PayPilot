<div align="center">

# API reference

[![Docs index](https://img.shields.io/badge/-Docs_index-475569?style=flat-square&logo=markdown&logoColor=white)](README.md)
[![Architecture](https://img.shields.io/badge/-Architecture-64748b?style=flat-square)](ARCHITECTURE.md)
[![Security](https://img.shields.io/badge/-Security-2563eb?style=flat-square)](SECURITY.md)
[![Agents](https://img.shields.io/badge/-Agents-16a34a?style=flat-square)](AGENTS.md)

</div>

Base URL `http://localhost:8000/api/v1`. Interactive docs at `/docs`, `/redoc`,
`/openapi.json`.

## Conventions

Every response uses one envelope:

```json
{ "success": true, "data": { }, "meta": { } }
```

Every failure uses one shape, and never includes a stack trace in production:

```json
{
  "success": false,
  "error": { "code": "PERMISSION_DENIED", "message": "...", "details": { } },
  "request_id": "8f2c…"
}
```

| Code | HTTP | Meaning |
| --- | --- | --- |
| `INVALID_CREDENTIALS` | 401 | Wrong email or password |
| `TOKEN_EXPIRED` / `INVALID_TOKEN` | 401 | Re-authenticate |
| `PERMISSION_DENIED` | 403 | Role lacks the permission. Audited |
| `MERCHANT_SCOPE_VIOLATION` | 403 | Merchant you are not a member of. Audited |
| `NOT_FOUND` | 404 | Absent, or belongs to another tenant |
| `CONFLICT` | 409 | Already exists |
| `APPROVAL_REQUIRED` | 409 | Money-moving action with no approval on record |
| `VALIDATION_ERROR` | 422 | Field errors in `details.fields` |
| `RATE_LIMITED` | 429 | `Retry-After` header set |
| `LLM_TIMEOUT` / `LLM_SCHEMA_ERROR` | 502/504 | Upstream model. Agents fall back |

Authentication: `Authorization: Bearer <access_token>`. The refresh token lives in
an HttpOnly cookie; send credentials with the request.

Merchant scope is resolved from your membership. `?merchant_id=` and
`X-Merchant-ID` are honoured **only** for merchants you belong to.

---

## Auth · `/auth`

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| POST | `/auth/register` | — | Creates the user and a workspace they own |
| POST | `/auth/login` | — | Returns tokens + sets the refresh cookie |
| POST | `/auth/refresh` | — | Rotates. Replay revokes the token family |
| POST | `/auth/logout` | auth | Revokes the current refresh token |
| POST | `/auth/logout-all` | auth | Revokes every session |
| GET | `/auth/me` | auth | User, merchant, role, effective permissions |
| PATCH | `/auth/me` | auth | Update profile |
| POST | `/auth/change-password` | auth | Revokes all sessions |
| POST | `/auth/forgot-password` | — | Always succeeds; cannot enumerate accounts |
| POST | `/auth/reset-password` | — | Consumes a reset token |

```bash
curl -X POST localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"owner@sharmacafe.in","password":"Autopilot@2024"}'
```

---

## Dashboard and analytics

| Method | Path | Permission |
| --- | --- | ---

## Inventory · items, ledger, book

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| GET | `/inventory/items` | `inventory:read` | Paged. `q` and `status` filters |
| GET | `/inventory/items/{id}` | `inventory:read` | Adds the live reorder decision and its blockers |
| POST | `/inventory/items/{id}/adjust` | `inventory:write` | Writes a ledger row. A reason is required |
| PATCH | `/inventory/items/{id}/policy` | `inventory:configure` | Reorder point, quantity, strategy, automatic ordering |
| POST | `/inventory/items/{id}/reorder` | `purchase_order:create` | Force a replenishment decision now |
| GET | `/inventory/ledger` | `inventory:ledger_read` | Append-only. Filter by item, type or correlation id |
| GET | `/inventory/book` | `inventory:ledger_read` | Opening, movements and closing per SKU |
| GET | `/inventory/book/export` | `inventory:reports_export` | Streams a seven-sheet `.xlsx` |
| POST | `/inventory/import/preview` | `inventory:configure` | Auto-maps columns; validates every row, writes nothing |
| POST | `/inventory/import/commit` | `inventory:configure` | Applies only the rows without errors |

Stock value and unit cost appear only with `inventory:value_read`. Without it the
same endpoints return counts and omit the money, rather than refusing.

`WS /inventory/stream` pushes live updates. The token arrives as a query
parameter because a browser cannot set headers on a websocket, and every frame
is filtered against the caller's permissions before it is sent.

---

## Procurement · vendors and purchase orders

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| GET | `/vendors` | `vendor:read` | With a count of what each one supplies |
| POST | `/vendors` | `vendor:manage` | |
| POST | `/vendors/{id}/supplies` | `vendor:manage` | Links a vendor to an item and its price |
| GET | `/purchase-orders` | `purchase_order:read` | Filter by status |
| POST | `/purchase-orders/{id}/approve` | `purchase_order:approve` | `approve: false` rejects |
| POST | `/purchase-orders/{id}/receive` | `purchase_order:receive` | Per line. A short receipt leaves the order partially received |

An order at or above `INVENTORY_APPROVAL_THRESHOLD` is held at
`PENDING_APPROVAL` and reaches no vendor until a human approves it.

---

## Automation · runs and traces

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| GET | `/inventory/automation` | `automation:view` | Every run, its steps and its reasoning |
| GET | `/inventory/trace/{correlation_id}` | `automation:view` | One causal chain: events, runs, movements, orders |
| POST | `/inventory/automation/dispatch` | `automation:manage` | Flush the outbox now. The relay does this on a timer |

`POST /webhooks/n8n/event` is the signed callback n8n uses, and its older alias
`/webhooks/n8n/inventory-event`. Both are HMAC-verified and excluded from the
schema. See [Inventory automation](../n8n/README.md).

---

## Agent memory · `/memory`

| Method | Path | Permission | Notes |
| --- | --- | --- | --- |
| GET | `/memory/status` | `memory:read` | Whether memory is enabled, reachable, and why not |
| GET | `/memory/search` | `memory:read` | Natural language. Returns `available: false` when memory is off, not an error |
| POST | `/memory/remember` | `memory:write` | Queued; the knowledge graph builds after the response |
| DELETE | `/memory` | `memory:admin` | Irreversible. Requires `confirm: true` |

Scope comes from the authenticated principal, never from a parameter. See
[Agent memory](MEMORY.md).

--- |
| GET | `/dashboard/overview?days=30` | `dashboard:read` |
| GET | `/growth/graph?days=30` | `growth:read` |
| GET | `/customers/metrics?days=30` | `customers:read` |
| GET | `/customers` | `customers:read` |
| POST | `/customers/segment/preview` | `customers:read` |
| GET | `/products/analytics?days=30` | `products:read` |

`/dashboard/overview` is deliberately one aggregated call — KPIs, trends, segment
breakdown, products, customer health and anomalies. The Command Center renders
from a single response rather than fanning out.

---

## Growth · opportunities, reviews, competitors, signals

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/opportunities` | `growth:read` |
| POST | `/opportunities/detect` | `growth:read` |
| GET | `/opportunities/{id}` | `growth:read` |
| POST | `/opportunities` | `growth:recommend` |
| PATCH | `/opportunities/{id}/status` | `growth:recommend` |
| GET | `/reviews/intelligence?days=30` | `reviews:read` |
| GET | `/reviews` | `reviews:read` |
| POST | `/reviews/search` | `reviews:read` |
| GET | `/competitors/intelligence` | `competitors:read` |
| GET | `/competitors` | `competitors:read` |
| GET | `/signals` | `signals:read` |
| POST | `/signals/{id}/dismiss` | `signals:read` |
| GET | `/inventory` | `inventory:read` |
| POST | `/inventory/{id}/action` | `inventory:write` |

These two are the *analytics* view of stock - days of cover and revenue at risk,
alongside the other growth surfaces. Managing stock, ordering and the ledger is a
separate group: see [Inventory](#inventory--items-ledger-book) and
[Procurement](#procurement--vendors-and-purchase-orders).

`POST /opportunities/detect` is idempotent: re-running refreshes existing
opportunities rather than duplicating them, and never rolls back one a human has
already acted on.

`POST /inventory/{id}/action` records a decision *you* took. The system never
places an order.

---

## Campaigns and experiments

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/campaigns` | `campaign:read` |
| POST | `/campaigns` | `campaign:create` |
| GET | `/campaigns/{id}` | `campaign:read` |
| POST | `/campaigns/{id}/approve` | `campaign:approve` |
| POST | `/campaigns/{id}/execute` | `campaign:execute` |
| GET | `/experiments` | `experiment:read` |
| POST | `/experiments` | `experiment:create` |
| GET | `/experiments/{id}` | `experiment:read` |
| POST | `/experiments/{id}/approve` | `experiment:approve` |
| POST | `/experiments/{id}/measure` | `experiment:measure` |
| GET | `/experiments/{id}/summary` | `experiment:read` |

`approve` and `execute` are separate permissions on purpose. `execute` returns
`409 APPROVAL_REQUIRED` without a recorded approval — **including for an Owner**.

`measure` recomputes conversion, lift, incremental revenue and profit, ROI and a
two-proportion z-test from the transaction ledger every time.

---

## Agents

| Method | Path | Permission |
| --- | --- | --- |
| POST | `/agents/ask` | `agents:run` |
| POST | `/agents/investigate` | `growth:recommend` |
| POST | `/agents/opportunities/{id}/approve` | `campaign:execute` **and** `experiment:approve` |
| POST | `/agents/experiments/{id}/measure` | `experiment:measure` |
| GET | `/agents/runs` | `agents:view` |
| GET | `/agents/runs/{id}` | `agents:view` |
| GET | `/agents/tools` | `agents:view` |

```bash
curl -X POST localhost:8000/api/v1/agents/investigate \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"question":"Why did my revenue fall?","days":30}'
```

Returns the run, its steps, its tool calls, the structured recommendation and
suggested follow-ups. `used_fallback: true` means no LLM was configured and the
deterministic path produced the answer.

`/agents/runs/{id}` is the human-readable trace: actions, tools, evidence,
decisions. Raw model reasoning is never recorded, so it is never returned.

---

## Voice · `/voice`

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/voice/session` | `agents:run` |
| GET | `/voice/assistant-config` | `settings:manage` |
| POST | `/voice/tool` | short-lived voice session token |
| POST | `/voice/webhook` | HMAC signature |

`/voice/session` returns the public key, assistant id, per-session overrides and a
30-minute scoped token. Vapi presents that token on each tool call, so voice
requests are authenticated and merchant-scoped like any other.

Voice tools route into the **same** agents as the web UI. The webhook is rejected
when no secret is configured, rather than trusted.

---

## Admin

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/health` | — |
| GET | `/merchants/current` | `dashboard:read` |
| GET | `/merchants/mine` | `dashboard:read` |
| GET | `/roles` | `dashboard:read` |
| GET | `/permissions` | `dashboard:read` |
| GET | `/users` | `users:manage` |
| POST | `/users/invite` | `users:manage` |
| POST | `/users/role` | `users:manage` |
| GET | `/audit-logs` | `audit:read` |
| GET | `/settings` | `settings:manage` |

`/health` reports database connectivity and which optional integrations are
active — and states plainly that the product runs without any of them.

---

## Permissions

| Permission | OWNER | ADMIN | ANALYST | STAFF | VIEWER |
| --- | :-: | :-: | :-: | :-: | :-: |
| `dashboard:read` · `growth:read` · `reviews:read` · `competitors:read` | ● | ● | ● | ● | ● |
| `customers:read` · `products:read` · `inventory:read` · `agents:view` | ● | ● | ● | ● | ● |
| `campaign:read` · `experiment:read` · `signals:read` | ● | ● | ● | ● | ● |
| `agents:run` | ● | ● | ● | ● | |
| `growth:recommend` | ● | ● | ● | | |
| `campaign:create` · `experiment:create` · `experiment:measure` | ● | ● | ● | | |
| `inventory:write` | ● | ● | | ● | |
| `campaign:approve` · `campaign:execute` · `experiment:approve` | ● | ● | | | |
| `settings:manage` · `audit:read` | ● | ● | | | |
| `users:manage` | ● | | | | |

The line that matters: **ANALYST can propose but cannot approve or execute.**

---

<div align="center">

[Docs index](README.md) · [Architecture](ARCHITECTURE.md) · [Security](SECURITY.md) ·
[Agents](AGENTS.md) · [Contributing](CONTRIBUTING.md)

</div>
