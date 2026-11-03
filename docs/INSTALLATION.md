<div align="center">

# Installation

[![Docs index](https://img.shields.io/badge/-Docs_index-475569?style=flat-square&logo=markdown&logoColor=white)](README.md)
[![Configuration](https://img.shields.io/badge/-Next:_Configuration-2563eb?style=flat-square)](CONFIGURATION.md)
[![Troubleshooting](https://img.shields.io/badge/-Troubleshooting-dc2626?style=flat-square)](TROUBLESHOOTING.md)

</div>

Getting PayPilot running locally. Budget about ten minutes, most of
it dependency downloads.

---

## Contents

- [Prerequisites](#prerequisites)
- [Fast path](#fast-path)
- [Step by step](#step-by-step)
- [Verify the installation](#verify-the-installation)
- [Platform notes](#platform-notes)
- [Running without Docker](#running-without-docker)
- [What gets installed](#what-gets-installed)
- [Next steps](#next-steps)

---

## Prerequisites

| Requirement | Version | Why | Check |
| --- | --- | --- | --- |
| **Python** | 3.11 or newer | Backend | `python --version` |
| **Node.js** | 20 or newer | Frontend | `node --version` |
| **Docker** | any recent | Postgres + pgvector | `docker --version` |
| **make** | any | Task runner | `make --version` |
| **git** | any | Clone | `git --version` |

Built and verified on Python 3.12.10, Node 22.15.1, Docker 29.7.2.

### If you do not have Docker

You can point at any PostgreSQL 14+ with the `vector` extension available —
including Supabase. See [Running without Docker](#running-without-docker).

### If you do not have make

Every target is a short shell command; run them directly. The
[fast path](#fast-path) shows the expansion.

---

## Fast path

```bash
git clone https://github.com/Madhur-Prakash/PayPilot
cd paypilot

cp .env.example .env
make setup          # env -> dependencies -> database -> migrations -> seed
make dev            # backend :8000, frontend :3000
```

Open <http://localhost:3000> and sign in with `owner@sharmacafe.in` /
`Autopilot@2024`.

<details>
<summary><b>Without make</b> — the same steps expanded</summary>

```bash
# 1. Environment
cp .env.example .env

# 2. Backend dependencies
cd backend
python -m venv .venv
# macOS / Linux:
source .venv/bin/activate
# Windows PowerShell:
#   .venv\Scripts\Activate.ps1
# Windows Git Bash:
#   source .venv/Scripts/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-optional.txt   # best effort
cd ..

# 3. Frontend dependencies
cd frontend && npm install && cd ..

# 4. Database
docker compose up -d postgres

# 5. Schema and data
cd backend
python -m alembic upgrade head
python -m app.seed.seed
cd ..

# 6. Run (two terminals)
cd backend && python -m uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev
```

</details>

---

## Step by step

### 1. Clone and enter

```bash
git clone <repository-url> paypilot
cd paypilot
```

### 2. Create the environment file

```bash
cp .env.example .env
```

The defaults work for local development out of the box. Nothing needs an API key.

> **Before deploying anywhere**, change `JWT_SECRET`. Generate one with:
> ```bash
> python -c "import secrets; print(secrets.token_urlsafe(64))"
> ```
> Full reference: [CONFIGURATION.md](CONFIGURATION.md).

### 3. Install dependencies

```bash
make install
```

This creates `backend/.venv`, installs Python requirements, then installs the
frontend's npm packages.

Optional extras (`logifyx` for structured logging, `fastembed` for real semantic
embeddings) install on a best-effort basis — the application degrades gracefully
if either is unavailable.

### 4. Start PostgreSQL

```bash
make db          # docker compose up -d postgres
make wait-db     # blocks until it accepts connections
```

Uses the `pgvector/pgvector:pg16` image on **port 5433** (not 5432, to avoid
colliding with an existing local Postgres). `vector` and `pgcrypto` are created on
first start by [`docker/postgres/init/01-extensions.sql`](../docker/postgres/init/01-extensions.sql).

### 5. Apply migrations

```bash
make migrate
```

Creates all 30 tables. The initial migration also creates the `vector` and
`pgcrypto` extensions, guarded so it still runs on SQLite.

### 6. Seed the demo data

```bash
make seed
```

Takes roughly 45-70 seconds: 1,700 customers, ~14,800 transactions, ~2,475
reviews with embeddings, competitors, inventory, signals, two historical
experiments, and the opportunities detected from all of it.

`make seed` is idempotent — it skips if data is already present. Use `make reseed`
to wipe and rebuild.

### 7. Run

```bash
make dev
```

Starts both. Or separately:

```bash
make backend     # http://localhost:8000
make frontend    # http://localhost:3000
```

---

## Verify the installation

### Health check

```bash
curl -s http://localhost:8000/api/v1/health | python -m json.tool
```

Expect:

```json
{
  "success": true,
  "data": {
    "status": "ok",
    "checks": {
      "database": "ok",
      "llm": "not_configured",
      "langfuse": "not_configured",
      "vapi": "not_configured",
      "embeddings": "hash",
      "logging_backend": "logifyx"
    }
  }
}
```

`not_configured` is expected and fine — everything works without those.

### Data is present

```bash
make seed-stats
```

```
  Merchant : Sharma Cafe (sharma-cafe)
  products            : 8
  customers           : 1,700
  transactions        : 14,819
  reviews             : 2,475
  competitors         : 3
  external signals    : 4
```

### Tests pass

```bash
make test
```

```
105 passed in 10s
```

Tests run on SQLite, so this works even with Docker stopped.

### The story is intact

```bash
make calibrate
```

Prints the figures the dashboard will show, computed without touching a database.
Revenue should be down roughly 12%, with the evening slot down roughly 32%.

### The UI loads

Open <http://localhost:3000>, sign in as `owner@sharmacafe.in` /
`Autopilot@2024`, and confirm the Command Center shows four KPI cards with
negative deltas and an Opportunity Radar with four entries.

---

## Platform notes

### macOS

```bash
brew install python@3.12 node docker make
```

Docker Desktop must be running before `make db`.

### Linux (Debian / Ubuntu)

```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv nodejs npm make
# Docker: https://docs.docker.com/engine/install/
```

If `docker compose` needs sudo, add yourself to the `docker` group:

```bash
sudo usermod -aG docker "$USER" && newgrp docker
```

### Windows

Use **Git Bash** or **WSL2**; the Makefile is POSIX shell.

```powershell
winget install Python.Python.3.12
winget install OpenJS.NodeJS.LTS
winget install Docker.DockerDesktop
```

`make` is not present by default. Either install it:

```powershell
winget install GnuWin32.Make
```

or use WSL2, or run the expanded commands in the
[fast path](#fast-path) `<details>` block.

Inside the venv on Windows, the interpreter is `backend/.venv/Scripts/python.exe`
(not `bin/python`). The Makefile detects both layouts automatically.

---

## Running without Docker

Any PostgreSQL 14+ with pgvector works.

### Existing local PostgreSQL

```bash
createdb autopilot
psql -d autopilot -c 'CREATE EXTENSION IF NOT EXISTS "vector";'
psql -d autopilot -c 'CREATE EXTENSION IF NOT EXISTS "pgcrypto";'
```

Then in `.env`:

```dotenv
DATABASE_URL=postgresql+asyncpg://YOUR_USER:YOUR_PASSWORD@localhost:5432/autopilot
```

```bash
make migrate && make seed
```

### Supabase

Enable the `vector` extension in **Database -> Extensions**, then use the
**session** connection string:

```dotenv
DATABASE_URL=postgresql+asyncpg://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
```

The engine detects the pooler and disables asyncpg's prepared-statement cache
automatically — required for transaction-pooling mode.

Full walkthrough: [DEPLOYMENT.md](DEPLOYMENT.md#supabase).

### No database at all

The test suite runs entirely on SQLite:

```bash
make test
```

And the dataset generator needs nothing:

```bash
make calibrate
```

---

## What gets installed

### Backend (`backend/requirements.txt`)

Pinned to the versions the test suite runs against. `pyproject.toml` declares *what* the project depends on; this file pins *which* versions, for installing with pip rather than uv.

| Package | Purpose |
| --- | --- |
| `fastapi`, `uvicorn` | Web framework and server |
| `pydantic`, `pydantic-settings` | Validation and configuration |
| `sqlalchemy[asyncio]`, `asyncpg`, `alembic` | ORM, async driver, migrations |
| `pgvector` | Vector column type |
| `PyJWT`, `argon2-cffi` | Tokens and password hashing |
| `httpx`, `tenacity`, `orjson` | HTTP, retries, fast JSON |
| `groq`, `langgraph`, `langchain-core` | LLM and agent orchestration |
| `langfuse` | Agent observability |
| `cognee` | Agent long-term memory (brings ~75 transitive packages) |
| `pytest`, `pytest-asyncio`, `aiosqlite` | Testing |
| `ruff`, `mypy` | Lint and types |

### Backend optional (`requirements-optional.txt`)

| Package | Purpose | If missing |
| --- | --- | --- |
| `logifyx` | Structured logging backend | Built-in JSON logger takes over |
| `fastembed` | Local ONNX embeddings | Deterministic hash embeddings used |

### Frontend (`frontend/package.json`)

| Package | Purpose |
| --- | --- |
| `next`, `react`, `react-dom` | Framework |
| `typescript`, `@types/*` | Types |
| `tailwindcss`, `tailwindcss-animate` | Styling |
| `@radix-ui/*`, `class-variance-authority` | shadcn/ui primitives |
| `framer-motion` | Motion |
| `recharts` | Charts |
| `@tanstack/react-query` | Server state |
| `axios` | The single HTTP client |
| `zustand` | Session state |
| `react-hook-form`, `zod`, `@hookform/resolvers` | Forms and validation |
| `lucide-react` | Icons |
| `sonner` | Toasts |
| `next-themes` | Dark mode |
| `@vapi-ai/web` | Voice (lazy-loaded) |

---

## Next steps

| | |
| --- | --- |
| [Configuration](CONFIGURATION.md) | Wire up Groq, Langfuse, Vapi, or Supabase |
| [Demo script](DEMO.md) | Walk the product end to end |
| [Architecture](ARCHITECTURE.md) | Understand how it is put together |
| [Troubleshooting](TROUBLESHOOTING.md) | If something above did not work |

---

<div align="center">

[Docs index](README.md) · [Project README](../README.md) ·
[Configuration](CONFIGURATION.md) · [Deployment](DEPLOYMENT.md)

</div>
