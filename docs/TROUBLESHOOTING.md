<div align="center">

# Troubleshooting

[![Docs index](https://img.shields.io/badge/-Docs_index-475569?style=flat-square&logo=markdown&logoColor=white)](README.md)
[![Installation](https://img.shields.io/badge/-Installation-64748b?style=flat-square)](INSTALLATION.md)
[![Configuration](https://img.shields.io/badge/-Configuration-2563eb?style=flat-square)](CONFIGURATION.md)
[![Deployment](https://img.shields.io/badge/-Deployment-16a34a?style=flat-square)](DEPLOYMENT.md)
[![Automation](https://img.shields.io/badge/-Automation-b45309?style=flat-square)](../n8n/README.md)

</div>

Symptom, cause, fix. Everything below was hit during development, not imagined.

---

## Contents

- [Start here](#start-here)
- [Installation and setup](#installation-and-setup)
- [Database](#database)
- [Migrations](#migrations)
- [Seeding](#seeding)
- [Backend runtime](#backend-runtime)
- [Authentication](#authentication)
- [Frontend](#frontend)
- [Agents and LLM](#agents-and-llm)
- [Tests](#tests)
- [Docker](#docker)
- [Windows](#windows)
- [Still stuck](#still-stuck)

---

## Start here

Four commands that identify most problems in under a minute.

```bash
curl -s http://localhost:8000/api/v1/health | python -m json.tool   # is it up, what is wired
make seed-stats                                                     # is there data
make test                                                           # is the code sane
make calibrate                                                      # is the dataset right
```

The health response tells you a great deal:

```json
{
  "checks": {
    "database": "ok",
    "llm": "not_configured",
    "langfuse": "not_configured",
    "vapi": "not_configured",
    "embeddings": "hash",
    "logging_backend": "logifyx"
  }
}
```

`not_configured` is not a fault. The product is built to run that way.

---

## Installation and setup

### `make: command not found`

`make` is not installed. Install it, use WSL2, or run the expanded commands in the
[Installation fast path](INSTALLATION.md#fast-path).

```bash
# macOS
brew install make
# Debian / Ubuntu
sudo apt install make
# Windows
winget install GnuWin32.Make
```

### `python: command not found` but `python3` works

The Makefile uses `python` inside the venv, where it always exists. Only the
initial venv creation uses the system interpreter:

```bash
make install PYTHON=python3
```

### `ERROR: Could not find a version that satisfies the requirement ...`

Python is older than 3.11. Check with `python --version`. The codebase uses
`StrEnum`, `datetime.UTC` and PEP 604 unions throughout.

### `logifyx` or `fastembed` fails to install

Expected on some platforms, and harmless. Both are in
`requirements-optional.txt` and installed on a best-effort basis. Without them the
built-in JSON logger and deterministic hash embeddings take over; the health
endpoint reports which is active.

### `npm install` fails with peer dependency errors

```bash
cd frontend
rm -rf node_modules package-lock.json
npm install
```

If it persists, check `node --version` is 20 or newer.

---

## Database

### `connection refused` on port 5433

Postgres is not running:

```bash
make db
make wait-db
```

`wait-db` blocks until the container accepts connections. Starting the API before
that point is the most common cause of a failed first run.

### Port 5433 is already allocated

Something else holds it. Either free it, or pick another port in `.env`:

```dotenv
POSTGRES_PORT=5434
DATABASE_URL=postgresql+asyncpg://autopilot:autopilot@localhost:5434/autopilot
```

Both lines must change. The compose file reads `POSTGRES_PORT`; the application
reads `DATABASE_URL`.

> Port 5433 rather than 5432 is deliberate — so the project never collides with a
> Postgres you already had.

### `type "vector" does not exist`

The pgvector extension is missing. On the Docker image it is created automatically
by [`docker/postgres/init/01-extensions.sql`](../docker/postgres/init/01-extensions.sql),
which only runs on a **fresh volume**. If you pointed the project at a pre-existing
database:

```bash
psql -d autopilot -c 'CREATE EXTENSION IF NOT EXISTS "vector";'
psql -d autopilot -c 'CREATE EXTENSION IF NOT EXISTS "pgcrypto";'
```

On Supabase, enable `vector` in **Database -> Extensions**.

### `password authentication failed for user "autopilot"`

The volume was created with different credentials than `.env` now specifies.
Postgres only reads `POSTGRES_PASSWORD` when initialising an empty data directory.

```bash
make db-reset      # destroys the volume and recreates it
make migrate seed
```

Destructive. Local demo data only.

### `prepared statement "__asyncpg_stmt_1__" already exists`

You are behind a transaction-mode connection pooler — typically Supabase on port
6543 — which multiplexes connections in a way asyncpg's statement cache cannot
survive.

The engine detects `pooler.supabase.com` and disables the cache automatically. If
you are on a different pooler, use the **session** connection string (port 5432),
or add it to the detection in
[`app/db/session.py`](../backend/app/db/session.py).

Details: [DEPLOYMENT.md](DEPLOYMENT.md#supabase).

---

## Migrations

### `Target database is not up to date`

```bash
make migrate
```

### `Can't locate revision identified by '...'`

The `alembic_version` table names a revision that no longer exists in
`migrations/versions/`, usually after switching branches.

```bash
cd backend
python -m alembic history          # what exists
python -m alembic current          # what the database believes
python -m alembic stamp head       # only if you are certain the schema matches
```

For a local demo database, `make db-reset && make migrate && make seed` is faster
and safer than reconciling by hand.

### `NameError: name 'pga_types' is not defined` in a generated migration

Alembic autogenerate renders the custom column types as `app.db.types.GUID()`,
but an aliased import produces a name that does not match.

The template in `migrations/script.py.mako` uses a plain import:

```python
import app.db.types
```

If you edited it to an alias, either revert, or fix the generated file's import to
match the rendered names. Both must agree.

### Autogenerate wants to drop and recreate every column

Usually a type-decorator mismatch — SQLAlchemy comparing `UTCDateTime` against
what it reflects from the database. Inspect the diff before accepting it:

```bash
cd backend
python -m alembic revision --autogenerate -m "check"
# read the file, then delete it if it is spurious
```

Never apply an autogenerated migration without reading it.

---

## Seeding

### `make seed` says data already exists

By design — it is idempotent. To rebuild:

```bash
make reseed
```

### Seeding takes over two minutes

Normal range is 45 to 70 seconds. Slower usually means embeddings are being
computed by `fastembed` on first run, which downloads and initialises an ONNX
model. Subsequent runs are faster.

To skip real embeddings entirely:

```dotenv
EMBEDDING_BACKEND=hash
```

Deterministic hash embeddings are sufficient for the demo; semantic search quality
drops but nothing breaks.

### `StringDataRightTruncation`

A column is narrower than the value being written. This happened for real:
`agent_runs.decision` was `VARCHAR(48)` and received a full sentence. Fixed by
migration `0002_widen_agent_decision.py`, which widens it to `Text`.

If you hit it on a new column, widen it with a migration rather than truncating
the value.

### The numbers do not match the docs

```bash
make calibrate
```

Expect revenue around -12%, evening revenue around -32%. If they differ, either
`SEED_RANDOM_SEED` changed, or a generator constant in
`app/seed/generators/dataset.py` was edited.

The seed is `20240917`. Any other value produces a valid but different business.

### The dashboard shows growth rather than decline

The date anchor has drifted. `default_anchor()` pins to the most recent Sunday, so
the comparison windows stay aligned to whole weeks. If the system clock is far
from real time, or a fixed anchor was hardcoded, the windows land in the wrong
place.

```bash
make reseed
```

---

## Backend runtime

### `[Errno 10048] error while attempting to bind on address ('0.0.0.0', 8000)`

Port 8000 is in use. Every target accepts an override:

```bash
make backend PORT=8010
```

Then point the frontend at it:

```dotenv
# the root .env
NEXT_PUBLIC_API_URL=http://localhost:8010/api/v1
```

Find the culprit:

```bash
# macOS / Linux
lsof -i :8000
# Windows
netstat -ano | findstr :8000
```

### `SettingsError: error parsing value for field "cors_origins"`

`pydantic-settings` tries to JSON-decode list-typed fields before validators run,
so a comma-separated value fails.

Already handled with `Annotated[list[str], NoDecode]` in
[`app/core/config.py`](../backend/app/core/config.py). If you add a new list
setting, apply the same annotation — or write the value as a JSON array in `.env`.

### `ValueError: JWT_SECRET must be at least 32 characters`

Working as intended.

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

### `AssertionError: Query default value cannot be set in Annotated`

FastAPI requires the default outside the annotation:

```python
# wrong
q: Annotated[str | None, Query(default=None)]
# right
q: Annotated[str | None, Query()] = None
```

### `MissingGreenlet: greenlet_spawn has not been called`

Async SQLAlchemy hit a lazy load outside an await context. Two forms:

**Reading a relationship that was not eagerly loaded.** Load it explicitly:

```python
stmt = select(AgentRun).options(selectinload(AgentRun.steps)).where(...)
```

**Assigning to a lazy-loaded collection.** Pass it to the constructor instead:

```python
# wrong
role.permissions = granted
# right
role = RoleModel(name=..., permissions=granted)
```

Both were hit during development — the first in the agent trace endpoints, the
second in `seed_rbac`.

### `TypeError: can't compare offset-naive and offset-aware datetimes`

SQLite returns naive datetimes; Postgres returns aware ones.

Solved structurally by the `UTCDateTime` type decorator in
[`app/db/types.py`](../backend/app/db/types.py), which guarantees timezone-aware
UTC on the way out of either engine. If you add a timestamp column, use
`UTCDateTime`, not `DateTime`.

### 500 with `INTERNAL_ERROR` and no detail

By design in production. The `request_id` in the response correlates to a full
structured log line:

```bash
grep '"request_id":"<id>"' backend/logs/*.log
```

Locally, set `DEBUG=true` for tracebacks in the response.

---

## Authentication

### Login succeeds, the next request is 401

The access token is not reaching the API. Check the `Authorization` header in the
Network tab. The token lives in memory only — a hard reload drops it, and the
client should silently refresh from the cookie.

### Refresh fails, you are signed out on every reload

The refresh cookie is not being sent. Usually one of:

| Cause | Fix |
| --- | --- |
| API origin not in `CORS_ORIGINS` | Add the exact origin, scheme and port included |
| `withCredentials` missing | Already set on the shared client; check nothing bypasses it |
| `COOKIE_SECURE=true` over plain HTTP | Set `false` for local development |
| Frontend and API on different sites | `COOKIE_SAMESITE=none` **and** `COOKIE_SECURE=true` |

### Every request is 401 after restarting the backend

`JWT_SECRET` changed — likely regenerated by `make env`. All existing tokens are
invalid, including refresh digests, which are HMAC-keyed with it. Sign in again.

### Account locked

Eight consecutive failures. Either wait for the lockout window, or clear it
locally:

```sql
UPDATE users SET failed_login_attempts = 0, locked_until = NULL WHERE email = 'owner@juniperoak.com';
```

### 403 `PERMISSION_DENIED` when you expect access

Check the role you signed in as. The demo users are:

| Email | Role |
| --- | --- |
| `owner@juniperoak.com` | OWNER |
| `admin@juniperoak.com` | ADMIN |
| `analyst@juniperoak.com` | ANALYST |
| `staff@juniperoak.com` | STAFF |
| `viewer@juniperoak.com` | VIEWER |

All use `Autopilot@2024`. The denial is also in the security event log:

```
GET /api/v1/admin/security-events
```

ANALYST cannot approve or execute — that is the
[approval gate](SECURITY.md#the-approval-gate), not a bug.

---

## Frontend

### `Network Error` on every request

The API is not running, or `NEXT_PUBLIC_API_URL` is wrong.

```bash
curl http://localhost:8000/api/v1/health
```

`NEXT_PUBLIC_*` variables are inlined at build time. Changing one requires a dev
server restart.

### CORS error in the console

The browser origin is not in the backend allow-list.

```dotenv
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

`localhost` and `127.0.0.1` are different origins to a browser. If you open the
app on one, the allow-list must contain that one.

### Port 3000 in use

```bash
make frontend WEB_PORT=3001
```

Then add `http://localhost:3001` to `CORS_ORIGINS`.

### `Hydration failed` warnings

Usually a value that differs between server and client render — `Date.now()`, a
random id, or `localStorage`. Theme handling is already guarded with `mounted`
state; new components that read browser state need the same.

### Charts render empty

Recharts needs a sized container. The wrappers use `ResponsiveContainer` inside a
parent with an explicit height. A new chart in a parent with `height: auto` will
render nothing and report no error.

### Type error: `Type '() => Role | null' is not assignable to ReactNode`

A Zustand selector returned the method rather than the value:

```tsx
// wrong
const role = useAuthStore((s) => s.role);
// right
const role = useAuthStore((s) => s.user?.role ?? null);
```

### `npm run build` fails but `npm run dev` works

The production build type-checks every route. Run `npm run typecheck` for the full
list of errors at once.

---

## Agents and LLM

### Every run says "Deterministic mode"

`GROQ_API_KEY` is not set, or the key is invalid. Check:

```bash
curl -s http://localhost:8000/api/v1/health | grep llm
```

This is a fully supported mode, not a degraded one — the recommendation, its
evidence and its numbers are all still produced. Only the prose differs.

### `LLM_ERROR` after a long wait

Groq is slow or unreachable. Tunables:

```dotenv
GROQ_TIMEOUT_SECONDS=45
GROQ_MAX_RETRIES=2
GROQ_FALLBACK_MODEL=openai/gpt-oss-20b
```

The client tries the primary model twice, then the fallback twice, then returns a
deterministic result. It never raises into a handler.

### `model_not_found` or `model_decommissioned`

Groq retires models. Set a current one:

```dotenv
GROQ_MODEL=openai/gpt-oss-120b
```

The model id is never hardcoded — it is read from the environment in one place.

### The agent recommends something nonsensical

Check whether `used_fallback` is true on the run. If the LLM is active and the
output is odd, the *numbers* are still trustworthy — they come from the detector,
and the orchestrator overwrites whatever the model produced for impact and
confidence. The prose is the only part the model owns.

### A trace shows 70 steps instead of 7

The LangGraph state reducers and the node return values have drifted out of
agreement. Channels are last-value-wins and nodes return the whole state; adding
`Annotated[list, operator.add]` without also changing nodes to return only their
delta appends the accumulated list to itself at every node.

See the warning in [`app/agents/state.py`](../backend/app/agents/state.py) and
[AGENTS.md](AGENTS.md#state).

### Langfuse shows nothing

Check the host matches the region of your keys — `https://cloud.langfuse.com` for
EU, `https://us.cloud.langfuse.com` for US. Tracing is entirely non-fatal by
design: if it is misconfigured, nothing raises and nothing appears.

---

## Tests

### `make test` fails with a database error

It should not touch Postgres at all. If it does, `DATABASE_URL` is leaking into
the test environment. The fixtures build their own SQLite engine; check nothing in
`conftest.py` was changed to read settings directly.

### `RuntimeError: Event loop is closed`

A fixture scope mismatch. The engine is session-scoped, sessions are
function-scoped, and `asyncio_default_fixture_loop_scope = "function"` in
`pyproject.toml` ties them together. Changing one without the others produces this.

### Tests pass but the app is wrong

Then it is a calibration problem, not a correctness problem:

```bash
make calibrate
```

See [TESTING.md](TESTING.md#what-tests-could-not-catch) — this happened, and it
was the most consequential bug in the project.

---

## Docker

### `make docker-up` starts nothing

The backend and frontend services are behind a profile:

```bash
docker compose --profile full up -d
```

`make db` alone starts only Postgres, which is what local development wants.

### The container cannot reach the database

Inside compose, the host is the service name, not `localhost`:

```dotenv
DATABASE_URL=postgresql+asyncpg://autopilot:autopilot@postgres:5432/autopilot
```

Note port 5432 inside the network — 5433 is only the host-side mapping.

### Changes do not appear

```bash
docker compose build --no-cache backend
docker compose --profile full up -d
```

### Out of disk

```bash
docker system prune -a --volumes    # destroys all local Docker data
```

---

## Windows

### The Makefile does not run

Use **Git Bash** or **WSL2**. The Makefile is POSIX shell. PowerShell will not
parse it.

### Venv path errors

Windows venvs put the interpreter in `Scripts/`, not `bin/`. The Makefile detects
both; if you are invoking directly:

```powershell
backend\.venv\Scripts\python.exe -m pytest
```

### Line ending warnings on shell scripts

```bash
git config --global core.autocrlf input
```

A `.sh` file with CRLF endings fails with a confusing `bad interpreter` error.

### `docker compose` cannot find the daemon

Docker Desktop is not running, or WSL integration is off for your distro. Check
**Settings -> Resources -> WSL Integration**.

---

## Still stuck

Collect this before asking anyone:

```bash
python --version
node --version
docker --version
curl -s http://localhost:8000/api/v1/health
make seed-stats
make test
tail -50 backend/logs/*.log
```

And when in doubt, the reset that fixes most local corruption:

```bash
make db-reset
make migrate
make seed
```

Local demo data only — it destroys the database volume.

---

<div align="center">

[Docs index](README.md) · [Installation](INSTALLATION.md) ·
[Configuration](CONFIGURATION.md) · [Deployment](DEPLOYMENT.md) ·
[Testing](TESTING.md)

</div>
