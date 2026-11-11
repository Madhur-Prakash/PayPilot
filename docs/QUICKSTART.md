<div align="center">

# Quick start

PayPilot running on your machine in about five minutes, with no API keys.

[![Docs index](https://img.shields.io/badge/-Docs_index-0b2a6f?style=flat-square)](README.md)
[![Project README](https://img.shields.io/badge/-Project_README-475569?style=flat-square)](../README.md)
[![Installation](https://img.shields.io/badge/-Installation-16a34a?style=flat-square)](INSTALLATION.md)
[![Configuration](https://img.shields.io/badge/-Configuration-2563eb?style=flat-square)](CONFIGURATION.md)
[![Troubleshooting](https://img.shields.io/badge/-Troubleshooting-dc2626?style=flat-square)](TROUBLESHOOTING.md)

</div>

---

## Contents

- [Choose a path](#choose-a-path)
- [Path A: everything in Docker](#path-a-everything-in-docker)
- [Path B: local development with Make](#path-b-local-development-with-make)
- [Path C: Windows PowerShell](#path-c-windows-powershell)
- [Sign in](#sign-in)
- [First things to try](#first-things-to-try)
- [Add real keys](#add-real-keys)
- [Stop and reset](#stop-and-reset)

---

## Choose a path

| Path | You need | You get | Best for |
| --- | --- | --- | --- |
| **A. Docker** | Docker Desktop or Docker Engine with Compose | Postgres, Redis, API, outbox worker, web app and n8n, all containerised | Evaluating the product |
| **B. Make** | Python 3.11-3.14, Node 20+, Git, Docker (for Postgres) | Hot-reloading backend and frontend on your machine | Developing |
| **C. PowerShell** | Same as B, on Windows without Make | Same as B | Developing on Windows |

Every path runs without keys. PayPal uses a labelled simulator (`SIM-` identifiers, `SIMULATED` badges) and the
agents run in deterministic mode. Product Discovery and Supply Intelligence need a free Channel3 key and show
setup steps until one is set.

---

## Path A: everything in Docker

```bash
git clone https://github.com/Madhur-Prakash/PayPilot.git
cd PayPilot
cp .env.example .env            # optional - the stack also starts without it
docker compose up -d --build
```

The first start builds the images, runs the migrations and seeds the demo merchant (about 15,000 transactions),
which takes about two minutes. Follow it with:

```bash
docker compose logs -f backend
```

| Service | URL |
| --- | --- |
| Web app | <http://localhost:3000> |
| API docs (Swagger) | <http://localhost:8000/docs> |
| API health | <http://localhost:8000/api/v1/health> |
| n8n | <http://localhost:5678> (create the n8n owner account on first visit) |

The n8n workflows are rendered, imported and published automatically before n8n starts. See
[Automation](AUTOMATION.md) for what they do.

---

## Path B: local development with Make

```bash
git clone https://github.com/Madhur-Prakash/PayPilot.git
cd PayPilot
make init
make dev
```

`make init` checks your tools, creates `.env` from `.env.example` (it never overwrites an existing one),
installs backend and frontend dependencies, starts Postgres in Docker, runs the migrations and seeds the demo
data. It never deletes data, so it is safe to re-run.

`make dev` starts Postgres if needed, then the backend on <http://localhost:8000> and the frontend on
<http://localhost:3000>. `Ctrl+C` stops both.

Useful variations:

```bash
make dev PORT=8010 WEB_PORT=3001   # different ports (update NEXT_PUBLIC_API_URL and CORS_ORIGINS to match)
make dev-backend                   # backend only
make dev-frontend                  # frontend only
make check                         # tools, versions, .env and integration modes
```

No Docker? Point `DATABASE_URL` in `.env` at any PostgreSQL 16 with the `vector` extension, then run
`make init`. See [Installation: running without Docker](INSTALLATION.md#running-without-docker).

---

## Path C: Windows PowerShell

```powershell
git clone https://github.com/Madhur-Prakash/PayPilot.git
cd PayPilot
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

The scripts call the same task runner as Make (`scripts/tasks.py`), so behaviour is identical.
`scripts\check.ps1` is the equivalent of `make check`. Add `-SkipDb` to `setup.ps1` to skip the database step.

---

## Sign in

Open <http://localhost:3000>. The login form is prefilled with the Owner account.

| Role | Email | What the role can do |
| --- | --- | --- |
| Owner | `owner@juniperoak.com` | Everything, including managing users |
| Admin | `admin@juniperoak.com` | Approve and execute purchases, payments, campaigns and experiments |
| Analyst | `analyst@juniperoak.com` | Investigate, source and negotiate; cannot approve or pay |
| Staff | `staff@juniperoak.com` | Receive goods and record inventory actions |
| Viewer | `viewer@juniperoak.com` | Read only |

The password for every account is `Autopilot@2024`.

---

## First things to try

Each step is a real API flow, not a mock-up. The figures are what the deterministic seed produces.

| # | Where | What happens |
| :-: | --- | --- |
| 1 | `/shop` (no sign-in) | Buy coffee beans with PayPal. The sale is recorded, stock drops and a low-stock event fires |
| 2 | `/command` | Command Center: revenue, stockout risk, PayPal mode badge, live business events |
| 3 | `/opportunities` | The demand spike for Premium Coffee Beans with its evidence |
| 4 | `/supply/reorder` | The deterministic price ceiling and budget. Start an RFQ |
| 5 | `/supply/negotiations/{id}` | Watch the buyer agent negotiate with three supplier agents; every message is signed and verified |
| 6 | `/approvals` | Sign in as the Analyst in a private window and try to approve: `403`. Approve as the Owner |
| 7 | `/supply/receiving` | Receive 100 of 150 bags: payment is held. Receive the rest: it is released |
| 8 | `/finance/payments` | Pay with PayPal (simulated without keys; sandbox with keys) and capture |
| 9 | `/supply/reconciliation` | PO, receipt, invoice and capture agree to the cent; margin moves from 35.6% to 43.8% |
| 10 | `/integrations` | Which integrations are live and which are labelled fallbacks |

From the API instead:

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"owner@juniperoak.com","password":"Autopilot@2024"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['data']['tokens']['access_token'])")

curl -s localhost:8000/api/v1/command-center -H "Authorization: Bearer $TOKEN" | python -m json.tool | head -40
```

A Postman collection with 59 requests is in [`postman/`](../postman/).

---

## Add real keys

All keys go in the root `.env`. Restart the backend after changing it.

| To enable | Set | Guide |
| --- | --- | --- |
| PayPal sandbox | `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_ENVIRONMENT=sandbox` | [PayPal: using the sandbox](PAYPAL.md#using-the-sandbox) |
| LLM wording and routing | `GROQ_API_KEY` | [Configuration: Groq](CONFIGURATION.md#llm-groq) |
| Product Discovery, Supply Intelligence | `CHANNEL3_API_KEY` | [Supply Intelligence](SUPPLY_INTELLIGENCE.md) |
| Agent traces | `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | [Configuration: Langfuse](CONFIGURATION.md#langfuse) |

Check what is configured, without printing any secret:

```bash
make check          # reads .env and reports each mode
make integrations   # one live call each to Channel3 and the PayPal sandbox
```

---

## Stop and reset

| Goal | Docker path | Make path |
| --- | --- | --- |
| Stop, keep data | `docker compose stop` | `Ctrl+C`, then `make docker-down` |
| Rebuild the demo data | `docker compose exec backend python -m app.seed.seed --reset` | `make seed-reset` |
| Wipe everything | `docker compose down -v` | `make reset-db CONFIRM=yes` |

`make reset-db` is destructive and refuses to run without `CONFIRM=yes`.

---

<div align="center">

[Docs index](README.md) | [Next: Installation](INSTALLATION.md)

</div>
