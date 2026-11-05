# Sponsor tools and integrations

[Back to docs](README.md)

This page says, for every tool the hackathon lists, **what PayPilot actually does with
it, whether that path is running against the real service, and how it was verified.**
Nothing is claimed that the code does not do. The same facts are served live by
`GET /api/v1/integrations/status` and shown on the **Integrations** screen.

## Summary

| Tool | Used? | What for | Real service in this repo's verification? |
| --- | --- | --- | --- |
| **PayPal Developer Platform** | Core | Transaction Search, Orders v2, Invoicing, Payouts, Subscriptions, verified webhooks | **Yes** - OAuth against the sandbox verified; REST paths otherwise verified with the simulator and mocked responses |
| **PayPal Agent Toolkit (MCP)** | Yes, read-only | Reporting and read tools reached through PayPilot's tool registry | **Partly** - handshake and `tools/list` verified live; see [below](#paypal-agent-toolkit-over-mcp) |
| **AG Grid** (Community 36.3) | Yes | Every data-heavy table | Yes (builds, renders) |
| **AG Studio** | Yes, incl. its AI agents | Pre-built + merchant-built dashboards over computed datasets, and Studio's agent harness running on PayPilot's LLM (`/studio`) | Renders in a real browser (evaluation mode); AI agents ran real turns on Groq - full runs need a paid Groq tier, see below |
| **Bryntum Gantt** (Enterprise 8.0) | Yes | Procurement timeline (`/supply/timeline`) | Renders in a real browser (production build); trial key registered and accepted, so it shows Bryntum's Trial badge until 2026-12-20 |
| **Channel3** | Yes | **Gear shelf** - live complementary products with affiliate buy links for the merchant's best seller; market price reference for purchase approvals | **Yes** - live API with a real key; built with Channel3's agent skill |
| **Elasticsearch** | Yes, optional | Evidence search (`/search`) | Mocked HTTP only; keyword fallback without `ELASTIC_URL` |
| **Kernel** | Yes, optional | Supplier-portal verification sessions | Mocked HTTP only; labelled fallback without a key |
| **Zapier** | Yes, optional | Signed business-event notifications | Mocked HTTP only; off without a hook URL |
| **Render** | Blueprint | `render.yaml`: API (runs the event relays), web, Postgres - all free plan | YAML validated; **not deployed** |
| **Postman** | Yes | Collection + environment | Collection structure validated; not run in Postman here |
| **APIMatic** | Spec export only | `docs/openapi.json` ready to import | The **Context Plugin was not used**, no APIMatic account used |
| **Astropods** | **Not used** | - | Docs reviewed; see below |

> The Devpost page lists sponsor prizes for **AG Grid, APIMatic, Bryntum, Channel3 and
> Render** only. Elasticsearch, Kernel, Zapier, Postman and Astropods are listed as
> tools you *may* use, with no prize attached.

## The rule every integration follows

* **A fallback is never disguised.** Without a key, Channel3, Kernel and the PayPal MCP
  bridge answer from a deterministic stand-in and every result carries
  `mode: "SIMULATED"`; the UI badges it. Elasticsearch and Zapier degrade to an in-process
  keyword search and "off".
* **None of them can move money or change a limit.** Channel3 and Elasticsearch read, Kernel
  observes, Zapier is outbound-only, and the MCP bridge refuses anything but reads. Limits
  come from the deterministic engine before any agent speaks; payments need a recorded
  human approval bound to exact terms.
* **Secrets stay server-side** and never appear in a response, a log line or `repr()`.
* **Tenant isolation and RBAC apply** - search results only include sources the caller's role
  may read; every query is merchant-scoped.

## PayPal Agent Toolkit over MCP

PayPal's remote MCP server exposes its Agent Toolkit as **46 tools** (verified against the
live sandbox on 2026-11-04). PayPilot reaches it through its **own tool registry**
(`paypal_mcp_read`, permission `paypal:read`) so tenant scoping, RBAC, logging and tracing
still apply - and so an agent can never use it to bypass the approval gates.

* **Transport:** HTTP+SSE. `GET https://mcp.sandbox.paypal.com/sse` with
  `Authorization: Bearer <PayPal access token>` returns an `endpoint` event; JSON-RPC is
  POSTed to that per-session URL (`202`) and replies arrive on the stream. (`/http` is a 404 on
  the sandbox host - the client was built from probing the real server, not from the docs.)
* **Read-only gate, decided before any network request:** the name must start with `list_`,
  `get_`, `show_` or `search_`, must not contain a state-changing fragment (`create`, `pay`,
  `send`, `capture`, `cancel`, ...), and is refused if the server annotates it
  `readOnlyHint: false`. Of the 46 real tools, **16 are callable** (`list_disputes`,
  `get_merchant_insights`, `list_transactions`, `list_invoices`, ...) and **30 are blocked**,
  including every tool that creates an order, pays, refunds, sends an invoice or accepts a
  dispute claim. PayPal's server sends no annotations today, so the name rules are what
  protect you.
* **The listener cannot be redirected:** the `endpoint` event decides where the bearer token
  is sent next, so it must resolve to the same host as the stream or the call is refused.
* **Known limitation (PayPal-side, observed 2026-11-04):** every tool call currently returns
  `{"ok": false, "code": "PAYPAL_API_SETUP_ERROR", "message": "Unsupported cache mode: default"}`
  inside a *successful* MCP response. PayPilot reports that as an error rather than showing it as
  data. Handshake, `tools/list`, argument validation and call routing all work; the tools
  themselves do not return data right now. If PayPal fixes their runtime, no change is needed
  here.

## AG Grid and AG Studio

* **AG Grid Community** (v36.3.0) renders every dense table (transactions, quotes, invoices,
  receipts, reconciliation, evidence), themed to the design system in light and dark.
* **AG Studio** (`ag-studio` / `ag-studio-react` 3.1.0) powers **Dashboard Studio**: a merchant
  drags fields onto a canvas to chart PayPilot's own datasets (`/integrations/studio/datasets`:
  PayPal transactions, procurements, negotiation offers, supplier agents, inventory cover). The
  datasets are **computed by the backend and filtered by the caller's permissions**; Studio only
  groups and charts them, it derives no financial figure. The report layout is kept in the
  browser (a per-viewer convenience).
* **First open is never blank:** `frontend/src/lib/studio/default-report.ts` builds an overview
  (stockout cover, revenue at risk, supplier scorecard, and - when the data exists - PayPal gross by
  day, procurement savings and negotiation rounds) from whichever datasets the backend returned.
  **Reset layout** returns to it.
* **Studio's AI agents run on PayPilot's LLM.** AG Studio ships an agent harness (lead, data, page,
  planning and widget agents) and never calls a model itself; the host supplies an `AgLlmAdapter`.
  PayPilot's adapter (`frontend/src/lib/studio/llm-adapter.ts`) posts each turn to
  `POST /api/v1/integrations/studio/ai/turn`, where `services/integrations/studio_ai.py` translates
  Studio's Responses-style items to chat completions and runs them on Groq (or any
  OpenAI-compatible provider set by `STUDIO_AI_BASE_URL` / `STUDIO_AI_API_KEY` / `STUDIO_AI_MODEL`).
  The **key never reaches the browser**, and the agents' tools execute in the browser against the
  dashboard only - they cannot read the database, call PayPal or change a record. Four prompt
  starters (stockout risk, supplier scorecard, negotiation story, PayPal trend) seed the chat.
* **Verified:** in a real browser (headless Edge) the agents completed real turns on Groq -
  reading the report and schema, planning, and delegating to Studio's Page and Planning agents -
  with tool calls executed by Studio. **Limit found:** Groq's *free* tier allows 8,000 tokens per
  minute (every free model on our key), and Studio's delegate agents carry 5-9k tokens of tool
  schemas per turn. The backend waits out 429s using `retry-after` and, on a 413, shrinks the
  answer budget to fit and retries - but on the free tier one request ("add a bar chart of
  reliability by supplier") still ran 16 turns over ~9 minutes and stopped at a plan without adding
  the chart (some delegate turns stayed too large; others failed Groq's tool-argument validation).
  **So the assistant is off on the hosted demo** (`STUDIO_AI_ENABLED=false` in `render.yaml`) until
  `STUDIO_AI_*` points at a provider with enough quota. The pre-built dashboard and the
  drag-and-drop editor need no LLM.
* **Licence:** AG Studio is commercial. Without a licence key it runs in evaluation mode
  (watermark and a console banner, "AG Studio Pro with AI" once the AI module is registered); all
  features are unlocked for trial. Request a 45-day trial key from AG Grid and set
  `NEXT_PUBLIC_AG_STUDIO_LICENSE_KEY` to remove it.
* **Pin both AG Grid packages to the version AG Studio requires** (`36.3.0`). A mismatch makes
  two copies of `ag-grid-community` load and Studio renders a blank canvas with
  `theme.withPart must be a Theming API part object` in the console.

## Bryntum Gantt

`/supply/timeline` shows each procurement as a parent task whose children are the stages that
**actually happened**, with the dates the system recorded, chained finish-to-start: RFQ and
negotiation -> human approval -> PO and delivery -> invoice -> PayPal payment. Goods receipts
are milestones, so a partial delivery is two diamonds and a half-filled bar; a blocked stage
(rejected approval, invoice discrepancy, overdue delivery) is red.

* It is a **read-only view of history, not a planner**: every task is `manuallyScheduled`, so
  Bryntum never reschedules anything and nothing can imply a commitment the backend did not make.
* Data comes from `GET /api/v1/supply/timeline` (`services/supply/timeline.py`), mapped by a
  unit-tested pure function.
* Packages: Bryntum **8.0.0, Enterprise tier**, from public npm, pinned exactly -
  `@bryntum/gantt-react-enterprise`, `@bryntum/gantt-enterprise`, `@bryntum/core-enterprise`.
  Every `@bryntum/*` package must stay at the same exact version and tier; a mismatch loads two
  copies of Bryntum Core and breaks the theme.
* CSS (`components/supply/procurement-gantt.tsx`), in this order: Font Awesome from
  `core-enterprise`, structural `gantt.css`, one theme (`stockholm-light.css`), then
  `procurement-gantt.css`, which colours each bar by stage state.
* Data sits on a `<BryntumGanttProjectModel>` passed to the Gantt by ref, so the 30-second
  refetch syncs the task store by id instead of rebuilding the chart.
* **Licence:** set `NEXT_PUBLIC_BRYNTUM_LICENSE_KEY` (root `.env`, a Docker build arg, or a Render
  env var; it is baked in at build time). The component registers it with
  `bryntum.licenseKey` before the first Gantt is created. Without it, the Enterprise package
  runs as Bryntum's 14-day trial, counted from first use, then masked. A free trial key from
  [bryntum.com](https://bryntum.com/download-trial/?product=gantt) runs to the key's end date
  (ours: 2026-12-20) but **still shows the Trial badge**. Only a purchased key removes it. The
  console confirms which applies (`Trial license ends ...` with a key, `No license key
  registered ...` without). The key is checked in the browser, so shipping it in the client
  bundle is expected. Keep it out of git anyway.
* The first screen scrolls to the earliest stage (`visibleDate`), because the `weekAndDay`
  preset snaps the axis back to the start of the week.
* **Planned vs actual (`baselinesFeature`, Enterprise):** a thin grey bar under a stage shows
  the window it was committed to: the RFQ deadline, the approval's expiry, the PO's expected
  delivery date. The backend sends a `baseline` only where such a date was recorded up front,
  so a stage with no plan has no grey bar; nothing is invented.
* **Progress line (`progressLineFeature`, Business+):** an amber line through each stage's
  progress point as of today, drawn only while today is on screen. A dip to the left means a
  stage is behind.
* **Labels (`labelsFeature`, Business+):** each stage's detail is printed beside its bar.

## Channel3 (gear shelf and market reference)

Built with Channel3's official agent skill (`npx skills add channel3-ai/skills --skill
channel3-api`, installed in `.agents/skills/channel3-api`) and verified against the **live API**
with a real key on 2026-11-05.

**Gear shelf (`/shelf`, `GET /api/v1/integrations/shelf`)** - the product experience. A coffee
shop's online customers buy beans, and the gear to brew them, which the shop does not stock.
For the merchant's best-selling online product, one `POST /v1/search` per slot (grinders,
pour-over kits, filters, travel mugs, bean storage), each constrained by a Channel3 **category
slug** and a **price band** (`filters.category_ids`, `filters.price` - filters, not
query-stuffing), returns live products with images, retailers, compare-at prices, offer counts
and **affiliate-tracked buy links** with their commission rates. Requests carry
`x-user-id: paypilot-<merchant>` so the merchant's clicks and sales appear in Channel3's
reporting. The page estimates monthly shelf sales and commission from the **measured** number of
recent buyers and an attach rate that is labelled an **assumption**. Results are cached for 30
minutes (Channel3 asks callers not to hold prices or offer links for hours); *Refresh prices*
bypasses it. Live run for the demo merchant: 212 recent bean buyers, 15 products from retailers
such as Belk, Hamilton Beach, Nordstrom, Macy's and Walmart at 2-8.4% commission - about $432 of
shelf sales and $22 of commission a month at a 6% attach rate.

**Market reference (`POST .../market/benchmark`, `GET .../market/procurement/{id}`)** -
min / median / max retail price and where the merchant's planned price sits, as **context for
the human approving a purchase** (retail prices are not supplier costs; it changes no limit,
budget or offer). A price is only reported when the results agree on a Channel3 category
(at least 3 results and 40% of them): semantic search for "whole bean coffee" returns
canisters, a face scrub and an espresso machine, and averaging those would be meaningless - so
for the demo's coffee beans the response says there is no consistent market price, while a
travel mug gets a real median ($27.95 across 10 comparable listings).

*Response shape (verified live):* a product is `{id, title, brands, images, category{slug},
offers}`; retailer, link, stock and commission live on each **offer**, and the client keeps the
cheapest in-stock one. Tests run against that exact shape with mocked HTTP and never spend
credits (`tests/unit/test_channel3_shelf.py`). Credits: the hackathon promo code
`PAYPAL-HACKATHON-2026` gives 20,000 free searches.

## Elasticsearch (evidence search)

One ranked search over the audit log, signed agent messages, negotiation offers, procurements,
supplier invoices, business events and reviews - each source requiring the permission that
protects it. With `ELASTIC_URL` set, `Re-index` bulk-upserts idempotently (`merchant:kind:ref`
ids) and search runs a `multi_match` that is **always** filtered by `merchant_id`. Without it,
the same documents are scored in-process and the screen says "Keyword fallback". Start a local
node with `docker compose --profile search up -d elasticsearch`.

*Verified:* request bodies, the tenant filter, bulk format and the fallback against mocks and the
full API. *Not verified:* against a running Elasticsearch (Docker was unavailable in the
verification environment).

## Kernel (supplier-portal check)

`POST /api/v1/integrations/kernel/sessions` opens a Kernel cloud browser (`POST
https://api.onkernel.com/browsers`, bearer auth) on a supplier's **public https page** so the
merchant can watch it live. Only `https` and real public hostnames are accepted (no raw IPs,
localhost or credentials in the URL). It **observes only** - it never logs in, fills a form or
pays - and the session expires on its own timeout. Every open is audited. The CDP socket is never
sent to the browser UI.

*Not verified:* the session-close call (`DELETE /browsers/{id}`) is best-effort - the sessions also
expire by timeout - and nothing was run against a live Kernel account.

## Zapier (notifications)

Set `ZAPIER_WEBHOOK_URL` to a *Webhooks by Zapier -> Catch Hook* URL and these events are
delivered, **signed** (`X-PayPilot-Signature: sha256=...`, `X-PayPilot-Event-Id` for de-dupe):
revenue anomaly, stockout risk, procurement required, supplier selected, purchase approved,
payment reconciled, margin changed. Delivery state is one row per (event, target) in
`integration_deliveries` (`UNIQUE(event_id, target)`), so an event is delivered **at most once**,
a Zapier outage never disturbs n8n, retries back off exponentially, and enabling it never replays
history older than a day. Zapier never approves, pays or changes a limit. (Zapier's MCP server -
which lets an agent *call* Zapier actions - is deliberately not connected: an agent that can
trigger arbitrary third-party actions would sit outside the approval gates.)

## APIMatic

`python scripts/export_openapi.py` writes `docs/openapi.json` (157 operations) from the FastAPI
app itself, ready to import into APIMatic to generate SDKs and a developer portal. **The APIMatic
Context Plugin was not used to build this, and no APIMatic account was used** - only the spec
export exists, and it is described as exactly that.

To actually use APIMatic (needs an account - free trial at apimatic.io):

1. `python scripts/export_openapi.py` (refreshes the spec).
2. APIMatic dashboard -> **Import API** -> upload `docs/openapi.json`. Fix anything its validator
   flags (it reports issues per operation).
3. **Generate SDK** for TypeScript and Python, and **Generate API Portal**; publish the portal.
4. Put the portal URL (and an SDK snippet) in the Devpost submission and the README, and change
   the APIMatic row above to say what was generated. Do not claim the Context Plugin unless you
   used it.

## Render, Postman, Astropods

* **Render:** `render.yaml` defines the API, web app and managed Postgres, all on the free plan,
  with every secret `sync: false`. The API runs the outbox and Zapier relays in-process
  (`OUTBOX_RELAY_IN_PROCESS=true`), so no paid worker is needed; n8n stays local (Docker Compose).
  It parses and passes review but **was not deployed** from this environment.
* **Postman:** `postman/PayPilot.postman_collection.json` (53 requests, with assertions) and
  `postman/PayPilot.local.postman_environment.json`. The new *Integrations & sponsors* folder
  includes the checks that matter - a write tool returns `403`, an unsafe portal URL returns
  `400`, responses contain no secrets.
* **Astropods:** its docs were reviewed. It deploys agents from an `astropods.yml` blueprint
  using the `ast` CLI. That CLI is not installed here, so a blueprint could not be validated and
  none was added. Agents deploy with the app and are traced with Langfuse instead.
