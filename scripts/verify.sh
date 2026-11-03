#!/usr/bin/env bash
# End-to-end verification: lint, typecheck, tests, build.
# Mirrors what CI would run.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "== backend lint =="
(cd backend && ./.venv/Scripts/python.exe -m ruff check app tests 2>/dev/null \
  || python -m ruff check app tests)

echo "== backend tests =="
(cd backend && ./.venv/Scripts/python.exe -m pytest -q 2>/dev/null \
  || python -m pytest -q)

echo "== frontend typecheck =="
(cd frontend && npx tsc --noEmit)

echo "== frontend build =="
(cd frontend && npm run build)

echo ""
echo "All checks passed."
