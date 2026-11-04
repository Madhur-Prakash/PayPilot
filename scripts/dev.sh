#!/usr/bin/env sh
# PayPilot - run database + backend + frontend. Same as `make dev`.  Usage: sh scripts/dev.sh
set -e
cd "$(dirname "$0")/.."
PY=$(command -v python3 || command -v python || true)
[ -n "$PY" ] || { echo "Python 3.11+ is required: https://www.python.org/downloads/"; exit 1; }
exec "$PY" scripts/tasks.py dev "$@"
