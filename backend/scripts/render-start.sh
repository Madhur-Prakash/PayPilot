#!/bin/sh
# Start command for the API on Render (render.yaml -> dockerCommand).
#
# Render hands dockerCommand to the container without shell quoting, so a
# `sh -c "a && b"` arrives as one quoted word and fails with "not found".
# Keeping the steps here lets dockerCommand stay quote-free.
#
# Migrate, seed the demo tenant (idempotent - skips when already seeded), then
# serve on the port Render assigns.
set -e

alembic upgrade head
python -m app.seed.seed
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*'
