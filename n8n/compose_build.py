"""docker-compose step: render the n8n workflows for the Docker network.

    python /work/n8n/compose_build.py /deploy

Runs inside the backend image (``n8n-build`` service), because it reads the
database: the demo merchant's id changes on every ``seed --reset``, so a value
pinned in ``.env`` goes stale and the scheduled sweeps would refuse to run. The
id is resolved here and handed to ``build_workflows.py`` through the environment,
together with ``N8N_BACKEND_URL_FOR_N8N=http://backend:8000`` from the compose file.
Everything else (the HMAC secret) still comes from ``.env``.
"""

from __future__ import annotations

import asyncio
import os
import runpy
import sys

DEMO_SLUG = "juniper-oak-coffee"


async def resolve_merchant_id() -> str:
    import app.db.base  # noqa: F401 - registers every model
    from app.db.models.merchant import Merchant
    from app.db.session import SessionLocal, dispose_engine
    from sqlalchemy import select

    try:
        async with SessionLocal() as session:
            rows = (await session.execute(select(Merchant.id, Merchant.slug).order_by(Merchant.created_at))).all()
    finally:
        await dispose_engine()
    for merchant_id, slug in rows:
        if slug == DEMO_SLUG:
            return str(merchant_id)
    return str(rows[0][0]) if rows else ""


def main() -> None:
    out = sys.argv[1] if len(sys.argv) > 1 else "/deploy"
    if not os.environ.get("PGA_MERCHANT_ID"):
        merchant_id = asyncio.run(resolve_merchant_id())
        if merchant_id:
            os.environ["PGA_MERCHANT_ID"] = merchant_id
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build_workflows.py")
    sys.argv = [script, out]
    runpy.run_path(script, run_name="__main__")


if __name__ == "__main__":
    main()
