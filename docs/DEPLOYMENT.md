<div align="center">

# Deployment

Running PayPilot beyond `localhost`: Docker Compose, the Render Blueprint, other container hosts, and what to
change before real traffic.

[![Docs index](https://img.shields.io/badge/-Docs_index-0b2a6f?style=flat-square)](README.md)
[![Configuration](https://img.shields.io/badge/-Configuration-2563eb?style=flat-square)](CONFIGURATION.md)
[![Security](https://img.shields.io/badge/-Security-dc2626?style=flat-square)](SECURITY.md)
[![Automation](https://img.shields.io/badge/-Automation-b45309?style=flat-square)](AUTOMATION.md)
[![Render](https://img.shields.io/badge/Render-Blueprint-46E3B7?style=flat-square&logo=render&logoColor=white)](../render.yaml)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white)](../docker-compose.yml)

</div>

---

## Contents

- [Deployment topology](#deployment-topology)
- [Before you deploy](#before-you-deploy)
- [Docker Compose](#docker-compose)
- [Render Blueprint](#render-blueprint)
- [Other platforms](#other-platforms)
- [Managed Postgres](#managed-postgres)
- [Migrations in production](#migrations-in-production)
- [Production checklist](#production-checklist)
- [Observability in production](#observability-in-production)
- [Scaling notes](#scaling-notes)
- [Backups and recovery](#backups-and-recovery)

---

## Deployment topology

Every deployment target runs the same five pieces. Only the API and Postgres are required.

```mermaid
flowchart LR
    B["Browser"] -->|HTTPS| WEB["Web app<br/>Next.js 15"]
    B -->|"HTTPS /api/v1, WebSocket"| API["API<br/>FastAPI, Docker"]
    API --> DB[("PostgreSQL 16<br/>+ pgvector")]
    API -.->|optional| R[("Redis or<br/>Render Key Value")]
    API -->|"signed outbox events"| N8N["n8n<br/>optional"]
    N8N -->|"signed callbacks"| API
    API <-->|"REST, verified webhooks"| PP["PayPal"]
    API --> EXT["Channel3, Groq, Langfuse,<br/>Zapier, Elasticsearch, Kernel"]
```

| Piece | Required | Image or runtime | Health check |
| --- | :-: | --- | --- |
| API | yes | [`backend/Dockerfile`](../backend/Dockerfile) (`python:3.12-slim`, port 8000) | `GET /api/v1/health` |
| PostgreSQL 16 + pgvector | yes | `pgvector/pgvector:pg16` or any managed Postgres with `vector` | `pg_isready` |
| Web app | for the UI | [`frontend/Dockerfile`](../frontend/Dockerfile) (`node:22-alpine`, port 3000) or a Node host | `GET /` |
| Redis | no | `redis:7-alpine` or Render Key Value | `redis-cli ping` |
| n8n | no | `n8nio/n8n:2.46.5` ([`n8n/Dockerfile`](../n8n/Dockerfile) on Render) | `GET /healthz` |

The outbox relay that delivers events to n8n runs either inside the API process
(`OUTBOX_RELAY_IN_PROCESS=true`) or as a separate worker (`python -m app.worker`).

---

## Before you deploy

Three changes are required for anything reachable from the internet.

**1. A real `JWT_SECRET`.** It signs access tokens and keys the HMAC that stores refresh tokens. The default in
`.env.example` is public.

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

**2. Production mode and secure cookies.**

```dotenv
APP_ENV=production
DEBUG=false
LOG_FORMAT=json
REFRESH_COOKIE_SECURE=true
```

`APP_ENV=production` enables HSTS and strips exception detail from error responses.

**3. Exact origins.**

```dotenv
FRONTEND_URL=https://app.example.com
BACKEND_URL=https://api.example.com
CORS_ORIGINS=https://app.example.com
```

Credentials are allowed on CORS, so a wildcard is neither accepted nor safe.

---

## Docker Compose

The whole product on one machine with one command.

```bash
cp .env.example .env        # optional; edit JWT_SECRET, APP_ENV, CORS_ORIGINS for anything public
docker compose up -d --build
docker compose logs -f backend
```

Without `.env` the stack still starts: simulated PayPal, deterministic agents.

### Services

[`docker-compose.yml`](../docker-compose.yml) defines:

| Service | Image or build | Host port | Role |
| --- | --- | --- | --- |
| `postgres` | `pgvector/pgvector:pg16` | 5433 | Database; `vector` and `pgcrypto` created on first start |
| `redis` | `redis:7-alpine` | 6379 | Rate limits, caches, realtime pub/sub; no persistence, 64 MB, `allkeys-lru` |
| `backend` | `backend/Dockerfile` | 8000 | Migrates, seeds (idempotent), serves the API |
| `frontend` | `frontend/Dockerfile` | 3000 | Next.js production build |
| `worker` | `backend/Dockerfile` | - | Delivers the event outbox to n8n every 15 seconds (`python -m app.worker`) |
| `n8n-build` | `backend/Dockerfile` | - | One-shot: renders the workflows for this network (callback `http://backend:8000`, merchant id read from the database) |
| `n8n-import` | `n8nio/n8n:2.46.5` | - | One-shot: imports and publishes the workflows before n8n boots |
| `n8n` | `n8nio/n8n:2.46.5` | 5678 | Scheduler and router for automation |
| `elasticsearch` | `elasticsearch:8.15.3` | 127.0.0.1:9200 | Optional, profile `search`: `docker compose --profile search up -d elasticsearch` |

Start order is enforced with health checks: `postgres` and `redis` -> `backend` (healthy after migrate and seed)
-> `n8n-build` -> `n8n-import` -> `n8n`. The backend's health check allows a 180-second start period for the
first seed.

The backend container command is:

```sh
alembic upgrade head && python -m app.seed.seed && uvicorn app.main:app --host 0.0.0.0 --port 8000
```

For a deployment with real users, remove `python -m app.seed.seed`; see
[production without demo data](#production-without-demo-data).

### Build-time frontend values

`NEXT_PUBLIC_*` values are compiled into the bundle, so they are build args, not runtime variables:

```yaml
frontend:
  build:
    args:
      NEXT_PUBLIC_API_URL: https://api.example.com/api/v1
      NEXT_PUBLIC_AG_STUDIO_LICENSE_KEY: ${NEXT_PUBLIC_AG_STUDIO_LICENSE_KEY:-}
      NEXT_PUBLIC_BRYNTUM_LICENSE_KEY: ${NEXT_PUBLIC_BRYNTUM_LICENSE_KEY:-}
```

Changing one requires `docker compose build frontend`, not a restart.

### Operations

| Task | Command |
| --- | --- |
| Postgres only (for `make dev`) | `docker compose up -d postgres` or `make docker-up` |
| Stop, keep data | `docker compose stop` or `make docker-down` |
| Rebuild after code changes | `docker compose up -d --build` |
| Re-seed the demo tenant | `docker compose exec backend python -m app.seed.seed --reset` |
| Refresh n8n after a re-seed (merchant id changed) | `docker compose up -d --force-recreate n8n-build n8n-import n8n` |
| Wipe all data | `docker compose down -v` |

The HMAC secret shared by the backend, worker and n8n workflows is `N8N_WEBHOOK_SECRET` from `.env`, falling back
to a local-only default.

---

## Render Blueprint

[`render.yaml`](../render.yaml) deploys the whole product on [Render](https://render.com), entirely on the free
plan. The hosted demo runs from it.

```mermaid
flowchart TB
    subgraph Render["Render workspace (region: oregon)"]
        WEB["paypilot-web<br/>Node web service"]
        API["paypilot-api<br/>Docker web service<br/>+ in-process relays"]
        N8N["paypilot-n8n<br/>Docker web service"]
        DOCS["paypilot-docs<br/>static site, APIMatic portal"]
        DB[("paypilot-db<br/>Postgres 16")]
        KV[("paypilot-redis<br/>Key Value, private")]
    end
    WEB -->|NEXT_PUBLIC_API_URL| API
    API -->|DATABASE_URL| DB
    API -->|REDIS_URL| KV
    API -->|N8N_INVENTORY_WEBHOOK_URL| N8N
    N8N -->|PGA_BACKEND_URL| API
    N8N -->|"n8n_ tables"| DB
```

### Resources

| Resource | Type | What it does |
| --- | --- | --- |
| `paypilot-db` | Managed Postgres 16 | Application data and pgvector agent memory. The first migration creates `vector` and `pgcrypto` |
| `paypilot-redis` | Key Value (Redis-compatible), private (`ipAllowList: []`), `allkeys-lru` | Rate-limit counters, Channel3 call budget and caches, realtime pub/sub. Never a source of truth; the API falls back to in-process state if it is unreachable |
| `paypilot-api` | Docker web service, `backend/` | [`backend/scripts/render-start.sh`](../backend/scripts/render-start.sh): `alembic upgrade head`, idempotent seed, `uvicorn` on `$PORT` with proxy headers. Health check `/api/v1/health`. Runs the outbox and Zapier relays in-process, so no paid worker is needed |
| `paypilot-n8n` | Docker web service, `n8n/` | Automation. State in the free Postgres (`n8n_` tables), workflows rebuilt from the repo on every boot. See [Automation: on Render](AUTOMATION.md#on-render-free-plan) |
| `paypilot-web` | Node web service, `frontend/` | `npm ci && npm run build`, then `npx next start -p $PORT` |
| `paypilot-docs` | Static site, `apimatic/` | Runs the APIMatic CLI to build PayPilot's developer portal. Needs `APIMATIC_API_KEY`; without it the build fails harmlessly |

Two environment groups wire it together without copying any value by hand:

* `paypilot-shared`: production settings, generated `JWT_SECRET`, `AGENT_PROTOCOL_SECRET`,
  `PAYPAL_SIMULATOR_WEBHOOK_SECRET` and `ZAPIER_SIGNING_SECRET`, and every optional key as `sync: false`.
* `paypilot-n8n-link`: one generated `N8N_WEBHOOK_SECRET`, attached to both the API and n8n.

`DATABASE_URL` and `REDIS_URL` come from `fromDatabase` and `fromService` references. Render's `postgres://` URL is
normalised to `postgresql+asyncpg://` by the backend.

### Steps

1. Push the repository to GitHub or GitLab.
2. In the Render dashboard choose **New -> Blueprint** and select the repository.
3. Render prompts for every `sync: false` secret. Leave them **blank** for the keyless demo, or fill in
   `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_SANDBOX_PAYEE_EMAIL`, `GROQ_API_KEY`,
   `CHANNEL3_API_KEY`, `LANGFUSE_*` and the others you need.
4. `render.yaml` hard-codes the hosted demo's URLs in `FRONTEND_URL`, `BACKEND_URL`, `CORS_ORIGINS`,
   `PGA_BACKEND_URL` and `NEXT_PUBLIC_API_URL`. Render adds a random suffix to hostnames, so replace these with your
   services' URLs, then redeploy the web service (Next.js inlines `NEXT_PUBLIC_*` at build time).
5. PayPal webhooks: register `https://<api-host>/api/v1/paypal/webhooks` in the PayPal developer dashboard and set
   `PAYPAL_WEBHOOK_ID` on the API.
6. n8n (optional): on `paypilot-n8n` set `PGA_MERCHANT_ID`, `N8N_INSTANCE_OWNER_EMAIL` and
   `N8N_INSTANCE_OWNER_PASSWORD_HASH`; on `paypilot-api` set `N8N_INVENTORY_WEBHOOK_URL` and `N8N_BASE_URL`.
   Details: [Automation: on Render](AUTOMATION.md#on-render-free-plan).
7. Verify: `GET https://<api-host>/api/v1/health` returns `status: ok` and `checks.redis: ok`.

### Free-plan behaviour

* Web services sleep after about 15 idle minutes; the first request after that takes about a minute. Open the
  site before a demo.
* The free database expires after 30 days.
* Because the API's caches live in Key Value, waking or redeploying the API does not re-spend Channel3 credits on
  results that are still fresh.
* A sleeping n8n cannot fire its 02:00 and 06:30 schedules. An external ping to its deep health URL a few minutes
  before each wakes it; see [Automation: keeping the schedules alive](AUTOMATION.md#keeping-the-schedules-alive).
* To move the relays out of the API, add a paid `type: worker` service running `python -m app.worker` and set
  `OUTBOX_RELAY_IN_PROCESS=false`.

---

## Other platforms

### Split deployment

The common production shape: the frontend on a CDN platform, the API on a container host, a managed database.

```
Browser
  |  https://app.example.com
  v
Frontend (Vercel, Netlify, Cloudflare Pages, Render)
  |  https://api.example.com/api/v1    CORS with credentials
  v
API container (Render, Fly.io, Railway, Cloud Run, ECS)
  |
  v
PostgreSQL 16 + pgvector (Render, Supabase, Neon, RDS, Cloud SQL)
```

The refresh token is an `HttpOnly` cookie scoped to `/api/v1/auth`. Choose cookie settings for the topology:

| Topology | Settings |
| --- | --- |
| Same site (`app.example.com` and `api.example.com`) | `REFRESH_COOKIE_SAMESITE=lax`, `REFRESH_COOKIE_SECURE=true` |
| Different sites (for example two `onrender.com` subdomains) | `REFRESH_COOKIE_SAMESITE=none`, `REFRESH_COOKIE_SECURE=true` |

`SameSite=None` requires `Secure`; without it browsers drop the cookie and users are signed out on every reload.

### Frontend on Vercel

| Setting | Value |
| --- | --- |
| Root directory | `frontend` |
| Framework | Next.js (auto-detected) |
| Build command | `npm run build` |
| Node version | 20 or 22 |
| Environment | `NEXT_PUBLIC_API_URL=https://api.example.com/api/v1`, `NEXT_PUBLIC_APP_NAME=PayPilot` |

Omit `NEXT_PUBLIC_DEMO_EMAIL` and `NEXT_PUBLIC_DEMO_PASSWORD` for anything with real users.

### API on a container host

Build context `backend/`. The image's default command serves on port 8000; on hosts that assign a port:

```bash
sh scripts/render-start.sh          # migrate, seed, serve on $PORT
# or, without the demo seed:
alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'
```

Fly.io example:

```bash
cd backend
fly launch --no-deploy
fly secrets set \
  DATABASE_URL="postgresql+asyncpg://..." \
  JWT_SECRET="$(python -c 'import secrets;print(secrets.token_urlsafe(64))')" \
  APP_ENV=production DEBUG=false LOG_FORMAT=json \
  REFRESH_COOKIE_SECURE=true CORS_ORIGINS="https://app.example.com"
fly deploy
```

Scale-to-zero platforms (Cloud Run) should use a pooled database connection.

### Multiple workers

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

Set `REDIS_URL` when running more than one worker or replica. Without it, rate limits and caches are per process
(four workers means four times the configured limit) and realtime events reach only the browsers connected to the
same process. The outbox relay claims batches with `SKIP LOCKED` and a lease, so several relays never deliver the
same event twice.

---

## Managed Postgres

Any PostgreSQL 14+ with the `vector` extension works. The first migration runs
`CREATE EXTENSION IF NOT EXISTS vector` and `pgcrypto`, guarded so it still runs on SQLite.

| Provider | Notes |
| --- | --- |
| Render | Wired by the Blueprint |
| Supabase | Enable `vector` under Database -> Extensions. Use the session pooler (port 5432); the transaction pooler (6543) also works because pooler URLs are detected and asyncpg's statement cache is disabled |
| Neon, RDS, Cloud SQL | Enable `vector`; use `postgresql+asyncpg://` (or paste `postgres://`, which is normalised) |

URL-encode special characters in the password. Seeding a remote database takes longer (about 15,000
transactions over the network); the seed is idempotent, so a timeout can be re-run.

---

## Migrations in production

Migrations live in [`backend/alembic/versions`](../backend/alembic/versions). Apply them as a release step, before
the new version serves traffic:

```bash
cd backend && python -m alembic upgrade head
```

Create one with `make migration MSG="add supplier ratings"`, then **read the generated file**: autogenerate misses
data migrations and occasionally proposes destructive drops. Roll back one step with
`python -m alembic downgrade -1`.

### Production without demo data

Remove the seed step from the start command and create the first user through registration:

```bash
curl -X POST https://api.example.com/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@company.com","password":"...","full_name":"Your Name","merchant_name":"Your Business"}'
```

Registration creates the user, a merchant workspace and an Owner membership.

---

## Production checklist

### Security

- [ ] `JWT_SECRET` generated, stored in a secret manager, never committed
- [ ] `APP_ENV=production`, `DEBUG=false`
- [ ] `REFRESH_COOKIE_SECURE=true` and `REFRESH_COOKIE_SAMESITE` matching the topology
- [ ] `CORS_ORIGINS` lists exact origins
- [ ] TLS terminated in front of the API
- [ ] Demo accounts removed or their passwords rotated; `NEXT_PUBLIC_DEMO_*` removed from the frontend build
- [ ] `PAYPAL_WEBHOOK_ID` set before relying on PayPal webhooks
- [ ] `AGENT_PROTOCOL_SECRET`, `N8N_WEBHOOK_SECRET`, `ZAPIER_SIGNING_SECRET` set explicitly

### Database

- [ ] Postgres 14+ with `vector` enabled
- [ ] Automated backups or point-in-time recovery on
- [ ] Migrations run as a release step
- [ ] Connection limits sized for the number of workers

### Operations

- [ ] `LOG_FORMAT=json`, logs shipped to an aggregator
- [ ] Health check wired to `/api/v1/health`
- [ ] `REDIS_URL` set if running more than one worker or replica
- [ ] Langfuse configured if you want agent traces
- [ ] Gmail credentials set if invitations and vendor emails must be delivered

---

## Observability in production

**Logs.** With `LOG_FORMAT=json` every line is one JSON object carrying `request_id`, `user_id`, `merchant_id`
and, inside agent runs, `agent_run_id`. Secrets are redacted before they reach any sink.

| Looking for | Filter |
| --- | --- |
| Slow requests | `message="http_request" AND duration_ms > 1000` |
| Permission denials | `message="permission_denied"` |
| Cross-tenant attempts | `message="merchant_scope_violation"` |
| Agent tool failures | `message="agent_tool_call" AND status="failed"` |

**Health.** `GET /api/v1/health` reports database, Redis, LLM, Langfuse, Vapi, email, embeddings and the logging
backend. It returns `200` with `status: "degraded"` when the database is unreachable, so a load balancer can tell
"up but broken" from "down". `GET /api/v1/health/live` is a bare liveness probe.

**Traces.** With Langfuse keys, each agent run is a trace whose URL is stored on the run and linked from the
agent trace screen.

---

## Scaling notes

| Component | Today | To scale |
| --- | --- | --- |
| API | Stateless once `REDIS_URL` is set | Add workers or replicas |
| Database | Composite indexes on `(merchant_id, ...)` access paths | Read replica for analytics; materialised period rollups |
| Analytics | Computed per request | Cache `AnalyticsService.metrics_snapshot` per merchant and period |
| Agent runs | Synchronous within the request | Move long investigations to a queue |
| Agent memory | HNSW index on `agent_memories.embedding` | Already indexed for approximate search |
| Frontend | Static assets, CDN-friendly | Nothing needed |

---

## Backups and recovery

```bash
pg_dump "postgresql://user:pass@host:5432/paypilot" --no-owner --no-privileges --format=custom \
  > paypilot-$(date +%F).dump

pg_restore --no-owner --no-privileges --dbname "postgresql://user:pass@host:5432/paypilot" \
  paypilot-2026-11-01.dump
```

Create `vector` and `pgcrypto` in the target database before restoring. Demo data never needs a backup: it is
deterministic and `make demo` rebuilds it.

---

<div align="center">

[Previous: Configuration](CONFIGURATION.md) | [Docs index](README.md) | [Next: Architecture](ARCHITECTURE.md)

</div>
