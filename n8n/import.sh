#!/usr/bin/env bash
# Build the workflows from .env and load them into a running n8n container.
#
#   ./n8n/import.sh [container-name]     # default: n8n
#
# n8n's CLI importer writes the `active` flag straight from the file and only
# reads the database at boot, so activation is re-asserted and the container is
# restarted afterwards - without that, an import quietly unregisters the
# webhook and the inventory loop stops dead.
set -euo pipefail

CONTAINER="${1:-n8n}"
# Work from this directory throughout: on Git Bash for Windows an absolute
# MSYS path ("/c/Users/...") is handed to a native python.exe unchanged and
# fails to open, while relative paths work under either shell.
cd "$(dirname "${BASH_SOURCE[0]}")"
export MSYS_NO_PATHCONV=1

python build_workflows.py

docker exec -u root "$CONTAINER" rm -rf /tmp/pga-deploy
docker cp deploy "$CONTAINER:/tmp/pga-deploy"
docker exec "$CONTAINER" n8n import:workflow --separate --input=/tmp/pga-deploy

for id in PGAInventoryRouter PGAInventorySweeps PGAGrowthScan; do
  # n8n 2.x: publish:workflow; update:workflow --active is the 1.x spelling.
  docker exec "$CONTAINER" n8n publish:workflow --id="$id" >/dev/null 2>&1 \
    || docker exec "$CONTAINER" n8n update:workflow --id="$id" --active=true >/dev/null 2>&1 \
    || true
done

echo "restarting $CONTAINER so the webhooks register..."
docker restart "$CONTAINER" >/dev/null

for _ in $(seq 1 60); do
  if [ "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:5678/healthz || true)" = "200" ]; then
    sleep 3
    echo
    # Probe the router's webhook with a bad signature instead of grepping the logs
    # (n8n 2.x no longer prints "Activated workflow"): 401 = active and verifying,
    # 404 = not registered.
    code="$(curl -s -o /dev/null -w '%{http_code}' -X POST http://localhost:5678/webhook/pga-inventory-event \
      -H 'Content-Type: application/json' -H 'X-Signature: sha256=bad' -d '{}' || true)"
    if [ "$code" = "401" ]; then
      echo "  webhook live: PGA 01 is active and rejecting unsigned requests (401)"
    else
      echo "  webhook answered $code, expected 401 - check the workflows are active in the n8n UI"
    fi
    exit 0
  fi
  sleep 2
done

echo "n8n did not come back within two minutes - check 'docker logs $CONTAINER'" >&2
exit 1
