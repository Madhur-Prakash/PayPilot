#!/usr/bin/env bash
# Build PayPilot's APIMatic artefacts: the developer portal, SDKs and Context Plugin.
#
#   scripts/apimatic.sh            spec + validate + portal + SDKs + plugin
#   scripts/apimatic.sh serve      live preview of the portal on http://localhost:23513
#   scripts/apimatic.sh portal     only the static portal (apimatic/portal)
#   scripts/apimatic.sh sdk        only the Python and TypeScript SDKs (apimatic/sdk)
#   scripts/apimatic.sh plugin     only the Context Plugin (apimatic/plugin)
#
# Needs the APIMatic CLI (npm i -g @apimatic/cli@2, Node 22.14+) and an APIMatic
# account. Either run `apimatic auth login` once, or put an API key in the root .env as
# APIMATIC_API_KEY (APIMatic dashboard -> Account -> API Keys). The key is never printed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="$ROOT/apimatic"
STEP="${1:-all}"

command -v apimatic >/dev/null 2>&1 || {
  echo "APIMatic CLI not found. Install it with: npm i -g @apimatic/cli@2" >&2
  exit 1
}

# Key from the environment, else from the root .env; blank means "use apimatic auth login".
KEY="${APIMATIC_API_KEY:-}"
if [[ -z "$KEY" && -f "$ROOT/.env" ]]; then
  KEY="$(grep -E '^APIMATIC_API_KEY=' "$ROOT/.env" | tail -1 | cut -d= -f2- | tr -d '"'"'"'\r' || true)"
fi
AUTH=()
[[ -n "$KEY" ]] && AUTH=(--auth-key="$KEY")

refresh_spec() {
  echo "==> Refreshing the OpenAPI spec from the FastAPI app"
  local py="python"
  [[ -x "$ROOT/backend/.venv/Scripts/python.exe" ]] && py="$ROOT/backend/.venv/Scripts/python.exe"
  [[ -x "$ROOT/backend/.venv/bin/python" ]] && py="$ROOT/backend/.venv/bin/python"
  (cd "$ROOT" && "$py" scripts/export_openapi.py)
}

validate() {
  echo "==> Validating the spec with APIMatic"
  apimatic api validate --input="$PROJECT" "${AUTH[@]}"
}

portal() {
  echo "==> Generating the static portal -> apimatic/portal"
  apimatic portal generate --input="$PROJECT" --destination="$PROJECT/portal" --force "${AUTH[@]}"
}

sdks() {
  for lang in python typescript; do
    echo "==> Generating the $lang SDK -> apimatic/sdk/$lang"
    apimatic sdk generate --language="$lang" --input="$PROJECT" --destination="$PROJECT/sdk/$lang" --force "${AUTH[@]}"
  done
}

plugin() {
  echo "==> Generating the PayPilot Context Plugin -> apimatic/plugin"
  apimatic plugin generate --input="$PROJECT" --destination="$PROJECT/plugin" --force "${AUTH[@]}"
}

case "$STEP" in
  serve) apimatic portal serve --input="$PROJECT" --open "${AUTH[@]}" ;;
  spec) refresh_spec ;;
  validate) validate ;;
  portal) portal ;;
  sdk) sdks ;;
  plugin) plugin ;;
  all) refresh_spec; validate; portal; sdks; plugin
       echo "Done. Preview the portal with: scripts/apimatic.sh serve" ;;
  *) echo "Unknown step '$STEP' (all | serve | spec | validate | portal | sdk | plugin)" >&2; exit 2 ;;
esac
