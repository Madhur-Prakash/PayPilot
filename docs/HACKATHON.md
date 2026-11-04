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
| Tooling | `make init` and a cross-platform task runner (`scripts/tasks.py`) behind Make, PowerShell and bash; Render Blueprint; background worker; Postman collection; Vitest |
| Tests | 80 new backend tests (financial engine, protocol security, PayPal client + simulator, PayPal APIs, pgvector memory, the end-to-end procurement lifecycle) - **288 passing** in total - plus frontend unit tests |

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
| Render | Deployment Blueprint (`render.yaml`) prepared; not deployed from this environment |
| Postman | `postman/PayPilot.postman_collection.json` |
| Claude Code | Coding assistant used to build the upgrade |

**Not used** (so not claimed): APIMatic Context Plugin, the PayPal AI Toolkit
build-time assistant, AG Studio / the Studio Agent Framework (AG Grid Community is
used instead), Bryntum, Elastic, PayPal Agent Toolkit / MCP at runtime (evaluated
- see [PAYPAL.md](PAYPAL.md#agent-toolkit-and-mcp)).

## For judges: testing without keys

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
* Meaningful PayPal use - transaction analytics, invoicing, payouts, supplier
  settlement, subscriptions, verified webhooks, reconciliation.
* Meaningful AI use - agent orchestration, negotiation strategy, growth diagnosis,
  recommendations, semantic memory.
* Runs without judges' keys - deterministic agents, simulated PayPal, clearly labelled.
* Open-source licence - MIT ([LICENSE](../LICENSE)).
* No committed secrets - `.env` is gitignored; `.env.example` has blank secrets.
* Not done from this environment: deploying to Render, recording the demo video,
  submitting to Devpost.
