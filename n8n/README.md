<div align="center">

# Inventory automation

[![Docs index](https://img.shields.io/badge/-Docs_index-475569?style=flat-square&logo=markdown&logoColor=white)](../docs/README.md)
[![Architecture](https://img.shields.io/badge/-Architecture-64748b?style=flat-square)](../docs/ARCHITECTURE.md)
[![Configuration](https://img.shields.io/badge/-Configuration-2563eb?style=flat-square)](../docs/CONFIGURATION.md)
[![Troubleshooting](https://img.shields.io/badge/-Troubleshooting-b45309?style=flat-square)](../docs/TROUBLESHOOTING.md)

</div>

n8n is the *scheduler and router* for inventory automation. It decides **when**
and **whether** to ask the backend to act. It never decides **what** to do: no
reorder quantity, no vendor choice, no approval threshold lives in a workflow
node. Those rules stay in `backend/app/services/inventory/`, under test, on the
side of the wire that owns the data.

That split is why a workflow can be edited in the n8n UI without anyone
reviewing a business rule change, and why the automation behaves identically
whether an event is replayed, retried, or triggered by hand from the UI.

## The loop

```
stock change
   -> DomainEvent written in the same transaction (the outbox)
   -> the outbox relay POSTs it, HMAC-signed, to the n8n webhook   [every 15s]
   -> n8n verifies the signature, routes on event_type
   -> n8n POSTs a signed request back to /api/v1/webhooks/n8n/event
   -> the backend decides, raises the purchase order, records an AutomationRun
   -> the UI sees it over the websocket
```

Both hops are signed, and every hop is idempotent. Measured end to end: about
ten seconds from the sale landing to the purchase order existing.

## What starts it

Two triggers, and they are different kinds of thing.

**The outbox relay** (`app/services/inventory/relay.py`) carries events out of
the backend on a timer — `INVENTORY_DISPATCH_INTERVAL_SECONDS`, 15 by default.
It lives in the backend rather than in an n8n schedule on purpose: draining a
transactional outbox is transport, not a business decision about when to act,
and it has to keep working when n8n is the thing that is down. It is also the
only thing that ever *retries* a failed delivery.

Each tick claims a batch by pushing `next_attempt_at` past a 90-second lease and
commits before sending anything, so the HTTP calls happen with no rows locked
and a second web worker's relay takes a disjoint batch (`SKIP LOCKED`) rather
than delivering the same events twice.

**The schedule trigger inside `PGA 02`** fires at 02:00 in n8n itself and asks
the backend to sweep. That one genuinely is a business schedule, so it belongs
in n8n where it can be seen and changed without a deploy.

The **Flush event outbox** button in the Automation Center calls the same
dispatch by hand. It is for impatience and debugging, not for correctness.

## Deploying

**With Docker Compose it is automatic.** `docker compose up -d --build` runs
`n8n-build` (renders the workflows with `compose_build.py`: callback
`http://backend:8000`, merchant id read from the database, secret from `.env` or
a local default), then `n8n-import` (imports and publishes them), and only then
starts `n8n` - so the webhook is registered on first boot, no restart needed.
After a `seed --reset` changes the merchant id:
`docker compose up -d --force-recreate n8n-build n8n-import n8n`.

**Into an n8n you run yourself:**

```bash
./n8n/import.sh            # builds from .env, imports, restarts, confirms
./n8n/import.sh my-n8n     # if the container is not called "n8n"
```

`n8n/deploy/` is generated and git-ignored — it contains the webhook secret
inline. `build_workflows.py` is the committed source of truth; edit that, never
the JSON, or the next import will overwrite your change.

The restart is not optional. n8n reads workflow activation only at boot, so an
imported workflow's webhook is not registered until the container restarts.

### On Render (free plan)

`render.yaml` deploys n8n as `paypilot-n8n`, next to the API. Nothing about the loop
changes - the outbox relay still POSTs signed events to an HTTPS webhook, and n8n still
calls the API back over HTTPS - so the only new thing is where n8n runs.

How it fits the free plan:

* **No disk, so Postgres.** n8n keeps workflows and execution history in the existing
  free Postgres (tables prefixed `n8n_`, beside the app's own). Execution history is
  pruned after a week to keep the free database small.
* **Workflows come from the repo, at every boot.** The image holds templates built by
  `build_workflows.py`; `render-start.sh` fills in the secret, backend URL and merchant
  id from the service's environment, imports and publishes them, then starts n8n -
  the same order Docker Compose uses. An edit made to a PGA workflow in the n8n UI is
  therefore overwritten on the next restart: change `build_workflows.py` instead.
* **One shared secret.** Render generates `N8N_WEBHOOK_SECRET` once (group
  `paypilot-n8n-link`) and gives it to both services - nothing to copy between them.
* **n8n -> API over the public URL**, because free services have no private network.

First deploy, after Render creates the service:

1. On **`paypilot-n8n`** set
   * `PGA_MERCHANT_ID` - sign in to the app, open `GET /api/v1/merchants/current`, copy
     the id. Without it only the 02:00 sweep and 06:30 scan refuse to run.
   * `N8N_INSTANCE_OWNER_EMAIL` and `N8N_INSTANCE_OWNER_PASSWORD_HASH` - the editor is on
     a public URL, and an unowned n8n lets the first visitor claim it. The password must
     be a bcrypt hash (n8n 2.17+):
     `pip install bcrypt && python -c "import bcrypt,getpass; print(bcrypt.hashpw(getpass.getpass().encode(), bcrypt.gensalt(10)).decode())"`.
     If either is blank the service still starts, logs a warning, and the first visitor
     owns it.
2. On **`paypilot-api`** set `N8N_INVENTORY_WEBHOOK_URL` to
   `https://<paypilot-n8n host>/webhook/pga-inventory-event` and `N8N_BASE_URL` to
   `https://<paypilot-n8n host>`. Render adds a random suffix to the hostname, so these
   cannot be written into the blueprint.
3. Confirm with the health URLs below.

Moving from an n8n you already run: leave it running until the Render one answers
`/webhook/pga-health`, then switch `N8N_INVENTORY_WEBHOOK_URL`. The shared secret is a new
value, so the old n8n's workflows would reject the API's signatures - that is expected,
not a bug.

#### Health URLs for an external monitor

All are plain `GET`s with no authentication and reveal nothing beyond up/down.

| URL | Healthy | What it proves |
|---|---|---|
| `/healthz` | `200 {"status":"ok"}` | The n8n process is up (also Render's health check) |
| `/healthz/readiness` | `200` | ... and its database is reachable |
| `/webhook/pga-health` | `200 {"status":"ok","n8n":"up","workflows":"registered"}` | ... and the PGA workflows are **registered**. `404` here means they are not, which is also what would break the event webhook |
| `/webhook/pga-health?deep=1` | `200 {"status":"ok","n8n":"up","backend":"reachable"}` | ... and n8n can reach the API it calls back into. `503 {"backend":"unreachable"}` if it cannot |

`?deep=1` waits up to 60 seconds for the API, so give the monitor a timeout of at least
that - a sleeping free API needs about a minute to wake, and the check wakes it.

#### Keeping the schedules alive

Free services sleep after about 15 idle minutes. A webhook wakes n8n (about a minute; the
outbox relay retries until it answers), but a **schedule trigger cannot fire while n8n is
asleep**, and a missed run is not caught up. So the 02:00 sweep and 06:30 growth scan need
n8n awake at those times. Point an external scheduler (cron-job.org, a GitHub Actions
cron, etc.) at the deep health URL a few minutes before each:

| When (America/Los_Angeles, n8n's timezone) | URL |
|---|---|
| 01:55 daily | `https://<n8n host>/webhook/pga-health?deep=1` |
| 06:25 daily | `https://<n8n host>/webhook/pga-health?deep=1` |

Each ping wakes n8n and, through `deep=1`, the API too, so the run that follows finds both
awake. **Do not poll more often than every 15 minutes** to "keep it warm": a free
service that never sleeps uses about 730 of the workspace's 750 free instance-hours a
month, leaving almost nothing for the API and web app.

Limits to know about: 512 MB is tight for n8n (the heap is capped at 384 MB so it fails
soft rather than being killed - if it restarts under load, that is why), and the free
Postgres expires after 30 days, taking n8n's state with it. The workflows are rebuilt
from the repo on every boot, so recreating the database loses only execution history and
any credentials you added by hand.

### Required in `.env`

| Variable | What it is |
|---|---|
| `N8N_WEBHOOK_SECRET` | Shared HMAC secret. Both directions. |
| `N8N_INVENTORY_WEBHOOK_URL` | Where the **backend** posts — `http://localhost:5678/webhook/pga-inventory-event` |
| `N8N_BACKEND_URL_FOR_N8N` | How **n8n** reaches the backend — from a container that is `http://host.docker.internal:8000`, not `localhost` |
| `PGA_MERCHANT_ID` | The merchant the nightly sweeps run for |
| `INVENTORY_DISPATCH_INTERVAL_SECONDS` | How often the relay delivers pending events (default 15) |

## Workflows

**`PGA 00 Health`** (webhook `GET /webhook/pga-health`, active)
A health check an external monitor can poll. Answers `200` when n8n is up and the PGA
workflows are registered; with `?deep=1` it also calls the backend's liveness route and
answers `503` if n8n cannot reach it. It carries no secret and does no work.

**`PGA 01 Inventory Event Router`** (webhook, active)
Verifies the signature, then routes on `event_type`:

| Event | What it asks for |
|---|---|
| `inventory.low_stock` | `replenish` — decide and raise a purchase order |
| `inventory.expiring_soon` | `sweep_aging` |
| `inventory.purchase_order_created` | nothing; logged so the event is visible |
| anything else | acknowledged, no action |

The signed callback accepts `replenish`, `sweep_aging`, `reconcile` and
`detect_opportunities`. It is served at both `/webhooks/n8n/event` and the
original `/webhooks/n8n/inventory-event`, which is no longer an accurate name
but is kept working for any workflow already pointing at it.

**`PGA 02 Inventory Nightly Sweeps`** (schedule, 02:00, active)
Asks for `sweep_aging` and `reconcile`. Both are idempotent, so a missed night
is picked up by the next run and there is no catch-up logic to get wrong.

**`PGA 03 Daily Growth Scan`** (schedule, 06:30, active)
Asks for `detect_opportunities`. Opportunity detection used to run only inside an
agent run or a manual API call, which meant nothing looked for new opportunities
unless a merchant asked — so "always-on intelligence" was true of inventory and
not of growth. The detector is deterministic arithmetic over the merchant's own
transactions, so a daily scan costs no LLM tokens, and the upsert is idempotent,
so re-running refreshes rather than duplicates.

## Three things that are easy to get wrong

**1. The Code nodes carry their own SHA-256.**
n8n's task-runner sandbox refuses `require('crypto')` — the error is
`Module 'crypto' is disallowed`, and it surfaces as a failed execution rather
than a bad signature, which is a confusing way to find out. The flag that would
allow it does not exist on n8n Cloud. So `lib/pga-hmac.js` implements HMAC-SHA256
in plain JavaScript and is inlined into every Code node at build time. It is
cross-checked against `node:crypto` — see the test in the repo history.

**2. Signatures cover *canonical* JSON, not the bytes on the wire.**
The body is parsed into a JavaScript object before any node can see it, so the
exact bytes are already gone by the time the signature is checked. Re-serialising
naively does not work: Python writes an integral float as `13.0` and JavaScript
writes `13`, so the two sides would hash different text and every event would
look forged. Both sides therefore serialise to a pinned form — sorted keys, no
spaces, integral floats narrowed to ints, no ASCII escaping. See
`canonical_json()` in `backend/app/services/inventory/events.py` and `canon()` in
`lib/pga-hmac.js`; **they must be changed together.**

**3. Every branch ends at a Respond node with an explicit status.**
Letting a node throw is not equivalent. With `responseMode: responseNode`, a
workflow that fails before reaching a Respond node answers with an empty
`200` — so a *rejected* event would be recorded as successfully delivered and
never retried. Instead the signature check routes its failure to a `401`, and a
backend that cannot be reached routes to a `502`, which is what tells the
outbox to try again.

## Checking it works

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST http://localhost:5678/webhook/pga-inventory-event \
  -H 'Content-Type: application/json' -H 'X-Signature: sha256=bad' -d '{}'
# 401 - the signature check is live
```

A `404` means the workflow is not active: re-run `import.sh`, which restarts the
container for exactly this reason.

The health workflow is the quicker check, and works from anywhere:

```bash
curl -s http://localhost:5678/webhook/pga-health          # {"status":"ok","n8n":"up","workflows":"registered"}
curl -s "http://localhost:5678/webhook/pga-health?deep=1" # also checks n8n -> backend
```
