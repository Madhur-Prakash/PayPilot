"""Render the deployable n8n workflows.

The workflows need three things this repo must not contain: the shared webhook
secret, the URL n8n uses to reach the backend, and the merchant the scheduled
sweeps run for. So the committed artefact is this generator, and the importable
JSON is built from the local ``.env`` at deploy time into ``n8n/deploy/`` -
which is git-ignored.

Run it with::

    python n8n/build_workflows.py            # -> n8n/deploy
    python n8n/build_workflows.py <outdir>

Design notes worth keeping in mind before editing a node:

* **No business rules live here.** Every workflow ends up asking the backend to
  decide something. n8n chooses *when* and *whether* to ask; it never computes a
  reorder quantity or picks a vendor. That keeps one copy of the rules, under
  test, on the side of the wire that owns the data.
* **The Code nodes carry their own crypto.** n8n's sandbox refuses
  ``require('crypto')`` and the flag that would permit it does not exist on n8n
  Cloud, so ``lib/pga-hmac.js`` is inlined into each node instead.
* **Signatures cover canonical JSON**, not whatever bytes happened to arrive -
  see ``canonical_json`` in ``backend/app/services/inventory/events.py``.
"""

from __future__ import annotations

import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "deploy")

CRYPTO_JS = io.open(os.path.join(HERE, "lib", "pga-hmac.js"), encoding="utf-8").read()


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = os.path.join(ROOT, ".env")
    if not os.path.exists(path):
        # Fine when the settings arrive through the environment (the compose
        # build step); the empty-secret check below still refuses to build.
        return env
    for raw in io.open(path, encoding="utf-8"):
        raw = raw.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            key, _, value = raw.partition("=")
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


ENV = load_env()


def setting(key: str, default: str = "") -> str:
    """The process environment wins over .env, so the docker-compose build step can
    point n8n at in-network URLs (http://backend:8000) without editing .env."""
    return os.environ.get(key) or ENV.get(key, default)


SECRET = setting("N8N_WEBHOOK_SECRET")
BACKEND = setting("N8N_BACKEND_URL_FOR_N8N", "http://host.docker.internal:8000")
MERCHANT = setting("PGA_MERCHANT_ID")

if not SECRET:
    raise SystemExit("N8N_WEBHOOK_SECRET is empty - refusing to build unsigned workflows.")

CALLBACK = f"{BACKEND}/api/v1/webhooks/n8n/inventory-event"

PREAMBLE = f"{CRYPTO_JS}\nconst SECRET = {json.dumps(SECRET)};\n"


# --------------------------------------------------------------------------- #
# Node builders
# --------------------------------------------------------------------------- #
def code_node(name: str, position: list[int], body: str, node_id: str) -> dict:
    """A Code node with the crypto helpers already in scope."""
    return {
        "parameters": {"jsCode": f"{PREAMBLE}\n{body.strip()}\n"},
        "id": node_id,
        "name": name,
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": position,
    }


def call_backend(name: str, position: list[int], node_id: str) -> dict:
    """POST the exact string that was signed.

    ``contentType: raw`` matters. Handing n8n a JSON *object* would let it
    re-serialise on the way out, and the bytes the backend hashes would no
    longer be the bytes that were signed.
    """
    return {
        "parameters": {
            "method": "POST",
            "url": CALLBACK,
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [
                    {"name": "X-Signature", "value": "=sha256={{ $json.signature }}"},
                    {"name": "X-Source", "value": "n8n"},
                ]
            },
            "sendBody": True,
            "contentType": "raw",
            "rawContentType": "application/json",
            "body": "={{ $json.raw }}",
            "options": {"timeout": 30000, "response": {"response": {"fullResponse": False}}},
        },
        "id": node_id,
        "name": name,
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": position,
        "retryOnFail": True,
        "maxTries": 3,
        "waitBetweenTries": 4000,
        # After the retries are spent, send the failure down a second output so
        # the webhook can answer 502 and the outbox knows to try again later.
        "onError": "continueErrorOutput",
    }


def webhook_node(name: str, path: str, position: list[int], node_id: str) -> dict:
    return {
        "parameters": {
            "httpMethod": "POST",
            "path": path,
            "responseMode": "responseNode",
            "options": {},
        },
        "id": node_id,
        "name": name,
        "type": "n8n-nodes-base.webhook",
        "typeVersion": 2,
        "position": position,
        "webhookId": path,
    }


def respond_node(
    name: str, expression: str, position: list[int], node_id: str, code: int = 200
) -> dict:
    """Answer the webhook with an explicit status.

    Every branch of the router ends in one of these. Letting a node throw instead
    is not equivalent: n8n answers a workflow that failed before reaching a
    Respond node with an empty ``200``, which the backend's outbox would read as
    a successful delivery and never retry.
    """
    return {
        "parameters": {
            "respondWith": "json",
            "responseBody": expression,
            "options": {"responseCode": code},
        },
        "id": node_id,
        "name": name,
        "type": "n8n-nodes-base.respondToWebhook",
        "typeVersion": 1,
        "position": position,
    }


def switch_node(name: str, rules: list[tuple[str, str]], position: list[int], node_id: str) -> dict:
    """Route on ``$json.event_type``. One output per rule, plus a fallback."""
    return {
        "parameters": {
            "rules": {
                "values": [
                    {
                        "conditions": {
                            "options": {
                                "caseSensitive": True,
                                "leftValue": "",
                                "typeValidation": "loose",
                                "version": 2,
                            },
                            "conditions": [
                                {
                                    "id": f"r{index}",
                                    "leftValue": "={{ $json.event_type }}",
                                    "rightValue": event_type,
                                    "operator": {
                                        "type": "string",
                                        "operation": "equals",
                                        "name": "filter.operator.equals",
                                    },
                                }
                            ],
                            "combinator": "and",
                        },
                        "renameOutput": True,
                        "outputKey": label,
                    }
                    for index, (event_type, label) in enumerate(rules)
                ]
            },
            "options": {"fallbackOutput": "extra", "renameFallbackOutput": "other"},
        },
        "id": node_id,
        "name": name,
        "type": "n8n-nodes-base.switch",
        "typeVersion": 3.2,
        "position": position,
    }


def schedule_node(name: str, hour: int, minute: int, position: list[int], node_id: str) -> dict:
    return {
        "parameters": {
            "rule": {"interval": [{"triggerAtHour": hour, "triggerAtMinute": minute}]}
        },
        "id": node_id,
        "name": name,
        "type": "n8n-nodes-base.scheduleTrigger",
        "typeVersion": 1.2,
        "position": position,
    }


def wire(*pairs: tuple[str, str | list[str]]) -> dict:
    """``connections`` from (source, target) pairs; a list means one output each."""
    out: dict[str, dict] = {}
    for source, target in pairs:
        targets = target if isinstance(target, list) else [target]
        out[source] = {
            "main": [
                ([] if node is None else [{"node": node, "type": "main", "index": 0}])
                for node in targets
            ]
        }
    return out


# --------------------------------------------------------------------------- #
# Shared JavaScript
# --------------------------------------------------------------------------- #
VERIFY_JS = """
// Verify the backend's HMAC before acting on anything. Knowing the webhook URL
// must not be enough on its own to drive procurement.
const item = $input.first();
const headers = item.json.headers || {};
const body = item.json.body || {};

const provided = String(headers['x-signature'] || '').replace(/^sha256=/, '');
const expected = hmacSha256(SECRET, utf8(canon(body)));

if (!digestsMatch(provided, expected)) {
  throw new Error('Invalid signature - refusing this event.');
}

return [{ json: body }];
"""


def ask_backend_js(action: str, extra: str = "") -> str:
    """Build a signed request for one backend action.

    ``$execution.id`` travels with it so an automation run in the UI can link
    straight back to the n8n execution that caused it.
    """
    return f"""
// The backend owns the decision; this only asks for it, signed. Business rules
// deliberately do not live in n8n.
const event = $input.first().json;

const body = {{
  action: {json.dumps(action)},
  merchant_id: event.merchant_id,
  correlation_id: event.correlation_id || '',
  n8n_execution_id: String($execution.id),
{extra}}};

return [{{ json: signCanonical(SECRET, body) }}];
"""


def sweep_js(actions: list[str]) -> str:
    return f"""
// Idempotent sweeps. A missed night is picked up by the next run, so there is
// no catch-up logic that could double-count.
const MERCHANT_ID = {json.dumps(MERCHANT)};
if (!MERCHANT_ID) {{
  throw new Error('No PGA_MERCHANT_ID was baked into this workflow at build time.');
}}

return {json.dumps(actions)}.map((action) => {{
  const body = {{
    action,
    merchant_id: MERCHANT_ID,
    n8n_execution_id: String($execution.id),
  }};
  const signed = signCanonical(SECRET, body);
  return {{ json: {{ ...signed, action }} }};
}});
"""


# --------------------------------------------------------------------------- #
# 1. Event router - the live path
# --------------------------------------------------------------------------- #
ROUTER = {
    "id": "PGAInventoryRouter",
    "active": True,
    "name": "PGA 01 Inventory Event Router",
    "nodes": [
        webhook_node("Inventory Event", "pga-inventory-event", [-680, 300], "wh1"),
        # A bad signature still throws - it belongs in the execution log as an
        # error - but the throw is caught on the second output so the caller
        # gets 401 rather than n8n's empty 200.
        {
            **code_node("Verify Signature", [-460, 300], VERIFY_JS, "vf1"),
            "onError": "continueErrorOutput",
        },
        switch_node(
            "Route By Event",
            [
                ("inventory.low_stock", "low_stock"),
                ("inventory.expiring_soon", "expiring"),
                ("inventory.purchase_order_created", "po_created"),
            ],
            [-220, 220],
            "sw1",
        ),
        code_node(
            "Sign Replenish Request",
            [40, -20],
            ask_backend_js(
                "replenish",
                "  inventory_item_id: event.entity_id,\n  event_id: event.event_id,\n",
            ),
            "sg1",
        ),
        call_backend("Ask Backend To Replenish", [280, -20], "hr1"),
        code_node("Sign Aging Sweep", [40, 180], ask_backend_js("sweep_aging"), "sg2"),
        call_backend("Ask Backend To Sweep", [280, 180], "hr2"),
        code_node(
            "Note Order Raised",
            [40, 380],
            """
// Nothing to ask the backend for - the order already exists. This branch keeps
// the event visible in the execution log instead of dropping it silently, and
// is where a vendor email or a Slack ping would hang.
const event = $input.first().json;
return [{ json: { noted: event.event_type, correlation_id: event.correlation_id } }];
""",
            "nt1",
        ),
        respond_node(
            "Acknowledge",
            (
                "={{ JSON.stringify({ success: true, accepted: true, "
                "event_id: $('Verify Signature').first().json.event_id, "
                "correlation_id: $('Verify Signature').first().json.correlation_id, "
                'status: "PROCESSING" }) }}'
            ),
            [620, 220],
            "rs1",
        ),
        respond_node(
            "Refuse Unsigned",
            '={{ JSON.stringify({ success: false, error: "invalid signature" }) }}',
            [-220, 520],
            "rs2",
            code=401,
        ),
        # 502, not 200: the backend's outbox reads the status and re-delivers,
        # which is the whole reason at-least-once delivery is safe here.
        respond_node(
            "Report Backend Failure",
            (
                "={{ JSON.stringify({ success: false, error: \"backend unreachable\", "
                "detail: String(($json.error && $json.error.message) || $json.error || "
                "\"no response\").slice(0, 300) }) }}"
            ),
            [620, 440],
            "rs3",
            code=502,
        ),
    ],
    "connections": {
        **wire(("Inventory Event", "Verify Signature")),
        "Verify Signature": {
            "main": [
                [{"node": "Route By Event", "type": "main", "index": 0}],
                [{"node": "Refuse Unsigned", "type": "main", "index": 0}],
            ]
        },
        "Route By Event": {
            "main": [
                [{"node": "Sign Replenish Request", "type": "main", "index": 0}],
                [{"node": "Sign Aging Sweep", "type": "main", "index": 0}],
                [{"node": "Note Order Raised", "type": "main", "index": 0}],
                [{"node": "Acknowledge", "type": "main", "index": 0}],
            ]
        },
        **wire(
            ("Sign Replenish Request", "Ask Backend To Replenish"),
            ("Sign Aging Sweep", "Ask Backend To Sweep"),
            ("Note Order Raised", "Acknowledge"),
        ),
        "Ask Backend To Replenish": {
            "main": [
                [{"node": "Acknowledge", "type": "main", "index": 0}],
                [{"node": "Report Backend Failure", "type": "main", "index": 0}],
            ]
        },
        "Ask Backend To Sweep": {
            "main": [
                [{"node": "Acknowledge", "type": "main", "index": 0}],
                [{"node": "Report Backend Failure", "type": "main", "index": 0}],
            ]
        },
    },
    "settings": {"executionOrder": "v1"},
}


# --------------------------------------------------------------------------- #
# 2. Nightly sweeps - the scheduled path
# --------------------------------------------------------------------------- #
SWEEPS = {
    "id": "PGAInventorySweeps",
    "active": True,
    "name": "PGA 02 Inventory Nightly Sweeps",
    "nodes": [
        schedule_node("Nightly 02:00", 2, 0, [-400, 300], "sc1"),
        code_node("Build Signed Sweeps", [-160, 300], sweep_js(["sweep_aging", "reconcile"]), "bs1"),
        call_backend("Run Sweep", [100, 300], "hr3"),
        code_node(
            "Summarise",
            [360, 300],
            """
// One line per sweep in the execution log, so a glance at n8n answers "did last
// night run?" without opening the backend.
return $input.all().map((entry) => ({
  json: {
    ok: entry.json && entry.json.success !== false,
    detail: entry.json && entry.json.data ? entry.json.data : entry.json,
  },
}));
""",
            "sm1",
        ),
    ],
    "connections": wire(
        ("Nightly 02:00", "Build Signed Sweeps"),
        ("Build Signed Sweeps", "Run Sweep"),
        ("Run Sweep", "Summarise"),
    ),
    "settings": {"executionOrder": "v1"},
}


# --------------------------------------------------------------------------- #
# 3. Daily growth scan - the "always-on" half of growth intelligence
# --------------------------------------------------------------------------- #
# Opportunity detection used to run only inside an agent run or a manual API
# call, which meant nothing looked for new opportunities unless a merchant asked.
# The detector is deterministic, so a daily scan costs no LLM tokens - it is
# arithmetic over the merchant's own transactions.
SCAN = {
    "id": "PGAGrowthScan",
    "active": True,
    "name": "PGA 03 Daily Growth Scan",
    "nodes": [
        schedule_node("Every morning 06:30", 6, 30, [-400, 300], "sc2"),
        code_node(
            "Sign Detection Request",
            [-160, 300],
            f"""
const MERCHANT_ID = {json.dumps(MERCHANT)};
if (!MERCHANT_ID) {{
  throw new Error('No PGA_MERCHANT_ID was baked into this workflow at build time.');
}}

const body = {{
  action: 'detect_opportunities',
  merchant_id: MERCHANT_ID,
  // Matches the window the dashboard defaults to, so a merchant opening the app
  // sees the same period the scan reasoned over.
  days: 30,
  n8n_execution_id: String($execution.id),
}};

return [{{ json: signCanonical(SECRET, body) }}];
""",
            "sg3",
        ),
        call_backend("Ask Backend To Scan", [100, 300], "hr4"),
        code_node(
            "Summarise",
            [360, 300],
            """
// One line in the execution log: how many opportunities this morning's scan
// found, so "is it still running?" is answerable at a glance.
const entry = $input.first().json;
const data = (entry && entry.data) || {};
return [{ json: { detected: data.detected ?? 0, titles: data.titles ?? [] } }];
""",
            "sm2",
        ),
    ],
    "connections": wire(
        ("Every morning 06:30", "Sign Detection Request"),
        ("Sign Detection Request", "Ask Backend To Scan"),
        ("Ask Backend To Scan", "Summarise"),
    ),
    "settings": {"executionOrder": "v1"},
}


WORKFLOWS = [
    ("01_event_router.json", ROUTER),
    ("02_nightly_sweeps.json", SWEEPS),
    ("03_growth_scan.json", SCAN),
]


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    for name, workflow in WORKFLOWS:
        path = os.path.join(OUT, name)
        io.open(path, "w", encoding="utf-8", newline="\n").write(
            json.dumps(workflow, indent=2)
        )
        print(f"  {name:<28} {len(workflow['nodes'])} nodes")

    print(f"\ncallback baked in : {CALLBACK}")
    print(f"merchant baked in : {MERCHANT or '(unset - scheduled sweeps will refuse to run)'}")
    print(f"output            : {OUT}")


if __name__ == "__main__":
    main()
