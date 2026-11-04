<div align="center">

# Deployment

[![Docs index](https://img.shields.io/badge/-Docs_index-475569?style=flat-square&logo=markdown&logoColor=white)](README.md)
[![Previous: Configuration](https://img.shields.io/badge/-Previous:_Configuration-64748b?style=flat-square)](CONFIGURATION.md)
[![Security](https://img.shields.io/badge/-Security-dc2626?style=flat-square)](SECURITY.md)
[![Automation](https://img.shields.io/badge/-Automation-b45309?style=flat-square)](../n8n/README.md)

</div>

Taking PayPilot beyond `localhost`.

---

## Contents

- [Before you deploy](#before-you-deploy)
- [Docker Compose (self-contained)](#docker-compose-self-contained)
- [Supabase](#supabase)
- [Split deployment](#split-deployment)
- [Frontend on Vercel](#frontend-on-vercel)
- [Backend on a container platform](#backend-on-a-container-platform)
- [Migrations in production](#migrations-in-production)
- [Production checklist](#production-checklist)
- [Observability](#observability)
- [Scaling notes](#scaling-notes)
- [Backups and recovery](#backups-and-recovery)

---

## Before you deploy

Three things are non-negotiable.

### 1. Generate a real `JWT_SECRET`

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

It signs access tokens **and** keys the HMAC that hashes refresh tokens. The
default in `.env.example` is a placeholder and is public.

### 2. Turn on secure cookies

```dotenv
REFRESH_COOKIE_SECURE=true
APP_ENV=production
DEBUG=false
```

`APP_ENV=production` also enables HSTS and strips exception detail from error
responses.

### 3. Lock down CORS

```dotenv
CORS_ORIGINS=https://app.yourdomain.com
FRONTEND_URL=https://app.yourdomain.com
BACKEND_URL=https://api.yourdomain.com
```

Credentials are allowed on CORS, so a wildcard is neither accepted nor safe.

---

## Docker Compose (self-contained)

The fastest path to a running deployment. Brings up Postgres with pgvector, the
backend, and the frontend.

```bash
cp .env.example .env
# edit .env: JWT_SECRET, APP_ENV, CORS_ORIGINS, REFRESH_COOKIE_SECURE
make docker-up
make logs
```

[`docker-compose.yml`](../docker-compose.yml) defines:

| Service | Image / build | Port | Profile |
| --- | --- | --- | --- |
| `postgres` | `pgvector/pgvector:pg16` | 5433 | always |
| `backend` | `backend/Dockerfile` | 8000 | `full` |
| `frontend` | `frontend/Dockerfile` | 3000 | `full` |

The backend container runs migrations and the seed on start:

```yaml
command: >
  sh -c "alembic upgrade head &&
         python -m app.seed.seed &&
         uvicorn app.main:app --host 0.0.0.0 --port 8000"
```

`app.seed.seed` is idempotent, so restarts do not duplicate data.

> **For a real deployment**, drop `python -m app.seed.seed` from the command —
> you do not want demo data in production. See
> [Migrations in production](#migrations-in-production).

### Build-time frontend configuration

`NEXT_PUBLIC_*` values are baked in at build time, so the API URL is a build arg:

```yaml
frontend:
  build:
    args:
      NEXT_PUBLIC_API_URL: https://api.yourdomain.com/api/v1
```

Changing it later requires a rebuild, not a restart.

### Stopping

```bash
make docker-down                    # stop, keep data
docker compose down -v              # stop and destroy the volume
```

---

## Supabase

Supabase supplies **PostgreSQL and pgvector**. Authentication stays in FastAPI —
Supabase Auth is not used as the application's auth abstraction.

### 1. Enable pgvector

Dashboard -> **Database** -> **Extensions** -> enable `vector`. Enable `pgcrypto`
too if it is not already on.

### 2. Get the session connection string

**Project Settings** -> **Database** -> **Connection string** -> **URI**. Use the
**session** pooler (port 5432), not the transaction pooler (6543), unless you
accept the caveat below.

```dotenv
DATABASE_URL=postgresql+asyncpg://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
```

Note the `+asyncpg` driver, and URL-encode any special characters in the password.

### 3. Migrate and verify

```bash
make migrate
curl -s localhost:8000/api/v1/health | python -m json.tool
```

### How the pooler is handled

[`db/session.py`](../backend/app/db/session.py) detects `pooler.supabase` (or
`pgbouncer=true`) in the URL and automatically:

- switches to `NullPool` — the pooler already pools
- sets `statement_cache_size=0` and `prepared_statement_cache_size=0`

asyncpg's implicit prepared-statement cache is incompatible with transaction
pooling; without this you get intermittent
`prepared statement "__asyncpg_..." does not exist` errors under load. You do not
need to configure any of it.

### Seeding a Supabase database

```bash
make seed
```

Expect it to take longer than locally — roughly 14,800 transactions over a network
round trip. It is idempotent, so a timeout can simply be re-run.

---

## Split deployment

The common production shape: frontend on a CDN platform, backend on a container
host, database managed.

```
  Browser
     |
     |  https://app.yourdomain.com
     v
  Frontend (Vercel / Netlify / Cloudflare Pages)
     |
     |  https://api.yourdomain.com/api/v1     CORS + credentials
     v
  Backend (Fly.io / Railway / Render / Cloud Run / ECS)
     |
     v
  PostgreSQL + pgvector (Supabase / RDS / Neon / Cloud SQL)
```

### Cookie considerations

The refresh token is an HttpOnly cookie scoped to `/api/v1/auth`.

**Same site** (`app.example.com` and `api.example.com` share `example.com`):

```dotenv
REFRESH_COOKIE_SAMESITE=lax
REFRESH_COOKIE_SECURE=true
```

**Cross site** (different registrable domains):

```dotenv
REFRESH_COOKIE_SAMESITE=none
REFRESH_COOKIE_SECURE=true
```

`SameSite=None` **requires** `Secure`, and browsers will silently drop the cookie
otherwise — the symptom is being logged out on every page refresh. Prefer a
same-site setup.

---

## Frontend on Vercel

```bash
cd frontend
vercel
```

| Setting | Value |
| --- | --- |
| Framework | Next.js (auto-detected) |
| Root directory | `frontend` |
| Build command | `npm run build` |
| Node version | 20 or 22 |

Environment variables (Project Settings -> Environment Variables):

```
NEXT_PUBLIC_API_URL   = https://api.yourdomain.com/api/v1
NEXT_PUBLIC_APP_NAME  = PayPilot
```

Omit `NEXT_PUBLIC_DEMO_EMAIL` and `NEXT_PUBLIC_DEMO_PASSWORD` — they exist to
prefill the login form for reviewers and have no place in a real deployment.

If voice is enabled, add `NEXT_PUBLIC_VAPI_PUBLIC_KEY` and
`NEXT_PUBLIC_VAPI_ASSISTANT_ID`. The public key is designed to be public; the
private key stays server-side.

> `NEXT_PUBLIC_*` values are compiled into the bundle. Changing one requires a
> redeploy, and none of them may be a secret.

---

## Backend on a container platform

The backend is a standard Python container — [`backend/Dockerfile`](../backend/Dockerfile)
builds on `python:3.12-slim` and exposes 8000 with a `HEALTHCHECK` against
`/api/v1/health`.

### Fly.io

```bash
cd backend
fly launch --no-deploy
fly secrets set \
  DATABASE_URL="postgresql+asyncpg://..." \
  JWT_SECRET="$(python -c 'import secrets;print(secrets.token_urlsafe(64))')" \
  APP_ENV=production \
  DEBUG=false \
  LOG_FORMAT=json \
  REFRESH_COOKIE_SECURE=true \
  CORS_ORIGINS="https://app.yourdomain.com"
fly deploy
```

### Railway / Render

Point at `backend/` as the build context. Start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Set the same environment variables. Health check path: `/api/v1/health`.

### Google Cloud Run

```bash
cd backend
gcloud run deploy growth-autopilot-api \
  --source . \
  --region asia-south1 \
  --allow-unauthenticated \
  --set-env-vars "APP_ENV=production,DEBUG=false,LOG_FORMAT=json" \
  --set-secrets "DATABASE_URL=db-url:latest,JWT_SECRET=jwt-secret:latest"
```

Cloud Run scales to zero, so use a pooled database (Supabase, Neon) rather than
holding direct connections.

### Workers

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

> **Warning.** Rate limiting is an in-process counter, so each worker has its own.
> Four workers means four times the configured limit. Move the `_hits` store in
> [`core/middleware.py`](../backend/app/core/middleware.py) to Redis before
> relying on it.

---

## Migrations in production

Never edit a deployed schema by hand.

### Applying

```bash
cd backend && python -m alembic upgrade head
```

Run it as a release step, before the new application version starts serving.

### Creating

```bash
make migration MSG="add campaign scheduling"
```

Then **read the generated file**. Autogenerate is a good first draft and a poor
final answer — it misses data migrations, gets constraint renames wrong, and
occasionally proposes a destructive drop.

Two project-specific notes, both handled by the template in
[`alembic/script.py.mako`](../backend/alembic/script.py.mako):

1. Portable column types render as `app.db.types.GUID()` and similar, so the
   migration imports `app.db.types`.
2. The initial migration creates the `vector` and `pgcrypto` extensions, guarded
   by a dialect check so it still runs on SQLite.

### Verifying there is no drift

```bash
make migration MSG="drift check"
# open the generated file; upgrade() should contain only `pass`
# then delete it
```

### Rolling back

```bash
make downgrade        # one step
```

Test the downgrade path before you need it.

### Production without demo data

Remove the seed step from the container command and create the first user through
registration:

```bash
curl -X POST https://api.yourdomain.com/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@company.com","password":"...","full_name":"Your Name","merchant_name":"Your Business"}'
```

Registration creates the user, a merchant workspace, and an OWNER membership. The
RBAC catalogue is seeded separately by `seed_rbac`, which is safe to run on its
own.

---

## Production checklist

### Security

- [ ] `JWT_SECRET` generated, stored in a secret manager, never committed
- [ ] `REFRESH_COOKIE_SECURE=true`
- [ ] `REFRESH_COOKIE_SAMESITE` matches your topology
- [ ] `APP_ENV=production`, `DEBUG=false`
- [ ] `CORS_ORIGINS` lists exact origins, no wildcard
- [ ] TLS terminated in front of the backend
- [ ] Demo accounts removed or passwords rotated
- [ ] `NEXT_PUBLIC_DEMO_*` removed from the frontend build

### Database

- [ ] Managed Postgres 14+ with `vector` enabled
- [ ] Connection string uses the `+asyncpg` driver
- [ ] Automated backups on
- [ ] Migrations applied as a release step
- [ ] Connection limits sized against worker count

### Operations

- [ ] `LOG_FORMAT=json`
- [ ] Logs shipped to an aggregator
- [ ] Health check wired to `/api/v1/health`
- [ ] Rate limiting moved to Redis, or documented as per-worker
- [ ] Langfuse configured if you want agent traces

### Before real traffic

- [ ] Analytics caching or materialised rollups added
- [ ] Refresh-token cleanup scheduled (`purge_expired`)
- [ ] Password-reset email delivery wired up
- [ ] Campaign delivery adapter implemented, or the simulation labelling kept

---

## Observability

### Structured logs

```dotenv
LOG_FORMAT=json
LOG_LEVEL=INFO
```

Every line is one JSON object:

```json
{
  "timestamp": "2026-09-14T05:44:12.881Z",
  "level": "INFO",
  "service": "paypilot",
  "environment": "production",
  "logger": "app.tools.base",
  "message": "agent_tool_call",
  "request_id": "6d3919aa5f5441e9",
  "user_id": "…",
  "merchant_id": "…",
  "agent_run_id": "…",
  "tool": "get_growth_metrics",
  "duration_ms": 142,
  "status": "ok"
}
```

Useful queries:

| Intent | Filter |
| --- | --- |
| Slow requests | `message="http_request" AND duration_ms > 1000` |
| Permission denials | `message="permission_denied"` |
| Cross-tenant attempts | `message="merchant_scope_violation"` |
| Agent tool failures | `message="agent_tool_call" AND status="failed"` |
| LLM problems | `message="llm_call_failed" OR message="llm_exhausted"` |

Secrets are redacted before reaching any sink — passwords, tokens, API keys and
cookies, recursively and case-insensitively.

### Agent traces

Set the Langfuse keys ([CONFIGURATION.md](CONFIGURATION.md#langfuse-observability))
and every agent run produces a trace with spans for nodes, generations for LLM
calls with token usage, and spans for tool calls. The trace URL is stored on the
run and linked from the Agent Trace screen.

### Health

`GET /api/v1/health` reports database connectivity and which integrations are
active. It returns `200` with `status: "degraded"` when the database is
unreachable, so a load balancer can distinguish "up but broken" from "down".

`GET /api/v1/health/live` is a bare liveness probe.

---

## Scaling notes

| Component | Current | To scale |
| --- | --- | --- |
| Backend | Stateless apart from the rate-limit counter | Add workers or replicas; move rate limiting to Redis |
| Database | Composite indexes on the real access paths | Read replica for analytics; materialise period rollups |
| Analytics | Computed per request | Cache `metrics_snapshot` per merchant and period |
| Agent runs | Synchronous | Move to a queue if investigations exceed a few seconds |
| Embeddings | Computed at seed time | Batch; pgvector HNSW index above ~100k rows |
| Frontend | Static, CDN-friendly | Nothing needed |

### The first bottleneck you will hit

`/dashboard/overview` runs roughly a dozen aggregate queries. It is already one
round trip from the browser's perspective, which was the design goal, but on a
large merchant it is the slowest endpoint. Cache
`AnalyticsService.metrics_snapshot` keyed by `(merchant_id, period)` — the seam is
already there.

---

## Backups and recovery

### Backing up

```bash
pg_dump "postgresql://user:pass@host:5432/autopilot" \
  --no-owner --no-privileges --format=custom \
  > autopilot-$(date +%F).dump
```

Managed providers give you point-in-time recovery; use it.

### Restoring

```bash
pg_restore --no-owner --no-privileges \
  --dbname "postgresql://user:pass@host:5432/autopilot" \
  autopilot-2026-09-14.dump
```

Ensure `vector` and `pgcrypto` exist in the target before restoring.

### Rebuilding demo data

Never needs a backup — it is deterministic:

```bash
make demo        # database + migrations + fresh seed, about 60 seconds
```

That is the point of a seeded generator rather than a SQL dump.

---

<div align="center">

[Docs index](README.md) · [Configuration](CONFIGURATION.md) ·
[Security](SECURITY.md) · [Architecture](ARCHITECTURE.md) ·
[Troubleshooting](TROUBLESHOOTING.md)

</div>

---

## Render (Blueprint)

`render.yaml` at the repository root deploys the whole product on
[Render](https://render.com):

| Resource | Type | Notes |
| --- | --- | --- |
| `paypilot-db` | Managed Postgres 16 | The first migration runs `CREATE EXTENSION vector` and `pgcrypto` |
| `paypilot-api` | Web service (Docker, `backend/`) | Start command runs `alembic upgrade head`, the idempotent demo seed, then uvicorn on `$PORT`; health check `/api/v1/health` |
| `paypilot-worker` | Background worker (Docker) | `python -m app.worker` delivers the event outbox (the API runs with `OUTBOX_RELAY_IN_PROCESS=false`) |
| `paypilot-web` | Web service (Node, `frontend/`) | `npm ci && npm run build`, `npx next start -p $PORT` |

Steps:

1. Push the repository to GitHub/GitLab.
2. Render dashboard -> **New -> Blueprint** -> select the repository.
3. Render prompts for the `sync: false` secrets. Leave them **blank** for the
   keyless demo (deterministic agents, simulated PayPal), or fill in
   `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID`, `GROQ_API_KEY`.
4. If your service names differ from the defaults, update `FRONTEND_URL`,
   `CORS_ORIGINS` (API) and `NEXT_PUBLIC_API_URL` (web), then redeploy the web
   service (Next.js inlines `NEXT_PUBLIC_*` at build time).
5. For PayPal webhooks, register `https://<api-host>/api/v1/paypal/webhooks` in
   the PayPal developer dashboard and set `PAYPAL_WEBHOOK_ID`.

`DATABASE_URL` comes from Render as `postgres://…`; the backend normalises it to
`postgresql+asyncpg://` (and `sslmode=` to asyncpg's `ssl=`) automatically.
Free-plan databases expire after 30 days and free web services sleep when idle.
