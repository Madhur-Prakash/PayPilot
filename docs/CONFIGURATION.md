<div align="center">

# Configuration

Every environment variable PayPilot reads, what it does, its default, and how to enable each integration.

[![Docs index](https://img.shields.io/badge/-Docs_index-0b2a6f?style=flat-square)](README.md)
[![Installation](https://img.shields.io/badge/-Installation-16a34a?style=flat-square)](INSTALLATION.md)
[![Deployment](https://img.shields.io/badge/-Deployment-46E3B7?style=flat-square)](DEPLOYMENT.md)
[![Security](https://img.shields.io/badge/-Security-dc2626?style=flat-square)](SECURITY.md)
[![PayPal](https://img.shields.io/badge/-PayPal-003087?style=flat-square&logo=paypal&logoColor=white)](PAYPAL.md)

</div>

---

## Contents

- [How configuration loads](#how-configuration-loads)
- [What runs without keys](#what-runs-without-keys)
- [Application](#application)
- [Database](#database)
- [Authentication](#authentication)
- [Networking and rate limiting](#networking-and-rate-limiting)
- [Redis](#redis)
- [PayPal](#paypal)
- [LLM (Groq)](#llm-groq)
- [AG Studio AI assistant](#ag-studio-ai-assistant)
- [Embeddings and agent memory](#embeddings-and-agent-memory)
- [Channel3 and product discovery](#channel3-and-product-discovery)
- [Supply agents and procurement](#supply-agents-and-procurement)
- [Inventory automation, outbox and n8n](#inventory-automation-outbox-and-n8n)
- [Optional integrations](#optional-integrations)
- [Langfuse](#langfuse)
- [Vapi voice](#vapi-voice)
- [Email (Gmail API)](#email-gmail-api)
- [Demo seed](#demo-seed)
- [Frontend variables](#frontend-variables)
- [Verifying configuration](#verifying-configuration)

---

## How configuration loads

[`backend/app/core/config.py`](../backend/app/core/config.py) defines one `Settings` object built with
`pydantic-settings`. Values are read from, in order of precedence:

1. Process environment variables.
2. The `.env` file at the **repository root**.

There is exactly one `.env` and both halves of the project read it. The frontend's
[`next.config.ts`](../frontend/next.config.ts) parses the same file before the build. Only variables named
`NEXT_PUBLIC_*` reach the browser, and they are compiled into the bundle at build time, so a secret must never
have that prefix.

`make env` creates `.env` from [`.env.example`](../.env.example) and never overwrites an existing file. The
copy works as-is.

A few conveniences are applied to values as they load:

* `DATABASE_URL` starting with `postgres://` or `postgresql://` is rewritten to `postgresql+asyncpg://`, and
  `sslmode=require` becomes asyncpg's `ssl=require`. Managed providers (Render, Supabase) can be pasted directly.
* `CORS_ORIGINS` accepts a comma-separated list.
* Secrets left blank that need a value (`AGENT_PROTOCOL_SECRET`, `ZAPIER_SIGNING_SECRET`,
  `PAYPAL_SIMULATOR_WEBHOOK_SECRET`) are derived from `JWT_SECRET` with a distinct label per purpose.

---

## What runs without keys

| Feature | Without its key | With it |
| --- | --- | --- |
| PayPal | Deterministic simulator; every id starts `SIM-`; rows and badges say `SIMULATED` | Real sandbox or live calls; rows say `SANDBOX` or `LIVE` |
| Agents | Every LangGraph node takes its deterministic path; runs are labelled "Deterministic mode" | Groq routes intents and writes the prose; numbers are unchanged |
| Product Discovery, Supply Intelligence | Routes answer `503 CHANNEL3_NOT_CONFIGURED` with setup steps; no invented products | Live Channel3 catalog |
| Gear shelf, market reference | Labelled `SIMULATED` reference catalogue | Live Channel3 results |
| Rate limits, caches, realtime | In-process | Shared through Redis |
| Evidence search | In-process keyword ranking, labelled "Keyword fallback" | Elasticsearch |
| Event delivery to n8n | Events recorded, marked `SKIPPED` | Signed delivery to the n8n webhook |
| Email | Rendered to the log | Sent through the Gmail API |
| Tracing, voice | Off | Langfuse traces, Vapi assistant |

---

## Application

| Variable | Default | Notes |
| --- | --- | --- |
| `APP_ENV` | `development` | `development`, `test`, `staging` or `production`. `production` enables HSTS and removes exception detail from error responses |
| `APP_NAME` | `paypilot` | Service name in logs |
| `APP_VERSION` | `1.0.0` | Reported by `/health` |
| `DEBUG` | `true` | When true outside production, error responses include the exception type. Stack traces never leave the process |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `LOG_FORMAT` | `console` | `console` for readable development output, `json` for one JSON object per line (use in any deployment) |
| `LOG_CONSOLE_LOGIFYX` | `true` | Use Logifyx's coloured console layout when installed; ignored with `LOG_FORMAT=json` |

---

## Database

| Variable | Default | Notes |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://autopilot:autopilot@localhost:5433/autopilot` | Required. The default is the Compose Postgres on host port 5433 |
| `DB_ECHO` | `false` | Log every SQL statement |
| `DB_POOL_SIZE` | `10` | Ignored when a pooler is detected |
| `DB_MAX_OVERFLOW` | `20` | Ignored when a pooler is detected |

If the URL contains `pooler.supabase` or `pgbouncer=true`,
[`db/session.py`](../backend/app/db/session.py) switches to `NullPool` and disables asyncpg's prepared-statement
cache, which transaction-mode poolers do not support.

---

## Authentication

| Variable | Default | Notes |
| --- | --- | --- |
| `JWT_SECRET` | `insecure-development-secret-change-me` | **Change for anything that is not your laptop.** Signs access tokens and keys the HMAC that stores refresh tokens. Rotating it signs everyone out |
| `JWT_ALGORITHM` | `HS256` | |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access tokens are short-lived; the refresh cookie provides continuity |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | `14` | |
| `REFRESH_COOKIE_NAME` | `pga_refresh` | |
| `REFRESH_COOKIE_SECURE` | `false` | Set `true` behind HTTPS |
| `REFRESH_COOKIE_SAMESITE` | `lax` | `lax` when frontend and API share a site; `none` (with `SECURE=true`) when they do not |

Generate a secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Details: [Security: tokens](SECURITY.md#tokens).

---

## Networking and rate limiting

| Variable | Default (`.env.example`) | Notes |
| --- | --- | --- |
| `FRONTEND_URL` | `http://localhost:3000` | Used in links the backend generates (PayPal return URLs, emails) |
| `BACKEND_URL` | `http://localhost:8000` | Public API URL; used to build the Vapi server-tool URL and PayPal webhook hints |
| `CORS_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Exact origins. Credentials are allowed, so wildcards are not. Localhost and ngrok origins are also accepted by a fixed pattern for development |
| `RATE_LIMIT_ENABLED` | `true` | |
| `RATE_LIMIT_REQUESTS` | `300` | Requests per caller per window |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | |

The limiter keys on the bearer token when present and the client address otherwise. Health probes and CORS
preflight are exempt. Responses carry `X-RateLimit-Limit` and `X-RateLimit-Remaining`; a `429` carries
`Retry-After`.

---

## Redis

Optional. With `REDIS_URL` set, four things move from process memory to Redis:

| What | Code | Why it matters |
| --- | --- | --- |
| HTTP rate-limit counters | [`core/ratelimit.py`](../backend/app/core/ratelimit.py) | One budget across workers and restarts |
| Per-merchant Channel3 call budget (40 per minute) | [`services/discovery/service.py`](../backend/app/services/discovery/service.py) | Survives restarts and deploys |
| Channel3 response caches | [`core/cache.py`](../backend/app/core/cache.py) | Every miss spends Channel3 credits |
| Realtime events | [`api/realtime.py`](../backend/app/api/realtime.py) | Pub/sub reaches browsers connected to any API instance |

Redis is never a source of truth, so it needs no persistence. It is never a hard dependency either: when it is
blank or down, every feature falls back to in-process state, and a circuit breaker skips Redis for
`REDIS_RETRY_SECONDS` after a failure. `GET /api/v1/health` reports `checks.redis` as `ok`, `unreachable` or
`not_configured` and never degrades `status` for it.

| Variable | Default | Notes |
| --- | --- | --- |
| `REDIS_URL` | blank | `redis://` or `rediss://`. Locally: `redis://localhost:6379/0` after `docker compose up -d redis` |
| `REDIS_KEY_PREFIX` | `paypilot` | Namespaces keys and channels so environments can share an instance |
| `REDIS_CONNECT_TIMEOUT_SECONDS` | `2` | Kept short so a slow Redis cannot slow requests |
| `REDIS_COMMAND_TIMEOUT_SECONDS` | `1.5` | |
| `REDIS_RETRY_SECONDS` | `15` | How long to use the fallback after a failure |
| `REALTIME_REDIS_ENABLED` | `true` | `false` keeps realtime process-local while Redis still serves the rest |

With Redis the limiter is a fixed window (`INCRBY` + `EXPIRE`, one small key per caller); without it, an
in-process sliding window.

---

## PayPal

| Variable | Default | Notes |
| --- | --- | --- |
| `PAYPAL_ENVIRONMENT` | `sandbox` | `sandbox` or `live` |
| `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` | blank | Blank = simulator. From developer.paypal.com, Apps and Credentials |
| `PAYPAL_WEBHOOK_ID` | blank | The id PayPal assigns to `https://<backend>/api/v1/paypal/webhooks`. Without it real webhooks are rejected (fail closed) |
| `PAYPAL_API_BASE_URL` | blank | Override the API host (proxy or mock). Derived from the environment when blank |
| `PAYPAL_TIMEOUT_SECONDS` | `30` | |
| `PAYPAL_MAX_RETRIES` | `2` | Retries on 429, 5xx and transport errors, honouring `Retry-After` |
| `PAYPAL_ORDERS_VIA_SDK` | `true` | Orders v2 create, get and capture through PayPal's APIMatic-generated Server SDK; `false` uses the hand-written REST client. Ignored when `PAYPAL_API_BASE_URL` is set |
| `PAYPAL_SIMULATION_ENABLED` | `true` | Allow the simulator when no credentials are set |
| `PAYPAL_BRAND_NAME` | `PayPilot` | Shown on PayPal approval pages |
| `DEFAULT_CURRENCY` | `USD` | |
| `PAYPAL_SIMULATOR_WEBHOOK_SECRET` | blank | Signs simulator webhooks; derived from `JWT_SECRET` when blank |
| `PAYPAL_SANDBOX_PAYEE_EMAIL` | blank | A sandbox business account the seeded supplier agents use as payee, so supplier payments complete end to end |
| `PAYPAL_MCP_ENABLED` | `true` | Read-only bridge to PayPal's Agent Toolkit MCP server |
| `PAYPAL_MCP_URL` | blank | Derived from the environment (`https://mcp.sandbox.paypal.com/sse` or the live host). A URL not ending in `/sse` is treated as Streamable HTTP |

Sandbox setup step by step: [PayPal: using the sandbox](PAYPAL.md#using-the-sandbox).

---

## LLM (Groq)

Optional. Without a key every agent node uses its deterministic path and produces the same figures, the same
recommendation and the same experiment decision; only the wording is simpler.

| Variable | Default | Notes |
| --- | --- | --- |
| `GROQ_API_KEY` | blank | From console.groq.com |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Read from configuration everywhere; the id appears in no other file |
| `GROQ_FALLBACK_MODEL` | `openai/gpt-oss-20b` | Tried after the primary exhausts its retries |
| `GROQ_TIMEOUT_SECONDS` | `45` | |
| `GROQ_MAX_RETRIES` | `2` | Authentication errors are not retried |
| `GROQ_TEMPERATURE` | `0.2` | Low on purpose: structured extraction, not creative writing |
| `GROQ_MAX_TOKENS` | `2048` | |

| | Without a key | With a key |
| --- | --- | --- |
| Metrics, opportunities, limits, experiment decisions | Identical | Identical |
| Intent routing | Keyword table | Model classification |
| Hypotheses and explanations | Templates filled with the computed figures | Natural language |
| Buyer-agent counter-offers | Deterministic strategy | The model may propose; out-of-bounds proposals are refused |

Confirm with `curl -s localhost:8000/api/v1/health`: `checks.llm` is `configured`. See
[Agents: LLM failure handling](AGENTS.md#llm-failure-handling).

---

## AG Studio AI assistant

Dashboard Studio's agents run on any OpenAI-compatible chat-completions API, through the backend. The key never
reaches the browser.

| Variable | Default | Notes |
| --- | --- | --- |
| `STUDIO_AI_ENABLED` | `true` | `false` hides the assistant; the dashboard and editor still work |
| `STUDIO_AI_BASE_URL` | blank | Blank uses Groq with `GROQ_API_KEY` |
| `STUDIO_AI_API_KEY` | blank | |
| `STUDIO_AI_MODEL` | blank | Blank uses `GROQ_MODEL` |
| `STUDIO_AI_REASONING_EFFORT` | `low` | |

Groq's free tier (about 8,000 tokens per minute) is too small for Studio's delegate agents. Use a paid key or a
provider such as `https://api.openai.com/v1` or `https://openrouter.ai/api/v1`. See
[Integrations: AG Studio](INTEGRATIONS.md#ag-grid-and-ag-studio).

---

## Embeddings and agent memory

| Variable | Default | Notes |
| --- | --- | --- |
| `EMBEDDING_PROVIDER` | `hash` | `hash` needs nothing and is byte-identical everywhere (lexical). `fastembed` runs a local ONNX model (semantic) and needs `requirements-optional.txt` |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Used by `fastembed` |
| `EMBEDDING_DIMENSIONS` | `384` | Also the width of the `vector(N)` columns; changing it needs a migration |
| `MEMORY_ENABLED` | `true` | pgvector agent memory in `agent_memories`; no extra service |
| `MEMORY_RECALL_TOP_K` | `6` | |
| `MEMORY_RECALL_TIMEOUT_SECONDS` | `5` | Recall returns empty on timeout; memory never delays an answer |

Changing the provider changes the vector space. Re-seed (`make seed-reset`) so stored vectors match. See
[Agent memory](MEMORY.md).

---

## Channel3 and product discovery

| Variable | Default | Notes |
| --- | --- | --- |
| `CHANNEL3_API_KEY` | blank | Free key at trychannel3.com/developers. Server side only; never logged or returned |
| `CHANNEL3_BASE_URL` | `https://api.trychannel3.com` | |
| `CHANNEL3_TIMEOUT_SECONDS` | `30` | |
| `CHANNEL3_MAX_RETRIES` | `2` | 429, 5xx and network errors only; 4xx never retried; conversation turns never retried |
| `CHANNEL3_CURRENCY` | `USD` | Channel3 prices in USD, CAD, AUD, GBP, EUR, SEK, CZK, RON |
| `CHANNEL3_COUNTRY` | `US` | |
| `DISCOVERY_FX_PER_USD` | `INR:88,JPY:150,CNY:7.2,SGD:1.35,AED:3.67` | Reference rates for budgets in currencies Channel3 does not price in; every converted search is labelled |
| `DISCOVERY_DETAIL_CACHE_SECONDS` | `600` | How long a fetched product detail is reused |

Verify the key with `make integrations`. See [Supply Intelligence](SUPPLY_INTELLIGENCE.md).

---

## Supply agents and procurement

| Variable | Default | Notes |
| --- | --- | --- |
| `AGENT_PROTOCOL_SECRET` | blank | HMAC root key for agent-to-agent messages; derived from `JWT_SECRET` when blank. Per-agent keys are derived from it |
| `PROCUREMENT_MAX_NEGOTIATION_ROUNDS` | `4` | |
| `PROCUREMENT_QUOTE_TTL_HOURS` | `48` | |
| `PROCUREMENT_DEFAULT_TARGET_MARGIN` | `0.40` | Sets the price ceiling: `selling price x (1 - margin)` |
| `PROCUREMENT_PRICE_TOLERANCE_PCT` | `0.02` | Three-way match unit-price tolerance |
| `PROCUREMENT_TOTAL_TOLERANCE_AMOUNT` | `1.00` | Three-way match total tolerance (USD) |

See [Supply Agents](SUPPLY_AGENTS.md).

---

## Inventory automation, outbox and n8n

| Variable | Default | Notes |
| --- | --- | --- |
| `INVENTORY_AUTOMATION_ENABLED` | `true` | |
| `INVENTORY_DRY_RUN` | `false` | Decide but do not raise purchase orders |
| `INVENTORY_APPROVAL_THRESHOLD` | `500` | Automatic reorders at or above this value (USD) wait for a human |
| `INVENTORY_DISPATCH_INTERVAL_SECONDS` | `15` | How often the outbox relay delivers events |
| `OUTBOX_RELAY_IN_PROCESS` | `true` | `true`: the API process runs the relays. `false`: run `python -m app.worker` |
| `N8N_INVENTORY_WEBHOOK_URL` | blank | Where the backend posts events, for example `http://localhost:5678/webhook/pga-inventory-event`. Blank = events recorded and marked `SKIPPED` |
| `N8N_WEBHOOK_SECRET` | blank | Shared HMAC secret, both directions. Blank = inbound automation fails closed |
| `N8N_BASE_URL` | `http://localhost:5678` | For "open in n8n" links |
| `N8N_API_KEY` | blank | |
| `N8N_BACKEND_URL_FOR_N8N` | `http://host.docker.internal:8000` | How n8n reaches the backend (read by the workflow builder) |
| `PGA_MERCHANT_ID` | blank | The merchant the scheduled sweeps run for (read by the workflow builder) |

Docker Compose sets the n8n values for you. See [Automation](AUTOMATION.md).

---

## Optional integrations

Blank means a labelled fallback, never a silent one. Details: [Integrations](INTEGRATIONS.md).

| Variable | Default | Notes |
| --- | --- | --- |
| `KERNEL_API_KEY`, `KERNEL_BASE_URL` | blank, `https://api.onkernel.com` | Observe-only supplier-page browser sessions |
| `ELASTIC_URL`, `ELASTIC_API_KEY`, `ELASTIC_INDEX_PREFIX` | blank, blank, `paypilot` | Evidence search. Local node: `docker compose --profile search up -d elasticsearch` |
| `ZAPIER_WEBHOOK_URL` | blank | A Webhooks by Zapier Catch Hook URL; treat it as a secret |
| `ZAPIER_SIGNING_SECRET` | blank | Signs Zapier deliveries; derived from `JWT_SECRET` when blank |
| `EXTERNAL_SEARCH_PROVIDER` | `seed` | `seed` uses the seeded external signals; `tavily` uses live web search |
| `TAVILY_API_KEY` | blank | Needed for `tavily` |
| `SUPABASE_URL`, `SUPABASE_ANON_KEY` | blank | Unused by default; Supabase is supported as a Postgres host only |
| `APIMATIC_API_KEY` | blank | Used only by `scripts/apimatic.*` and the Render docs site, never by the app. See [API portal and SDKs](APIMATIC.md) |

---

## Langfuse

| Variable | Default | Notes |
| --- | --- | --- |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | blank | Both needed |
| `LANGFUSE_BASE_URL` | `https://cloud.langfuse.com` | Must match your keys' region (US: `https://us.cloud.langfuse.com`). Overrides `LANGFUSE_HOST` |
| `LANGFUSE_ENABLED` | `true` | |

With keys set, each agent run becomes a trace with spans for graph nodes, generations for LLM calls (with token
usage) and spans for tool calls. Payloads pass through the same redaction as the logger. Without keys the tracer
is a no-op, so agent code never branches on it.

---

## Vapi voice

| Variable | Default | Notes |
| --- | --- | --- |
| `VAPI_PUBLIC_KEY`, `VAPI_PRIVATE_KEY`, `VAPI_ASSISTANT_ID` | blank | From dashboard.vapi.ai |
| `VAPI_WEBHOOK_SECRET` | blank | Shared secret Vapi presents on server-URL requests. Without it the webhook is rejected |
| `VAPI_SIGNATURE_HEADER` | `x-vapi-signature` | |
| `VAPI_SIGNATURE_ALGORITHM` | `sha256` | |

Setup:

1. Create an assistant in Vapi and set the keys above.
2. `GET /api/v1/voice/assistant-config` (needs `settings:manage`) returns the system prompt and tool
   definitions; `POST /api/v1/voice/sync` pushes them.
3. Set the assistant's server URL to `https://<backend>/api/v1/voice/tool`.
4. Mirror the public key and assistant id into `NEXT_PUBLIC_VAPI_PUBLIC_KEY` and `NEXT_PUBLIC_VAPI_ASSISTANT_ID`.

`GET /api/v1/voice/session` issues a 30-minute token scoped to voice, so every voice tool call is authenticated
and merchant-scoped like a web request. Voice tools call the same agents as the web UI and can never approve or
execute.

---

## Email (Gmail API)

| Variable | Default | Notes |
| --- | --- | --- |
| `GMAIL_CREDENTIALS_B64` | blank | Base64 OAuth credential. Mint it with `python backend/scripts/mint_gmail_token.py` |
| `GMAIL_SENDER` | blank | |
| `EMAIL_FROM_NAME` | `PayPilot` | |

Without credentials, invitations and vendor purchase-order emails are rendered to the log, and the purchase
order's "Notify vendor" step shows as declined. `POST /api/v1/settings/email/test` sends a test message.

---

## Demo seed

| Variable | Default | Notes |
| --- | --- | --- |
| `SEED_RANDOM_SEED` | `20240917` | Every figure in these docs is measured at this seed |
| `DEMO_OWNER_EMAIL` | `owner@juniperoak.com` | |
| `DEMO_OWNER_PASSWORD` | `Autopilot@2024` | |
| `DEMO_MERCHANT_NAME` | `Juniper & Oak Coffee` | |

Run `make calibrate` before re-seeding after any change; see [Data](DATA.md#calibration).

---

## Frontend variables

All compiled into the browser bundle at build time. Changing one requires a rebuild (or a dev server restart).

| Variable | Default | Notes |
| --- | --- | --- |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000/api/v1` | Must include `/api/v1` |
| `NEXT_PUBLIC_APP_NAME` | `PayPilot` | |
| `NEXT_PUBLIC_DEMO_EMAIL`, `NEXT_PUBLIC_DEMO_PASSWORD` | demo Owner | Prefill the login form. Remove for any real deployment |
| `NEXT_PUBLIC_VAPI_PUBLIC_KEY`, `NEXT_PUBLIC_VAPI_ASSISTANT_ID` | blank | The Vapi public key is designed to be public |
| `NEXT_PUBLIC_AG_STUDIO_LICENSE_KEY` | blank | Removes AG Studio's evaluation watermark |
| `NEXT_PUBLIC_BRYNTUM_LICENSE_KEY` | blank | Blank runs Bryntum's 14-day trial; a trial key runs to its end date; a purchased key removes the badge |

---

## Verifying configuration

| Check | Command |
| --- | --- |
| Tools, `.env`, PayPal mode, Groq and Channel3 keys | `make check` |
| Live Channel3 and PayPal sandbox credentials (no secrets printed) | `make integrations` |
| What the running API has wired | `curl -s localhost:8000/api/v1/health` |
| Which sponsor integrations are live and which are fallbacks | `GET /api/v1/integrations/status` or the `/integrations` page |

---

<div align="center">

[Previous: Installation](INSTALLATION.md) | [Docs index](README.md) | [Next: Deployment](DEPLOYMENT.md)

</div>
