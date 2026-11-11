<div align="center">

# Installation

A complete local development environment, step by step, on macOS, Linux or Windows.

[![Docs index](https://img.shields.io/badge/-Docs_index-0b2a6f?style=flat-square)](README.md)
[![Quick start](https://img.shields.io/badge/-Quick_start-16a34a?style=flat-square)](QUICKSTART.md)
[![Configuration](https://img.shields.io/badge/-Configuration-2563eb?style=flat-square)](CONFIGURATION.md)
[![Troubleshooting](https://img.shields.io/badge/-Troubleshooting-dc2626?style=flat-square)](TROUBLESHOOTING.md)

</div>

---

## Contents

- [Prerequisites](#prerequisites)
- [Automated setup](#automated-setup)
- [Manual setup](#manual-setup)
- [Verify the installation](#verify-the-installation)
- [Running without Docker](#running-without-docker)
- [Platform notes](#platform-notes)
- [What gets installed](#what-gets-installed)
- [The task runner](#the-task-runner)

---

## Prerequisites

| Tool | Version | Required | Used for | Check |
| --- | --- | :-: | --- | --- |
| Python | 3.11 to 3.14 | yes | Backend (`requires-python = ">=3.11,<3.15"`) | `python --version` |
| Node.js | 20 or newer | yes | Frontend (`engines.node >= 20`) | `node --version` |
| npm | ships with Node | yes | Frontend dependencies | `npm --version` |
| Git | any | yes | Clone | `git --version` |
| Docker | any recent, with Compose | recommended | Local Postgres 16 + pgvector, optional Redis and n8n | `docker compose version` |
| GNU Make | any | optional | Short commands; every target has a PowerShell or Python equivalent | `make --version` |
| uv | any | optional | Faster backend installs (used automatically when present) | `uv --version` |

The container images use Python 3.12 and Node 22.

---

## Automated setup

```bash
git clone https://github.com/Madhur-Prakash/PayPilot.git
cd PayPilot
make init
```

`make init` runs, in order:

1. **Tool check.** Python, Node, npm and Git must be present; Docker and uv are reported if missing.
2. **Environment.** Copies `.env.example` to `.env` only if `.env` does not exist. The copy works as-is.
3. **Dependencies.** `uv sync` in `backend/` when uv is installed, otherwise a `backend/.venv` virtualenv with
   `pip install -r requirements.txt` plus the optional extras (best effort). Then `npm ci` in `frontend/`.
4. **Database.** If Docker is running: `docker compose up -d postgres`, wait until `pg_isready`, run
   `alembic upgrade head`, seed the demo data. If Docker is not running but `DATABASE_URL` points at a reachable
   database, it migrates and seeds that one. Otherwise it tells you what to run next.

Then start everything:

```bash
make dev
```

On Windows without Make, use `scripts\setup.ps1` and `scripts\dev.ps1` (see [Quick start](QUICKSTART.md#path-c-windows-powershell)).
On macOS and Linux without Make, `sh scripts/setup.sh` and `sh scripts/dev.sh` do the same.

---

## Manual setup

The same steps without the task runner, useful when something needs to be done differently.

### 1. Environment file

```bash
cp .env.example .env
```

There is exactly one `.env`, at the repository root. Both the backend and the frontend read it. Every secret is
blank by default. See [Configuration](CONFIGURATION.md).

### 2. Backend dependencies

```bash
cd backend
python -m venv .venv

# macOS / Linux
source .venv/bin/activate
# Windows PowerShell
.venv\Scripts\Activate.ps1
# Windows Git Bash
source .venv/Scripts/activate

python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-optional.txt   # optional: local embedding model
cd ..
```

### 3. Frontend dependencies

```bash
cd frontend
npm ci
cd ..
```

### 4. Database

```bash
docker compose up -d postgres
```

This starts `pgvector/pgvector:pg16` on host port **5433** (not 5432, so it never collides with a Postgres you
already run). [`docker/postgres/init/01-extensions.sql`](../docker/postgres/init/01-extensions.sql) creates the
`vector` and `pgcrypto` extensions on first start.

Optional, for shared rate limits and caches:

```bash
docker compose up -d redis
# then in .env:  REDIS_URL=redis://localhost:6379/0
```

### 5. Schema and demo data

```bash
cd backend
python -m alembic upgrade head
python -m app.seed.seed
cd ..
```

The seed is idempotent: if the demo merchant already exists it does nothing. `python -m app.seed.seed --reset`
removes the demo tenant and rebuilds it.

### 6. Run

Two terminals:

```bash
cd backend && python -m uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend && npm run dev
```

---

## Verify the installation

### Health

```bash
curl -s http://localhost:8000/api/v1/health | python -m json.tool
```

```json
{
  "success": true,
  "data": {
    "status": "ok",
    "checks": {
      "database": "ok",
      "redis": "not_configured",
      "llm": "not_configured",
      "langfuse": "not_configured",
      "vapi": "not_configured",
      "email": "...",
      "embeddings": "hash",
      "logging_backend": "..."
    }
  }
}
```

`not_configured` is expected; every feature has a documented behaviour without its integration. `status` is
`degraded` only when the database is unreachable.

### Configuration report

```bash
make check
```

Prints the tool versions, whether `.env` is present, the PayPal mode (`SIMULATED` or `SANDBOX/LIVE`), whether
Groq and Channel3 keys are set, and whether dependencies are installed.

### The UI

Open <http://localhost:3000>, sign in as `owner@juniperoak.com` / `Autopilot@2024`, and open the Command Center.

### Tests

```bash
make test-backend
```

The backend suite runs on SQLite in memory, so it passes with Docker stopped and no keys set. See
[Testing](TESTING.md).

### The demo story without a database

```bash
make calibrate
```

Generates the dataset in memory and prints the figures the dashboard will show. See [Data](DATA.md#calibration).

---

## Running without Docker

Any PostgreSQL 14 or newer with the `vector` extension works.

### An existing local PostgreSQL

```bash
createdb autopilot
psql -d autopilot -c 'CREATE EXTENSION IF NOT EXISTS "vector";'
psql -d autopilot -c 'CREATE EXTENSION IF NOT EXISTS "pgcrypto";'
```

```dotenv
DATABASE_URL=postgresql+asyncpg://YOUR_USER:YOUR_PASSWORD@localhost:5432/autopilot
```

```bash
make migrate && make seed
```

### A managed database

Use the provider's connection string with the `postgresql+asyncpg://` scheme. A plain `postgres://` or
`postgresql://` URL is normalised to `postgresql+asyncpg://` automatically, and `sslmode=` is translated to
asyncpg's `ssl=`. Connection poolers (Supabase pooler, PgBouncer) are detected and handled; see
[Deployment: managed Postgres](DEPLOYMENT.md#managed-postgres).

### No database at all

The test suite and the calibration harness need no database:

```bash
make test-backend
make calibrate
```

---

## Platform notes

### macOS

```bash
brew install python@3.12 node git
brew install --cask docker
```

Start Docker Desktop before `make init`.

### Linux (Debian, Ubuntu)

```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv nodejs npm make git
# Docker Engine: https://docs.docker.com/engine/install/
sudo usermod -aG docker "$USER" && newgrp docker
```

The Makefile uses `python3` on non-Windows systems.

### Windows

```powershell
winget install Python.Python.3.12
winget install OpenJS.NodeJS.LTS
winget install Git.Git
winget install Docker.DockerDesktop
```

Make is optional on Windows: the PowerShell scripts in `scripts\` call the same task runner. If you prefer Make,
`winget install GnuWin32.Make` or use WSL2. The task runner detects the Windows virtualenv layout
(`backend\.venv\Scripts\python.exe`) automatically.

---

## What gets installed

### Backend

[`backend/requirements.txt`](../backend/requirements.txt) pins the versions the test suite runs against;
[`backend/pyproject.toml`](../backend/pyproject.toml) declares the same dependencies for uv.

| Package | Purpose |
| --- | --- |
| `fastapi`, `uvicorn` | Web framework and ASGI server |
| `pydantic`, `pydantic-settings` | Validation and configuration |
| `sqlalchemy[asyncio]`, `asyncpg`, `alembic` | ORM, async Postgres driver, migrations |
| `pgvector` | Vector column type for agent memory and review search |
| `PyJWT`, `argon2-cffi` | Access tokens and password hashing |
| `httpx`, `tenacity`, `orjson` | HTTP clients, retries, fast JSON |
| `paypal-server-sdk` | PayPal's APIMatic-generated Server SDK (Orders v2) |
| `groq`, `langgraph`, `langchain-core` | LLM client and agent orchestration |
| `langfuse` | Agent tracing |
| `redis` | Optional shared rate limits, caches and pub/sub |
| `openpyxl` | Inventory import and Excel export |
| `google-api-python-client`, `google-auth`, `Jinja2` | Optional Gmail delivery and email templates |
| `pytest`, `pytest-asyncio`, `aiosqlite`, `fakeredis` | Tests on in-memory SQLite, Redis fakes |
| `ruff`, `mypy` | Lint and type checks |

[`backend/requirements-optional.txt`](../backend/requirements-optional.txt) adds `logifyx` (structured console
rendering) and `fastembed` (local ONNX embeddings). Without them, the built-in log renderer and deterministic
hash embeddings are used.

### Frontend

| Package | Purpose |
| --- | --- |
| `next` 15, `react` 19, `typescript` 5.7 | Framework |
| `tailwindcss`, `@radix-ui/*`, `class-variance-authority` | Styling and shadcn/ui primitives |
| `@tanstack/react-query`, `axios`, `zustand` | Server state, the single HTTP client, session state |
| `ag-grid-community`, `ag-grid-react` 36.3 | Data grids |
| `ag-studio`, `ag-studio-react` | Dashboard Studio |
| `@bryntum/gantt-react-enterprise`, `@bryntum/scheduler-react-enterprise` 8.0 | Procurement timeline, subscription radar |
| `recharts`, `framer-motion` | Charts and motion |
| `react-hook-form`, `zod` | Forms and validation |
| `@vapi-ai/web` | Voice (lazy-loaded) |
| `vitest` | Unit tests |

---

## The task runner

Every Make target delegates to [`scripts/tasks.py`](../scripts/tasks.py), a standard-library Python script, so
the commands behave the same on every platform. `make help` lists them all.

| Target | Does |
| --- | --- |
| `make init` | First-time setup (tools, `.env`, dependencies, database, migrations, seed) |
| `make install` | Backend and frontend dependencies only |
| `make env` | Create `.env` from `.env.example` if missing |
| `make check` | Tools, versions, `.env` and integration modes |
| `make integrations` | One live call each to Channel3 and the PayPal sandbox; prints no secrets |
| `make dev`, `make dev-backend`, `make dev-frontend` | Run the app (`PORT`, `WEB_PORT` override the ports) |
| `make docker-up` | Postgres only; `FULL=1` for the whole Compose stack |
| `make docker-down`, `make docker-logs` | Stop containers (data kept), tail logs |
| `make migrate`, `make migration MSG="..."` | Apply migrations, autogenerate a new one |
| `make seed`, `make seed-reset` | Idempotent demo seed, rebuild the demo tenant |
| `make reset-db CONFIRM=yes` | Destroy and rebuild the local database |
| `make demo` | Postgres, migrations and a fresh demo seed |
| `make calibrate` | Print the seeded story's figures without a database |
| `make test`, `make test-backend`, `make test-frontend` | Test suites |
| `make lint`, `make format`, `make typecheck`, `make build`, `make verify` | Quality gates |
| `make clean` | Remove caches and build output (never `.env`, dependencies, data or logs) |
| `make n8n-build`, `make n8n-import` | Render the n8n workflows; import them into a running n8n |

---

<div align="center">

[Previous: Quick start](QUICKSTART.md) | [Docs index](README.md) | [Next: Configuration](CONFIGURATION.md)

</div>
