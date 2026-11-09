# Sponsor tools and integrations

[Back to docs](README.md)

This page says, for every tool the hackathon lists, **what PayPilot actually does with
it, whether that path is running against the real service, and how it was verified.**
Nothing is claimed that the code does not do. The same facts are served live by
`GET /api/v1/integrations/status`.

## Summary

| Tool | Used? | What for | Real service in this repo's verification? |
| --- | --- | --- | --- |
| **PayPal Developer Platform** | Core | Transaction Search, Orders v2 (on PayPal's official Server SDK), Invoicing, Payouts, Subscriptions, verified webhooks | **Yes** - a real sandbox supplier payment was created, approved by the buyer and captured; other paths verified with the simulator and mocked responses |
| **PayPal Agent Toolkit (MCP)** | Yes, read-only | Reporting and read tools reached through PayPilot's tool registry | **Partly** - handshake and `tools/list` verified live; see [below](#paypal-agent-toolkit-over-mcp) |
| **AG Grid** (Community 36.3) | Yes | Every data-heavy table | Yes (builds, renders) |
| **AG Studio** | Yes, incl. its AI agents | Pre-built + merchant-built dashboards over computed datasets, and Studio's agent harness running on PayPilot's LLM (`/studio`) | Renders in a real browser (evaluation mode); AI agents ran real turns on Groq - full runs need a paid Groq tier, see below |
| **Bryntum Gantt + Scheduler** (Enterprise 8.0) | Yes | Procurement timeline with agent-driven rescheduling (`/supply/timeline`); subscription revenue radar (`/finance/subscriptions/radar`) | Renders in a real browser (production build); trial key registered and accepted, so it shows Bryntum's Trial badge until 2026-12-20 |
| **Channel3** | Yes (**LIVE** on the hosted demo) | **Product Discovery** (natural-language search, comparison, similar products, URL lookup, conversational shopping agent) and **Supply Intelligence** (assortment expansion, alternatives, market prices, recommendations); **gear shelf**; market price reference for purchase approvals | **Yes** - live API with a real key (search, details, similar, categories, conversations verified 2026-11-06); built with Channel3's agent skill |
| **Elasticsearch** | Yes, optional | Evidence search (`/search`) | Mocked HTTP only; **off on the hosted demo** (labelled keyword fallback) |
| **Kernel** | Yes, optional | Supplier-portal verification sessions | Mocked HTTP in tests; **key configured on the hosted demo**, session-close call unverified; labelled fallback without a key |
| **Zapier** | Yes, optional | Signed business-event notifications | Mocked HTTP only; **off on the hosted demo** (no hook URL) |
| **Render** | Yes - **deployed** | `render.yaml`: API (runs the event relays), web, Postgres + pgvector, **Key Value (Redis)**, n8n, docs portal - all free plan | **Yes** - the hosted demo runs from it; `/health` reports `redis: ok`; see [below](#render-postman-astropods) |
| **Postman** | Yes | Collection (59 requests) + environment | Collection structure validated; not run in Postman here |
| **APIMatic** | Yes | Supplier payments run on PayPal's **APIMatic-generated Server SDK**, written with the **PayPal Context Plugin**; PayPilot's own spec, guides and portal config in `apimatic/` | SDK path verified against the sandbox; PayPilot's spec passes `apimatic api validate` with 0 errors, and its portal, Python + TypeScript SDKs and Context Plugin were built with the APIMatic CLI |
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
* Also imported: `@bryntum/scheduler-enterprise` (side effect only), because the "today" line is
  Scheduler's `timeRanges` feature and only registers in Gantt when that package is loaded -
  without it Gantt throws `Invalid type name "timeRanges"`.
* CSS (`components/supply/procurement-gantt.tsx`), in this order: Font Awesome from
  `core-enterprise`, structural `gantt.css`, one theme (`stockholm.css`, the `light-dark()`
  variant), then `procurement-gantt.css`, which maps Bryntum's variables onto PayPilot's design
  tokens - so the chart follows the app's light/dark mode - and colours each bar by stage state.
* **Layout:** the grid shows each stage with its detail underneath, a status pill and a progress
  bar; the timeline shows only bars, dependencies and a "Today" line, so no text ever overlaps a
  bar. Hovering a bar shows its dates and detail (escaped - names and emails are never HTML).
  *Fit* (`zoomToFit`) puts every stage on screen and re-fits when the card resizes; *Day / Week /
  Month* switch presets; *Today* scrolls to now. The chart is sized to its rows, and the host has
  `contain: inline-size`, so a wide timeline scrolls inside the card and never widens the page.
* Summary bars: Bryntum paints parent tasks as brackets with both `clip-path` and, in browsers
  that support it, `border-shape`; at our 8px bar height that left only the end notches, so both
  are reset for a plain rounded track filled to the procurement's progress.
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
* **Planned vs actual (`baselinesFeature`, Enterprise), behind a toggle:** a thin grey bar under
  a stage shows the window it was committed to: the RFQ deadline, the approval's expiry, the
  PO's expected delivery date. The backend sends a `baseline` only where such a date was
  recorded up front, so a stage with no plan has no grey bar; nothing is invented. Off by
  default to keep the chart calm; the toggle only appears when some stage has a plan.
* **Today (`timeRangesFeature` with `showCurrentTimeLine`):** an amber vertical line labelled
  "Today". (It replaced an earlier progress line and on-bar labels, which overlapped the bars.)
* **Agent-driven rescheduling.** *Deliveries in flight* (above the chart) has a **Supplier
  reports delay** button per open PO. It plays the supplier's side of the protocol: the
  supplier's agent sends a **signed `DELIVERY_UPDATE` (status `DELAYED`)** over the same verified
  bus as every other agent message (`POST /purchase-orders/{id}/delivery-delay`,
  `ProcurementLifecycle.report_delivery_delay`). Only then does the PO's `expected_at` move. The
  first committed date is kept as `original_expected_at`, so on the next refetch:
  * the **delivery bar** extends to the new date and turns **red**, with the reason in its detail;
  * the **PayPal payment** - drawn as *scheduled* after the delivery, because the money is only
    released after goods receipt and three-way match - **moves with it** and turns red too;
  * **Plan vs actual switches on by itself**, so the original plan sits under both bars and the
    slip is visible at a glance. The delay is also in the agent conversation, the run trace and
    the audit log (`DELIVERY_DELAYED`).

  The chart is still read-only: the date moved because an agent reported it over the protocol,
  never because someone dragged a bar.

## Bryntum Scheduler (subscription revenue radar)

`/finance/subscriptions/radar` puts every PayPal subscriber on one timeline with
`@bryntum/scheduler-react-enterprise` (8.0.0, same tier and version as the Gantt):

* **One row per subscriber, one bar per billing period.** Left of the "Today" line: periods
  PayPal collected (green), the period whose charge **failed** (red), PayPal's automatic
  **retries** and a **suspension** as milestones. Right of it: projected **renewals**
  (outlined), the next renewal of a subscriber with failed payments **at risk** (dashed amber),
  and a suspended subscriber's renewals **paused** (dashed grey).
* Rows are sorted by risk, and the locked grid shows subscriber, plan, health (with the failed
  count) and MRR. Tiles above: MRR, revenue renewing in 30 days, revenue at risk, recoveries.
* **Click a subscriber -> Recover payment** runs the real subscription action (PayPal
  Subscriptions `activate`; seeded demo records stay on the simulator). The row redraws with a
  green **Recovered** marker, because every lifecycle action is stamped into the record's history.
* Data: `GET /api/v1/paypal/subscriptions/radar` (`services/paypal/radar.py`), derived only from
  the subscription records (billing anchor `next_billing_at`, stepped back to `started_at`) and
  that history - it never invents a payment the record does not imply.
* Read-only: drag, resize, the event editor and context menus are off.
* CSS: Bryntum's rule is one structural sheet and one theme from the highest product in use, so
  the radar loads the same `gantt.css` + `stockholm.css` as the timeline (Gantt's sheet holds
  Scheduler's rules) plus `subscription-radar.css`, which maps the variables onto PayPilot's tokens.

## Channel3 (Product Discovery, Supply Intelligence, gear shelf, market reference)

**Product Discovery and Supply Intelligence** are the main Channel3 experience: natural-language
search (`/v1/search` with brand / category / price / retailer filters), product details
(`/v1/products/{id}`), similar products (`/v1/similar`, with the documented title-search fallback on
`404`), URL enrichment (`/v1/lookup`), brand and category resolution (`/v1/brands/search`,
`/v1/categories/search`) and the conversational shopping agent (`/v1/conversations`, buffered).
Those routes **never fall back**: without a key they answer `503 CHANNEL3_NOT_CONFIGURED` with
setup steps. Verified live on 2026-11-06 (search, details, similar, categories, conversations).
Full description: [SUPPLY_INTELLIGENCE.md](SUPPLY_INTELLIGENCE.md).


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

PayPilot uses APIMatic in two directions.

### 1. Consuming: supplier payments on PayPal's APIMatic-generated Server SDK

The step that moves money - create the supplier's PayPal order (supplier as payee), read it
back, capture it after the buyer approves - runs on **`paypal-server-sdk` 2.4.0**, PayPal's
official SDK generated by APIMatic (`backend/app/integrations/paypal/server_sdk.py`).
`PayPalClient.create_order / get_order / capture_order` delegate to it when
`PAYPAL_ORDERS_VIA_SDK=true` (the default). The hand-written REST client keeps the other PayPal
APIs, and tests that inject a mock transport stay on it.

It was written with the **APIMatic PayPal Context Plugin** installed in Claude Code. Its
skills - getting-started, client-initialization, authentication, calling-endpoints, models,
error-handling, configuration-resilience, testing - grounded the integration in the installed
SDK's real source instead of guesses, and caught traps that would otherwise have shipped:

| Plugin guidance | What it changed in PayPilot |
| --- | --- |
| The client is long-lived; build once, reuse | One `PaypalServersdkClient` per process, so the OAuth token and connection pool survive between calls |
| `environment` has a default - map it explicitly | `Environment.SANDBOX` / `PRODUCTION` chosen from `PAYPAL_ENVIRONMENT`, never left to the default |
| Auth is `ClientCredentialsAuthCredentials` passed as `client_credentials_auth_credentials=`; the automatic token fetch hides the real 401 behind "token is undefined or expired" | An `o_auth_token_provider` calls `fetch_token()` itself, so a rejected credential surfaces as `OAuthProviderException` with its real status |
| Orders operations take a single options dict (shape 2) and return an `ApiResponse` envelope | `create_order({"body": OrderRequest, "paypal_request_id": ..., "prefer": ...})`, payload read from the envelope |
| Optional model fields are *absent*, not `None`; `PaypalWalletExperienceContext` defaults to `GET_FROM_FILE` / `CONTINUE` | Typed `OrderRequest` / `PurchaseUnitRequest` / `AmountBreakdown` / `PayeeBase` models; `NO_SHIPPING` and `PAY_NOW` set explicitly for a B2B payment |
| Typed `ErrorException` fields are unassigned when a gateway returns HTML; `AuthValidationException` is *not* an `ApiException`; a `ConnectionError` on a write means "outcome unknown" | `getattr` for every typed field; separate branches for auth and transport; a transport failure is reported as retry-safe with the same `PayPal-Request-Id` |
| Generated retry defaults cover GET/PUT only | POST added for create/capture - safe because every write carries a `PayPal-Request-Id`, so a retry can never pay twice |
| The test seam is your own `requests.Session` via `http_client_instance`; route the stub by URL because the token POST comes first | `tests/unit/test_paypal_server_sdk.py` drives the real SDK serialization and error mapping with no network |

The SDK uses the synchronous `requests` transport, so each call runs in a worker thread
(`asyncio.to_thread`) to keep FastAPI's event loop free. `GET /integrations/status` reports the
APIMatic row as `SDK` when this path is active.

### 2. Publishing: PayPilot's own API on APIMatic

`python scripts/export_openapi.py` writes the spec (157 operations, readable operation ids,
servers, description, licence) to `docs/openapi.json` and `apimatic/src/spec/openapi.json`.
`apimatic/` is a ready APIMatic project: portal branding and navigation, four guides
(authentication, procure-to-pay, the supplier-agent protocol, money controls), Python and
TypeScript SDKs, and a **PayPilot Context Plugin** definition - so an external supplier agent
can integrate with PayPilot the same way PayPilot integrated with PayPal. `scripts/apimatic.sh`
(or `.ps1`) refreshes the spec and builds the portal, both SDKs and the plugin with the APIMatic
CLI; the `paypilot-docs` service in `render.yaml` rebuilds and hosts the portal as a free static
site. Both need an APIMatic account key (`APIMATIC_API_KEY`); see
[apimatic/README.md](../apimatic/README.md).

Built and checked: the spec passes `apimatic api validate` with **0 errors**. The export writes
OpenAPI 3.0.3 (FastAPI's 3.1 `anyOf [X, null]` becomes `nullable`, which APIMatic needs to accept
real `null`s), strips Pydantic's per-field titles, inlines the file-upload bodies, drops empty enum
values, declares every tag and gives every operation a description. The generated portal has the
guides, an API reference with a live playground and cURL / Python / TypeScript samples, SDK pages
and a Context Plugin page, and offers the SDKs and plugin as zip downloads. The Python SDK
(`pay_pilot_api`, sync and async) was installed and run against the local API: login, the revenue
radar and the procurement list all deserialise into typed models. The plugin has manifests for
Claude Code, Codex and Cursor. Generated output is git-ignored and rebuilt by the script.

## Render, Postman, Astropods

* **Render:** one Blueprint (`render.yaml`) defines everything on the free plan, and the hosted demo runs from it.
  * **API** (Docker): migrates, seeds the demo tenant idempotently, serves on `$PORT`, health check
    `/api/v1/health`, and runs the outbox and Zapier relays in-process (`OUTBOX_RELAY_IN_PROCESS=true`) so no
    paid worker is needed. **Web** (Node) and **docs** (static APIMatic portal) are separate services.
  * **Postgres 16** holds the application data and the pgvector agent memory.
  * **Key Value** (Redis-compatible, private, `allkeys-lru`) backs four things - shared HTTP rate-limit counters,
    the per-merchant Channel3 call budget, the Channel3 response caches (a free service restarts on every deploy
    and idle sleep, which would otherwise empty them and re-spend credits), and pub/sub so realtime events reach
    browsers on any API instance. It is never a source of truth and **falls back to in-process state when
    unreachable** (circuit breaker, 31 tests). See [CONFIGURATION.md](CONFIGURATION.md#redis).
  * **n8n** is defined for the free plan (state in the free Postgres, workflows rebuilt from the repo at boot, a
    generated shared HMAC secret, health URLs for an external monitor); see
    [n8n/README.md](../n8n/README.md#on-render-free-plan).
  * Wiring is declarative: an env group with generated secrets and `fromDatabase` / `fromService` references, so
    no connection string is copied by hand. Every other secret is `sync: false`.
  * **Free-plan realities, stated rather than hidden:** services sleep after about 15 idle minutes (the first
    request takes about a minute), the free database expires after 30 days, and a sleeping n8n cannot fire its
    schedules without an external ping.
* **Postman:** `postman/PayPilot.postman_collection.json` (59 requests, with assertions) and
  `postman/PayPilot.local.postman_environment.json`. The new *Integrations & sponsors* folder
  includes the checks that matter - a write tool returns `403`, an unsafe portal URL returns
  `400`, responses contain no secrets.
* **Astropods:** its docs were reviewed. It deploys agents from an `astropods.yml` blueprint
  using the `ast` CLI. That CLI is not installed here, so a blueprint could not be validated and
  none was added. Agents deploy with the app and are traced with Langfuse instead.
