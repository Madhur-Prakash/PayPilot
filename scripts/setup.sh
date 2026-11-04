#!/usr/bin/env sh
# PayPilot - first-time setup (macOS / Linux / Git Bash / WSL). Same as `make init`.
# Never overwrites .env and never deletes data.   Usage: sh scripts/setup.sh [--skip-db]
set -e
cd "$(dirname "$0")/.."
PY=$(command -v python3 || command -v python || true)
[ -n "$PY" ] || { echo "Python 3.11+ is required: https://www.python.org/downloads/"; exit 1; }
exec "$PY" scripts/tasks.py init "$@"
