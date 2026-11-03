<div align="center">

# PayPilot

### An AI Growth Scientist for every merchant

**Team PayFlux**

[![Status](https://img.shields.io/badge/status-working_demo-16a34a?style=flat-square)](docs/DEMO.md)
[![Tests](https://img.shields.io/badge/tests-208_passing-16a34a?style=flat-square&logo=pytest&logoColor=white)](docs/TESTING.md)
[![Lint](https://img.shields.io/badge/ruff-clean-16a34a?style=flat-square&logo=ruff&logoColor=white)](docs/CONTRIBUTING.md)
[![Types](https://img.shields.io/badge/typecheck-clean-16a34a?style=flat-square&logo=typescript&logoColor=white)](docs/CONTRIBUTING.md)
[![License](https://img.shields.io/badge/license-MIT-475569?style=flat-square)](LICENSE)

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.141-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=flat-square&logo=postgresql&logoColor=white)](https://www.postgresql.org)
[![pgvector](https://img.shields.io/badge/pgvector-0.8-4169E1?style=flat-square&logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2-1C3C3C?style=flat-square&logo=langchain&logoColor=white)](https://langchain-ai.github.io/langgraph/)
[![Groq](https://img.shields.io/badge/Groq-GPT--OSS-F55036?style=flat-square&logo=groq&logoColor=white)](https://groq.com)

[![Next.js](https://img.shields.io/badge/Next.js-15.1-000000?style=flat-square&logo=nextdotjs&logoColor=white)](https://nextjs.org)
[![React](https://img.shields.io/badge/React-19-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.7-3178C6?style=flat-square&logo=typescript&logoColor=white)](https://www.typescriptlang.org)
[![Tailwind](https://img.shields.io/badge/Tailwind-3.4-06B6D4?style=flat-square&logo=tailwindcss&logoColor=white)](https://tailwindcss.com)
[![shadcn/ui](https://img.shields.io/badge/shadcn%2Fui-components-000000?style=flat-square&logo=shadcnui&logoColor=white)](https://ui.shadcn.com)
[![Docker](https://img.shields.io/badge/Docker-compose-2496ED?style=flat-square&logo=docker&logoColor=white)](docs/DEPLOYMENT.md)

**[Install](docs/INSTALLATION.md)** &nbsp;·&nbsp;
**[Configure](docs/CONFIGURATION.md)** &nbsp;·&nbsp;
**[Deploy](docs/DEPLOYMENT.md)** &nbsp;·&nbsp;
**[Architecture](docs/ARCHITECTURE.md)** &nbsp;·&nbsp;
**[API](docs/API.md)** &nbsp;·&nbsp;
**[Demo script](docs/DEMO.md)** &nbsp;·&nbsp;
**[All docs](docs/README.md)**

</div>

---

Most merchant analytics tools show you what happened. This one runs the whole loop:

```
Observe  ->  Diagnose  ->  Hypothesize  ->  Recommend  ->  Act  ->  Measure  ->  Learn
```

It finds a growth opportunity, quantifies it in rupees, shows the evidence behind
it, proposes a specific intervention, waits for your approval, runs it as a
controlled experiment against a held-out control group, measures the lift, and
tells you whether to **SCALE** or **STOP**.

---

## Table of contents

| Section | |
| --- | --- |
| [What it actually does](#what-it-actually-does) | The demo story, with real numbers |
| [Five rules this codebase enforces](#five-rules-this-codebase-enforces) | And where each is enforced |
| [It runs with no API keys](#it-runs-with-no-api-keys) | Deterministic fallback path |
| [Quick start](#quick-start) | Three commands |
| [Architecture at a glance](#architecture-at-a-glance) | Layers and the agent graph |
| [The screens](#the-screens) | All 24 dashboard routes |
| [Project layout](#project-layout) | Where things live |
| [Commands](#commands) | The Makefile |
| [Documentation](#documentation) | Full index |
| [Team](#team) | PayFlux |

---

## What it actually does

Sign in as the demo merchant (Sharma Cafe) and the Growth Command Center shows:

| Metric | Value | Change |
| --- | --- | --- |
| Revenue | Rs 4.94L | **-12.9%** |
| Orders | 2,353 | -7.9% |
| Average order value | Rs 210 | -5.5% |
| Repeat rate | 38.3% | -11.8% |

The Growth Graph decomposes that movement:

```
Revenue                       -12.9%
  |- Orders                    -7.9%     decomposes_into   (arithmetic)
  |- AOV                       -5.5%     decomposes_into   (arithmetic)
  `- Repeat customers         -11.8%     correlates_with
       `- EVENING segment     -32.3%     decomposes_into
            `- Evening service time  +25.6%   correlates_with
                 `- Waiting-time complaints  +117%   evidenced_by  (reviews)
```

The Growth Scientist produces a quantified opportunity:

> **Recover lost evening repeat customers** — Rs 14,470/month, 92% confidence
>
> **Hypothesis.** Repeat customers in the evening slot are lapsing faster than
> anywhere else in the business. Average service time in that slot moved +25.6%
> over the same window, and negative review volume for the same slot moved in
> step with it. *These are correlated signals observed over the same period, not
> a demonstrated cause.*
>
> **Recommended.** Run a targeted evening win-back experiment against the lapsed
> segment, with a held-out control group so the lift is measurable.
>
> **Considered and not chosen.** A blanket percentage discount — it cuts margin
> across customers who were never at risk and does not address the signal the
> evidence points to.

Approve it, and the agents execute:

```
Created campaign targeting 578 customers
Created experiment with 285 control / 293 test
Launched campaign (simulated delivery)
Generated the experiment trading window so results are measurable
```

Then the Measurement Agent computes the result from the transaction ledger:

| | |
| --- | --- |
| Control conversion | 8.9% |
| Test conversion | 14.4% |
| Conversion lift | **+61.0%** |
| Incremental revenue | Rs 12,553 |
| Incremental profit | Rs 8,900 |
| ROI | 7.85x |
| Significance | p = 0.042 (two-proportion z-test) |
| **Decision** | **SCALE** |

Full walkthrough: **[docs/DEMO.md](docs/DEMO.md)**

---

## Five rules this codebase enforces

Not aspirations. Each is enforced in code and covered by a test.

### 1. The LLM never calculates a business number

Every financial figure is computed in SQL/Python
([`repositories/transaction.py`](backend/app/repositories/transaction.py),
[`services/analytics/service.py`](backend/app/services/analytics/service.py)).
The model receives a structured fact sheet and reasons over it.

Even when an LLM **is** configured, the orchestrator overwrites
`estimated_impact`, `confidence` and `requires_approval` with the detector's
values before persisting. The model may phrase. It may not price.

### 2. Correlation is never presented as causation

Growth-graph edges are only `decomposes_into`, `correlates_with` or
`evidenced_by`. Every system prompt states the rule.
`test_the_growth_graph_never_claims_causation` asserts the edge set is closed and
that "caused by", "because of" and "is causing" never appear in node
interpretations.

### 3. Humans approve anything that moves money

An agent can create a campaign and an experiment. It cannot approve or launch
one. `CampaignService.execute` raises `APPROVAL_REQUIRED` without a recorded
approval — **even for an Owner**. The `execute_campaign` tool refuses outright
and points at the human approval endpoint.

### 4. Tenant isolation is structural, not remembered

The merchant is resolved from the user's membership, never from a client-supplied
id. A `merchant_id` in the query string is a *request*, honoured only if an active
membership exists. `MerchantScopedRepository` filters on `merchant_id` in `get`,
`list`, `count` and `create`, so a cross-tenant fetch returns *not found* and a
create cannot write into another tenant.

### 5. Seeded and simulated data is labelled as such

Every relevant response carries `ProvenanceMeta`; the UI badges it. Nothing claims
live Paypal transaction access, real customer messaging, or competitor-platform
scraping — because none of that exists here.

Detail: **[docs/SECURITY.md](docs/SECURITY.md)** and
**[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**

---

## It runs with no API keys

With no `GROQ_API_KEY`, no `LANGFUSE_*` and no `VAPI_*`, the dashboard, analytics,
opportunity detection, growth graph, experiments and **the full agent workflow**
still run.

Every graph node has a deterministic fallback, so the figures, the opportunity and
the SCALE/STOP decision are identical either way — only the prose is simpler. Runs
taken that way are flagged `used_fallback: true` and badged "Deterministic mode"
in the UI, rather than passed off as model output.

Add a Groq key and the same workflow gains natural-language phrasing, intent
routing and richer interpretation. See
**[docs/CONFIGURATION.md](docs/CONFIGURATION.md#groq-llm)**.

---

## Quick start

Requires **Docker**, **Python 3.11+**, **Node 20+**. Full guide with
platform-specific notes: **[docs/INSTALLATION.md](docs/INSTALLATION.md)**.

```bash
cp .env.example .env
make setup     # env -> dependencies -> database -> migrations -> seed
make dev       # backend :8000 + frontend :3000
```

Open <http://localhost:3000>.

| Role | Email | Can |
| --- | --- | --- |
| Owner | `owner@sharmacafe.in` | Everything, including user management |
| Admin | `admin@sharmacafe.in` | Approve and execute |
| Analyst | `analyst@sharmacafe.in` | Propose — **cannot** execute |
| Staff | `staff@sharmacafe.in` | Operations, inventory actions |
| Viewer | `viewer@sharmacafe.in` | Read only |

Password for all: `Autopilot@2024`

Sign in as Analyst, then as Owner, and watch the same button disappear while the
same API call returns `403 PERMISSION_DENIED`.

> **Port 8000 already in use?** `make backend PORT=8010`, then set
> `NEXT_PUBLIC_API_URL=http://localhost:8010/api/v1` in the root `.env`.
> More in [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

---

## Architecture at a glance

```
Next.js 15 App Router  (TypeScript, Tailwind, shadcn/ui, Framer Motion, Recharts)
    |   one Axios client - auth, correlation id, envelope unwrap, silent refresh
    |   TanStack Query for server state, Zustand for the session only
    v
FastAPI  (Pydantic v2)
    |   middleware:  request id -> rate limit -> CORS -> security headers
    |   deps:        authenticate -> resolve merchant -> require_permission
    v
Services  ---->  Repositories  ---->  PostgreSQL 16 + pgvector
                 (all tenant-scoped)
    |
    v
LangGraph agents  ---->  Tool registry   typed - authorized - scoped
    |                                    logged - traced - recorded
    |-- Groq (GPT-OSS)   interpretation only, never arithmetic
    |-- Langfuse         traces, generations, tool spans, latency
    `-- Logifyx          structured logging
```

### The agent graph

```
START
  |
  v
intake                     intent classification (LLM, or keyword fallback)
  |
  v
growth_scientist           deterministic metrics + opportunity detection
  |
  |--> review_intelligence       emerging complaints, quoted evidence
  |--> market_intelligence       competitor perception, external signals
  |
  v
synthesize                 evidence -> GrowthRecommendation (schema-validated)
  |
  v
approval_gate              <-- THE GRAPH ENDS HERE for money-moving actions
  |
  v
respond -> END
```

Resuming after approval is **not a path the model can take**. The approval
endpoint — authenticated and permission-checked — drives Action Agent ->
Experiment Agent -> Measurement Agent -> Learning.

Deep dive: **[docs/AGENTS.md](docs/AGENTS.md)** ·
**[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**

---

## The screens

Twenty-four routes, grouped the way the sidebar groups them - around the growth
loop rather than the database schema.

### Observe

| Route | What it is |
| --- | --- |
| `/dashboard` | Command Center: revenue, orders, AOV, repeat rate, anomalies |
| `/growth` | Growth Graph: revenue decomposed to its root causes |

### Diagnose

| Route | What it is |
| --- | --- |
| `/opportunities` | Opportunity constellation, ranked by value. Nodes can be added by hand and dismissed |
| `/reviews` | Topic and sentiment mining, with search, star filters and pagination |
| `/competitors` | Competitive position and comparative ratings |
| `/signals` | External market events, scored against this merchant's revenue exposure |

### Act

| Route | What it is |
| --- | --- |
| `/campaigns` | Drafts, the approval gate, and execution |
| `/experiments` | Test versus control, with a two-proportion significance test |
| `/impact` | Impact Tree: recommendation to action to measurement to learning |

### Understand

| Route | What it is |
| --- | --- |
| `/customers` | RFM segmentation and retention |
| `/products` | Performance and market-basket pairs |
| `/inventory` | Live stock, reorder policy, and the automation that acts on it |
| `/inventory/[id]` | One SKU: position, the reorder decision and its blockers, batches, movements |
| `/inventory/book` | Opening, movements and closing per SKU, with an Excel export |
| `/inventory/ledger` | Every stock movement, filterable by item, type or correlation id |
| `/vendors` | Who the automation can order from, and what each supplies |
| `/purchase-orders` | Raised orders, the approval gate, and goods receiving |
| `/inventory/automation` | Automation Center: every automated run, its steps and its reasoning |

### Agents

| Route | What it is |
| --- | --- |
| `/agents` | Agent activity: tool calls, evidence and decisions |
| `/memory` | What the agents remember. Search it, add to it, erase it |
| `/voice` | Voice Growth Scientist |
| `/observability` | Langfuse traces, token usage and latency per run |
| `/activity` | Audit log: every consequential action, with its actor |
| `/settings` | Merchant, integrations and RBAC |

---

## Project layout

```
.
|-- backend/
|   |-- app/
|   |   |-- api/v1/         auth · dashboard · growth · campaigns · agents · inventory · memory · voice · admin
|   |   |-- core/           config · security · permissions · exceptions · logging · middleware
|   |   |-- db/             session · portable column types · 39 models
|   |   |-- repositories/   all database access, tenant-scoped by construction
|   |   |-- services/       analytics · growth · campaigns · experiments · inventory · reviews · ...
|   |   |-- agents/         LangGraph state, nodes, graph, orchestrator, prompts, memory
|   |   |-- tools/          the 24-tool agent registry
|   |   |-- integrations/   groq · langfuse · vapi · cognee · email · embeddings · external search
|   |   `-- seed/           deterministic demo dataset + calibration harness
|   |-- alembic/            migrations
|   `-- tests/              unit · integration · api   (208 tests)
|-- frontend/
|   `-- src/
|       |-- app/            (auth) and (dashboard) route groups
|       |-- components/     ui · layout · charts · growth · agents · opportunities · inventory · voice
|       |-- lib/api/        the single Axios client + typed endpoints
|       |-- hooks/          React Query hooks
|       `-- stores/         auth session
|-- n8n/                    workflow generator, deploy script, HMAC library
|-- samples/                inventory import demo workbook
|-- docker/                 Postgres init (pgvector, pgcrypto)
|-- docs/                   full documentation
|-- scripts/                verify.sh
|-- docker-compose.yml
|-- Makefile
`-- .env.example
```

By the numbers: **85 API endpoints**, **39 tables**, **24 agent tools**,
**38 permissions** across **5 roles**, **208 tests**, **24 dashboard routes**.

---

## Commands

```bash
make help          # list every target

make setup         # one-shot: env, deps, database, migrations, seed
make dev           # backend + frontend together
make backend       # FastAPI only      (PORT=8010 to override)
make frontend      # Next.js only      (WEB_PORT=3001 to override)

make db            # start Postgres + pgvector
make migrate       # alembic upgrade head
make migration MSG="add x"
make downgrade     # roll back one

make seed          # idempotent
make reseed        # wipe and rebuild the demo tenant
make demo          # database + migrations + fresh seed
make calibrate     # verify the seeded story without a database

make test          # 105 backend tests (SQLite, no Docker needed)
make lint / format / typecheck
make check         # everything CI would run

make docker-up     # the whole stack in containers
make docker-down
make logs
```

---

## Documentation

Start at the **[documentation index](docs/README.md)**.

### Getting running

| Document | What it covers |
| --- | --- |
| [Installation](docs/INSTALLATION.md) | Prerequisites, platform notes, step-by-step, verification |
| [Configuration](docs/CONFIGURATION.md) | Every environment variable; Groq, Langfuse, Vapi, Supabase setup |
| [Deployment](docs/DEPLOYMENT.md) | Docker Compose, managed Postgres, cloud platforms, hardening |
| [Troubleshooting](docs/TROUBLESHOOTING.md) | Symptoms, causes, fixes |

### Understanding it

| Document | What it covers |
| --- | --- |
| [Architecture](docs/ARCHITECTURE.md) | Layering, the rules, data model, observability, bugs the tests caught |
| [Agents](docs/AGENTS.md) | The seven agents, the graph, the tool registry, LLM failure handling |
| [Agent memory](docs/MEMORY.md) | What the agents remember, how tenants stay isolated, cognee setup |
| [Inventory automation](n8n/README.md) | The outbox relay, the n8n workflows, and what actually triggers them |
| [Security](docs/SECURITY.md) | Auth, RBAC, tenant isolation, approval gates, audit logging |
| [Data](docs/DATA.md) | How the demo dataset is generated and why it reproduces exactly |

### Using it

| Document | What it covers |
| --- | --- |
| [API reference](docs/API.md) | Every endpoint, envelopes, error codes, permission matrix |
| [Demo script](docs/DEMO.md) | Five-minute walkthrough with the exact numbers |
| [Testing](docs/TESTING.md) | What is tested, how to run it, how to add to it |
| [Contributing](docs/CONTRIBUTING.md) | Conventions, workflow, adding a feature end to end |

Interactive API docs are served by the running backend at
<http://localhost:8000/docs> (Swagger), `/redoc`, and `/openapi.json`.

---

## Demo data

`Sharma Cafe`, Pune. Deterministic from seed `20240917`:

- 8 products, 1,700 customers, ~14,800 transactions across 180 days
- ~2,475 reviews, 3 competitors with ~495 seeded reviews
- 2 completed historical experiments — one SCALE, one STOP

The business story is **discoverable, never asserted**. No code says "the answer
is waiting time". Evening regulars churn on staggered days, their baskets shrink,
service times drift up, and reviews are generated *from the orders they describe*
— so complaint volume rises on its own. The analytics layer surfaces the
correlations and the agent reasons over them.

Verify without a database:

```bash
make calibrate
```

Details: **[docs/DATA.md](docs/DATA.md)**

---

## Testing

```bash
make test
```

208 tests on SQLite, so they need no Docker. The portable column types in
[`db/types.py`](backend/app/db/types.py) let the same models run on both engines.

The suite is weighted toward what the system must **refuse** to do — cross-tenant
reads, unauthorised writes, execution without approval, refresh-token replay.
Three real bugs were found and fixed by writing it; they are documented in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#8-bugs-the-tests-caught).

Full breakdown: **[docs/TESTING.md](docs/TESTING.md)**

---

## Production considerations

Honest about what is and is not production-ready.

**Ready.** Argon2id hashing, rotating refresh tokens with family revocation on
replay, server-side RBAC, structural tenant isolation, Alembic migrations,
structured logging with secret redaction, audit logging that survives a
rolled-back request, request ids, security headers, schema-validated LLM output
with bounded retries and fallbacks.

**Before real traffic.** Rate limiting is in-process — move the counter to Redis
for multi-worker deployments. Analytics are computed per request — add a cache or
materialised rollups. Campaign delivery is simulated — a real channel is a new
adapter behind `CampaignService`. Add refresh-token cleanup, password-reset email
delivery and 2FA. Set `REFRESH_COOKIE_SECURE=true` and a real `JWT_SECRET`.

**Deliberately not built.** The ML pricing/demand model — excluded from this stage
by the brief. `OpportunityKind.PRICING` is the extension point.

Checklist: **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md#production-checklist)**

---

## Team

<div align="center">

### PayFlux

| | |
| :--: | :--: |
| [![Bhanvi Nayer](https://img.shields.io/badge/Bhanvi_Nayer-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/bhanvinayer) | [![Madhur Prakash Mangal](https://img.shields.io/badge/Madhur_Prakash_Mangal-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/Madhur-Prakash) |
| [github.com/bhanvinayer](https://github.com/bhanvinayer) | [github.com/Madhur-Prakash](https://github.com/Madhur-Prakash) |

</div>

---

## License

[MIT](LICENSE). All demo data is fictional.
