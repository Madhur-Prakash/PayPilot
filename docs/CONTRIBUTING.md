<div align="center">

# Contributing

The rules the codebase follows, where code goes, and how to add a feature end to end.

[![Docs index](https://img.shields.io/badge/-Docs_index-0b2a6f?style=flat-square)](README.md)
[![Architecture](https://img.shields.io/badge/-Architecture-003087?style=flat-square)](ARCHITECTURE.md)
[![Testing](https://img.shields.io/badge/-Testing-16a34a?style=flat-square)](TESTING.md)
[![Security](https://img.shields.io/badge/-Security-dc2626?style=flat-square)](SECURITY.md)
[![Ruff](https://img.shields.io/badge/lint-ruff-D7FF64?style=flat-square&logo=ruff&logoColor=black)](https://docs.astral.sh/ruff/)

</div>

---

## Contents

- [Setup](#setup)
- [Project rules](#project-rules)
- [Where code goes](#where-code-goes)
- [Backend conventions](#backend-conventions)
- [Frontend conventions](#frontend-conventions)
- [Adding a feature end to end](#adding-a-feature-end-to-end)
- [Database changes](#database-changes)
- [Changing the demo dataset](#changing-the-demo-dataset)
- [Before you open a pull request](#before-you-open-a-pull-request)

---

## Setup

```bash
make init      # tools, .env, dependencies, Postgres, migrations, seed
make dev       # backend :8000 with reload, frontend :3000
```

Details: [Installation](INSTALLATION.md).

---

## Project rules

These are enforced by code review and by tests. A change that breaks one is a bug, whatever else it fixes.

| Rule | In practice |
| --- | --- |
| **The LLM never calculates a business number** | Compute amounts, limits, scores and statistics in SQL or `Decimal` code. Give the model computed facts; reset any number it returns to the computed value |
| **Money moves only after a human approval bound to exact terms** | Any new money-moving action raises an `approval_requests` row with canonical terms and a hash, is executed by a person through a permission-checked endpoint, and derives its idempotency key from the approval. Agent tools may request, never approve or pay |
| **The backend enforces all authorization** | Every route declares `require_permission(...)`. Frontend checks only hide controls |
| **Tenant isolation is structural** | Services take the merchant at construction; repositories extend `MerchantScopedRepository` |
| **No fake claims** | Simulated data and fallbacks are labelled. PayPal rows store their mode. Nothing invents products, prices or payments |
| **No causal language without an experiment** | Use "correlates with", "moved in step with". The Growth Graph has no causal edge type |

---

## Where code goes

```
backend/app/
  api/v1/          route handlers only       no queries, no business logic
  services/        business logic            owns computation and transactions
  repositories/    data access               owns queries; tenant-scoped
  db/models/       SQLAlchemy models
  schemas/         Pydantic wire contracts
  agents/          LangGraph workflows, nodes, prompts, orchestrators
  tools/           the agent tool registry and allow-lists
  integrations/    external clients          PayPal, Channel3, Groq, Langfuse, Vapi, ...
  core/            config, security, permissions, middleware, logging, Redis
  seed/            deterministic demo data
```

Dependencies point one way:

```
api  ->  services  ->  repositories  ->  database
            ^
          tools  <-  agents
```

| Never | Instead |
| --- | --- |
| A query in a route handler | A repository method |
| Business logic in a repository | A service method |
| A service importing `Request` or `Depends` | Pass plain values in |
| `merchant_id` as a service method argument | Pass it once, to the constructor |
| A direct SDK or HTTP call to an external service from a service | A client in `app/integrations/` |
| An agent reaching a service directly | A registered tool |

---

## Backend conventions

**Async everywhere.** `async def` all the way down. A blocking SDK (the PayPal Server SDK uses `requests`) runs in
`asyncio.to_thread`.

**Services take the merchant at construction.**

```python
class AnalyticsService:
    def __init__(self, session: AsyncSession, merchant_id: uuid.UUID) -> None:
        self.session = session
        self.merchant_id = merchant_id
```

**Repositories inherit the scoped base.** `get`, `list_all`, `count`, `exists` and `create` are already filtered. For
a custom query, start from `self.scoped()`; never `select(Model)` directly in a scoped repository.

```python
class CampaignRepository(MerchantScopedRepository[Campaign]):
    model = Campaign

    async def pending_approval(self) -> list[Campaign]:
        stmt = self.scoped().where(Campaign.status == CampaignStatus.PENDING_APPROVAL)
        return list((await self.session.scalars(stmt)).all())
```

**Handlers declare permissions and return the envelope.**

```python
@router.post("/campaigns/{campaign_id}/execute")
async def execute_campaign(
    campaign_id: uuid.UUID,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.CAMPAIGN_EXECUTE)),
) -> APIResponse[CampaignDetail]:
    service = CampaignService(session, principal.merchant_id)
    return APIResponse(data=await service.execute(campaign_id, actor=principal))
```

Errors are raised as `AppError` subclasses from [`core/exceptions.py`](../backend/app/core/exceptions.py) and
rendered by the registered handlers; never build an error response by hand.

**Timestamps use `UTCDateTime`**, not `DateTime`, so values are timezone-aware on both Postgres and SQLite.

**Money uses `Decimal`.** Never `float` for an amount, and never sum different currencies.

**Settings come from `settings`.** No module reads `os.environ`. A new setting goes in
[`core/config.py`](../backend/app/core/config.py) and [`.env.example`](../.env.example), and in
[Configuration](CONFIGURATION.md).

**Typing.** Full annotations; `X | None`, `StrEnum`, `Literal` for closed sets.

**Comments explain why.** A comment states the constraint or the bug that made the code this way, not what the next
line does.

---

## Frontend conventions

```
frontend/src/
  app/              App Router pages: (auth), (dashboard), shop
  components/ui/    shadcn/ui primitives and motion helpers
  components/*/     feature components by domain
  hooks/            TanStack Query hooks
  lib/api/          the single Axios client and endpoint wrappers
  stores/           Zustand: session and small UI state
  types/            wire types mirroring the backend schemas
```

**One HTTP client.** Everything goes through [`lib/api/client.ts`](../frontend/src/lib/api/client.ts), which owns
the base URL, the envelope unwrap, the in-memory access token, and a shared refresh-once-then-retry so concurrent
401s produce one refresh. Do not call `fetch` directly or create a second Axios instance.

**Server state is TanStack Query; session state is Zustand.** Anything from the API belongs in a query hook with a
consistent key.

**The access token never touches storage.** Not `localStorage`, not `sessionStorage`, not a readable cookie.

**Permission gating is a courtesy.** `useAuthStore().can("payment:execute")` hides a button the backend would refuse
anyway.

**Motion respects the user.** Animation helpers in [`components/ui/motion.tsx`](../frontend/src/components/ui/motion.tsx)
check `useReducedMotion`; use them rather than `framer-motion` directly.

**Pinned component versions.** AG Grid must match the version AG Studio requires, and every `@bryntum/*` package must
share one exact version and tier. See [Integrations](INTEGRATIONS.md).

---

## Adding a feature end to end

Worked example: exposing a new metric.

1. **Repository:** the scoped query in `app/repositories/`.
2. **Service:** the computation in `app/services/<domain>/`, taking the merchant at construction. If it produces a
   number a merchant may act on, it is computed here, not by a model.
3. **Schema:** the response model in `app/schemas/`.
4. **Route:** a thin handler in `app/api/v1/` with `require_permission(...)`. Use an existing permission if one fits;
   a new one goes in [`core/permissions.py`](../backend/app/core/permissions.py) with a description and role grants
   (a test fails if a permission belongs to no role).
5. **Tool (if an agent should see it):** register it in `app/tools/` with a permission and add it to the right
   allow-list. See [Agents: extending the agent layer](AGENTS.md#extending-the-agent-layer).
6. **Frontend:** a type in `types/`, an endpoint wrapper in `lib/api/`, a query hook in `hooks/`, then the component.
7. **Tests:** a permission test, an isolation test with `outsider_headers`, and a tool-authorization test if you
   added a tool. See [Testing: writing tests](TESTING.md#writing-tests).
8. **Spec:** `python scripts/export_openapi.py` to refresh [`docs/openapi.json`](openapi.json), and update
   [API reference](API.md).

---

## Database changes

```bash
# 1. Edit the model in app/db/models/
make migration MSG="add supplier ratings"     # 2. autogenerate
# 3. Read the generated file in backend/alembic/versions/
make migrate                                   # 4. apply
make test-backend                              # 5. the suite builds the schema from the models
```

Autogenerate is a first draft: it misses data migrations, can mis-detect renames and occasionally proposes a drop.
Use the portable types from `app.db.types`, guard Postgres-only statements (extensions, HNSW indexes) by dialect, and
keep migrations additive where possible.

---

## Changing the demo dataset

After any edit under `app/seed/generators/`:

```bash
make calibrate        # read the figures before re-seeding
make seed-reset       # rebuild the demo tenant
```

Tests check correctness; calibration checks that the dataset still tells the intended story. See
[Data: calibration](DATA.md#calibration).

---

## Before you open a pull request

```bash
make verify           # ruff + next lint, tsc (+ advisory mypy), pytest + vitest
make build            # backend import check + next build
```

* The project rules above still hold.
* New settings are in `config.py`, `.env.example` and [Configuration](CONFIGURATION.md).
* New endpoints have a permission, a test, and a row in [API reference](API.md).
* New integrations have a labelled fallback and appear in `GET /integrations/status` and [Integrations](INTEGRATIONS.md).
* Docs that describe the change are updated in the same pull request.

Commit messages: imperative subject under about 72 characters (`feat: add supplier delivery delays`), with a body that
explains why when it is not obvious.

---

<div align="center">

[Previous: Testing](TESTING.md) | [Docs index](README.md) | [Next: Troubleshooting](TROUBLESHOOTING.md)

</div>
