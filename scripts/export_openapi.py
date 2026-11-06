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
        {"url": "https://paypilot-api-bjn2.onrender.com", "description": "Hosted demo (Render)"},
        {"url": "http://localhost:8000", "description": "Local (docker compose up)"},
    ]
    info = spec.setdefault("info", {})
    info["title"] = "PayPilot API"
    info["description"] = DESCRIPTION
    # Exported as OpenAPI 3.0.3, the version APIMatic's validator and generators read fully
    # (apimatic_clean converts the few 3.1-only constructs FastAPI emits).
    spec["openapi"] = "3.0.3"
    info["license"] = {"name": "MIT", "url": "https://opensource.org/licenses/MIT"}
    inline_upload_bodies(spec)
    readable_schema_names(spec)
    apimatic_clean(spec)
    declare_tags(spec)
    return spec


# --------------------------------------------------------------------------- #
# APIMatic validation (`apimatic api validate`): fix what it reports as errors.
# Nothing here changes the API - only how the spec describes it.
# --------------------------------------------------------------------------- #
TAG_DESCRIPTIONS = {
    "supply-agents": "Procurement: demand, supplier agents, RFQs, negotiation, purchase orders, receiving, "
                     "three-way matching and the PayPal supplier payment.",
    "governance": "Approval inbox, approval decisions and the payments ledger.",
    "intelligence": "Business events and growth signals derived from inventory.",
    "integrations": "Sponsor integrations: Channel3 gear shelf and market reference, evidence search, "
                    "Kernel portal checks, PayPal MCP, Zapier, AG Studio datasets and assistant.",
    "inventory": "Inventory items, stock movements, replenishment policies and automation.",
    "memory": "Long-term agent memory: status, semantic search, recent memories, teach and erase.",
    "paypal": "PayPal: transaction sync, invoices, payouts, subscriptions (and the revenue radar), webhooks.",
}


def inline_upload_bodies(spec: dict) -> None:
    """Inline each multipart (file upload) body into its operation.

    FastAPI puts them in components (`Body_import_commit_..._post`). The generated SDKs already
    take those fields as form parameters (`file: FileInput`), but a component also becomes a model
    whose file field the Python SDK cannot build - importing the package then fails. Inline, the
    body is only form parameters.
    """
    schemas = spec.get("components", {}).get("schemas", {})
    prefix = "#/components/schemas/"
    inlined: set[str] = set()
    for item in spec["paths"].values():
        for method, operation in item.items():
            if method not in METHODS:
                continue
            media = ((operation.get("requestBody") or {}).get("content") or {}).get("multipart/form-data")
            ref = (media or {}).get("schema", {}).get("$ref", "")
            name = ref[len(prefix):] if ref.startswith(prefix) else ""
            if name in schemas:
                media["schema"] = json.loads(json.dumps(schemas[name]))
                media["schema"].pop("title", None)
                inlined.add(name)
    text = json.dumps(spec)
    for name in inlined:
        if f'"{prefix}{name}"' not in text:
            schemas.pop(name, None)


def _pascal(text: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[^0-9A-Za-z]+", text) if part)


def readable_schema_names(spec: dict) -> None:
    """`APIResponse_Paginated_CampaignOut__` -> `APIResponsePaginatedCampaignOut`, and
    `app__api__v1__supply__ReceiveLine` -> `SupplyReceiveLine`. They become SDK model names,
    and APIMatic flags keys over 50 characters."""
    schemas = spec.get("components", {}).get("schemas", {})
    renames: dict[str, str] = {}
    taken = set(schemas)
    for key in list(schemas):
        upload = re.match(r"Body_(.+?)_api_v1_", key)
        if upload:  # FastAPI's multipart body: Body_import_commit_api_v1_..._post -> ImportCommitBody
            new = _pascal(upload.group(1)) + "Body"
        elif "__" not in key:
            continue
        elif key.startswith("app__"):
            parts = [p for p in key.split("__") if p]
            new = _pascal(parts[-2]) + parts[-1] if len(parts) >= 2 else _pascal(key)
        else:
            new = _pascal(key)
        base, n = new, 2
        while new in taken:
            new, n = f"{base}{n}", n + 1
        taken.add(new)
        renames[key] = new
    if not renames:
        return
    for old, new in renames.items():
        schemas[new] = schemas.pop(old)
    prefix = "#/components/schemas/"

    def fix_refs(node):
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith(prefix) and ref[len(prefix):] in renames:
                node["$ref"] = prefix + renames[ref[len(prefix):]]
            for value in node.values():
                fix_refs(value)
        elif isinstance(node, list):
            for value in node:
                fix_refs(value)

    fix_refs(spec)


def _clean_schema(schema, *, keep_title: str | None = None) -> None:
    """Walk one schema (schema-aware, so a *property* named `title` is never touched)."""
    if not isinstance(schema, dict):
        return
    # OpenAPI 3.0 nullability. FastAPI writes `anyOf: [X, {"type": "null"}]` (3.1); APIMatic does
    # not read that as nullable, so a real `null` from the API (e.g. a user's empty phone) fails
    # SDK deserialization. 3.0 says the same thing with `nullable: true`.
    branches = schema.get("anyOf")
    if isinstance(branches, list):
        nulls = [b for b in branches if b == {"type": "null"}]
        if nulls:
            others = [b for b in branches if b != {"type": "null"}]
            del schema["anyOf"]
            schema["nullable"] = True
            if len(others) == 1:
                only = others[0]
                if "$ref" in only:
                    schema["allOf"] = [only]  # siblings of a $ref are ignored in 3.0
                else:
                    for key, value in only.items():
                        schema.setdefault(key, value)
            elif others:
                schema["anyOf"] = others
    if "const" in schema:
        schema["enum"] = [schema.pop("const")]
    # Pydantic titles every field ("Quantity", "Name" ...); APIMatic reads those as
    # 952 duplicate schema titles. Only a component schema keeps one - its own key.
    if keep_title is not None:
        schema["title"] = keep_title
    elif isinstance(schema.get("title"), str):
        del schema["title"]
    # OpenAPI 3.1's numeric exclusive bounds are rejected; an inclusive bound is close enough
    # for documentation and SDK validation (the API itself still enforces the exact rule).
    for exclusive, inclusive in (("exclusiveMinimum", "minimum"), ("exclusiveMaximum", "maximum")):
        value = schema.get(exclusive)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            schema.setdefault(inclusive, value)
            del schema[exclusive]
    # An uploaded file. FastAPI writes the 3.1 form (`contentMediaType`), which APIMatic turns
    # into a response-file type the Python SDK cannot even import; `format: binary` makes it a
    # proper file upload parameter in every generated SDK.
    if schema.get("type") == "string" and schema.get("contentMediaType") == "application/octet-stream":
        del schema["contentMediaType"]
        schema["format"] = "binary"
    if isinstance(schema.get("enum"), list):
        schema["enum"] = [v for v in schema["enum"] if v not in ("", None)]
        if not schema["enum"]:
            del schema["enum"]
    for name, sub in (schema.get("properties") or {}).items():
        _clean_schema(sub)
    for key in ("items", "not", "additionalProperties"):
        _clean_schema(schema.get(key))
    for key in ("anyOf", "oneOf", "allOf", "prefixItems"):
        for sub in schema.get(key) or []:
            _clean_schema(sub)


def apimatic_clean(spec: dict) -> None:
    for key, schema in spec.get("components", {}).get("schemas", {}).items():
        _clean_schema(schema, keep_title=key)
    for item in spec["paths"].values():
        for method, operation in item.items():
            if method not in METHODS:
                continue
            # Summaries may not contain ':' or '?'. Keep the short head as the summary and
            # the full sentence as the description when the route has no docstring.
            summary = (operation.get("summary") or "").strip()
            full = summary
            if ": " in summary:
                summary = summary.split(": ", 1)[0]
            summary = summary.replace("?", "").replace(":", " -").strip()
            if summary:
                operation["summary"] = summary
            if not (operation.get("description") or "").strip():
                text = full or operation.get("operationId", "").replace("_", " ").capitalize()
                operation["description"] = text if text.endswith((".", "?", "!")) else text + "."
            for parameter in operation.get("parameters") or []:
                _clean_schema(parameter.get("schema"))
            body = operation.get("requestBody") or {}
            for media in (body.get("content") or {}).values():
                _clean_schema(media.get("schema"))
            for response in (operation.get("responses") or {}).values():
                for media in (response.get("content") or {}).values():
                    _clean_schema(media.get("schema"))


def declare_tags(spec: dict) -> None:
    """Every tag an operation uses is declared once, so the portal groups and describes it."""
    declared = {t["name"]: t for t in spec.get("tags") or []}
    for item in spec["paths"].values():
        for method, operation in item.items():
            if method not in METHODS:
                continue
            for tag in operation.get("tags") or []:
                if tag not in declared:
                    declared[tag] = {"name": tag, "description": TAG_DESCRIPTIONS.get(
                        tag, f"{tag.replace('-', ' ').capitalize()} endpoints.")}
    spec["tags"] = list(declared.values())


DEFAULT_OUT = ROOT / "docs" / "openapi.json"
APIMATIC_SPEC = ROOT / "apimatic" / "src" / "spec" / "openapi.json"


if __name__ == "__main__":
    raise SystemExit(main())
