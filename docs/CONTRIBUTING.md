<div align="center">

# Contributing

[![Docs index](https://img.shields.io/badge/-Docs_index-475569?style=flat-square&logo=markdown&logoColor=white)](README.md)
[![Architecture](https://img.shields.io/badge/-Architecture-64748b?style=flat-square)](ARCHITECTURE.md)
[![Testing](https://img.shields.io/badge/-Testing-2563eb?style=flat-square)](TESTING.md)
[![API](https://img.shields.io/badge/-API_reference-16a34a?style=flat-square)](API.md)

</div>

How to work in this codebase without breaking the things that make it defensible.

---

## Contents

- [Setup](#setup)
- [The five rules](#the-five-rules)
- [Where code goes](#where-code-goes)
- [Backend conventions](#backend-conventions)
- [Frontend conventions](#frontend-conventions)
- [Adding a feature end to end](#adding-a-feature-end-to-end)
- [Database changes](#database-changes)
- [Changing the seeded dataset](#changing-the-seeded-dataset)
- [Before you commit](#before-you-commit)
- [Writing style](#writing-style)

---

## Setup

```bash
make setup      # env -> dependencies -> database -> migrations -> seed
make dev        # backend :8000, frontend :3000
```

Detail: [INSTALLATION.md](INSTALLATION.md).

---

## The five rules

These are not preferences. Each is enforced by a test, and breaking one changes
what the product is allowed to claim.

### 1. The LLM never calculates a business number

Every figure a merchant sees is computed in Python or SQL. The model reads
already-computed metrics and chooses words.

If you need a new number, it goes in a service. Not in a prompt.

### 2. No causal language without a controlled experiment

The vocabulary is **signal**, **correlation**, **evidence**, **hypothesis**. An
experiment with a held-out control is what turns a hypothesis into a finding.

`test_the_growth_graph_never_claims_causation` walks every edge and asserts its
type is `decomposes_into`, `correlates_with` or `evidenced_by`. Adding a `causes`
edge fails the suite.

### 3. Financial actions require human approval

An agent may recommend. A human approves. The graph terminates at
`approval_gate`, and there is no compiled edge from it to execution.

If you add an action that spends money, changes pricing, or contacts customers, it
must be created `PENDING_APPROVAL` and executed only from an authenticated
endpoint with an explicit permission.

### 4. The backend enforces all authorization

Never trust a frontend permission check, a merchant id from the client, or a
resource id in a URL. Frontend gating exists so the UI does not offer buttons that
would fail — it is not a control.

### 5. No fake claims

Nothing here touches real money, real PayPal systems, real customer messaging, or
real competitor platforms. Simulated data is labelled "Demo Simulation" wherever
it appears, and the health endpoint reports honestly which integrations are wired.

If you add an integration, label it correctly in both directions: do not claim it
when it is absent, and do not hide it when it is present.

---

## Where code goes

```
backend/app/
  api/v1/           route handlers only     - no queries, no business logic
  services/         business logic          - owns all computation
  repositories/     data access             - owns all queries
  db/models/        SQLAlchemy models
  schemas/          Pydantic wire contracts
  agents/           LangGraph nodes, graph, prompts, orchestrator
  tools/            the agent tool registry
  integrations/     external clients        - Groq, Langfuse, Vapi, embeddings
  core/             config, security, permissions, logging, middleware
  seed/             the deterministic dataset generator
```

The dependency direction is strictly one way:

```
api  ->  services  ->  repositories  ->  database
          ^
        tools
```

Services never import from `api`. Repositories never import services. Tools sit
above services and never reach past them into repositories.

### The rules that keep this honest

| Never | Instead |
| --- | --- |
| A query in a route handler | A repository method |
| Business logic in a repository | A service method |
| A service importing `Request` or `Depends` | Pass plain values in |
| A model imported into `api/` for a query | Call the service |
| `merchant_id` as a service method argument | Pass it once, to the constructor |

---

## Backend conventions

### Async everywhere

`async def` all the way down. A blocking call in an async handler stalls the event
loop for every concurrent request.

### Services take the merchant at construction

```python
class AnalyticsService:
    def __init__(self, session: AsyncSession, merchant_id: uuid.UUID) -> None:
        self.session = session
        self.merchant_id = merchant_id
```

No method accepts a merchant id. There is no argument to get wrong.

### Repositories inherit the scoped base

```python
class CampaignRepository(MerchantScopedRepository[CampaignModel]):
    model = CampaignModel
```

`get`, `list_all`, `count`, `exists` and `create` are already merchant-filtered. If
you write a custom query, start from `self.scoped()`:

```python
async def active_for_segment(self, segment_id: uuid.UUID) -> list[CampaignModel]:
    stmt = self.scoped().where(CampaignModel.segment_id == segment_id)
    return list((await self.session.scalars(stmt)).all())
```

Never `select(Model)` directly in a scoped repository. That is how a tenant leak
gets written.

### Handlers declare permissions

```python
@router.post("/{campaign_id}/execute", response_model=ApiResponse[CampaignDetail])
async def execute_campaign(
    campaign_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_permission(Permission.CAMPAIGN_EXECUTE))],
    session: DbSession,
) -> ApiResponse[CampaignDetail]:
    service = CampaignService(session, principal.merchant_id)
    return ok(await service.execute(campaign_id, actor=principal))
```

Never compare role strings in a handler. Declare the permission.

### Everything returns an envelope

```json
{ "success": true, "data": { ... }, "request_id": "..." }
```

Use `ok(...)` from `app/schemas/common.py`. Errors are raised as `AppError`
subclasses and formatted by the registered handlers — never constructed by hand in
a handler.

### Timestamps use `UTCDateTime`

```python
created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
```

Not `DateTime`. The decorator guarantees timezone-aware UTC out of both Postgres
and SQLite, which is what lets the suite run without a database.

### Typing

Full annotations. `mypy app` must stay clean. Prefer `X | None` over
`Optional[X]`, `StrEnum` over bare strings, and `Literal` for closed sets.

---

## Frontend conventions

```
frontend/src/
  app/              Next.js App Router routes
  components/ui/    shadcn primitives + motion helpers
  components/*/     feature components by domain
  features/         composed feature blocks
  hooks/            TanStack Query hooks
  lib/api/          the single Axios client and endpoint wrappers
  schemas/          Zod form schemas
  stores/           Zustand - session only
  types/            wire types mirroring the backend schemas
```

### One HTTP client

Everything goes through [`lib/api/client.ts`](../frontend/src/lib/api/client.ts).
It owns the base URL, the envelope unwrap, the in-memory access token, and the
refresh-once-then-retry behaviour with a shared promise so concurrent 401s produce
one refresh rather than a stampede.

Do not call `fetch` directly. Do not create a second Axios instance.

### Server state is TanStack Query, session state is Zustand

Zustand holds the user, the role and the access token. Nothing else. Anything that
comes from the API belongs in a query hook, keyed consistently:

```ts
export function useGrowthMetrics(days = 30) {
  return useQuery({
    queryKey: ["growth", "metrics", days],
    queryFn: () => growthApi.metrics(days),
    staleTime: 60_000,
  });
}
```

### The access token never touches storage

Module-scoped variable only. Not `localStorage`, not `sessionStorage`, not a
non-`HttpOnly` cookie. A page reload losing it is the intended behaviour — the
refresh cookie mints a new one.

### Motion respects the user

Every animation helper in
[`components/ui/motion.tsx`](../frontend/src/components/ui/motion.tsx) checks
`useReducedMotion`. New animated components use those helpers rather than reaching
for `framer-motion` directly.

### Permission gating is a courtesy

```tsx
{can("campaign:execute") && <ExecuteButton />}
```

This exists so the UI does not offer a button that would 403. The backend check is
the real one, and it runs regardless.

---

## Adding a feature end to end

Worked example: surfacing per-hour revenue.

### 1. Repository — the query

```python
# app/repositories/transactions.py
async def revenue_by_hour(self, start: datetime, end: datetime) -> list[tuple[int, float]]:
    stmt = (
        self.scoped(select(func.extract("hour", TransactionModel.occurred_at), func.sum(...)))
        .where(TransactionModel.occurred_at.between(start, end))
        .group_by(func.extract("hour", TransactionModel.occurred_at))
    )
    return [(int(h), float(v)) for h, v in (await self.session.execute(stmt)).all()]
```

### 2. Service — the computation

```python
# app/services/analytics/service.py
async def hourly_revenue(self, days: int = 30) -> HourlyRevenue:
    start, end = window(days)
    rows = await self.transactions.revenue_by_hour(start, end)
    ...
    return HourlyRevenue(points=points, peak_hour=peak, quiet_hour=quiet)
```

All arithmetic lives here. Not in the handler, not in a prompt.

### 3. Schema — the contract

```python
# app/schemas/analytics.py
class HourlyRevenuePoint(SchemaBase):
    hour: int
    revenue: float
    orders: int

class HourlyRevenue(SchemaBase):
    points: list[HourlyRevenuePoint]
    peak_hour: int
    quiet_hour: int
```

### 4. Route — thin

```python
# app/api/v1/dashboard.py
@router.get("/hourly-revenue", response_model=ApiResponse[HourlyRevenue])
async def hourly_revenue(
    principal: Annotated[Principal, Depends(require_permission(Permission.DASHBOARD_READ))],
    session: DbSession,
    days: Annotated[int, Query(ge=7, le=180)] = 30,
) -> ApiResponse[HourlyRevenue]:
    return ok(await AnalyticsService(session, principal.merchant_id).hourly_revenue(days))
```

Four lines. Resolve, delegate, wrap.

### 5. Tool — if an agent should see it

```python
@registry.register(
    "get_hourly_revenue",
    description="Revenue by hour of day, with the peak and quiet hours identified.",
    args_model=WindowArgs,
    permission=Permission.DASHBOARD_READ,
)
async def get_hourly_revenue(ctx: ToolContext, args: WindowArgs) -> tuple[dict, str]:
    data = await AnalyticsService(ctx.session, ctx.merchant_id).hourly_revenue(args.days)
    payload = data.model_dump()
    return payload, f"Peak hour {data.peak_hour}:00, quiet hour {data.quiet_hour}:00."
```

Then add it to the relevant allow-list in `app/tools/__init__.py`.

### 6. Types and hook

```ts
// src/types/api.ts
export interface HourlyRevenue {
  points: { hour: number; revenue: number; orders: number }[];
  peak_hour: number;
  quiet_hour: number;
}

// src/hooks/use-dashboard.ts
export function useHourlyRevenue(days = 30) {
  return useQuery({
    queryKey: ["dashboard", "hourly-revenue", days],
    queryFn: () => dashboardApi.hourlyRevenue(days),
  });
}
```

### 7. Tests

```python
async def test_hourly_revenue_sums_to_the_daily_total(self, client, owner_headers):
    ...

async def test_hourly_revenue_requires_dashboard_read(self, client, outsider_headers):
    ...

async def test_the_hourly_tool_is_denied_without_the_permission(self, session, seeded):
    ...
```

Three tests: the arithmetic is consistent, the endpoint is scoped, the tool is
gated. Every new capability gets all three.

---

## Database changes

```bash
# 1. Edit the model in app/db/models/
# 2. Generate
make migration MSG="add hourly revenue index"
# 3. READ the generated file
# 4. Apply
make migrate
# 5. Verify a round trip
make downgrade && make migrate
```

Step 3 is not optional. Autogenerate does not understand the custom type
decorators perfectly and will occasionally propose dropping and recreating columns
it should leave alone.

Rules:

- Never edit an applied migration. Write a new one.
- Every migration has a working `downgrade()`.
- New timestamps use `UTCDateTime`.
- New tenant-owned tables get `merchant_id` with an index, and a repository that
  inherits `MerchantScopedRepository`.

---

## Changing the seeded dataset

The dataset carries the entire demo narrative. Changing a constant changes the
story, and the test suite will not notice.

```bash
# after any edit under app/seed/generators/
make calibrate
```

Expect roughly:

```
  Revenue              -12.20%
  Orders                -4.85%
  AOV                   -7.72%
  Repeat rate           -7.65%
  Evening revenue      -31.85%
  Evening service time +24.50%
```

Two constraints that must survive any change:

**The story must be discoverable, never announced.** The analytics layer surfaces
the signals; nothing hardcodes the conclusion. There is no string anywhere saying
"the answer is waiting time" — the evening decline, the service-time drift and the
complaint rate are separate measured facts that happen to line up.

**The dataset must be reproducible.** Everything derives from a seeded `Random`.
Same seed, same numbers, on any machine. No `datetime.now()` inside a generator,
no unseeded randomness, no set iteration order affecting output.

Background: [DATA.md](DATA.md) and
[TESTING.md](TESTING.md#what-tests-could-not-catch).

---

## Before you commit

```bash
make check          # lint + typecheck + backend tests + frontend typecheck
make calibrate      # if you touched app/seed/
```

Or the full CI-equivalent:

```bash
./scripts/verify.sh
```

Checklist:

- [ ] `make check` passes
- [ ] New endpoints declare a permission
- [ ] New repositories inherit `MerchantScopedRepository`
- [ ] New tools have a denial test
- [ ] New timestamps use `UTCDateTime`
- [ ] No secrets, no hardcoded merchant ids
- [ ] No new causal language
- [ ] Simulated data is labelled
- [ ] `make calibrate` still tells the right story, if the seed changed
- [ ] Docs updated if behaviour changed

### Commit messages

Imperative mood, one line, the reason if it is not obvious:

```
Add hourly revenue breakdown to the dashboard
Fix audit rows being lost when the request rolls back
Widen agent_runs.decision to Text - it was truncating sentences
```

---

## Writing style

Applies to code comments, docstrings and documentation alike.

**Comments explain why, not what.** The code says what.

```python
# Written on its own connection: this request is about to raise, and the
# request session will be rolled back.
await record_security_event(...)
```

**Name the assumption.** Every modelling constant carries its reasoning:

```python
RECOVERY_RATE = 0.35   # share of lapsed customers a win-back realistically recovers
```

A merchant may act on a number this produces. The assumption behind it should be
visible to whoever reads the code next.

**Flag limits rather than papering over them.** The rate limiter is per-process unless
`REDIS_URL` is set, and says so. The experiment simulation is labelled. Where the brief's own figures were
internally inconsistent, the deviation is documented in
[DATA.md](DATA.md) rather than quietly resolved.

**No emojis** in code, comments, commits or documentation. Icons and badges where
a visual marker helps.

---

<div align="center">

[Docs index](README.md) · [Architecture](ARCHITECTURE.md) ·
[Testing](TESTING.md) · [Security](SECURITY.md) · [API reference](API.md)

</div>
