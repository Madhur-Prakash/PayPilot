<div align="center">

# PayPilot

### The AI operating system for merchants

**AI Growth Scientist + Agent-to-Agent Supply Network + PayPal financial operations**

PayPal AI Hackathon 2026 · Idea 4 (Growth Autopilot) + Idea 5 (Supply Agents) · Team PayFlux

[![Tests](https://img.shields.io/badge/backend_tests-288_passing-16a34a?style=flat-square&logo=pytest&logoColor=white)](docs/TESTING.md)
[![Lint](https://img.shields.io/badge/ruff-clean-16a34a?style=flat-square&logo=ruff&logoColor=white)](docs/CONTRIBUTING.md)
[![Types](https://img.shields.io/badge/typecheck-clean-16a34a?style=flat-square&logo=typescript&logoColor=white)](docs/CONTRIBUTING.md)
[![PayPal](https://img.shields.io/badge/PayPal-Orders_v2_·_Invoicing_·_Payouts_·_Subscriptions_·_Webhooks-003087?style=flat-square&logo=paypal&logoColor=white)](docs/PAYPAL.md)
[![License](https://img.shields.io/badge/license-MIT-475569?style=flat-square)](LICENSE)

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL_16_+_pgvector-4169E1?style=flat-square&logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector)
[![LangGraph](https://img.shields.io/badge/LangGraph-1C3C3C?style=flat-square&logo=langchain&logoColor=white)](https://langchain-ai.github.io/langgraph/)
[![Next.js](https://img.shields.io/badge/Next.js_15-000000?style=flat-square&logo=nextdotjs&logoColor=white)](https://nextjs.org)
[![AG Grid](https://img.shields.io/badge/AG_Grid-v36-0f172a?style=flat-square)](https://www.ag-grid.com)

**[Demo (3 min)](docs/DEMO.md)** ·
**[Hackathon notes](docs/HACKATHON.md)** ·
**[PayPal](docs/PAYPAL.md)** ·
**[Supply Agents](docs/SUPPLY_AGENTS.md)** ·
**[Architecture](docs/ARCHITECTURE.md)** ·
**[All docs](docs/README.md)**

</div>

---

> **PayPilot doesn't just tell merchants what happened. It helps them decide what
> to do next, coordinates the agents that execute it, and measures the impact on
> their business.**

## The problem

Small merchants run on thin margins and little time. They can see last week's
sales, but not *why* they moved or what to do about it. When a product suddenly
sells, they find out it is out of stock after the fact; sourcing more means
emailing suppliers, chasing quotes, haggling and reconciling invoices by hand -
and every purchase quietly changes the margin their growth decisions assume.
Automating any of this is risky, because the steps that matter move money.

## What PayPilot does

One product connects three layers:

| Layer | Loop |
| --- | --- |
| **Growth Intelligence** | Observe -> diagnose -> hypothesize -> recommend -> **approve** -> act -> measure (controlled experiment) -> learn |
| **Procurement Intelligence** | Detect demand -> stock need -> discover suppliers -> RFQ -> **agent-to-agent negotiation** -> evaluate -> **approve** -> PO -> invoice -> receive -> match -> **approve payment** -> PayPal -> reconcile -> learn |
| **Unified intelligence** | Shared events, memory and financial data: demand drives procurement, procurement cost drives margin, inventory shapes campaigns, supplier outcomes shape future sourcing |

**Who it's for:** independent merchants who sell in person and online through
PayPal - the demo is *Juniper & Oak Coffee*, a Portland coffee shop with an online
bean store - and the staff roles around them (Owner, Admin, Analyst, Staff, Viewer).

## The signature scenario

1. Growth Intelligence sees online demand for **Premium Coffee Beans** up **+71%**
   (7 -> 12 bags/day) and flags *"Capture rising demand"*.
2. Inventory Intelligence: **42 bags, 3.5 days of cover**, 3-day lead time ->
   procure **150**, needed within **3 days**.
3. The deterministic engine sets the limits **before any agent speaks**:
   `$18.00 × (1 − 40%) = $10.80` max landed per bag, **$1,620** budget.
4. The Buyer Agent sends an RFQ to **three independent supplier agents** - each
   with private pricing, stock, delivery and negotiation behaviour.
5. They negotiate over multiple rounds through **signed, typed protocol
   messages**; every offer is validated by the backend.
6. Evaluation recommends **Cascadia Coffee Collective - $1,455.00 landed**,
   **$248.77** below the best opening quote. Pacific Bean Exchange is excluded
   (9-day delivery, only 90 bags).
7. An **Analyst** tries to approve -> **403**. The **Owner** approves the exact,
   hash-bound terms.
8. A purchase order is issued; the supplier agent invoices.
9. **Partial receipt** (100 of 150) -> the three-way match holds payment.
   The rest arrives -> match clears -> **payment approval**.
10. **PayPal Orders v2** pays the supplier (simulated without keys, sandbox with keys).
11. Reconciliation: PO × receipt × invoice × capture agree to the cent; inventory
    revalued to **$10.12/bag**; product margin **35.6% -> 43.8%**; supplier
    reliability updated; the Command Center reflects it all.

Walkthrough: **[docs/DEMO.md](docs/DEMO.md)**.

## Non-negotiables, enforced in code

1. **No AI arithmetic.** Every amount comes from a `Decimal` engine
   ([`services/supply/policy.py`](backend/app/services/supply/policy.py)) or SQL. An
   LLM may propose a counter-offer; out-of-bounds proposals are refused, not clamped.
2. **Humans approve money movement** - Owners included. Agents can request,
   never approve; the agent tools for approving or paying always refuse.
3. **Approvals bind to exact terms** (SHA-256 of the canonical details, policy
   version). Any change invalidates the approval, durably.
4. **Idempotent payments.** `PayPal-Request-Id` / `sender_batch_id` derived from
   the business action; one live execution per invoice.
5. **Verified webhooks only.** PayPal's verify-webhook-signature first; event id
   as replay guard; unverified events stored as rejected and never acted on.
6. **Signed agent messages.** Per-agent HMAC, schema validation, sender roles,
   freshness, nonce/idempotency replay protection, tenant isolation.
7. **Tenant isolation is structural** - merchant from membership, every query scoped.
8. **Nothing simulated is presented as real** - `SIMULATED` / `SANDBOX` / `LIVE`
   on every PayPal row and badge; simulated supplier agents are labelled.
9. **Correlation is not causation** - the Growth Graph only uses
   `decomposes_into`, `correlates_with`, `evidenced_by`.

Details: [docs/SECURITY.md](docs/SECURITY.md) · [docs/SUPPLY_AGENTS.md](docs/SUPPLY_AGENTS.md).

## PayPal APIs used

| API | Used for |
| --- | --- |
| OAuth 2.0 client credentials | Cached, auto-refreshed tokens (server-side only) |
| Transaction Search | Incremental sync in <=31-day windows -> transaction intelligence (gross/net, fees, refunds, failures, repeat payers) |
| Orders v2 (+ Payments v2 authorizations) | Supplier invoice settlement, payee = supplier |
| Invoicing v2 | Merchant -> customer invoices with reminders and cancellation |
| Payouts | Cashback rewards - approval-gated; never used for supplier settlement |
| Catalog / Plans / Subscriptions | Plans, lifecycle actions, failed-payment recovery |
| Webhooks (verify-webhook-signature) | Captures, refunds, payouts, invoices, subscription events |

Without credentials everything runs against a deterministic simulator with `SIM-`
identifiers. See **[docs/PAYPAL.md](docs/PAYPAL.md)**.

## AI and services

| | |
| --- | --- |
| **LangGraph** | Growth workflow and procurement workflow; both terminate at the approval gate |
| **Groq GPT-OSS** (`openai/gpt-oss-120b`) | Optional: explanations, intent routing, buyer-agent negotiation strategist |
| **pgvector** | Agent long-term memory (HNSW cosine) and semantic review search |
| **Langfuse** | Optional traces for agent runs and tool calls |
| **Vapi** | Optional voice assistant (growth, supply, approvals, PayPal - read-only) |
| **n8n** | Event routing from the transactional outbox |

**Runs without any key**: every graph node has a deterministic path; runs are
labelled *Deterministic mode*.

## Sponsor tools actually used

* **AG Grid Community** - transactions, quote comparison, invoices, receipts,
  reconciliations, payments, RFQs.
* **Render** - complete Blueprint (`render.yaml`: API, web, worker, Postgres);
  not deployed from this environment.
* **Postman** - [`postman/PayPilot.postman_collection.json`](postman/PayPilot.postman_collection.json)
  walks the whole signature scenario.

Not used, so not claimed: APIMatic, AG Studio, Bryntum, Elastic, PayPal Agent
Toolkit/MCP at runtime ([why](docs/PAYPAL.md#agent-toolkit-and-mcp)).

## Architecture

```
Next.js 15 (React 19, TypeScript, Tailwind, shadcn/ui, TanStack Query, AG Grid, Recharts)
   │  one Axios client · polling + WebSocket hub
   ▼
FastAPI (Pydantic v2) ── auth → merchant scope → require_permission
   │
   ├─ Growth: analytics · Growth Graph · opportunities (+ supply-aware) · campaigns · experiments
   ├─ Supply: inventory intelligence · supplier agents · buyer agent · negotiation · evaluation
   │          · approvals · PO · receiving · three-way match · reconciliation
   ├─ Finance: PayPal gateway (client | simulator) · sync · webhooks · invoices · payouts · subscriptions
   ├─ Governance: approval inbox · audit log · RBAC (51 permissions, 5 roles)
   ├─ Agents: LangGraph (growth + procurement) · 36-tool registry · signed agent protocol
   └─ Unified events (transactional outbox) ──► n8n / worker / WebSocket
   ▼
PostgreSQL 16 + pgvector (56 tables) · SQLAlchemy 2 · Alembic
```

148 API endpoints · 56 tables · 36 agent tools · 51 permissions · 44 dashboard screens.

## Getting started

Requires **Python 3.11-3.14**, **Node 20+**, **Git**, and **Docker** (for the
local Postgres; or bring your own Postgres 16 with `vector`).

```bash
make init     # tools check -> .env (never overwritten) -> deps -> Postgres -> migrations -> demo seed
make dev      # backend http://localhost:8000 (docs at /docs) + frontend http://localhost:3000
```

Windows PowerShell without Make:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

### Demo credentials

| Role | Email | Can |
| --- | --- | --- |
| Owner | `owner@juniperoak.com` | Everything, including users |
| Admin | `admin@juniperoak.com` | Approve purchases and payments, execute |
| Analyst | `analyst@juniperoak.com` | Source and negotiate - **cannot** approve or pay |
| Staff | `staff@juniperoak.com` | Receive goods, inventory actions |
| Viewer | `viewer@juniperoak.com` | Read only |

Password for all: `Autopilot@2024`.

### Commands

```bash
make help        # every target
make check       # tools, versions, .env, PayPal/LLM mode
make test        # backend pytest (SQLite, no Docker) + frontend vitest
make lint        # ruff + next lint
make typecheck   # tsc (+ advisory mypy)
make build       # backend import check + next build
make docker-up   # Postgres (FULL=1 for the whole stack)
make migrate     # alembic upgrade head
make seed        # idempotent demo seed   ·   make seed-reset to rebuild it
make reset-db    # DESTRUCTIVE - requires CONFIRM=yes
make clean       # caches and build output only
```

### Configuration

One `.env` at the repository root (created by `make env` from `.env.example`;
the copy works as-is). Key settings:

| Variable | Purpose |
| --- | --- |
| `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_ENVIRONMENT` | Sandbox/live PayPal; blank = simulator |
| `PAYPAL_WEBHOOK_ID` | Required to accept real webhooks |
| `PAYPAL_SANDBOX_PAYEE_EMAIL` | Sandbox business account used as supplier payee |
| `GROQ_API_KEY` | Optional LLM; blank = deterministic mode |
| `PROCUREMENT_*` | Negotiation rounds, quote TTL, default margin, matching tolerances |
| `MEMORY_ENABLED` | pgvector agent memory (on by default) |

Full reference: [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

## Testing

```bash
make test-backend    # 288 tests: unit, integration, API - SQLite, no Docker, no keys
make test-frontend   # vitest
```

Highlights: the financial engine (Decimal limits, tampered totals), the agent
protocol (bad signatures, cross-tenant, stale, schema violations, replays), the
PayPal client against mocked PayPal responses (token refresh, retries,
idempotency, 31-day windows, webhook verification), the simulator, approval
invalidation, RBAC denials, tenant isolation, pgvector memory isolation, and the
**end-to-end procurement lifecycle through the real API**.

## Deployment

`render.yaml` deploys Postgres, the API (Docker), the web app and a background
worker on Render; secrets are prompted (leave blank for the keyless demo). See
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md#render-blueprint). Docker Compose runs
the same stack locally: `make docker-up FULL=1`.

## What we built during the hackathon

PayPilot started as our "Growth Autopilot" from a previous hackathon (growth
analytics, Growth Graph, opportunities, campaigns, experiments, inventory
automation, vendors/POs, RBAC, LangGraph agents, voice). **After October 1,
2026** we added:

* the **PayPal integration layer** (client + simulator, transaction sync and
  intelligence, Orders v2 settlement, invoicing, payouts, subscriptions,
  verified webhooks, reconciliation);
* the **Supply Agents network** (Inventory Intelligence, three independent
  supplier agents, the Buyer Agent, multi-round negotiation, deterministic
  evaluation, the procurement LangGraph workflow);
* the **signed agent-to-agent protocol**;
* the **deterministic financial and negotiation engine**;
* the **full procurement lifecycle** (hash-bound approvals, POs, invoices,
  partial receiving, three-way matching, PayPal payment, reconciliation,
  supplier learning);
* **unified intelligence** (business events, supply-aware growth opportunities,
  inventory constraints on campaigns, procurement cost -> margin);
* the **Approval Center**, 13 new permissions, **pgvector memory** (replacing an
  external memory library), **19 new screens** with AG Grid, US localization,
  `make init` + cross-platform scripts, Render Blueprint, Postman collection and
  **80 new tests**.

Full breakdown: [docs/HACKATHON.md](docs/HACKATHON.md).

## Known limitations

* No PayPal credentials were available while building: PayPal paths are verified
  against the simulator and mocked PayPal responses; follow
  [docs/PAYPAL.md](docs/PAYPAL.md#using-the-sandbox) to run against the sandbox.
* Supplier agents in the demo are simulated policy engines (labelled as such);
  external agents can connect through the signed inbound endpoint.
* Analytics run on a seeded demo dataset; synced PayPal transactions are shown
  separately with their mode.
* Sandbox supplier payments need a payer approval in PayPal before capture.
* Not done from this environment: Render deployment, demo video, Devpost submission.

## Project layout

```
backend/app/
  api/v1/            auth · dashboard · growth · campaigns · agents · inventory · supply · approvals
                     · paypal · intelligence · memory · voice · admin
  services/          analytics · growth · campaigns · experiments · inventory
                     · supply (policy, demand, protocol, supplier/buyer agents, negotiation,
                       evaluation, approvals, lifecycle) · paypal (sync, webhooks, finance)
                     · intelligence (events, unified)
  integrations/      paypal (client, simulator, gateway) · vector_memory · groq · langfuse · vapi
  agents/            growth graph · procurement_graph · orchestrator · memory narratives
  tools/             36-tool registry (incl. supply, PayPal, memory)
  db/models/         … · supply · governance · paypal · memory
  seed/              deterministic demo (US merchant) + supply network
frontend/src/app/(dashboard)/
  command · supply/* · approvals · finance/* · agents/communication · (growth screens) · …
scripts/             tasks.py (cross-platform) · setup/dev/check (.ps1 + .sh)
postman/             PayPilot.postman_collection.json
render.yaml · docker-compose.yml · Makefile · .env.example
```

## License

MIT - see [LICENSE](LICENSE).
