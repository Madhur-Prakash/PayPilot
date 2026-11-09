#!/bin/sh
# Start command for n8n on Render (n8n/Dockerfile -> ENTRYPOINT).
#
# Mirrors what docker-compose does in three services (n8n-build, n8n-import, n8n),
# in one process, because a Render service is one container:
#   1. fill the workflow templates from the service's environment,
#   2. import and publish them *before* n8n starts - n8n reads workflow activation
#      only at boot, so importing into a running instance would leave the webhooks
#      unregistered,
#   3. exec n8n.
#
# The workflows are rewritten from the repo on every boot, so an edit made in the n8n
# UI to a PGA workflow does not survive a restart - change n8n/build_workflows.py.
set -eu

log() { echo "[pga] $*"; }

# ---- where n8n lives ---------------------------------------------------------------
# Render injects the service's public URL and the port it expects us to listen on.
export N8N_PORT="${PORT:-5678}"
if [ -n "${RENDER_EXTERNAL_URL:-}" ]; then
  export WEBHOOK_URL="${RENDER_EXTERNAL_URL%/}/"
  export N8N_EDITOR_BASE_URL="${RENDER_EXTERNAL_URL%/}"
  host="${RENDER_EXTERNAL_URL#*://}"
  export N8N_HOST="${host%%/*}"
  export N8N_PROTOCOL=https
  export N8N_PROXY_HOPS="${N8N_PROXY_HOPS:-1}"   # one proxy (Render's) in front of us
  log "public URL ${WEBHOOK_URL}"
fi

# ---- who may sign in ---------------------------------------------------------------
# The editor is on a public URL, and an unclaimed n8n lets the first visitor create
# the owner account. n8n can create the owner from the environment instead (v2.17+),
# but only with a bcrypt hash; without one, say so rather than start half-configured.
if [ -n "${N8N_INSTANCE_OWNER_EMAIL:-}" ] && [ -n "${N8N_INSTANCE_OWNER_PASSWORD_HASH:-}" ]; then
  export N8N_INSTANCE_OWNER_MANAGED_BY_ENV=true
  export N8N_INSTANCE_OWNER_FIRST_NAME="${N8N_INSTANCE_OWNER_FIRST_NAME:-PayPilot}"
  export N8N_INSTANCE_OWNER_LAST_NAME="${N8N_INSTANCE_OWNER_LAST_NAME:-Admin}"
  log "owner account managed from the environment (${N8N_INSTANCE_OWNER_EMAIL})"
else
  unset N8N_INSTANCE_OWNER_MANAGED_BY_ENV || true
  log "WARNING: N8N_INSTANCE_OWNER_EMAIL / N8N_INSTANCE_OWNER_PASSWORD_HASH are not set."
  log "         The first person to open the editor URL will become its owner - set them."
fi

# ---- workflows ---------------------------------------------------------------------
WORKDIR="$(mktemp -d)"
node /pga/render-workflows.js /pga/workflows "$WORKDIR"

n8n import:workflow --separate --input="$WORKDIR"
for id in PGAHealth PGAInventoryRouter PGAInventorySweeps PGAGrowthScan; do
  # n8n 2.x: publish:workflow; update:workflow --active is the 1.x spelling.
  n8n publish:workflow --id="$id" >/dev/null 2>&1 \
    || n8n update:workflow --id="$id" --active=true >/dev/null 2>&1 \
    || log "could not activate $id - check it in the editor"
done
# The rendered files carry the webhook secret inline.
rm -rf "$WORKDIR"

log "starting n8n on port ${N8N_PORT}"
exec n8n start
