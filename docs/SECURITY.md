<div align="center">

# Security model

[![Docs index](https://img.shields.io/badge/-Docs_index-475569?style=flat-square&logo=markdown&logoColor=white)](README.md)
[![Architecture](https://img.shields.io/badge/-Architecture-64748b?style=flat-square)](ARCHITECTURE.md)
[![API](https://img.shields.io/badge/-API_reference-2563eb?style=flat-square)](API.md)
[![Deployment](https://img.shields.io/badge/-Deployment-16a34a?style=flat-square)](DEPLOYMENT.md)

</div>

The governing principle, stated once and then enforced everywhere:

> **Never trust the frontend.** Not its permission checks, not the merchant id it
> sends, not the resource id in a URL. And never trust the model. The backend
> decides.

---

## Contents

- [Threat model](#threat-model)
- [Authentication](#authentication)
- [Tokens](#tokens)
- [Authorization](#authorization)
- [Tenant isolation](#tenant-isolation)
- [The approval gate](#the-approval-gate)
- [Constraining the model](#constraining-the-model)
- [Audit and security events](#audit-and-security-events)
- [Logging and redaction](#logging-and-redaction)
- [Transport and headers](#transport-and-headers)
- [Rate limiting](#rate-limiting)
- [Input validation](#input-validation)
- [Secrets](#secrets)
- [Honest limits](#honest-limits)
- [Checklist before real traffic](#checklist-before-real-traffic)

---

## Threat model

What this implementation is built to withstand.

| Threat | Control |
| --- | --- |
| Credential stuffing | Argon2id, strength rules, per-account lockout, rate limiting |
| Stolen access token | 15-minute lifetime, signed, typed, no server state to tamper with |
| Stolen refresh token | Opaque, stored hashed, single-use, family revocation on replay |
| XSS reading the session | Access token in memory only, refresh token `HttpOnly` |
| CSRF on refresh | `SameSite` cookie, explicit CORS allow-list, credentialed requests only from known origins |
| Privilege escalation | Permission checks server-side on every route, roles never read from the client |
| Cross-tenant access | Repository-level scoping, membership-verified merchant resolution |
| Agent exceeding its mandate | Per-tool permission checks, tool allow-lists, execution behind a human endpoint |
| Model-driven financial action | Structurally impossible: the graph ends at the approval gate |
| Model-generated SQL | No such path exists. Tools call services; services own their queries |
| Silent tampering | Durable audit trail that survives the rollback of the rejected request |
| Secret leakage through logs | Recursive redaction plus a masking sink |

---

## Authentication

[`app/core/security.py`](../backend/app/core/security.py) ·
[`app/services/auth/service.py`](../backend/app/services/auth/service.py)

### Passwords

Argon2id, the current recommendation for password hashing:

```python
PasswordHasher(
    time_cost=2,
    memory_cost=64 * 1024,   # 64 MiB
    parallelism=2,
    hash_len=32,
    salt_len=16,
)
```

Memory-hard by construction, so GPU and ASIC attacks lose most of their advantage.
Parameters live in one place and `check_needs_rehash` runs on every successful
login, so raising the cost later upgrades stored hashes transparently as users
sign in.

### Strength rules

Ten characters minimum, 128 maximum, with lowercase, uppercase, digit and symbol.
Every unmet rule is reported at once rather than one per attempt:

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Password must contain at least 10 characters, one uppercase letter, one symbol.",
    "details": { "requirements": ["at least 10 characters", "one uppercase letter", "one symbol"] }
  }
}
```

### Lockout

Eight consecutive failures lock the account. The counter is incremented through an
**independent database session**, because the request that failed is about to be
rolled back — see [Audit and security events](#audit-and-security-events).

### Enumeration

A wrong password and an unknown email produce the same `INVALID_CREDENTIALS`
response, with the same shape and a comparable code path. Password-reset requests
always report success.

---

## Tokens

Two tokens with deliberately different properties.

```
Access token                        Refresh token
-----------------------------       -----------------------------
JWT, HS256                          32 bytes from secrets.token_urlsafe
15 minutes                          30 days
Held in JavaScript memory           HttpOnly, Secure, SameSite cookie
Sent as Authorization: Bearer       Sent automatically by the browser
Stateless                           Row in refresh_tokens
Cannot be revoked individually      Revocable, and revocable by family
```

### Why the access token is never persisted in the browser

`localStorage` and `sessionStorage` are readable by any script on the origin. A
single XSS gives an attacker a token they can exfiltrate and replay. Keeping it in
a module-scoped variable means a page reload loses it — which is the point: the
`HttpOnly` refresh cookie mints a new one, and script never touches the durable
credential.

### Why the refresh token is not a JWT

It carries no claims, so there is nothing to forge. It is a random string whose
only meaning is a row in the database — which means it can be revoked, and that
revocation takes effect immediately.

### Storage

Stored as an HMAC-SHA256 digest keyed with `JWT_SECRET`, never as plaintext and
never as a bare hash:

```python
def hash_refresh_token(token: str) -> str:
    return hmac.new(settings.jwt_secret.encode(), token.encode(), hashlib.sha256).hexdigest()
```

A database dump alone does not yield usable tokens; the attacker also needs the
application secret. Lookup is by digest, so the comparison is an indexed equality
on a value that is useless without the key.

### Rotation and replay detection

Every refresh issues a new token and marks the old one used. Tokens form a chain
through `family_id`.

```
login        -> token A   (family F)
refresh A    -> token B   (family F), A marked used
refresh B    -> token C   (family F), B marked used

refresh A again  ->  A is already used
                     ==> the family has been compromised
                     ==> revoke every token in family F
                     ==> B and C stop working immediately
```

The legitimate user is signed out and must authenticate again. That is the correct
outcome: the alternative is an attacker holding a valid session alongside them.

Family revocation is written through an independent session, for the same reason
the lockout counter is — the request is about to raise.

### Logout

`POST /auth/logout` revokes the presented token's whole family and clears the
cookie. `POST /auth/logout-all` revokes every family for the user.

---

## Authorization

[`app/core/permissions.py`](../backend/app/core/permissions.py) ·
[`app/api/deps.py`](../backend/app/api/deps.py)

### 38 permissions

`resource:action`, always.

| Group | Permissions |
| --- | --- |
| Analytics | `dashboard:read`, `growth:read`, `growth:recommend`, `customers:read`, `products:read`, `reviews:read`, `competitors:read`, `signals:read` |
| Campaigns | `campaign:read`, `campaign:create`, `campaign:approve`, `campaign:execute` |
| Experiments | `experiment:read`, `experiment:create`, `experiment:approve`, `experiment:measure` |
| Inventory | `inventory:read`, `inventory:write` |
| Agents | `agents:view`, `agents:run` |
| Admin | `settings:manage`, `users:manage`, `audit:read` |

### Five roles

| Role | Holds | Cannot |
| --- | --- | --- |
| **OWNER** | Everything | — |
| **ADMIN** | Analyst plus approve, execute, settings, audit | Manage users |
| **ANALYST** | Read, run agents, create campaigns and experiments, measure | Approve or execute anything |
| **STAFF** | Read, run agents, write inventory | Create or approve anything |
| **VIEWER** | Read only | Everything else |

The separation that matters is ANALYST from ADMIN. An analyst can investigate,
propose and create — and cannot spend a dollar. That boundary is what makes the
approval gate meaningful rather than ceremonial.

### The lattice

```
VIEWER  subset of  ANALYST  subset of  ADMIN  subset of  OWNER
```

Composed from frozensets, so the containment is structural rather than asserted:

```python
_ANALYST = _READ_ONLY | { GROWTH_RECOMMEND, AGENTS_RUN, CAMPAIGN_CREATE, ... }
_ADMIN   = _ANALYST   | { CAMPAIGN_APPROVE, CAMPAIGN_EXECUTE, ... }
_OWNER   = _ADMIN     | { USERS_MANAGE }
```

STAFF sits deliberately outside the chain: it holds `inventory:write`, which
ANALYST does not. Tests assert the four-role lattice and the STAFF exception
separately.

### Enforcement

Route handlers never compare role strings. They declare a permission:

```python
@router.post("/{campaign_id}/execute")
async def execute_campaign(
    campaign_id: uuid.UUID,
    principal: Principal = Depends(require_permission(Permission.CAMPAIGN_EXECUTE)),
    ...
):
```

`require_permission` is a dependency factory. A missing permission records a
security event and raises `PermissionDeniedError` before the handler body runs.

Frontend permission checks exist only so the UI does not offer buttons that would
fail. They are a courtesy, not a control, and the backend re-derives permissions
from the membership row on every request.

---

## Tenant isolation

Three layers, so a mistake in one does not become a breach.

### 1. Merchant resolution is membership-verified

A client may *request* a merchant through `?merchant_id=` or `X-Merchant-ID`. The
request is honoured only if an active membership exists:

```python
membership = await memberships.get_for_user_and_merchant(user.id, requested)
if membership is None:
    await record_security_event(action=AuditAction.MERCHANT_SCOPE_VIOLATION, ...)
    raise MerchantScopeError()
```

A client-supplied id is a request, never an authority.

### 2. Repositories scope by construction

[`MerchantScopedRepository`](../backend/app/repositories/base.py) overrides
`get`, `list_all`, `count`, `exists` and `create`:

```python
async def get(self, entity_id):
    stmt = select(self.model).where(
        self.model.id == _as_uuid(entity_id),
        self.model.merchant_id == self.merchant_id,      # not optional
    )
```

A guessed UUID from another tenant returns `None`, which becomes a 404 — not a
403, because the resource genuinely does not exist within the caller's scope.

`create` sets `merchant_id` from the repository, ignoring any value the caller
passes. It is not possible to write a row into another tenant through this class.

### 3. Services take the merchant at construction

```python
service = AnalyticsService(session, principal.merchant_id)
```

No service method accepts a merchant id. There is no argument to get wrong.

---

## The approval gate

> Any financially consequential action requires explicit merchant approval.

Enforced structurally, not by policy.

### The graph stops

```
intake -> growth_scientist -> [specialists] -> synthesize -> approval_gate -> respond -> END
```

`approval_gate` is terminal for anything money-moving. There is no edge from it to
execution. The graph *cannot* execute a campaign, because no such path is
compiled.

### The tool refuses

`execute_campaign` is registered and always refuses:

```python
return {
    "executed": False,
    "reason": "Campaign execution requires explicit merchant approval.",
    "next_step": "POST /api/v1/campaigns/{campaign_id}/execute",
}, "Execution requires merchant approval and cannot be performed by the agent."
```

Registered deliberately: an agent reaching for it gets a clear, structured
explanation rather than an unexplained absence.

### Everything is created pending

| Created by an agent | Initial state |
| --- | --- |
| Campaign | `PENDING_APPROVAL` |
| Experiment | `PENDING_APPROVAL` |
| Segment | Preview only — a read-only projection of who would be targeted |

### Approval is a human endpoint

`POST /api/v1/agents/opportunities/{id}/approve` requires **both**
`campaign:execute` and `experiment:approve`, and writes an approval record
carrying actor, timestamp, IP address, user agent and the decision.

Declining is recorded too. "We considered this and said no" is part of the trail.

---

## Constraining the model

LLM output is untrusted input. Treated accordingly.

| Risk | Control |
| --- | --- |
| Invented figures | Every number is computed server-side; the model receives them already calculated |
| Model overwriting an estimate | The orchestrator overwrites the model's `estimated_impact`, `confidence` and `requires_approval` with the detector's values |
| Malformed output | Pydantic validation, then a deterministic fallback. Nothing downstream parses prose |
| Generated SQL | No path exists. Tools call services; services own their queries |
| Unrestricted mutation | Tools are a fixed registry with typed arguments and per-tool permissions |
| Widening its own scope | `ToolContext` carries the merchant and the caller's permissions; no tool argument can change either |
| Prompt injection through review text | Review content reaches the model only inside aggregated summaries, and the model holds no capability a crafted review could usefully steer |
| Leaked reasoning | Chain-of-thought is never captured or persisted, only the structured output |

The model's authority in this system is limited to: choosing which read tool to
call next, and phrasing the result.

---

## Audit and security events

### Two trails

| | `audit_logs` | `security_events` |
| --- | --- | --- |
| Records | Business actions: approvals, executions, role changes | Denials, scope violations, failed logins, token replay |
| Written by | The request session | An **independent** session |
| Read by | `GET /api/v1/admin/audit` (`audit:read`) | `GET /api/v1/admin/security-events` (`audit:read`) |

### Why the independent session matters

This was a real bug, and it was three bugs wearing one coat.

The denial path looked correct:

```python
if missing:
    session.add(SecurityEvent(...))   # same session as the request
    raise PermissionDeniedError(...)
```

The raise propagates, FastAPI returns 403, and the request session rolls back —
taking the audit row with it. The system recorded denials perfectly right up until
the moment it needed to record one.

The same defect had two further consequences:

- The failed-login counter never incremented, so **lockout did nothing**.
- Token-family revocation on replay never persisted, so **a stolen token's
  successor stayed valid**.

Fixed in
[`app/services/auth/security_events.py`](../backend/app/services/auth/security_events.py),
where every security write goes through its own session:

```python
async def record_security_event(...) -> None:
    async with session_scope() as session:      # independent connection
        session.add(SecurityEventModel(...))
    # committed regardless of what the request session does next
```

`record_security_event`, `revoke_token_family` and `record_failed_login` all work
this way. Failures inside them are swallowed and logged: an auditing problem must
never become an availability problem.

### What is recorded

Permission denied, merchant-scope violation, failed login, account locked, token
replay detected, token family revoked, campaign approved, campaign executed,
experiment approved, role changed, user invited.

---

## Logging and redaction

[`app/core/logging.py`](../backend/app/core/logging.py)

Never logged, under any level or configuration: passwords, password hashes,
access tokens, refresh tokens, API keys, cookies, `Authorization` headers,
client secrets.

Two independent mechanisms:

**1. Recursive redaction before the record is built.** `redact()` walks dicts and
lists and replaces any key matching the sensitive-name patterns with `***`. Nested
structures are covered, so a token buried three levels inside a context dict does
not survive.

**2. A masking sink.** Logifyx is configured with `mask=True`, which applies a
second pass at the sink. Defence in depth: a new field name nobody added to the
pattern list is still likely to be caught.

Every line is structured, and carries `request_id`, `merchant_id` and `user_id`
from a `ContextVar` bound by the request middleware — so an incident can be
reconstructed without any payload needing to contain identifying detail.

> The `ContextVar` default is `None`, not `{}`. A mutable default shared across
> requests is a cross-request data leak waiting to happen.

---

## Transport and headers

Set on every response by `SecurityHeadersMiddleware`:

| Header | Value |
| --- | --- |
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `X-Permitted-Cross-Domain-Policies` | `none` |
| `Permissions-Policy` | `camera=(), geolocation=(), payment=(), usb=()` |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` — production only |

HSTS is production-only on purpose: pinning HTTPS on `localhost` breaks local
development in a way that is tedious to undo in a browser.

### CORS

An explicit allow-list from `CORS_ORIGINS`, with `allow_credentials=True`. There
is no wildcard path, and none is reachable by configuration — a wildcard with
credentials is rejected by browsers anyway, and would be wrong here regardless.

### Cookies

| Attribute | Development | Production |
| --- | --- | --- |
| `HttpOnly` | true | true |
| `Secure` | false | **true** |
| `SameSite` | `lax` | `lax`, or `none` when the API is on a different site |
| `Path` | `/api/v1/auth` | `/api/v1/auth` |

`SameSite=none` requires `Secure=true`. If the frontend and API are on different
registrable domains, see
[DEPLOYMENT.md](DEPLOYMENT.md#split-deployment).

---

## Rate limiting

Sliding window, per identity and per resource group.

```python
identity = authorization[-24:] if authorization else client_ip
key      = f"{identity}:{path_segment}"
```

Authenticated callers get their own bucket, so one noisy IP behind a shared NAT
cannot starve a tenant. Health probes are exempt. `OPTIONS` is exempt, so CORS
preflight is never the thing that gets limited.

Responses carry `X-RateLimit-Limit` and `X-RateLimit-Remaining`; a 429 carries
`Retry-After`.

> **The limiter is in-process.** With N workers the effective limit is N times the
> configured value. The seam is the point — swap `self._hits` for Redis to make it
> correct across workers. Flagged rather than papered over.

---

## Input validation

Everything crossing the boundary is validated by Pydantic v2 before a handler
runs.

| Input | Constraint |
| --- | --- |
| Path ids | `uuid.UUID` — a non-UUID is 422, never a query |
| Windows | `Field(ge=7, le=180)` |
| Pagination | `limit` capped, `offset` non-negative |
| Enums | `Literal` or `StrEnum` |
| Bodies | Typed schemas |
| Tool arguments | Their own Pydantic models, validated before dispatch |

Queries are built with SQLAlchemy expressions. There is no string interpolation
into SQL anywhere in the codebase, and no route handler contains a query — that
belongs to the repository layer.

---

## Secrets

**Never committed.** `.env` is gitignored; `.env.example` carries placeholders
only. There are no credentials in the repository, and a `JWT_SECRET` shorter than
32 characters is rejected at startup.

```python
@field_validator("jwt_secret")
def _validate_secret(cls, v: str) -> str:
    if len(v) < 32:
        raise ValueError("JWT_SECRET must be at least 32 characters")
    return v
```

Generate one with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Rotating `JWT_SECRET` invalidates every access token **and** every stored refresh
token digest, since the digest is HMAC-keyed with it. Everyone is signed out. That
is the intended behaviour for a compromised secret.

Merchant ids are never hardcoded. The demo merchant is resolved by slug in the
seeder, and every runtime path derives the merchant from the authenticated
membership.

---

## Honest limits

This is a hackathon build. What it does not do:

| Not implemented | Note |
| --- | --- |
| Multi-factor authentication | The schema has room; the flow is not built |
| Distributed rate limiting | In-process only, as described above |
| Field-level encryption at rest | Relies on the database's own encryption |
| Key rotation with overlap | Rotating `JWT_SECRET` signs everyone out |
| Automated dependency scanning | No Dependabot or equivalent configured |
| Penetration testing | None performed |
| SOC 2 / PCI alignment | Not assessed |
| Real payment or messaging execution | **Nothing here touches real money or sends a real message.** Campaign delivery is simulated and labelled as such throughout the UI |

The last row is the one that matters most for how this product presents itself.
Simulated execution is labelled "Demo Simulation" wherever it appears, and no
screen claims access to live PayPal systems, real customer messaging, or competitor
platforms.

---

## Checklist before real traffic

- [ ] `JWT_SECRET` replaced with 64+ random bytes, stored in a secret manager
- [ ] `APP_ENV=production` — enables HSTS and secure cookies, disables `/docs`
- [ ] `DEBUG=false`
- [ ] `CORS_ORIGINS` set to exact production origins, no wildcards
- [ ] `COOKIE_SECURE=true`
- [ ] `COOKIE_SAMESITE` correct for your topology
- [ ] Database credentials rotated away from any seeded default
- [ ] TLS terminated in front of the application
- [ ] Rate limiting backed by shared state if running multiple workers
- [ ] `LOG_JSON=true` and logs shipped somewhere durable
- [ ] Demo seed data removed from any environment with real users
- [ ] Every OWNER account confirmed as intentional

Expanded, with platform specifics:
[DEPLOYMENT.md](DEPLOYMENT.md#production-checklist).

---

<div align="center">

[Docs index](README.md) · [Architecture](ARCHITECTURE.md) ·
[Agents](AGENTS.md) · [API reference](API.md) · [Deployment](DEPLOYMENT.md)

</div>
