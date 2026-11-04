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
| **AG Studio** | Yes | Merchant-built dashboards over computed datasets (`/studio`) | Renders in a real browser, in evaluation mode |
| **Bryntum Gantt** | Yes | Procurement timeline (`/supply/timeline`) | Renders in a real browser, trial build |
| **Channel3** | Yes | Market price reference for the buyer agent | Mocked HTTP only; labelled fallback without a key |
| **Elasticsearch** | Yes, optional | Evidence search (`/search`) | Mocked HTTP only; keyword fallback without `ELASTIC_URL` |
| **Kernel** | Yes, optional | Supplier-portal verification sessions | Mocked HTTP only; labelled fallback without a key |
| **Zapier** | Yes, optional | Signed business-event notifications | Mocked HTTP only; off without a hook URL |
| **Render** | Blueprint | `render.yaml`: API, web, worker, Postgres | YAML validated; **not deployed** |
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
* **Licence:** AG Studio is commercial. Without a licence key it runs in evaluation mode
  (watermark and a console banner); all features are unlocked for trial. Request a 45-day trial
  key from AG Grid to remove it.
* **Pin both AG Grid packages to the version AG Studio requires** (`36.3.0`). A mismatch makes
  two copies of `ag-grid-community` load and Studio renders a blank canvas with
  `theme.withPart must be a Theming API part object` in the console.
* **Not implemented:** the *Studio Agent Framework* (letting an agent build or edit dashboards
  from natural language) - it needs your own LLM wired into Studio's agent API, which was not
  verified. Studio's drag-and-drop editor is what ships.

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
* Bryntum is installed as the **trial** package, aliased: `"@bryntum/gantt":
  "npm:@bryntum/gantt-trial@^7.3.8"`. The trial draws a watermark and is for evaluation; a
  commercial deployment needs a Bryntum licence.

## Channel3 (market reference)

`POST /api/v1/integrations/market/benchmark` and `GET .../market/procurement/{id}` search
Channel3 (`POST https://api.trychannel3.com/v1/search`, header `x-api-key`) and return
min / median / max retail price plus where the merchant's planned selling price sits. It is
**context for the human approving a purchase** - retail prices are not supplier cost prices, and
the response says it changes no limit, budget or offer. Set `CHANNEL3_API_KEY` (Channel3 offers
free monthly credits; the hackathon code is on the sponsor page) to go live.

*Verified:* request shape, headers, parsing and error handling against mocked responses.
*Not verified:* Channel3's exact response schema - the parser is deliberately defensive and
counts anything it cannot read instead of inventing it.

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

`python scripts/export_openapi.py` writes `docs/openapi.json` (155 operations) from the FastAPI
app itself, ready to import into APIMatic to generate SDKs and a developer portal. **The APIMatic
Context Plugin was not used to build this, and no APIMatic account was used** - only the spec
export exists, and it is described as exactly that.

## Render, Postman, Astropods

* **Render:** `render.yaml` defines the API, web app, worker and managed Postgres, with every
  secret `sync: false`. It parses and passes review but **was not deployed** from this
  environment.
* **Postman:** `postman/PayPilot.postman_collection.json` (53 requests, with assertions) and
  `postman/PayPilot.local.postman_environment.json`. The new *Integrations & sponsors* folder
  includes the checks that matter - a write tool returns `403`, an unsafe portal URL returns
  `400`, responses contain no secrets.
* **Astropods:** its docs were reviewed. It deploys agents from an `astropods.yml` blueprint
  using the `ast` CLI. That CLI is not installed here, so a blueprint could not be validated and
  none was added. Agents deploy with the app and are traced with Langfuse instead.
