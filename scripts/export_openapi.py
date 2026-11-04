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
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(ROOT / "docs" / "openapi.json"), help="output file")
    args = parser.parse_args()

    # Importing the app must not need (or touch) a database or real credentials.
    os.environ.setdefault("APP_ENV", "test")
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    for key in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "GROQ_API_KEY", "CHANNEL3_API_KEY",
                "KERNEL_API_KEY", "ELASTIC_API_KEY", "ZAPIER_WEBHOOK_URL"):
        os.environ[key] = ""
    sys.path.insert(0, str(BACKEND))

    from app.main import app  # noqa: E402  (after the environment is prepared)

    spec = app.openapi()
    operations = sum(1 for item in spec["paths"].values() for m in item if m in ("get", "post", "put", "patch", "delete"))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out} - {operations} operations, {len(spec['paths'])} paths, "
          f"{len(spec.get('components', {}).get('schemas', {}))} schemas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
