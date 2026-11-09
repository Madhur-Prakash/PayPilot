<div align="center">

# Architecture

[![Docs index](https://img.shields.io/badge/-Docs_index-475569?style=flat-square&logo=markdown&logoColor=white)](README.md)
[![Agents](https://img.shields.io/badge/-Agents-64748b?style=flat-square)](AGENTS.md)
[![Security](https://img.shields.io/badge/-Security-2563eb?style=flat-square)](SECURITY.md)
[![API reference](https://img.shields.io/badge/-API_reference-16a34a?style=flat-square)](API.md)
[![Agent memory](https://img.shields.io/badge/-Agent_memory-7c3aed?style=flat-square)](MEMORY.md)
[![Automation](https://img.shields.io/badge/-Automation-b45309?style=flat-square)](../n8n/README.md)

</div>

How PayPilot is put together, and why each decision was made.

---

## 1. Shape

A modular monolith. Not microservices — the brief asks for production-ready
architecture, not distributed-systems overhead for a single product surface.

```
┌──────────────────────────────────────────────────────────────────────┐
│ Next.js 15 App Router                                                │
│   one Axios client (auth, correlation id, envelope unwrap, refresh)  │
│   TanStack Query for server state · Zustand for the session only     │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ HTTPS, Bearer + HttpOnly refresh cookie
┌───────────────────────────────▼──────────────────────────────────────┐
│ FastAPI                                                              │
│   middleware:  request id → rate limit → CORS → security headers     │
│   deps:        authenticate → resolve merchant → require_permission  │
│   handlers:    thin. validate, delegate, shape the response.         │
├──────────────────────────────────────────────────────────────────────┤
│ Services        business logic, transactions, approval gates         │
├──────────────────────────────────────────────────────────────────────┤
│ Repositories    ALL database access. Tenant-scoped by construction.  │
├──────────────────────────────────────────────────────────────────────┤
│ PostgreSQL 16 + pgvector                                             │
└──────────────────────────────────────────────────────────────────────┘
          ▲                                   ▲
          │                                   │
┌─────────┴──────────┐              ┌─────────┴──────────────────────┐
│ LangGraph agents   │─── tools ───►│ Tool registry                  │
│ orchestrator owns  │              │  typed · authorized · scoped   │
│ runs, traces, steps│              │  logged · traced · recorded    │
└─────────┬──────────┘              └────────────────────────────────┘
          │
          ├──► Groq (GPT-OSS)  interpretation only
          ├──► Langfuse        traces, generations, tool spans
          └──► Logifyx         structured logs
```

**The layering rule:** a route handler never writes a query; a repository never
contains business logic; a service never renders a response. Agent tools are the
only bridge between the model and the business, and they sit *above* services, so
an agent can never reach the database directly.

---

## 2. The rule that shapes everything

> **The LLM never calculates a business number.**

This is the spec's critical AI-engineering rule, and it drives the whole design.

```
PostgreSQL / Python                  LLM
─────────────────────                ───
revenue        = $24.7K      ──►     reads structured metrics
repeat_rate    = 38.3%               selects which tool to call next
evening change = −32.3%              writes the hypothesis and the explanation
opportunity    = $724/mo          phrases the recommendation
confidence     = 0.92
```

Enforced in three places:

1. **Tools return computed results.** No tool hands raw rows to a model.
2. **The detector sizes opportunities.** `OpportunityDetector` computes
   `estimated_value_monthly` and `confidence` from explicit, auditable formulas.
3. **The orchestrator overwrites the model.** In `nodes.synthesize`, after the LLM
   returns a `GrowthRecommendation`, `estimated_impact`, `confidence` and
   `requires_approval` are reset to the detector's values. The model may phrase.
   It may not price.

A corollary: the product works with **no LLM at all**. Every node has a
deterministic fallback, and runs taken that way are flagged `used_fallback` and
badged in the UI rather than passed off as model output.

---

## 3. Correlation is not causation

The growth graph is the product's most persuasive screen, which makes it the
easiest place to overclaim. Three defences:

**Typed edges.** Only three relationships exist:

| Edge | Meaning | Used for |
| --- | --- | --- |
| `decomposes_into` | arithmetic — the parent *is* these parts | revenue → orders × AOV |
| `correlates_with` | moved over the same window | evening revenue ↔ service time |
| `evidenced_by` | a different source shows the same thing | service time ↔ review complaints |

**Prompt discipline.** Every system prompt in `agents/prompts.py` carries the same
rule, with the vocabulary to use instead.

**A test.** `test_the_growth_graph_never_claims_causation` asserts the edge set is
closed and that "caused by", "because of" and "is causing" never appear in node
interpretations.

The honest framing the product uses: *these signals moved together; a controlled
experiment is what would establish whether acting on one moves the other.* Which
is exactly what the next step does.

---

## 4. Security

### Authentication

- **Argon2id** password hashing (`time_cost=2`, `memory_cost=64 MiB`).
- **Short-lived JWT** access tokens (30 min default).
- **Opaque refresh tokens**, stored only as an HMAC-SHA256 keyed hash, in an
  HttpOnly `SameSite=Lax` cookie scoped to `/api/v1/auth`. Page JavaScript cannot
  read them.
- **Rotation on every use**, with `family_id` linking a rotation chain. Replaying
  a retired token revokes the **whole family** — the standard response to a stolen
  token.
- Unknown email and wrong password produce the same error, after comparable work,
  so the response cannot be used to enumerate accounts.

The access token is held **in memory only** on the frontend. Durability comes from
the refresh cookie: on page load, `bootstrap()` silently exchanges it.

### Authorization

Three independent gates on every protected request:

```python
principal = Depends(require_permission(Permission.CAMPAIGN_EXECUTE))
```

1. **Authenticated** — valid unexpired token, active account.
2. **Scoped** — the merchant is resolved from `MerchantMembership`. A
   `merchant_id` from the client is a *request*, honoured only if a membership
   exists; otherwise `403 MERCHANT_SCOPE_VIOLATION`, audited.
3. **Permitted** — the permission set is re-derived server-side from the stored
   role. The frontend's `permissions` array only hides controls.

Roles are a strict lattice (`VIEWER ⊂ ANALYST ⊂ ADMIN ⊂ OWNER`), asserted by test.
The split that matters: **ANALYST can create but not approve or execute.**

### Tenant isolation

Structural rather than remembered. `MerchantScopedRepository` overrides `get`,
`list_all`, `count` and `create` to filter on `merchant_id`, so a cross-tenant
fetch returns *not found* rather than another merchant's row, and a create cannot
write into another tenant even if the caller passes one.

### Durable security auditing

A subtle bug the tests caught. A denied request raises, and FastAPI's session
dependency rolls back — which would take the audit row with it. Exactly the
events worth keeping would vanish.

`services/auth/security_events.py` writes permission denials, scope violations,
failed logins, the lockout counter and token-family revocation through an
**independent session**, committed immediately, so they survive the rollback of
the request that produced them.

---

## 5. The agent system

### The graph

```
START
  │
  ▼
intake                    intent classification (LLM or keyword fallback)
  │
  ▼
growth_scientist          get_growth_metrics · get_customer_segments
  │                       detect_growth_opportunities · detect_anomalies
  ├──► review_intelligence      get_review_summary · search_reviews
  ├──► market_intelligence      get_competitor_summary · get_external_signals
  │
  ▼
synthesize                evidence → GrowthRecommendation (schema-validated)
  │
  ▼
approval_gate             ◄── THE GRAPH ENDS HERE for anything money-moving
  │
  ▼
respond → END
```

Resuming after approval is **not a path the model can take**. The approval
endpoint — authenticated, permission-checked — drives Action → Experiment →
Measurement → Learning.

### State channels

Every key is last-value-wins, and nodes return the whole state. Correct because
the graph is strictly sequential: `growth_scientist` routes to exactly one
successor.

This is documented in `agents/state.py` because getting it wrong is subtle and
expensive. An earlier version used `Annotated[list, append]` reducers *and* had
nodes return the full accumulated state — so LangGraph appended the accumulated
list to itself at every node. Seven steps became 352 tool calls. If a genuinely
concurrent fan-out is ever added, the reducers must come back **and** nodes must
return only their own delta; doing one without the other silently duplicates
everything.

### Tools

Every tool call is typed, authorized, merchant-scoped, logged, traced, persisted
and error-safe. `registry.execute()` never raises — failures come back as a
`ToolResult` with `ok=False`, so a denied permission or a malformed argument
degrades the answer instead of crashing the run.

23 tools across analytics, intelligence and actions. Each agent gets an explicit
allow-list (`app/tools/__init__.py`) so one agent cannot reach for another's
capabilities.

### LLM failure handling

`LLMService.structured()` is the only entry point. Timeout → bounded retries →
fallback model → deterministic fallback value. A malformed or schema-invalid
response can never raise into a handler:

```
complete()  → retries, then the fallback model
extract_json() → bare JSON, fenced blocks, or prose-wrapped
schema.model_validate() → on failure, return the caller's fallback
```

`GrowthRecommendation` also normalises what models actually get wrong:
`confidence: 82` becomes `0.82`; `"$9,840"` becomes `9840.0`.

---

## 6. Data model

30 tables. UUID primary keys, `created_at`/`updated_at` everywhere, foreign keys
with explicit cascades, composite indexes on the real access paths
(`merchant_id + business_date`, `merchant_id + status`).

### Portable column types

`app/db/types.py` lets one model definition run on Postgres *and* SQLite:

| Type | Postgres | SQLite |
| --- | --- | --- |
| `GUID` | `UUID` | `CHAR(36)` |
| `JSONB` | `JSONB` | JSON `TEXT` |
| `StringArray` | `TEXT[]` | JSON `TEXT` |
| `Vector` | `vector(384)` | JSON `TEXT` |
| `UTCDateTime` | `TIMESTAMPTZ` | `DATETIME`, coerced to aware UTC on read |

This is why `make test` runs 515 tests with no Docker.

`UTCDateTime` exists because of a real bug: Postgres round-trips aware datetimes,
SQLite drops the offset, and comparing the two raises `TypeError`. Fixing it in
the type keeps every call site free of defensive `tzinfo` checks.

Status fields are strings with Python constant classes, not Postgres enums —
adding a status should not require a migration.

---

## 7. Observability

**Structured logging** via Logifyx when installed, with an identical built-in
fallback. `setup_logify()` swaps the global logger class, which would give every
third-party logger its own handlers and its own file, so the integration
registers, builds the one sink it wants, then restores the previous class.

Request-scoped fields (`request_id`, `user_id`, `merchant_id`, `agent_run_id`,
`trace_id`) ride in contextvars and merge into every record automatically.

Secrets are redacted before they reach any sink — passwords, tokens, API keys,
cookies, nested and case-insensitive.

**Langfuse** wraps each agent run in a trace with spans for nodes, generations for
LLM calls (with token usage) and spans for tool calls. Every method is
exception-safe: observability must never break the request it observes. Absent
keys produce a no-op, so agent code never branches on "is tracing configured".

---

## 8. Bugs the tests caught

Worth recording, because each was invisible until something asserted against it.

**1. `agent_runs.decision` was `VARCHAR(48)`** but received a sentence. First real
agent run: `StringDataRightTruncationError`. Fixed by widening to `TEXT`
(migration `0002`).

**2. LangGraph state duplication.** Append reducers plus nodes returning the full
state. 7 steps became 70+, 8 tool calls became 352. Fixed by making every channel
last-value-wins and documenting the coupling.

**3. Security audit rows were rolled back.** A permission denial raises, the
session rolls back, the audit row disappears. The `denial audited` check failed
and exposed it. The same bug meant **the failed-login counter never incremented**,
so the account lockout did nothing — and **token-family revocation on replay never
persisted**, so a stolen token's successor stayed valid. All three now write
through an independent session.

**4. Lazy-load in the agent endpoints.** The run object returned by the
orchestrator has unloaded collections; touching them triggered implicit IO on an
async session (`MissingGreenlet`). Fixed by re-reading with eager loads.

**5. Seeded customer tenure manufactured fake growth.** A third of the customer
base "joined" during the comparison windows, so non-evening segments appeared to
grow 10% and masked the real decline. Found by the calibration harness, not by a
test — which is why that harness exists.

---

## 9. Deliberate omissions

**ML pricing/demand model.** Excluded by the brief at this stage.
`OpportunityKind.PRICING` is the extension point.

**Real campaign delivery.** Simulated, labelled everywhere. The approval and
execution *control flow* is real — only the channel adapter is a stub.

**Competitor scraping.** Seeded benchmark data, labelled. No platform is accessed.

**Distributed rate limiting.** Done when `REDIS_URL` is set (Render Key Value):
the limiter, the Channel3 caches and the realtime hub share Redis, and fall back to
in-process state when it is absent or down. See [CONFIGURATION.md](CONFIGURATION.md#redis).

---

<div align="center">

[Docs index](README.md) · [Agents](AGENTS.md) · [Security](SECURITY.md) ·
[Data](DATA.md) · [API reference](API.md)

</div>
