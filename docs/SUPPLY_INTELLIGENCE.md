# Supply Intelligence, Product Discovery and the Merchant OS agents

PayPilot's merchant operating system connects three things:

| Layer | What it does here |
| --- | --- |
| **Channel3** | Live product intelligence - search, details, similar products, URL lookup, conversational shopping |
| **PayPilot's AI agents** | Understand the request, analyse the merchant's own data, rank, compare, recommend, orchestrate |
| **PayPal** | Payments for approved purchases - Orders v2 create / get / capture, verified webhooks |

Nothing in this module is simulated to look real. Without `CHANNEL3_API_KEY` the
Channel3-backed routes answer **503 `CHANNEL3_NOT_CONFIGURED`** with setup steps; without
PayPal credentials payments run on the existing simulator and every row says `SIMULATED`.

## Screens

| Screen | Route | What it shows |
| --- | --- | --- |
| Supply Intelligence | `/supply/intelligence` | Detected expansion opportunity, KPIs, Growth Autopilot, recommendations, assortment opportunities, category performance, inventory turnover, recently discovered products, market price comparisons |
| Product Discovery | `/discovery` | Natural-language search, "what I understood" panel, advanced filters, ranked product cards with reasons, similar products, URL enrichment, search history, compare tray |
| Product details | `/discovery/products/{id}` | Gallery, offers per retailer, variants, specifications, similar products, shortlist |
| Comparison | `/discovery/compare?ids=a,b,c` | Four evidence-backed verdicts and the full side-by-side matrix ("Not listed" where a retailer published nothing) |
| Shopping assistant | `/discovery/assistant` | Multi-turn conversation with Channel3's shopping agent; remembered constraints; live product results |
| Alternatives & prices | `/supply/market` | Alternatives to one of your products; your price vs live retail listings |
| AI Recommendations | `/recommendations` | Every recommendation with evidence, estimated impact + assumptions, confidence, lifecycle and controls |
| Agent Console | `/agents/console` | Ask the Merchant OS; routing, execution trace, tool calls; Agent Activity feed |
| Payment Management | `/finance/payment-management` | Approval workflow, PayPal orders, capture, order details, history |

The Command Center (`/command`) and Business Overview (`/dashboard`) show the detected
expansion opportunity at the top.

## Channel3 integration

`backend/app/integrations/sponsors/channel3_catalog.py` - one client, verified against
the live API on 2026-11-06 (and against the `channel3-api` agent skill in `.claude/skills`):

| Endpoint | Used for |
| --- | --- |
| `POST /v1/search` | Product discovery, assortment expansion, market prices, alternatives (title search) |
| `POST /v1/similar` | Similar products; a `404` (not yet indexed) falls back to a search by title, as documented |
| `GET /v1/products/{id}` | Product details (free call) - always re-fetched before prices/links are shown |
| `POST /v1/lookup` | URL enrichment |
| `GET /v1/categories/search` | Turning a category hint into a `category_ids` filter (filters beat query-stuffing) |
| `GET /v1/brands/search` | Turning a brand name into `brand_ids` (exact name match only) |
| `POST /v1/conversations` (`stream: false`) | The conversational shopping agent; budget pinned as a filter |

* **Auth** - `x-api-key`, server side only. Every merchant call carries an opaque
  `x-user-id: paypilot-<merchant>` for Channel3's click/sale attribution - never a name or email.
* **Reliability** - per-request timeout, bounded retries with exponential backoff and
  `Retry-After` on network errors, timeouts, 429 and 5xx; 4xx are never retried; a
  conversation turn is never retried (it is not idempotent).
* **Rate limiting** - the API-wide limiter plus 40 Channel3 calls / minute / merchant.
* **Normalisation** - only what Channel3 returned. Ratings appear only when Channel3 sends
  them; a missing specification stays missing; offer URLs (short-lived, affiliate-tracked)
  are never stored - snapshots in `discovered_products` drop them.
* **Currencies** - Channel3 prices in USD, CAD, AUD, GBP, EUR, SEK, CZK, RON. A budget in
  another currency ("under ₹5,000") is converted with the configurable reference rate in
  `DISCOVERY_FX_PER_USD`, and the response says so ("not a live exchange rate").

### From a sentence to ranked products

1. **Intent** (`services/discovery/intent.py`) - a deterministic parser extracts budget,
   currency, ranges, brands, exclusions, retailers, use case, features, sale/stock
   preferences. With `GROQ_API_KEY` an LLM may refine the *words* (product phrase,
   category hint, features); it cannot change a price, and a brand is accepted only if the
   merchant typed it.
2. **Request** - brands -> `brand_ids`, category hint -> `category_ids` (widened once,
   and labelled, if it returns fewer than 3 results), budget -> `price`, plus retailers,
   availability and sale filters.
3. **Ranking** (`services/discovery/ranking.py`) - a 0-100 score from Channel3 relevance,
   budget fit, availability, requested features, brand preference, retailer coverage,
   Channel3 ratings (only when >= 10 reviews) and - with an LLM and a stated use case -
   an AI use-case fit judged only from the returned facts. Components that do not apply are
   left out and the weights renormalised; every card lists its reasons.

### Comparison

`services/discovery/comparison.py` answers, with evidence:

* **Better value** - lowest in-stock price; rating-per-price only if *every* product has a rating.
* **More suitable specifications** - requested features first, then documented attributes and features.
* **Fits your customers** - closest to the merchant's own average order value and catalog
  price band (from their transactions).
* **Best alternative** - the closest runner-up (same category, shared specs, price gap).

## Supply Intelligence

* **Assortment analysis** (`services/supply_intel/analysis.py`) - SQL only: category and
  product performance vs the previous window, channel and daypart split, basket pairs,
  inventory turnover and days of cover, and **expansion candidates** - complementary slots
  next to products whose demand is real and rising (the coffee slots reuse the gear
  shelf's verified Channel3 category slugs).
* **Market price intelligence** (`pricing.py`) - your selling price vs comparable live
  listings, kept only when they cluster in one Channel3 category. Your unit cost is shown
  separately and labelled; retail prices never touch a budget or limit. Automatic checks
  cover retail products only (a cafe drink is not a bottled retail pack).
* **Alternatives** - your product -> closest Channel3 listing -> `/v1/similar`, with the
  difference to *your* price; any alternative can be saved as a recommendation.

### Recommendations and their lifecycle

```
DETECTED -> ANALYZED -> RECOMMENDED -> APPROVED -> EXECUTED -> MEASURED
                                   \-> REJECTED
```

| Field | Source |
| --- | --- |
| Evidence | SQL over your sales (buyers, units, growth, online share) and Channel3 (listings, median retail price, retailers) |
| Expected impact | Labelled **estimate**; assumptions listed (the attach rate is an assumption, not a measurement) |
| Suggested test quantity | Only when there are >= 10 buyers; bounded 6-48 |
| Confidence | Additive from data volume, rising demand, listings found, online share - each reason listed |
| Description | Deterministic; an LLM may reword it from the facts (numbers unchanged), marked "AI-written" |

Generation is idempotent: an open recommendation for the same slot is refreshed in place;
one a person decided in the last 14 days is not re-proposed.

* **Approve / reject** - `procurement:approve`. Rejections are written to agent memory as a
  signal not to re-propose without new evidence.
* **Execute** (no money) - assortment/alternative: add the product to the catalog
  (`C3-<id>` SKU, source recorded) so its sales can be measured; pricing: apply the
  capped price test.
* **Measure** - units, revenue and orders since execution from the transaction ledger
  (pricing: vs the same-length window before), the PayPal payment status, and attainment
  against the estimate to date. "No sales yet" is reported as such.

## Payments: AI-proposed purchases through PayPal

```
recommendation APPROVED
  -> POST /supply/recommendations/{id}/purchase   (person or PayPal Transaction Agent)  -> MERCHANT_PURCHASE approval, PENDING
  -> POST /approvals/{id}/decide                  (person with payment:approve)          -> terms re-hashed from live state
  -> POST /payments/orders                        (person with payment:execute)          -> PayPal Orders v2 create, idempotent
  -> payer approves at the PayPal approve link    (sandbox buyer account)
  -> POST /payments/capture                       (person with payment:execute)          -> order re-read; capture only if APPROVED
  -> PAYMENT.CAPTURE.COMPLETED webhook            (signature-verified, replay-guarded)   -> same settlement, idempotent
```

* The approval binds (SHA-256) the recommendation, Channel3 product, quantity, the
  supplier's unit cost (never a retail price), total, currency and payee. If the
  recommendation's product changes, the approval is **invalidated**, not granted.
* One live execution per approval: the idempotency key is derived from the approval
  (`merchant-purchase:<approval>:<attempt>`) and sent as `PayPal-Request-Id`; a double
  click returns the same order. A failed create re-opens the approval (no money moved).
* Rows reuse `approval_requests` and `financial_executions`, so they also appear in the
  Approvals inbox and the existing Payments ledger, with `SANDBOX` / `LIVE` / `SIMULATED`.
* Channel3 never provides checkout: retailer links go to the retailer's site.

## The Merchant OS agents

`backend/app/agents/merchant_os.py` - one LangGraph workflow, seven agents:

```
START -> orchestrator -> <specialist> -> synthesize -> approval_gate -> END
```

| Agent | Tools |
| --- | --- |
| Orchestrator | Routes: explicit choice, LLM classification, or keywords (deterministic fallback) |
| Business Intelligence | `get_sales_summary`, `get_product_performance`, `analyze_assortment`, `get_inventory_status` |
| Product Discovery | `discover_products`, `get_product_details`, `find_similar_products`, `compare_products` |
| Supply Intelligence | `analyze_assortment`, `discover_products`, `find_similar_products`, `list_supply_recommendations` |
| Pricing Intelligence | `get_market_price_intelligence`, `get_market_benchmark` |
| Growth Strategy (Growth Autopilot) | `analyze_assortment`, `generate_supply_recommendations`, `list_supply_recommendations`, `get_top_opportunity` |
| PayPal Transaction | `get_payment_history`, `get_paypal_transaction_insights`, `request_purchase_payment` (approval request only) |

Every call goes through the existing `ToolRegistry`: typed arguments, a permission check
against the person the agents act for, merchant scope, structured logs, Langfuse spans and
a row in `agent_tool_calls`. Transient tool failures are retried (up to 2, backoff). The
graph ends at the approval gate; **no agent can approve, create an order, capture or pay.**
The LLM may route and word answers; it is told to keep every number and verdict exactly
as the tools stated them.

The **Merchant Growth Autopilot** (`POST /growth/autopilot/run`) is the Growth Strategy
agent's workflow: analyse performance -> identify opportunities -> discover products on
Channel3 -> generate recommendations -> estimate impact -> present -> request approval.
Execution and measurement continue only from a person's click.

## API

All under `/api/v1`, merchant-scoped by membership, permission-gated.

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/supply/discovery/status` | `products:read` |
| POST | `/supply/search` | `products:read` |
| POST | `/supply/compare` | `products:read` |
| POST | `/supply/similar` | `products:read` |
| POST | `/supply/enrich` | `products:read` |
| GET | `/supply/products/{id}` · POST `/supply/products/{id}/shortlist` | `products:read` |
| GET | `/supply/searches` · `/supply/discovered` · `/supply/comparisons` | `products:read` |
| POST | `/supply/assistant` · GET `/supply/assistant/conversations[/{id}]` | `products:read` |
| GET | `/supply/intelligence` · `/supply/assortment` · `/supply/catalog-products` | `products:read` |
| POST | `/supply/pricing` · `/supply/alternatives` | `products:read` |
| POST | `/supply/alternatives/save` | `growth:recommend` |
| GET | `/supply/recommendations[/{id}]` | `growth:read` |
| POST | `/supply/recommendations/generate` · `/{id}/measure` | `growth:recommend` |
| POST | `/supply/recommendations/{id}/approve` · `/reject` · `/execute` | `procurement:approve` |
| POST | `/supply/recommendations/{id}/purchase` | `procurement:create` (creates an approval) |
| POST | `/growth/autopilot/run` · GET `/growth/autopilot` | `growth:recommend` + `agents:run` · `growth:read` |
| POST | `/agents/execute` | `agents:run` |
| GET | `/agents/activity` · `/agents/catalogue` | `agents:view` |
| POST | `/payments/orders` · `/payments/capture` | `payment:execute` |
| GET | `/payments/orders/{id}` · `/payments/history` | `paypal:read` |
| POST | `/payments/webhooks/paypal` | none - signature-verified (alias of `/paypal/webhooks`) |

## Persistence

Migration `0007_supply_intelligence` (additive - no existing table altered):
`product_searches`, `discovered_products`, `product_comparisons`,
`merchant_recommendations`, `shopping_conversations`. Agent runs, approvals and payments
reuse `agent_runs` / `agent_steps` / `agent_tool_calls`, `approval_requests` and
`financial_executions`.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `CHANNEL3_API_KEY` | blank | Enables everything above (free key at trychannel3.com/developers) |
| `CHANNEL3_BASE_URL` | `https://api.trychannel3.com` | |
| `CHANNEL3_TIMEOUT_SECONDS` / `CHANNEL3_MAX_RETRIES` | `30` / `2` | Per-request timeout, bounded retries |
| `CHANNEL3_CURRENCY` / `CHANNEL3_COUNTRY` | `USD` / `US` | Locale offers are priced in |
| `DISCOVERY_FX_PER_USD` | `INR:88,JPY:150,...` | Reference rates for budgets in other currencies (labelled) |
| `DISCOVERY_DETAIL_CACHE_SECONDS` | `600` | Product-detail reuse window |
| `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` / `PAYPAL_ENVIRONMENT=sandbox` | blank | Real sandbox orders; blank = labelled simulator |
| `PAYPAL_WEBHOOK_ID` | blank | Needed to accept real PayPal webhooks |
| `PAYPAL_SANDBOX_PAYEE_EMAIL` | blank | A sandbox business account to use as the supplier payee |
| `GROQ_API_KEY` | blank | Optional LLM (routing, wording, use-case fit); everything works without it |

`make integrations` verifies the Channel3 key and the PayPal sandbox credentials with one
lightweight call each, without printing a secret.

## Demo (Supply Intelligence path)

See [DEMO.md](DEMO.md#supply-intelligence-and-merchant-os-four-minutes).

## Tests

`tests/unit/test_channel3_catalog.py`, `tests/unit/test_discovery_engine.py`,
`tests/integration/test_supply_intelligence.py` - Channel3 is mocked at the HTTP transport
(the real client, request builder and parser run) and PayPal is the simulator. They cover
normalisation, documented filters, retries, no-key behaviour, intent parsing, currency
conversion, ranking, comparison, conversation memory, routing, the discovery API, RBAC,
tenant isolation, the full recommendation -> approval -> PayPal order -> capture -> webhook
path, approval invalidation on changed terms, recommendation generation and dedupe, and the
agents (including that the PayPal agent can request but never pay).
