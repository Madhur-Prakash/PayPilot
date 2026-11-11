<div align="center">

# Security

Authentication, authorization, tenant isolation, money controls, signed integrations and auditing.

[![Docs index](https://img.shields.io/badge/-Docs_index-0b2a6f?style=flat-square)](README.md)
[![Architecture](https://img.shields.io/badge/-Architecture-003087?style=flat-square)](ARCHITECTURE.md)
[![API reference](https://img.shields.io/badge/-API_reference-0f766e?style=flat-square)](API.md#permission-matrix)
[![Deployment](https://img.shields.io/badge/-Deployment-46E3B7?style=flat-square)](DEPLOYMENT.md#production-checklist)
[![PayPal](https://img.shields.io/badge/-PayPal-003087?style=flat-square&logo=paypal&logoColor=white)](PAYPAL.md)

</div>

---

> **Never trust the client, and never trust the model.** Not the frontend's permission checks, not the merchant id it
> sends, not a resource id in a URL, and not a number an LLM produced. The backend decides.

---

## Contents

- [Threat model](#threat-model)
- [Authentication](#authentication)
- [Tokens](#tokens)
- [Authorization](#authorization)
- [Tenant isolation](#tenant-isolation)
- [Money controls](#money-controls)
- [Constraining the model](#constraining-the-model)
- [Signed messages and webhooks](#signed-messages-and-webhooks)
- [Auditing](#auditing)
- [Logging and redaction](#logging-and-redaction)
- [Transport, headers and CORS](#transport-headers-and-cors)
- [Rate limiting](#rate-limiting)
- [Input validation](#input-validation)
- [Secrets](#secrets)
- [Known gaps](#known-gaps)

---

## Threat model

| Threat | Control |
| --- | --- |
| Credential stuffing | Argon2id, password strength rules, lockout after 8 failures, rate limiting |
| Stolen access token | 30-minute lifetime, signed and typed |
| Stolen refresh token | Opaque, stored only as a keyed hash, single use, family revocation on replay |
| XSS reading the session | Access token in memory only; refresh token in an `HttpOnly` cookie |
| CSRF on refresh | `SameSite` cookie scoped to `/api/v1/auth`, explicit CORS allow-list |
| Privilege escalation | `require_permission` on every route; roles re-derived server-side from the membership |
| Cross-tenant access | Membership-verified merchant resolution; repositories filter every query by merchant |
| An agent exceeding its mandate | Per-tool permission checks, per-agent allow-lists, every workflow ends at an approval gate |
| A model moving money | No path exists: approval and payment are human endpoints; agent tools for them always refuse |
| Tampered terms after approval | Approval bound to a SHA-256 of the exact terms, re-verified at execution |
| Double payment on retry | `PayPal-Request-Id` and `sender_batch_id` derived from the business action |
| Forged PayPal events | `verify-webhook-signature` on the raw body, fail closed without `PAYPAL_WEBHOOK_ID`, event-id replay guard |
| Forged agent or automation messages | Per-agent HMAC with freshness and replay checks; HMAC on both n8n hops |
| Silent tampering | Durable audit trail that survives the rollback of the rejected request |
| Secret leakage through logs | Recursive redaction before any sink |

---

## Authentication

Code: [`core/security.py`](../backend/app/core/security.py), [`services/auth/service.py`](../backend/app/services/auth/service.py).

**Passwords** are hashed with Argon2id (`time_cost=2`, `memory_cost=64 MiB`, `parallelism=2`, 32-byte hash, 16-byte
salt). `check_needs_rehash` runs on every successful login, so raising the cost later upgrades stored hashes
transparently.

**Strength rules:** 10 to 128 characters, with a lowercase letter, an uppercase letter, a digit and a symbol. Every
unmet rule is reported at once.

**Lockout:** 8 consecutive failures lock the account for 15 minutes (`ACCOUNT_LOCKED`). The counter is written on an
independent database session, because the failed request is about to be rolled back.

**Enumeration:** a wrong password and an unknown email produce the same `INVALID_CREDENTIALS` response after
comparable work. Password-reset requests always report success.

---

## Tokens

| | Access token | Refresh token |
| --- | --- | --- |
| Format | JWT, `HS256`, typed (`access`) | 32 random bytes, opaque |
| Lifetime | 30 minutes (`JWT_ACCESS_TOKEN_EXPIRE_MINUTES`) | 14 days (`JWT_REFRESH_TOKEN_EXPIRE_DAYS`) |
| Held in | JavaScript memory only | `HttpOnly` cookie, path `/api/v1/auth` |
| Sent as | `Authorization: Bearer` | Automatically by the browser to `/auth/*` |
| Stored server-side | No | HMAC-SHA256 digest keyed with `JWT_SECRET` |
| Revocable | Expires | Individually, by family, or all for a user |

**Why the access token is never persisted in the browser.** `localStorage` is readable by any script on the origin;
one XSS would yield a replayable token. A page reload loses the in-memory token, and the `HttpOnly` refresh cookie
mints a new one.

**Why the refresh token is not a JWT.** It carries no claims, so there is nothing to forge, and revocation takes
effect immediately. A database dump alone does not yield usable tokens; the attacker also needs `JWT_SECRET`.

**Rotation and replay detection.** Every refresh issues a new token and marks the old one used; tokens in one chain
share a `family_id`.

```
login            -> token A (family F)
refresh A        -> token B (family F), A used
refresh B        -> token C (family F), B used
refresh A again  -> A is already used: family F is compromised
                 -> every token in F revoked; B and C stop working immediately
```

The revocation is written on an independent session. `POST /auth/logout` revokes the presented token;
`POST /auth/logout-all`, a password change and a password reset revoke every session for the user.

---

## Authorization

Code: [`core/permissions.py`](../backend/app/core/permissions.py), [`api/deps.py`](../backend/app/api/deps.py).

**51 permissions** in `resource:action` form, **5 roles**:

| Role | Permissions | Holds | Cannot |
| --- | :-: | --- | --- |
| Owner | 51 | Everything | - |
| Admin | 50 | Analyst plus approve and execute (purchases, payments, campaigns, experiments), PayPal management, inventory configuration, settings, audit | Manage users |
| Analyst | 32 | Read, run agents, create campaigns and experiments, measure, source and negotiate, PayPal sync, write memory | Approve or execute anything that moves money |
| Staff | 24 | Read, run agents, write inventory, receive goods | Create or approve anything |
| Viewer | 21 | Read only | Everything else |

Roles are composed from frozensets (`_ADMIN = _ANALYST | {...}`, `_OWNER = _ADMIN | {USERS_MANAGE}`), so
`Viewer < Analyst < Admin < Owner` holds structurally. Staff sits outside the chain. Owners can define custom roles
from the same catalogue. Full matrix: [API reference: permission matrix](API.md#permission-matrix).

**Enforcement.** Handlers never compare role strings; they declare a permission:

```python
@router.post("/supplier-invoices/{invoice_id}/approve-payment")
async def approve_payment(
    invoice_id: uuid.UUID,
    principal: Principal = Depends(require_permission(Permission.PAYMENT_APPROVE)),
    ...
):
```

A missing permission records an audit event and raises `PERMISSION_DENIED` before the handler runs. The frontend's
permission checks only hide controls; the backend re-derives the permission set from the membership on every request.

---

## Tenant isolation

Three layers, so one mistake does not become a breach.

1. **Merchant resolution is membership-verified.** A client may request a merchant through `?merchant_id=` or
   `X-Merchant-ID`; it is honoured only if an active membership exists. Otherwise `MERCHANT_SCOPE_VIOLATION`, audited.
2. **Repositories scope by construction.** [`MerchantScopedRepository`](../backend/app/repositories/base.py) overrides
   `get`, `list_all`, `count`, `exists` and `create` to filter on and set `merchant_id`. A guessed id from another
   tenant returns `404`, not `403`, because it does not exist within the caller's scope.
3. **Services take the merchant at construction** (`AnalyticsService(session, principal.merchant_id)`); no service
   method accepts a merchant id.

The same rule holds outside HTTP: agent tools receive the merchant through `ToolContext` with no argument to widen
it; agent memory filters every query by merchant; signed agent messages carry a `tenant_id` checked at the
verification boundary; realtime frames go only to the merchant's own connections.

---

## Money controls

| Control | Detail |
| --- | --- |
| Limits before agents | The price ceiling and budget are computed by the `Decimal` engine and frozen with a policy version before any agent speaks |
| Offers validated | Every offer is recomputed and classified `INVALID`, `OUT_OF_POLICY` or `VALID`; out-of-bounds LLM proposals are refused, not clamped |
| Human approval | Purchases need `procurement:approve`; payments need `payment:approve` then `payment:execute`. Owners must still record the decision |
| Bound to exact terms | SHA-256 of the canonical terms stored on the approval and re-checked at decision and execution; any change sets `INVALIDATED` durably |
| Three-way match | Supplier payment is only proposed when PO, goods received and invoice agree within tolerance |
| Idempotent execution | One live execution per approval or invoice; `PayPal-Request-Id` derived from the action |
| Honest modes | `SANDBOX`, `LIVE` or `SIMULATED` stored on every PayPal row |
| Campaigns and experiments | `execute` returns `409 APPROVAL_REQUIRED` without a recorded approval, for every role |

See [Architecture: the approval gate](ARCHITECTURE.md#the-approval-gate) and [Supply Agents](SUPPLY_AGENTS.md).

---

## Constraining the model

LLM output is treated as untrusted input.

| Risk | Control |
| --- | --- |
| Invented figures | Every number is computed server-side; the model receives them already calculated |
| Overwritten estimates | The orchestrator resets impact, confidence and `requires_approval` to the detector's values |
| Malformed output | Pydantic validation, then a deterministic fallback; nothing parses prose |
| Generated SQL or arbitrary calls | No path exists; tools are a fixed, typed registry that calls services |
| Widening scope | `ToolContext` carries the merchant and the caller's permissions; tool arguments cannot change either |
| Prompt injection through reviews or catalog text | External text reaches the model inside computed summaries; the model holds no capability a crafted string could use to move money |
| PayPal MCP write tools | Blocked by name and annotation before any network request; 30 of 46 tools refused for every role |
| Leaked reasoning | Chain-of-thought is never captured or stored |

---

## Signed messages and webhooks

| Channel | Mechanism | Failure mode |
| --- | --- | --- |
| PayPal webhooks | `verify-webhook-signature` with the raw body embedded byte-for-byte; `event_id` unique | No `PAYPAL_WEBHOOK_ID` or failed verification: stored `REJECTED`, never acted on |
| Agent-to-agent protocol | Per-agent HMAC-SHA256 over canonical JSON; tenant, identity, 5-minute freshness, strict schema, sender role, nonce and idempotency-key replay checks | Rejected at `MessageBus.deliver` before any handler |
| n8n outbound and callbacks | HMAC-SHA256 over canonical JSON (`X-Signature: sha256=...`), shared `N8N_WEBHOOK_SECRET`; events claimed once in `processed_events` | Blank secret or bad signature: rejected (fail closed) |
| Zapier | `X-PayPilot-Signature: sha256=...` with `ZAPIER_SIGNING_SECRET`; `X-PayPilot-Event-Id` for de-duplication | Outbound only |
| Vapi | Shared secret (bearer, `X-Vapi-Secret` or HMAC header); tool calls also need a 30-minute voice-scoped session token | No secret configured: webhook rejected |
| Kernel | `https` public hostnames only; no raw IPs, localhost or credentials in URLs; observe-only | `400 BAD_REQUEST` |

---

## Auditing

All security and business events go to `audit_logs`
([`repositories/merchant.py`](../backend/app/repositories/merchant.py), `AuditLogRepository`), readable through
`GET /audit-logs` (`audit:read`). Recorded actions include login, failed login, logout, token refresh, token reuse
detected, password reset and change, user creation, role change, permission denied, merchant-scope violation,
campaign and experiment lifecycle, opportunity detection, agent runs and actions, inventory actions, procurement,
approvals, payments and delivery delays.

**Why security events use their own session.** This was a real bug. A denial raised an exception, FastAPI rolled back
the request session, and the audit row went with it. The same defect meant the failed-login counter never
incremented (so lockout did nothing) and token-family revocation on replay never persisted. All three now go through
[`services/auth/security_events.py`](../backend/app/services/auth/security_events.py), which writes on an
independent session committed immediately. Failures inside it are logged and swallowed: an auditing problem must
never become an availability problem.

---

## Logging and redaction

[`core/logging.py`](../backend/app/core/logging.py). Passwords, password hashes, tokens, API keys, cookies,
`Authorization` headers and client secrets are never logged at any level. `redact()` walks nested dictionaries and
lists and replaces sensitive keys case-insensitively before a record is built; Langfuse payloads pass through the
same function. Every line carries `request_id`, `merchant_id` and `user_id` from context variables bound by the
request middleware, so an incident can be reconstructed without payloads containing identifying detail.

---

## Transport, headers and CORS

Set on every response by `SecurityHeadersMiddleware` ([`core/middleware.py`](../backend/app/core/middleware.py)):

| Header | Value |
| --- | --- |
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `X-Permitted-Cross-Domain-Policies` | `none` |
| `Permissions-Policy` | `camera=(), geolocation=(), payment=(), usb=()` |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` (production only) |

**CORS:** an explicit allow-list from `CORS_ORIGINS` with credentials allowed, plus a fixed pattern for `localhost`
and ngrok development origins. No wildcard.

**Cookies:** `HttpOnly`, path `/api/v1/auth`; `Secure` and `SameSite` from configuration. `SameSite=None` requires
`Secure=true`. See [Deployment: split deployment](DEPLOYMENT.md#split-deployment).

---

## Rate limiting

Per caller (the bearer token's tail when present, otherwise the client address, hashed), across all routes except
health probes and CORS preflight. With Redis it is a fixed window shared by every worker; without Redis an in-process
sliding window, which means N workers allow N times the limit. A `429` carries `Retry-After`. The online store's
order creation and Channel3 calls (40 per minute per merchant) have their own budgets. See
[Configuration: networking and rate limiting](CONFIGURATION.md#networking-and-rate-limiting).

---

## Input validation

Everything crossing the boundary is validated by Pydantic v2 before a handler runs: path ids are `uuid.UUID` (a
non-UUID is `422`, never a query), windows are bounded (`ge=7, le=180`), pagination is capped, enums are `Literal`
or `StrEnum`, bodies are typed schemas, and agent tool arguments have their own models. Queries are SQLAlchemy
expressions; there is no string interpolation into SQL, and no route handler contains a query. The online store
accepts product ids and quantities only and prices the cart server-side.

---

## Secrets

* `.env` is git-ignored; [`.env.example`](../.env.example) has every secret blank.
* Secrets are read only through `Settings`, used server-side, and never returned by the API or written to logs.
* Secrets left blank that need a value (`AGENT_PROTOCOL_SECRET`, `ZAPIER_SIGNING_SECRET`,
  `PAYPAL_SIMULATOR_WEBHOOK_SECRET`) are derived from `JWT_SECRET` with a distinct label per purpose; set them
  explicitly in production.
* `make check` fails if `APP_ENV=production` while `JWT_SECRET` is the development default.
* Rotating `JWT_SECRET` invalidates every access token and every stored refresh-token digest: everyone is signed
  out, which is the intended response to a compromised secret.
* `NEXT_PUBLIC_*` values are compiled into the browser bundle and must never hold a secret.

---

## Known gaps

| Not implemented | Note |
| --- | --- |
| Multi-factor authentication | The flow is not built |
| Key rotation with overlap | Rotating `JWT_SECRET` signs everyone out |
| Field-level encryption at rest | Relies on the database's own encryption |
| Automated dependency scanning | Not configured |
| Penetration test, compliance assessment | Not performed |

The production checklist is in [Deployment: production checklist](DEPLOYMENT.md#production-checklist).

---

<div align="center">

[Previous: API reference](API.md) | [Docs index](README.md) | [Next: Data](DATA.md)

</div>
