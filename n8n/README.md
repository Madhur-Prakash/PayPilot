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

### Required in `.env`

| Variable | What it is |
|---|---|
| `N8N_WEBHOOK_SECRET` | Shared HMAC secret. Both directions. |
| `N8N_INVENTORY_WEBHOOK_URL` | Where the **backend** posts — `http://localhost:5678/webhook/pga-inventory-event` |
| `N8N_BACKEND_URL_FOR_N8N` | How **n8n** reaches the backend — from a container that is `http://host.docker.internal:8000`, not `localhost` |
| `PGA_MERCHANT_ID` | The merchant the nightly sweeps run for |
| `INVENTORY_DISPATCH_INTERVAL_SECONDS` | How often the relay delivers pending events (default 15) |

## Workflows

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
