# Devpost submission draft

[Back to docs](README.md)

Paste each section into the matching Devpost field. Replace the three `<...>`
links before submitting, and keep the claims in step with
[SPONSORS.md](SPONSORS.md) - every tool listed there says whether it ran against
the real service.

---

## Tagline

An AI operating system for small merchants: agents that grow revenue, source and
negotiate stock, and settle suppliers through PayPal - with a human approving
every dollar.

## Inspiration

A small coffee shop owner is the growth analyst, the buyer and the accountant at
once. Their PayPal data already says when sales slip and which product is about to
run out, but turning that into a decision - and then into a negotiated purchase
order and a correct payment - takes hours they don't have. We wanted agents that
do that work end to end, without ever being trusted with the money.

## What it does

PayPilot runs a merchant's business loop on top of PayPal:

* **Growth:** a Growth Scientist reads PayPal transactions, finds opportunities
  (for example *capture rising demand for whole-bean coffee: 7 -> 12 bags/day*),
  and measures campaigns with controlled experiments.
* **Supply agents:** Inventory Intelligence sees the beans will run out in 3.5
  days. A Buyer Agent sends an RFQ to three independent supplier agents, each with
  private pricing, and negotiates over several rounds. Every message between
  agents is typed and HMAC-signed; every offer is checked against a limit the
  backend computed *before any agent spoke* (`$18 x (1 - 40%) = $10.80` per bag).
  The winner saves **$248.77** on a **$1,455.00** order.
* **Financial control:** an Analyst who tries to approve gets **HTTP 403**; the
  Owner approves terms bound to a hash, so any change invalidates the approval.
  Receiving 100 of 150 bags holds payment (three-way match); the last 50 release it.
* **PayPal settlement:** the supplier is paid with **PayPal Orders v2** (payee =
  supplier, idempotency key, sandbox approve -> capture), then reconciled to the
  cent. Inventory is revalued and the product's margin moves **35.6% -> 43.8%**.
* **Finance:** Transaction Search sync and insights, Invoicing, approval-gated
  cashback **Payouts**, Subscriptions recovery, and verified webhooks.
* **Dashboards:** AG Grid tables everywhere, an AG Studio dashboard that opens
  pre-built and is edited by drag-and-drop, and a Bryntum Gantt of every
  procurement's real history.

## How we built it

* **Backend:** FastAPI, SQLAlchemy 2 (async), PostgreSQL 16 + pgvector, Alembic.
  Money is `Decimal` end to end; limits, scoring, matching and revaluation are
  deterministic code, never an LLM.
* **Agents:** LangGraph workflows for growth and procurement (both stop at a human
  approval gate); Groq `gpt-oss-120b` for narration, intent routing and a buyer
  strategist whose proposals are bounds-checked before use; pgvector memory.
* **PayPal:** our own REST client (OAuth caching and refresh, retries,
  `PayPal-Request-Id` idempotency, debug ids) for Transaction Search, Orders v2,
  Invoicing, Payouts, Subscriptions and webhook verification, plus a labelled
  simulator so judges can run everything without keys. PayPal's Agent Toolkit is
  reachable read-only over MCP; every money-moving tool is blocked in code.
* **Frontend:** Next.js 15 + React 19, TanStack Query, AG Grid 36.3, AG Studio
  3.1, Bryntum Gantt. We also wired Studio's AI agent harness to our backend's LLM
  through an `AgLlmAdapter` (the key never reaches the browser); it works, but on
  Groq's free tier Studio's agents are too slow to finish a request, so the hosted
  demo keeps it switched off.
* **Ops:** Docker Compose for the whole stack including n8n, a Render Blueprint
  that fits the free plan, a Postman collection, an OpenAPI export.

## Challenges we ran into

* **Keeping AI away from the money.** Agents propose; the backend disposes. Every
  offer is validated against a policy version, approvals are bound to a SHA-256 of
  the exact terms, and payment needs a second approval.
* **Signatures across languages.** Python and JavaScript serialise JSON
  differently (`13.0` vs `13`), so both sides sign a pinned canonical form.
* **Real PayPal is stricter than any mock.** The sandbox rejected INR
  (`CURRENCY_NOT_SUPPORTED`) and needed app features switched on; the sandbox MCP
  server currently errors on every tool call, which we surface as an error instead
  of pretending it worked.
* **Sponsor SDK details.** Two copies of AG Grid blanked AG Studio until both
  packages were pinned to the version Studio requires; Studio's agents send more
  tokens per turn than Groq's free tier allows per minute, so we taught the relay
  to wait out rate limits and shrink its answer budget to fit - still not enough
  for a full agent run on a free key.

## Accomplishments that we're proud of

* A complete purchase-to-pay loop where every figure is reproducible and every
  money movement has a named human approver.
* Agent-to-agent negotiation with real, persisted, verified protocol messages.
* <!-- update before submitting --> backend and frontend test suites green,
  including the full procurement lifecycle through the real API.

## What we learned

Agents are most useful when the boundary is explicit: deterministic code owns
limits and money, agents own search, negotiation and explanation, and humans own
the decision. That split also made the system far easier to test.

## What's next

Live PayPal (beyond the sandbox), real supplier endpoints speaking the signed
protocol, scheduled Studio reports, and deeper market data from Channel3 in the
buyer agent's opening position.

## Built with

`python` `fastapi` `postgresql` `pgvector` `sqlalchemy` `langgraph` `groq`
`paypal` `paypal-orders-v2` `paypal-payouts` `paypal-invoicing` `paypal-subscriptions`
`paypal-agent-toolkit` `mcp` `next.js` `react` `typescript` `ag-grid` `ag-studio`
`bryntum` `channel3` `n8n` `docker` `render` `postman` `langfuse` `vapi`

## Links

* Live demo: `<Render URL>` - log in as `owner@juniperoak.com` / `Autopilot@2024`
  (other roles in [DEMO.md](DEMO.md)); first load may take a minute (free plan).
* Video: `<YouTube URL>`
* Code: `<GitHub URL>`

## Testing instructions for judges

No keys needed: `docker compose up -d --build`, open <http://localhost:3000>, and
follow [DEMO.md](DEMO.md) (three minutes). PayPal runs in a labelled simulator and
agents in deterministic mode unless keys are configured.
