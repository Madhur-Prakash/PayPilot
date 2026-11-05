"""Export PayPilot's OpenAPI 3 specification.

    python scripts/export_openapi.py                 # writes docs/openapi.json
    python scripts/export_openapi.py --out spec.json

The spec is generated from the FastAPI app itself, so it is always what the code
actually serves. It is the input APIMatic needs to generate SDKs and a developer
portal for PayPilot's API (import the file at https://www.apimatic.io/). It also
imports into Postman and Swagger tooling.

It contains no credentials: the app's settings are never serialised into it, and
the only security scheme is the bearer-token one the API really uses.

Standard library plus the backend's own dependencies; needs no database.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(ROOT / "docs" / "openapi.json"),
                        help="output file (the default also refreshes apimatic/src/spec/openapi.json)")
    args = parser.parse_args()

    # Importing the app must not need (or touch) a database or real credentials.
    os.environ.setdefault("APP_ENV", "test")
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    for key in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "GROQ_API_KEY", "CHANNEL3_API_KEY",
                "KERNEL_API_KEY", "ELASTIC_API_KEY", "ZAPIER_WEBHOOK_URL"):
        os.environ[key] = ""
    sys.path.insert(0, str(BACKEND))

    from app.main import app  # imported after the environment is prepared

    spec = polish(app.openapi(), app)
    operations = sum(1 for item in spec["paths"].values() for m in item if m in METHODS)
    text = json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    outs = [Path(args.out)]
    if args.out == str(DEFAULT_OUT):
        outs.append(APIMATIC_SPEC)  # the APIMatic project builds SDKs, portal and plugin from this copy
    for out in outs:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out} - {operations} operations, {len(spec['paths'])} paths, "
              f"{len(spec.get('components', {}).get('schemas', {}))} schemas")
    return 0


METHODS = ("get", "post", "put", "patch", "delete")

DESCRIPTION = """\
PayPilot is an AI operating system for small merchants on PayPal: a Growth Scientist that finds
revenue opportunities in PayPal transactions, Supply Agents that source and negotiate stock with
independent supplier agents, and PayPal financial operations (Orders v2 supplier settlement,
Invoicing, Payouts, Subscriptions, verified webhooks, reconciliation).

**Money never moves without a person.** Every limit is computed by a deterministic engine before
any agent speaks; purchases and payments need a recorded human approval bound to a SHA-256 hash of
the exact terms; agent tools refuse to approve or pay.

**Authentication.** `POST /api/v1/auth/login` returns an access token; send it as
`Authorization: Bearer <token>`. Every resource is scoped to the caller's merchant and permissions
(Owner, Admin, Analyst, Staff, Viewer)."""


def readable_operation_ids(spec: dict) -> None:
    """Readable, unique operation ids - they become SDK method names.

    FastAPI's default id is `<function>` + `<path, non-word chars as _>` + `_<method>`, e.g.
    `create_procurement_api_v1_procurement_post`. Strip that suffix back to `create_procurement`;
    when two operations share a function name, prefix the tag (`paypal_list_invoices`).
    """
    wanted: list[tuple[dict, str, str]] = []
    for path, item in spec["paths"].items():
        for method, operation in item.items():
            if method not in METHODS:
                continue
            current = operation.get("operationId", "")
            suffix = re.sub(r"\W", "_", path) + "_" + method
            name = current[: -len(suffix)] if current.endswith(suffix) and len(current) > len(suffix) else current
            name = name.rstrip("_") or name  # `status_` (named to avoid shadowing) -> `status`
            tag = (operation.get("tags") or ["api"])[0].replace("-", "_")
            wanted.append((operation, name, tag))
    counts = Counter(name for _, name, _ in wanted)
    used: set[str] = set()
    for operation, name, tag in wanted:
        final = name if counts[name] == 1 else f"{tag}_{name}"
        n = 2
        while final in used:
            final, n = f"{name}_{n}", n + 1
        used.add(final)
        operation["operationId"] = final


def polish(spec: dict, app) -> dict:
    """Make the spec good input for APIMatic: servers, readable operation ids, a real description."""
    readable_operation_ids(spec)
    spec["servers"] = [
        {"url": "https://paypilot-api.onrender.com", "description": "Hosted demo (Render)"},
        {"url": "http://localhost:8000", "description": "Local (docker compose up)"},
    ]
    info = spec.setdefault("info", {})
    info["title"] = "PayPilot API"
    info["description"] = DESCRIPTION
    info["license"] = {"name": "MIT", "identifier": "MIT"}
    return spec


DEFAULT_OUT = ROOT / "docs" / "openapi.json"
APIMATIC_SPEC = ROOT / "apimatic" / "src" / "spec" / "openapi.json"


if __name__ == "__main__":
    raise SystemExit(main())
