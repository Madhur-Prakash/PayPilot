<div align="center">

# Configuration

[![Docs index](https://img.shields.io/badge/-Docs_index-475569?style=flat-square&logo=markdown&logoColor=white)](README.md)
[![Previous: Installation](https://img.shields.io/badge/-Previous:_Installation-64748b?style=flat-square)](INSTALLATION.md)
[![Next: Deployment](https://img.shields.io/badge/-Next:_Deployment-2563eb?style=flat-square)](DEPLOYMENT.md)
[![Agent memory](https://img.shields.io/badge/-Agent_memory-7c3aed?style=flat-square)](MEMORY.md)
[![Automation](https://img.shields.io/badge/-Automation-b45309?style=flat-square)](../n8n/README.md)

</div>

Everything is environment-driven. Nothing is hardcoded — not the model name, not a
merchant id, not a secret. The full template is
[`.env.example`](../.env.example).

---

## Contents

- [How configuration loads](#how-configuration-loads)
- [Core application](#core-application)
- [Database](#database)
- [Authentication and JWT](#authentication-and-jwt)
- [Groq (LLM)](#groq-llm)
- [Embeddings](#embeddings)
- [Langfuse (observability)](#langfuse-observability)
- [Vapi (voice)](#vapi-voice)
- [Supabase](#supabase)
- [External signals](#external-signals)
- [Networking and rate limiting](#networking-and-rate-limiting)
- [Demo seed](#demo-seed)
- [Frontend variables](#frontend-variables)
- [Verifying configuration](#verifying-configuration)

---

## How configuration loads

[`app/core/config.py`](../backend/app/core/config.py) defines a single
`Settings` object built with `pydantic-settings`. Values are read, in order of
precedence:

1. Actual environment variables
2. `.env` at the repository root

There is exactly one `.env`, at the root, and both halves of the project read it.

Everything else imports `settings` from that module. There is no second source of
truth, and no module reads `os.environ` directly.

The frontend reads the same root `.env` - `frontend/next.config.ts` parses it and
seeds `process.env` before the build. Only `NEXT_PUBLIC_*` variables reach the
browser, and those are compiled into the bundle, so **never put a secret behind a
`NEXT_PUBLIC_` name**.

---

## Core application

```dotenv
APP_ENV=development          # development | test | staging | production
APP_NAME=paypilot
APP_VERSION=1.0.0
DEBUG=true
LOG_LEVEL=INFO               # DEBUG | INFO | WARNING | ERROR
LOG_FORMAT=console           # console | json
LOG_CONSOLE_LOGIFYX=true    # false to use the built-in console renderer
```

| Variable | Notes |
| --- | --- |
| `APP_ENV` | `production` disables debug detail in error responses and enables HSTS |
| `DEBUG` | When true and not production, error responses include the exception type. Stack traces never leave the process |
| `LOG_FORMAT` | `console` gives readable dev output with structured fields; `json` emits one JSON object per line |
| `LOG_CONSOLE_LOGIFYX` | Render stdout with Logifyx's coloured layout. Set `false` for the built-in renderer. Ignored when Logifyx is absent or `LOG_FORMAT=json` |

> `LOG_FORMAT=json` is what you want in any deployed environment — it is what log
> aggregators can parse. See [ARCHITECTURE.md](ARCHITECTURE.md#7-observability).

---

## Database

```dotenv
DATABASE_URL=postgresql+asyncpg://autopilot:autopilot@localhost:5433/autopilot
DB_ECHO=false
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
```

| Variable | Notes |
| --- | --- |
| `DATABASE_URL` | Must use the `+asyncpg` driver. Port **5433** for the bundled Docker Postgres |
| `DB_ECHO` | Logs every SQL statement. Useful once, noisy always |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | Ignored when a connection pooler is detected |

### Pooler detection

[`db/session.py`](../backend/app/db/session.py) inspects the URL. If it contains
`pooler.supabase` or `pgbouncer=true`, it switches to `NullPool` and sets
`statement_cache_size=0`, because asyncpg's implicit prepared-statement cache is
incompatible with transaction-pooling mode. You do not need to configure this.

---

## Authentication and JWT

```dotenv
JWT_SECRET=change-me
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=14
REFRESH_COOKIE_NAME=pga_refresh
REFRESH_COOKIE_SECURE=false
REFRESH_COOKIE_SAMESITE=lax
```

> **Warning.** `JWT_SECRET` is the single most important value here. It signs
> access tokens **and** keys the HMAC that hashes refresh tokens. Generate one:
>
> ```bash
> python -c "import secrets; print(secrets.token_urlsafe(64))"
> ```
>
> Rotating it invalidates every existing session, which is the correct behaviour
> if it is ever exposed.

| Variable | Notes |
| --- | --- |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | Short on purpose. The refresh cookie handles continuity |
| `REFRESH_COOKIE_SECURE` | **Set `true` behind HTTPS.** Without it the cookie travels in plaintext |
| `REFRESH_COOKIE_SAMESITE` | `lax` suits same-site deployments. Use `none` (with `secure=true`) only if the frontend is on a different site |

Details: [SECURITY.md](SECURITY.md#authentication).

---

## Groq (LLM)

```dotenv
GROQ_API_KEY=
GROQ_MODEL=openai/gpt-oss-120b
GROQ_FALLBACK_MODEL=openai/gpt-oss-20b
GROQ_TIMEOUT_SECONDS=45
GROQ_MAX_RETRIES=2
GROQ_TEMPERATURE=0.2
GROQ_MAX_TOKENS=2048
```

**Entirely optional.** With no key, every agent node uses its deterministic
fallback and the product still produces the same figures, the same opportunity and
the same SCALE/STOP decision. Those runs are flagged `used_fallback: true` and
badged "Deterministic mode" in the UI.

### Enabling it

1. Get a key from [console.groq.com](https://console.groq.com).
2. Set `GROQ_API_KEY`.
3. Restart the backend.
4. Confirm: `curl -s localhost:8000/api/v1/health` shows `"llm": "configured"`.

### What changes

| | Without a key | With a key |
| --- | --- | --- |
| Metrics, opportunities, experiments, decisions | Identical | Identical |
| Intent routing | Keyword heuristic | Model classification |
| Hypothesis and explanation | Template with real figures | Natural language |
| Conversational answers | Structured summary | Full prose |

### Model selection

`GROQ_MODEL` is read from configuration everywhere; the name appears in no other
file. `GROQ_FALLBACK_MODEL` is tried if the primary fails after its retries.

Low `GROQ_TEMPERATURE` (0.2) is deliberate — this is a structured-extraction task,
not a creative one.

More: [AGENTS.md](AGENTS.md#llm-failure-handling).

---

## Embeddings

```dotenv
EMBEDDING_PROVIDER=hash        # hash | fastembed
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
EMBEDDING_DIMENSIONS=384
```

| Provider | Network | Determinism | Quality |
| --- | --- | --- | --- |
| `hash` (default) | None | Byte-identical everywhere | Lexical — matches shared vocabulary |
| `fastembed` | Downloads a model once | Stable after download | Genuine semantics |

The default is a hashed bag-of-ngrams projection with light stemming and
sub-word features. It is **lexical, not semantic**: it ranks well *within* a
filtered topic, which is how the agent uses it (`search_reviews` always passes a
topic), but it will not connect unrelated wordings.

Switch for real semantic search:

```dotenv
EMBEDDING_PROVIDER=fastembed
```

Then re-seed so stored vectors match: `make reseed`.

> **Warning.** Changing provider or `EMBEDDING_DIMENSIONS` invalidates every
> stored vector. `EMBEDDING_DIMENSIONS` also determines the `vector(N)` column
> width, so changing it requires a migration.

---

## Langfuse (observability)

```dotenv
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com
LANGFUSE_ENABLED=true
```

Optional. Absent keys produce a no-op tracer, so agent code never branches on
whether tracing is configured.

### Enabling it

1. Create a project at [cloud.langfuse.com](https://cloud.langfuse.com) (or
   self-host).
2. Set both keys.
3. Restart. `/api/v1/health` shows `"langfuse": "configured"`.
4. Run an investigation. Each agent run appears as a trace.

### What is captured

```
trace: growth_investigate
  |- span    growth_workflow
  |- generation  intent_classification    model, tokens, latency
  |- span    tool:get_growth_metrics      arguments, result, duration
  |- span    tool:get_customer_segments
  |- generation  growth_recommendation
  |- event   approval_executed
  `- output  opportunity, estimated_impact, confidence
```

Metadata on every trace: `merchant_id`, `user_id`, `agent_name`, `workflow`,
`environment`, `service`.

Payloads pass through the same redaction as the structured logger, so no secret
reaches Langfuse. The trace URL is stored on the agent run and surfaced as a link
in the Agent Trace UI.

---

## Vapi (voice)

```dotenv
VAPI_PUBLIC_KEY=
VAPI_PRIVATE_KEY=
VAPI_ASSISTANT_ID=
VAPI_WEBHOOK_SECRET=
```

Optional. Without it the "Talk to Growth Scientist" button stays visible and
explains what is missing rather than disappearing.

### Enabling it

1. Create an assistant at [dashboard.vapi.ai](https://dashboard.vapi.ai).
2. Set `VAPI_PUBLIC_KEY`, `VAPI_PRIVATE_KEY`, `VAPI_ASSISTANT_ID`.
3. Fetch the configuration to paste in:

   ```bash
   curl -s localhost:8000/api/v1/voice/assistant-config \
     -H "Authorization: Bearer $TOKEN" | python -m json.tool
   ```

   Returns the system prompt and four tool definitions.
4. In the Vapi dashboard set the **server URL** to
   `https://your-host/api/v1/voice/tool` and forward the session token as an
   `Authorization: Bearer` header.
5. Set `VAPI_WEBHOOK_SECRET` and configure the same secret in Vapi.
6. Mirror `VAPI_PUBLIC_KEY` and `VAPI_ASSISTANT_ID` into the root `.env` as
   `NEXT_PUBLIC_VAPI_*`.

### How the security works

`GET /voice/session` issues a **30-minute scoped token** carrying
`scope: "voice"`. Vapi presents it on each tool call, so every voice request is
authenticated and merchant-scoped exactly like a web request. The webhook is
**rejected when no secret is configured**, rather than trusted.

Voice tools route into the *same* backend agents as the web UI — there is one
implementation of the business logic. The assistant is explicitly instructed that
it may recommend but never approve or execute.

---

## Supabase

```dotenv
SUPABASE_URL=
SUPABASE_ANON_KEY=
```

Supabase provides **PostgreSQL and pgvector only**. Authentication is implemented
in FastAPI, per the brief — Supabase Auth is not used as the application's auth
abstraction.

Setup: [DEPLOYMENT.md](DEPLOYMENT.md#supabase).

---

## External signals

```dotenv
EXTERNAL_SEARCH_PROVIDER=seed    # seed | tavily
TAVILY_API_KEY=
```

| Provider | Behaviour |
| --- | --- |
| `seed` (default) | Signals come from the merchant's seeded `external_signals`, scored against real revenue exposure |
| `tavily` | Live web search, when `TAVILY_API_KEY` is set |

With `seed`, the core demo never depends on the network. Either way a signal is
only surfaced when it ties to the merchant's actual exposure — this is
deliberately not a news feed.

---

## Networking and rate limiting

```dotenv
FRONTEND_URL=http://localhost:3000
BACKEND_URL=http://localhost:8000
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS=300
RATE_LIMIT_WINDOW_SECONDS=60
```

| Variable | Notes |
| --- | --- |
| `CORS_ORIGINS` | Comma-separated. Credentials are allowed, so wildcards are not |
| `RATE_LIMIT_*` | Sliding window, **in-process**. See the warning below |
| `BACKEND_URL` | Used to build the Vapi server-tool URL |

> **Warning.** Rate limiting uses an in-memory counter, so each worker keeps its
> own. With four workers the effective limit is four times the configured value.
> For production, swap the `_hits` store in
> [`core/middleware.py`](../backend/app/core/middleware.py) for Redis. The seam is
> there for exactly this.

---

## Demo seed

```dotenv
SEED_RANDOM_SEED=20240917
DEMO_OWNER_EMAIL=owner@juniperoak.com
DEMO_OWNER_PASSWORD=Autopilot@2024
DEMO_MERCHANT_NAME=Juniper & Oak Coffee
```

Changing `SEED_RANDOM_SEED` produces a different but equally valid dataset. The
tuned figures documented in [DATA.md](DATA.md#what-comes-out) apply to `20240917`.

> Verify any change with `make calibrate` before re-seeding — it measures the
> generated dataset in about three seconds, against roughly a minute for a seed.

---

## Frontend variables

the root `.env`:

```dotenv
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
NEXT_PUBLIC_APP_NAME=PayPilot
NEXT_PUBLIC_DEMO_EMAIL=owner@juniperoak.com
NEXT_PUBLIC_DEMO_PASSWORD=Autopilot@2024
NEXT_PUBLIC_VAPI_PUBLIC_KEY=
NEXT_PUBLIC_VAPI_ASSISTANT_ID=
```

| Variable | Notes |
| --- | --- |
| `NEXT_PUBLIC_API_URL` | Must include `/api/v1`. Change it if you moved the backend port |
| `NEXT_PUBLIC_DEMO_*` | Prefills the login form so a reviewer is not hunting for credentials. Remove for any real deployment |

> **Warning.** `NEXT_PUBLIC_*` values are **compiled into the browser bundle**.
> Never put a private key, a secret, or a database URL here. The Vapi *public*
> key is designed to be public; the private key is not and stays server-side.

`make env` writes this file if it is missing, matching whatever `PORT` you use.

---

## Verifying configuration

### Health endpoint

```bash
curl -s localhost:8000/api/v1/health | python -m json.tool
```

`checks` reports each integration as `configured` or `not_configured`.

### Settings screen

Sign in as Owner and open **Settings -> Integrations** for the same information,
plus the active embedding provider and logging backend.

### From Python

```bash
cd backend && ./.venv/Scripts/python.exe -c "
from app.core.config import settings
print('env      :', settings.app_env)
print('database :', settings.database_url.split('@')[-1])
print('llm      :', settings.llm_enabled, settings.groq_model)
print('langfuse :', settings.langfuse_active)
print('vapi     :', settings.vapi_active)
print('embedding:', settings.embedding_provider, settings.embedding_dimensions)
print('cors     :', settings.cors_origins)
"
```

---

## Full variable reference

| Variable | Default | Required | Section |
| --- | --- | :--: | --- |
| `APP_ENV` | `development` | | [Core](#core-application) |
| `APP_NAME` | `paypilot` | | [Core](#core-application) |
| `APP_VERSION` | `1.0.0` | | [Core](#core-application) |
| `DEBUG` | `true` | | [Core](#core-application) |
| `LOG_LEVEL` | `INFO` | | [Core](#core-application) |
| `LOG_FORMAT` | `console` | | [Core](#core-application) |
| `LOG_CONSOLE_LOGIFYX` | `true` | | [Core](#core-application) |
| `DATABASE_URL` | local Docker | **yes** | [Database](#database) |
| `DB_ECHO` | `false` | | [Database](#database) |
| `DB_POOL_SIZE` | `10` | | [Database](#database) |
| `DB_MAX_OVERFLOW` | `20` | | [Database](#database) |
| `JWT_SECRET` | placeholder | **yes** | [Auth](#authentication-and-jwt) |
| `JWT_ALGORITHM` | `HS256` | | [Auth](#authentication-and-jwt) |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | | [Auth](#authentication-and-jwt) |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | `14` | | [Auth](#authentication-and-jwt) |
| `REFRESH_COOKIE_NAME` | `pga_refresh` | | [Auth](#authentication-and-jwt) |
| `REFRESH_COOKIE_SECURE` | `false` | | [Auth](#authentication-and-jwt) |
| `REFRESH_COOKIE_SAMESITE` | `lax` | | [Auth](#authentication-and-jwt) |
| `GROQ_API_KEY` | empty | | [Groq](#groq-llm) |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | | [Groq](#groq-llm) |
| `GROQ_FALLBACK_MODEL` | `openai/gpt-oss-20b` | | [Groq](#groq-llm) |
| `GROQ_TIMEOUT_SECONDS` | `45` | | [Groq](#groq-llm) |
| `GROQ_MAX_RETRIES` | `2` | | [Groq](#groq-llm) |
| `GROQ_TEMPERATURE` | `0.2` | | [Groq](#groq-llm) |
| `GROQ_MAX_TOKENS` | `2048` | | [Groq](#groq-llm) |
| `EMBEDDING_PROVIDER` | `hash` | | [Embeddings](#embeddings) |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | | [Embeddings](#embeddings) |
| `EMBEDDING_DIMENSIONS` | `384` | | [Embeddings](#embeddings) |
| `LANGFUSE_PUBLIC_KEY` | empty | | [Langfuse](#langfuse-observability) |
| `LANGFUSE_SECRET_KEY` | empty | | [Langfuse](#langfuse-observability) |
| `LANGFUSE_HOST` | cloud | | [Langfuse](#langfuse-observability) |
| `LANGFUSE_ENABLED` | `true` | | [Langfuse](#langfuse-observability) |
| `VAPI_PUBLIC_KEY` | empty | | [Vapi](#vapi-voice) |
| `VAPI_PRIVATE_KEY` | empty | | [Vapi](#vapi-voice) |
| `VAPI_ASSISTANT_ID` | empty | | [Vapi](#vapi-voice) |
| `VAPI_WEBHOOK_SECRET` | empty | | [Vapi](#vapi-voice) |
| `SUPABASE_URL` | empty | | [Supabase](#supabase) |
| `SUPABASE_ANON_KEY` | empty | | [Supabase](#supabase) |
| `EXTERNAL_SEARCH_PROVIDER` | `seed` | | [Signals](#external-signals) |
| `TAVILY_API_KEY` | empty | | [Signals](#external-signals) |
| `FRONTEND_URL` | `localhost:3000` | | [Networking](#networking-and-rate-limiting) |
| `BACKEND_URL` | `localhost:8000` | | [Networking](#networking-and-rate-limiting) |
| `CORS_ORIGINS` | localhost | **yes** | [Networking](#networking-and-rate-limiting) |
| `RATE_LIMIT_ENABLED` | `true` | | [Networking](#networking-and-rate-limiting) |
| `RATE_LIMIT_REQUESTS` | `300` | | [Networking](#networking-and-rate-limiting) |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | | [Networking](#networking-and-rate-limiting) |
| `SEED_RANDOM_SEED` | `20240917` | | [Seed](#demo-seed) |
| `DEMO_OWNER_EMAIL` | `owner@juniperoak.com` | | [Seed](#demo-seed) |
| `DEMO_OWNER_PASSWORD` | `Autopilot@2024` | | [Seed](#demo-seed) |
| `DEMO_MERCHANT_NAME` | `Juniper & Oak Coffee` | | [Seed](#demo-seed) |

---

<div align="center">

[Docs index](README.md) · [Installation](INSTALLATION.md) ·
[Deployment](DEPLOYMENT.md) · [Security](SECURITY.md) ·
[Troubleshooting](TROUBLESHOOTING.md)

</div>
