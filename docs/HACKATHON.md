# PayPal AI Hackathon 2026 - submission notes

[Back to docs](README.md)

## What PayPilot is

An AI operating system for small merchants that combines **Idea 4 - Growth
Autopilot for PayPal merchants** and **Idea 5 - Supply Agents** into one product:
an AI Growth Scientist that finds and measures revenue opportunities, an
agent-to-agent procurement network that sources and negotiates stock, and PayPal
financial operations (transaction intelligence, invoicing, payouts, supplier
settlement, webhooks, reconciliation) - with a human approving every money
movement and a deterministic engine computing every figure.

## What we built during the hackathon (after October 1, 2026)

The **starting point** was our earlier "Growth Autopilot" app (built for a
previous hackathon in India): growth analytics, the Growth Graph, opportunity
detection, campaigns and controlled experiments, inventory with automated
reorders, vendors and purchase orders, RBAC, LangGraph agents, Langfuse tracing,
a voice assistant, and n8n automation.

**New in this hackathon:**

| Area | What was added |
| --- | --- |
| PayPal | A real REST client (OAuth caching/refresh, retries, idempotency keys, debug ids) for Transaction Search, Orders v2, Payments v2 authorizations, Invoicing v2, Payouts, Catalog/Plans/Subscriptions and webhook verification; a deterministic labelled simulator; incremental 31-day-window transaction sync with checkpoints; transaction intelligence; verified, idempotent webhook processing; customer invoices; approval-gated cashback payouts; subscription recovery |
| Supply Agents | Inventory Intelligence (velocity, cover, stockout risk, reorder quantity); three independent supplier agents with private policies; a Buyer Agent; multi-round negotiation with backend-validated offers and optional LLM proposals that are bounds-checked; deterministic supplier scoring; a LangGraph procurement workflow that stops at the approval gate |
| Agent protocol | Typed, schema-versioned, per-agent HMAC-signed messages; one verification boundary (tenant, identity, signature, freshness, schema, sender role, replay); an inbound endpoint for external agents |
| Financial engine | `Decimal`-only limits (`price × (1 − margin)`), landed cost, budget, savings, invoice variance, weighted-average cost; offer validation that catches tampered totals |
| Procurement lifecycle | Hash-bound purchase approvals (invalidated on any change), PO creation, supplier invoices, partial goods receipts, three-way matching with tolerances, payment approval, PayPal Orders v2 settlement, reconciliation, inventory revaluation, supplier performance learning |
| Unified intelligence | Cross-module business events on the transactional outbox; supply-aware growth opportunities; inventory constraints on campaign recommendations; procurement cost -> product margin; a unified Command Center |
| Governance | A unified Approval Center; 13 new permissions (procurement, payment, PayPal, approvals, events); new audit actions; agent tools that refuse to approve or pay |
| Memory | Replaced the external memory library with pgvector-native memory (HNSW cosine index, tenant isolation in SQL, entity tags, no LLM or API key required) |
| Frontend | 19 new screens: Command Center, Supply Command Center, Reorder, Supplier Network + profiles, RFQ Management, Live Negotiations + the Negotiation Workspace, Quote Comparison, Goods Receiving, Supplier Invoices, Reconciliation, Approval Center, Agent Communication, PayPal Transactions, Payments, Payouts, Invoices, Subscriptions, Webhooks; navigation regrouped into Command / Growth / Supply / Agents / Finance / Governance; AG Grid for data-heavy tables |
| Localization | US merchant (Juniper & Oak Coffee, Portland), USD everywhere, US names, PayPal spelling; Paytm-specific "PayPal-side audience" logic reframed to PayPal-powered levers the merchant controls |
| Tooling | `make init` and a cross-platform task runner (`scripts/tasks.py`) behind Make, PowerShell and bash; Render Blueprint (API, web, Postgres, Key Value, n8n, docs portal); worker in Docker Compose; Postman collection; Vitest |
| Redis | Render Key Value behind one seam (`app/core/redis.py`): shared HTTP rate-limit counters, the per-merchant Channel3 budget, Channel3 caches that survive free-plan sleeps and deploys, and realtime pub/sub between API processes - with a circuit breaker that falls back to in-process state, so Redis is never a hard dependency |
| n8n on Render | The automation engine defined for the free plan: state in the free Postgres, workflows rebuilt from the repo at boot, a generated shared HMAC secret, and a health workflow (`/webhook/pga-health`) an external monitor can poll |
| Tests | **515 backend tests** (financial engine, protocol security, PayPal client + simulator, PayPal APIs, pgvector memory, the Redis layer, the end-to-end procurement lifecycle) plus frontend unit tests |

## AI and tools actually used

| Tool | How |
| --- | --- |
| LangGraph | Growth workflow and the new procurement workflow (both end at the approval gate) |
| Groq / GPT-OSS (`openai/gpt-oss-120b`, fallback `-20b`) | Optional: growth narration, intent routing, and the buyer-agent negotiation strategist (proposals are bounds-checked by the backend) |
| pgvector | Agent long-term memory and semantic review search |
| Langfuse | Optional tracing of agent runs and tool calls |
| Vapi | Optional voice assistant (now with supply/approval/PayPal read tools) |
| n8n | Event routing from the transactional outbox (never financial logic) |
| AG Grid Community (v36) | Data grids for transactions, quotes, invoices, receipts, reconciliations, payments |
| AG Studio | Dashboard Studio - pre-built and merchant-built dashboards over backend-computed datasets, plus Studio's AI agent harness running on PayPilot's LLM via an `AgLlmAdapter` (evaluation mode; full agent runs need a paid Groq tier) |
| Bryntum Gantt + Scheduler | Procurement timeline of the real RFQ -> payment stages, rescheduled when a supplier agent reports a delay (signed `DELIVERY_UPDATE`); subscription revenue radar on Scheduler (Bryntum 8.0 Enterprise, licence key via `NEXT_PUBLIC_BRYNTUM_LICENSE_KEY`) |
| PayPal Agent Toolkit (MCP) | Read-only bridge through PayPilot's tool registry; write tools blocked in code |
| Channel3 | Gear shelf of live complementary products with affiliate links, and a market price reference beside a purchase (labelled fallback without a key) |
| Elasticsearch | Evidence search across audit, messages, offers, invoices, events, reviews (keyword fallback without a node) |
| Kernel | Observe-only supplier-page verification sessions (labelled fallback without a key) |
| Zapier | Signed, at-most-once business-event notifications |
| Render | Deployed from one Blueprint (`render.yaml`), free plan: API (Docker), web, Postgres + pgvector, **Key Value (Redis)**, n8n and the APIMatic docs portal. Details: [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md#render) |
| Postman | `postman/PayPilot.postman_collection.json` + environment (59 requests with assertions) |
| APIMatic | Supplier payments (Orders v2) on PayPal's APIMatic-generated Server SDK, written with the PayPal Context Plugin; PayPilot's own spec, guides and portal config in `apimatic/` |
| Claude Code | Coding assistant used to build the upgrade |

**Not used** (so not claimed): Astropods.
Full, per-tool detail with what was and was not verified: [SPONSORS.md](SPONSORS.md).

## For judges

Start with **[PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)**: why PayPal is central, how every sponsor tool is used,
the key features, and the judging criteria mapped to evidence.

### Testing without keys

```bash
git clone <repo> && cd PayPilot-Paypal
make init          # checks tools, creates .env, installs deps, starts Postgres (Docker), migrates, seeds
make dev           # http://localhost:3000
```

No Docker? `make init` still installs everything; point `DATABASE_URL` at any
Postgres 16 with the `vector` extension, then `make migrate seed`. The test suite
needs neither Docker nor keys: `make test`.

Then follow [DEMO.md](DEMO.md) - the full scenario takes three minutes. What to
look for:

1. A deterministic limit computed before any agent speaks (`$18 × (1 − 40%) = $10.80`).
2. Three supplier agents negotiating with real, persisted, signed messages.
3. Every offer labelled with the backend's verdict; AI proposals shown separately.
4. An Analyst denied with HTTP 403; an Owner approving exact, hash-bound terms.
5. A partial receipt holding payment; a full receipt releasing it.
6. A PayPal Orders v2 payment (labelled *Simulated* without credentials), reconciled to the cent.
7. Inventory revalued and product margin up, visible back in the Command Center.

## Compliance checklist

* Working application - backend, frontend, seed data, tests and builds all run.
* Meaningful PayPal use - PayPal is the merchant's data source and the only payment rail:
  transaction analytics, supplier settlement, invoicing, payouts, subscriptions, verified
  webhooks, reconciliation ([PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md#2-why-paypal-is-central-not-decoration)).
* Meaningful AI use - agent orchestration, negotiation strategy, growth diagnosis,
  recommendations, semantic memory.
* Runs without judges' keys - deterministic agents, simulated PayPal, clearly labelled.
* Hosted demo - <https://paypilot-web-0lqv.onrender.com>; PayPal **sandbox**, Channel3 **live**, LLM configured.
* Open-source licence - MIT ([LICENSE](../LICENSE)).
* No committed secrets - `.env` is gitignored; `.env.example` has blank secrets.
* Team to-do before submitting: record the demo video and submit on Devpost.
