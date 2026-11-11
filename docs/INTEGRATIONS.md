<div align="center">

# Integrations

Every third-party service and component PayPilot uses beyond PayPal: what it does here, where the code is, how it
behaves without a key, and how it was verified.

[![Docs index](https://img.shields.io/badge/-Docs_index-0b2a6f?style=flat-square)](README.md)
[![PayPal](https://img.shields.io/badge/-PayPal-003087?style=flat-square&logo=paypal&logoColor=white)](PAYPAL.md)
[![Configuration](https://img.shields.io/badge/-Configuration-2563eb?style=flat-square)](CONFIGURATION.md)
[![Automation](https://img.shields.io/badge/-Automation-b45309?style=flat-square)](AUTOMATION.md)
[![API portal](https://img.shields.io/badge/-API_portal_and_SDKs-0f766e?style=flat-square)](APIMATIC.md)

</div>

---

## Contents

- [Summary](#summary)
- [Rules every integration follows](#rules-every-integration-follows)
- [Channel3](#channel3)
- [AG Grid and AG Studio](#ag-grid-and-ag-studio)
- [Bryntum Gantt](#bryntum-gantt)
- [Bryntum Scheduler](#bryntum-scheduler)
- [APIMatic](#apimatic)
- [Render and Redis](#render-and-redis)
- [Elasticsearch](#elasticsearch)
- [Kernel](#kernel)
- [Zapier](#zapier)
- [Groq, Langfuse and Vapi](#groq-langfuse-and-vapi)
- [Postman](#postman)
- [Integration status endpoint](#integration-status-endpoint)

---

## Summary

| Integration | Used for | Code | Without a key | Verified against |
| --- | --- | --- | --- | --- |
| **Channel3** | Product discovery, shopping agent, Supply Intelligence, gear shelf, market reference | [`channel3_catalog.py`](../backend/app/integrations/sponsors/channel3_catalog.py), [`channel3.py`](../backend/app/integrations/sponsors/channel3.py) | Discovery routes answer `503` with setup steps; shelf and market reference use a labelled `SIMULATED` catalogue | Live API |
| **AG Grid** Community 36.3 | Every dense table | `frontend/src/components` | n/a (open source) | Builds and renders |
| **AG Studio** 3.1 | Dashboard Studio and its AI agents (`/studio`) | [`lib/studio/`](../frontend/src/lib/studio), [`studio_ai.py`](../backend/app/services/integrations/studio_ai.py) | Evaluation watermark; AI off without a model | Real browser; agent turns on Groq |
| **Bryntum** Gantt and Scheduler 8.0 | Procurement timeline, subscription revenue radar | [`procurement-gantt.tsx`](../frontend/src/components/supply/procurement-gantt.tsx), [`subscription-radar.tsx`](../frontend/src/components/finance/subscription-radar.tsx) | 14-day trial, then masked | Real browser, production build |
| **APIMatic** | PayPal Server SDK for supplier payments; PayPilot's own portal and SDKs | [`server_sdk.py`](../backend/app/integrations/paypal/server_sdk.py), [`apimatic/`](../apimatic) | n/a | Live sandbox; spec validates with 0 errors |
| **Render** | Hosting from one Blueprint | [`render.yaml`](../render.yaml) | n/a | Hosted demo runs from it |
| **Redis / Key Value** | Shared rate limits, Channel3 caches, realtime pub/sub | [`core/redis.py`](../backend/app/core/redis.py) | In-process fallback | Unit tests with fakeredis; hosted `/health` reports `redis: ok` |
| **Elasticsearch** | Evidence search (`/search`) | [`elastic.py`](../backend/app/integrations/sponsors/elastic.py) | Labelled keyword fallback | Mocked HTTP |
| **Kernel** | Observe-only supplier-page browser | [`kernel.py`](../backend/app/integrations/sponsors/kernel.py) | No browser started | Mocked HTTP |
| **Zapier** | Signed business-event notifications | [`zapier.py`](../backend/app/integrations/sponsors/zapier.py), [`services/integrations/zapier.py`](../backend/app/services/integrations/zapier.py) | Off | Mocked HTTP |
| **n8n** | Event routing and schedules | [`n8n/`](../n8n) | Events recorded, marked `SKIPPED` | Docker Compose and Render; see [Automation](AUTOMATION.md) |
| **Groq** | LLM routing, wording, negotiation strategist | [`groq.py`](../backend/app/integrations/groq.py) | Deterministic mode | Live API |
| **Langfuse** | Agent traces | [`langfuse.py`](../backend/app/integrations/langfuse.py) | No-op tracer | Live (hosted demo) |
| **Vapi** | Voice assistant | [`vapi.py`](../backend/app/integrations/vapi.py) | Button explains what is missing | Live (hosted demo) |
| **Postman** | API collection with assertions | [`postman/`](../postman) | n/a | Collection structure validated |

---

## Rules every integration follows

* **A fallback is never disguised.** Without a key, results carry `mode: "SIMULATED"` and the UI badges them, or the
  route answers `503` with setup steps. Nothing invents products, prices or payments.
* **None of them can move money or change a limit.** Channel3 and Elasticsearch read, Kernel observes, Zapier is
  outbound-only, the PayPal MCP bridge refuses everything but reads. Limits come from the deterministic engine;
  payments need a recorded human approval.
* **Secrets stay server-side** and never appear in a response, a log line or `repr()`.
* **Tenant isolation and RBAC apply.** Every query is merchant-scoped; search results include only sources the
  caller's role may read.

---

## Channel3

Channel3 is a product catalog API covering thousands of retailers. PayPilot uses it in four places.

| Where | How |
| --- | --- |
| `/discovery`, `/discovery/assistant`, `/discovery/compare` | **Product Discovery:** natural-language search, comparison, similar products, URL enrichment and the conversational shopping agent. See [Supply Intelligence](SUPPLY_INTELLIGENCE.md) |
| `/supply/intelligence`, `/supply/market`, `/recommendations` | **Supply Intelligence:** assortment expansion, alternatives, market price intelligence and recommendations |
| `/shelf` | **Gear shelf:** for the best-selling online product, one filtered search per slot (grinders, pour-over kits, filters, travel mugs, storage) using a Channel3 category slug and a price band. Live products with affiliate-tracked buy links and commission rates. Monthly shelf sales and commission are estimated from the measured number of recent buyers and an attach rate labelled as an assumption. Cached 30 minutes; *Refresh prices* bypasses the cache |
| Purchase approvals | **Market reference:** minimum, median and maximum retail price beside a purchase, as context for the person approving. Reported only when results agree on a category (at least 3 results and 40% of them), because semantic search can return unrelated items. It never changes a limit, budget or offer |

Response shape (verified live): a product is `{id, title, brands, images, category{slug}, offers}`; retailer, link,
stock and commission live on each offer, and the client keeps the cheapest in-stock one. Requests carry
`x-user-id: paypilot-<merchant>` for attribution. Responses are cached in Redis when configured, so restarts do not
re-spend credits. Tests run against the verified shape with mocked HTTP:
[`tests/unit/test_channel3_shelf.py`](../backend/tests/unit/test_channel3_shelf.py),
[`tests/unit/test_channel3_catalog.py`](../backend/tests/unit/test_channel3_catalog.py).

The integration was built with Channel3's official agent skill, vendored in
[`.agents/skills/channel3-api`](../.agents/skills/channel3-api).

---

## AG Grid and AG Studio

**AG Grid Community 36.3** renders every dense table: transactions, quotes, supplier invoices, receipts,
reconciliation, payments, payouts, invoices, subscriptions, webhooks, RFQs and evidence. Grids are themed to the
design system in light and dark mode.

**AG Studio** (`ag-studio`, `ag-studio-react`) powers **Dashboard Studio** at `/studio`:

* **Datasets are computed by the backend** (`GET /integrations/studio/datasets`: PayPal transactions, procurements,
  negotiation offers, supplier agents, inventory cover) and filtered by the caller's permissions. Studio only groups
  and charts them; it derives no financial figure. The layout is kept in the browser per viewer.
* **The first open is never blank.** [`lib/studio/default-report.ts`](../frontend/src/lib/studio/default-report.ts)
  builds an overview (stockout cover, revenue at risk, supplier scorecard, PayPal gross by day, procurement savings,
  negotiation rounds) from whichever datasets the backend returned. *Reset layout* returns to it.
* **Studio's AI agents run on PayPilot's LLM.** Studio ships an agent harness (lead, data, page, planning and widget
  agents) and calls no model itself; the host supplies an `AgLlmAdapter`.
  [`lib/studio/llm-adapter.ts`](../frontend/src/lib/studio/llm-adapter.ts) posts each turn to
  `POST /api/v1/integrations/studio/ai/turn`, where
  [`services/integrations/studio_ai.py`](../backend/app/services/integrations/studio_ai.py) translates Studio's
  Responses-style items to chat completions and runs them on Groq or any OpenAI-compatible provider
  (`STUDIO_AI_*`). The key never reaches the browser, and the agents' tools act on the dashboard only.
* **Quota:** Groq's free tier allows about 8,000 tokens per minute and Studio's delegate agents carry 5-9k tokens of
  tool schemas per turn. The backend waits out `429`s and shrinks the answer budget on `413`, but full runs need a
  paid tier, so the assistant is off on the hosted demo (`STUDIO_AI_ENABLED=false`).
* **Licence:** without `NEXT_PUBLIC_AG_STUDIO_LICENSE_KEY` Studio runs in evaluation mode with a watermark.
* **Version pinning:** both AG Grid packages must match the version AG Studio requires (`36.3.0`). A mismatch loads
  two copies of `ag-grid-community` and Studio renders a blank canvas.

---

## Bryntum Gantt

`/supply/timeline` shows each procurement as a parent task whose children are the stages that actually happened,
chained finish-to-start: RFQ and negotiation -> approval -> purchase order and delivery -> invoice -> PayPal
payment. Goods receipts are milestones, so a partial delivery is two diamonds and a half-filled bar. A blocked
stage (rejected approval, invoice discrepancy, overdue delivery) is red.

| Aspect | Implementation |
| --- | --- |
| Data | `GET /api/v1/supply/timeline` ([`services/supply/timeline.py`](../backend/app/services/supply/timeline.py)), mapped by a unit-tested pure function |
| Read-only by design | Every task is `manuallyScheduled`; nothing can imply a commitment the backend did not make |
| Planned vs actual | `baselinesFeature`: a grey bar under a stage shows the window it was committed to (RFQ deadline, approval expiry, expected delivery). Sent only where such a date was recorded |
| Agent-driven rescheduling | A supplier agent's signed `DELIVERY_UPDATE` (status `DELAYED`) moves the delivery and the PayPal payment that waits on it; both turn red and planned-vs-actual switches on. See [Supply Agents: delivery delays](SUPPLY_AGENTS.md#delivery-delays) |
| Today line | `timeRangesFeature` with `showCurrentTimeLine` |
| Updates | Data sits on a `BryntumGanttProjectModel`, so the 30-second refetch syncs the task store by id |
| Theming | Structural `gantt.css`, the `stockholm` theme, then `procurement-gantt.css` mapping Bryntum's variables to PayPilot's design tokens for light and dark |
| Packages | `@bryntum/gantt-react-enterprise`, `@bryntum/gantt-enterprise`, `@bryntum/core-enterprise` 8.0.0, pinned exactly. `@bryntum/scheduler-enterprise` is imported for the `timeRanges` feature. All `@bryntum/*` packages must share one version and tier |
| Licence | `NEXT_PUBLIC_BRYNTUM_LICENSE_KEY`, baked in at build time. Without it the Enterprise package runs as a 14-day trial; a trial key runs to its end date; both show a Trial badge |

---

## Bryntum Scheduler

`/finance/subscriptions/radar` puts every PayPal subscriber on one timeline with
`@bryntum/scheduler-react-enterprise` 8.0.0.

* One row per subscriber, one bar per billing period. Before the Today line: collected periods (green), failed
  charges (red), PayPal's retries and suspensions as milestones. After it: projected renewals, at-risk renewals of
  subscribers with failed payments (dashed amber) and paused renewals (dashed grey).
* Rows sorted by risk; tiles for MRR, revenue renewing in 30 days, revenue at risk and recoveries.
* **Recover payment** runs the real subscription action (`activate`) and the row redraws with a Recovered marker.
* Data: `GET /api/v1/paypal/subscriptions/radar` ([`services/paypal/radar.py`](../backend/app/services/paypal/radar.py)),
  derived only from subscription records and their history; it never invents a payment.
* Read-only: drag, resize, the event editor and context menus are off.

---

## APIMatic

PayPilot uses APIMatic in two directions.

**Consuming.** Supplier payments (Orders v2 create, get, capture) run on PayPal's APIMatic-generated Server SDK,
`paypal-server-sdk` 2.4.0, written with the APIMatic PayPal Context Plugin. What the plugin's guidance changed in the
code is listed in [PayPal: on the APIMatic-generated Server SDK](PAYPAL.md#on-the-apimatic-generated-server-sdk).
`GET /integrations/status` reports the APIMatic row as `SDK` when `PAYPAL_ORDERS_VIA_SDK=true`.

**Publishing.** PayPilot's own API is an APIMatic project in [`apimatic/`](../apimatic): an OpenAPI 3.0.3 spec
that passes `apimatic api validate` with 0 errors, four guides (authentication, procure-to-pay, the supplier-agent
protocol, money controls), Python and TypeScript SDKs and a PayPilot Context Plugin, so an external supplier agent
can integrate with PayPilot the way PayPilot integrated with PayPal. Build and usage:
[API portal and SDKs](APIMATIC.md).

---

## Render and Redis

[`render.yaml`](../render.yaml) defines the whole product on Render's free plan: the API (Docker, with the event
relays in-process), the web app, Postgres 16 with pgvector, a private Key Value instance, n8n and the static
APIMatic portal. Environment groups carry generated secrets, and `fromDatabase` / `fromService` references wire the
connection strings. Deployment steps and free-plan behaviour: [Deployment: Render Blueprint](DEPLOYMENT.md#render-blueprint).

Redis (Render Key Value in production, `redis:7-alpine` in Compose) carries the shared rate-limit counters, the
per-merchant Channel3 call budget, Channel3 caches and realtime pub/sub. It is never a source of truth; when it is
unreachable a circuit breaker switches to in-process state for `REDIS_RETRY_SECONDS`.
See [Configuration: Redis](CONFIGURATION.md#redis).

---

## Elasticsearch

`/search` is one ranked evidence search over the audit log, signed agent messages, negotiation offers,
procurements, supplier invoices, business events and reviews. Each source requires the permission that protects
it. With `ELASTIC_URL` set, *Re-index* (`POST /integrations/search/reindex`, `settings:manage`) bulk-upserts
idempotently (`merchant:kind:ref` ids) and search runs a `multi_match` that is always filtered by `merchant_id`.
Without it, the same documents are scored in-process and the screen says "Keyword fallback".

```bash
docker compose --profile search up -d elasticsearch     # then ELASTIC_URL=http://localhost:9200
```

Verified: request bodies, the tenant filter, bulk format and the fallback, against mocks and through the API.

---

## Kernel

`POST /api/v1/integrations/kernel/sessions` (`procurement:negotiate`) opens a Kernel cloud browser on a supplier's
public `https` page so the merchant can watch it live. Only `https` URLs on real public hostnames are accepted (no
raw IPs, localhost or credentials in the URL). It observes only: it never logs in, fills a form or pays. Sessions
expire on their own timeout, every open is audited, and the CDP socket is never sent to the browser.
`DELETE /integrations/kernel/sessions/{id}` closes a session on a best-effort basis.

---

## Zapier

Set `ZAPIER_WEBHOOK_URL` to a Webhooks by Zapier Catch Hook and these business events are delivered, signed
(`X-PayPilot-Signature: sha256=...`, `X-PayPilot-Event-Id` for de-duplication): revenue anomaly, stockout risk,
procurement required, supplier selected, purchase approved, payment reconciled, margin changed.

Delivery state is one `integration_deliveries` row per (event, target) with a unique constraint, so an event is
delivered at most once, a Zapier outage never disturbs n8n, retries back off exponentially, and enabling Zapier
never replays history older than a day. Zapier's MCP server is deliberately not connected: an agent able to
trigger arbitrary third-party actions would sit outside the approval gates. `GET /integrations/zapier` shows state;
`POST /integrations/zapier/test` sends a test event.

---

## Groq, Langfuse and Vapi

| Service | Role | Details |
| --- | --- | --- |
| Groq (`openai/gpt-oss-120b`, fallback `openai/gpt-oss-20b`) | Intent routing, narration, buyer-agent negotiation strategist, AG Studio agents | [Agents: LLM failure handling](AGENTS.md#llm-failure-handling), [Configuration: Groq](CONFIGURATION.md#llm-groq) |
| Langfuse | Traces for agent runs: node spans, LLM generations with token usage, tool spans | [Configuration: Langfuse](CONFIGURATION.md#langfuse) |
| Vapi | Voice assistant; server tools call the same agents as the web UI | [Agents: voice](AGENTS.md#voice), [Configuration: Vapi](CONFIGURATION.md#vapi-voice) |

---

## Postman

[`postman/PayPilot.postman_collection.json`](../postman/PayPilot.postman_collection.json) has 59 requests in eight
folders (Auth; Command and intelligence; Supply agents; Governance; Receiving, matching, payment; PayPal; Memory;
Integrations), with assertions, plus
[`PayPilot.local.postman_environment.json`](../postman/PayPilot.local.postman_environment.json). Checks include: a
write tool through the MCP bridge returns `403`, an unsafe Kernel URL returns `400`, and responses never contain
secrets. Run the Auth folder first; it stores the token for the rest.

---

## Integration status endpoint

`GET /api/v1/integrations/status` (`dashboard:read`) returns, for every integration above, its mode (`LIVE`,
`SANDBOX`, `SIMULATED`, `SDK`, off), what it is used for and where the code is. The `/integrations` page renders the
same data together with system checks (LLM, tracing, PayPal, Redis). It is the source of truth if this document
and the running app ever disagree.

---

<div align="center">

[Previous: PayPal integration](PAYPAL.md) | [Docs index](README.md) | [Next: Automation](AUTOMATION.md)

</div>
