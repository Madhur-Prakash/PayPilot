<div align="center">

# Testing

The backend and frontend test suites, what each one proves, and how to extend them.

[![Docs index](https://img.shields.io/badge/-Docs_index-0b2a6f?style=flat-square)](README.md)
[![Contributing](https://img.shields.io/badge/-Contributing-64748b?style=flat-square)](CONTRIBUTING.md)
[![Data](https://img.shields.io/badge/-Data-12805c?style=flat-square)](DATA.md#calibration)
[![Tests](https://img.shields.io/badge/backend_tests-535-16a34a?style=flat-square&logo=pytest&logoColor=white)](#backend-suite)
[![Vitest](https://img.shields.io/badge/frontend-vitest-6E9F18?style=flat-square&logo=vitest&logoColor=white)](#frontend-suite)

</div>

---

## Contents

- [Running the tests](#running-the-tests)
- [Backend suite](#backend-suite)
- [Fixtures](#fixtures)
- [What the tests enforce](#what-the-tests-enforce)
- [Mocking policy](#mocking-policy)
- [Frontend suite](#frontend-suite)
- [Lint, types and builds](#lint-types-and-builds)
- [Calibration](#calibration)
- [Writing tests](#writing-tests)

---

## Running the tests

| Command | Runs |
| --- | --- |
| `make test` | Backend pytest, then frontend vitest |
| `make test-backend` | Backend only |
| `make test-frontend` | Frontend only (`npm run test`, which is `vitest run`) |
| `make verify` | Lint, typecheck, then all tests |
| `scripts/verify.sh` | Backend lint, backend tests, frontend typecheck, frontend production build |

From `backend/` with the virtualenv active:

```bash
pytest                                        # everything
pytest tests/unit                             # one directory
pytest tests/api/test_auth.py                 # one file
pytest -k "isolation"                         # by name
pytest -x --lf                                # stop at first failure, rerun last failures
```

**No database, Docker or keys needed.** Tests run on in-memory SQLite through `aiosqlite`. The same models,
services and API run on both engines thanks to the portable column types in
[`db/types.py`](../backend/app/db/types.py), so a passing test exercises production code paths, not a parallel
implementation. External services are mocked at the HTTP transport; PayPal runs on the simulator.

Configuration in [`backend/pyproject.toml`](../backend/pyproject.toml):

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "session"
testpaths = ["tests"]
addopts = "-q --disable-warnings"
```

---

## Backend suite

478 test functions; with parametrisation, 535 collected tests.

| File | Functions | Covers |
| --- | :-: | --- |
| **unit/** | | |
| `test_procurement_policy.py` | 34 | `Decimal` ceiling and budget, offer validation, tampered totals, evaluation scoring |
| `test_agent_protocol.py` | 10 | Signed agent messages: bad signatures, cross-tenant, stale, schema violations, replays, sender roles |
| `test_paypal_client.py` | 21 | PayPal REST client against mocked responses: token refresh, retries, idempotency keys, 31-day windows, webhook verification; the simulator |
| `test_paypal_server_sdk.py` | 5 | The real `paypal-server-sdk` serialisation and error mapping through a stub `requests.Session` |
| `test_permissions_and_security.py` | 23 | Role map, password policy, tokens, redaction |
| `test_agent_memory.py` | 24 | pgvector memory, recall, tenant isolation |
| `test_experiment_math.py` | 20 | Two-proportion z-test against hand-computed values, decision rule, deterministic split |
| `test_inventory_signing.py` | 17 | n8n HMAC and canonical JSON |
| `test_redis_layer.py` | 31 | Rate limits, caches, pub/sub, circuit breaker, Redis-down fallbacks |
| `test_realtime_hub.py` | 7 | WebSocket hub fan-out and permission filtering |
| `test_channel3_catalog.py` | 15 | Channel3 client: filters, normalisation, retries, no-key behaviour |
| `test_channel3_shelf.py` | 10 | Gear shelf on the verified Channel3 response shape |
| `test_discovery_engine.py` | 18 | Intent parsing, currency conversion, ranking, comparison |
| `test_sponsor_integrations.py` | 40 | Elasticsearch, Kernel, Zapier, MCP bridge adapters and the integration status endpoint |
| `test_studio_ai.py` | 22 | AG Studio LLM relay: item translation, 429 and 413 handling |
| **api/** | | |
| `test_auth.py` | 13 | Login, protected routes, rotation, **token reuse revokes the whole family**, registration, logout |
| `test_rbac_and_isolation.py` | 19 | Tenant isolation, role permissions, approval gate, roles endpoint matches the enforced map |
| `test_memory_api.py` | 12 | Memory endpoints, permissions, scope |
| `test_paypal_api.py` | 10 | PayPal endpoints and webhook handling through the API |
| **integration/** | | |
| `test_supply_agents.py` | 6 | **End-to-end procurement lifecycle through the real API**: RFQ, negotiation, approvals, partial receipt, three-way match, payment, reconciliation |
| `test_supply_intelligence.py` | 20 | Recommendation -> approval -> PayPal order -> capture -> webhook; invalidation on changed terms; agents can request but never pay |
| `test_supply_sponsors.py` | 25 | Integrations inside the supply flow |
| `test_shop.py` | 18 | Customer checkout: server pricing, webhook-before-return and return-before-webhook idempotency, oversold handling |
| `test_analytics_and_agents.py` | 22 | Analytics determinism, tool authorization, the growth loop end to end, provenance labelling |
| `test_dual_market_growth.py` | 12 | Store and online growth allocation |
| `test_outbox_relay.py` | 15 | Outbox claiming, leases, retries, delivery states |
| `test_inventory_import.py` | 8 | Spreadsheet import preview and commit |
| `test_seed_rerun.py` | 1 | The seed is idempotent |

---

## Fixtures

[`tests/conftest.py`](../backend/tests/conftest.py)

| Fixture | Scope | Provides |
| --- | --- | --- |
| `engine` | session | In-memory SQLite engine with the full schema |
| `session` | function | `AsyncSession` rolled back after each test |
| `seeded` | session | A compact deterministic dataset (a few hundred transactions, not the full demo) |
| `client` | function | `httpx.AsyncClient` over the real ASGI app |
| `owner_headers`, `admin_headers`, `analyst_headers`, `staff_headers`, `viewer_headers` | function | Authenticated as each role through the real login endpoint |
| `outsider_headers` | function | A user of a **different** merchant, which is what makes isolation tests meaningful |

No fixture manufactures a token directly; every API test signs in the way a user does.

---

## What the tests enforce

Coverage percentage is not the target. These tests exist to stop specific failures:

| Rule | Enforced by |
| --- | --- |
| Money moves only with a human approval | `test_execution_without_approval_is_refused`, the procurement lifecycle test, Supply Intelligence purchase tests |
| Agents cannot approve or pay | Tool-refusal tests; `test_execute_campaign_is_gated_on_approval_not_permission_alone` |
| Approvals bind to exact terms | Invalidation tests in the policy and Supply Intelligence suites |
| Payments are idempotent | PayPal client idempotency-key tests; double-click tests on order creation |
| Webhooks are verified | Webhook verification and replay tests; shop webhook-before-return tests |
| Agent messages are authentic | Protocol tests for signature, tenant, freshness, schema, role and replay |
| Tenants are isolated | `test_each_tenant_sees_only_its_own_figures`, memory isolation, tools cannot be pointed at another merchant |
| No causal claims | `test_the_growth_graph_never_claims_causation` |
| Works without an LLM | `test_the_recommendation_is_deterministic_without_an_llm` |
| Simulation is labelled | `TestProvenanceLabelling`, integration status tests |
| Replay of a refresh token revokes the family | `test_token_reuse_revokes_the_whole_family` |
| Secrets never reach logs | Redaction tests |
| An account cannot be orphaned | `test_the_last_owner_cannot_be_demoted` |
| Redis is never a hard dependency | Redis-down fallback tests |

### Bugs the suite caught

* **Rolled-back audit writes.** `test_token_reuse_revokes_the_whole_family` exposed that security events were
  written on the request session and vanished with its rollback, which also meant lockout never locked and token
  revocation never persisted. See [Security: auditing](SECURITY.md#auditing).
* **Inconsistent windows.** `test_revenue_equals_orders_times_aov` caught an AOV computed over a different date
  window than the revenue it was divided into.
* **Biased experiment split.** `test_ordering_does_not_change_assignment` caught groups formed by slicing an ordered
  result set, which correlated allocation with tenure. Assignment now hashes the customer id.
* **Non-reproducible analytics.** `test_the_same_query_returns_the_same_numbers` caught a `datetime.now()` inside a
  window boundary.

---

## Mocking policy

1. Do not mock what you own. Services and repositories run for real against SQLite.
2. Mock at the network boundary only: PayPal (or use the simulator), Channel3, Groq, Langfuse, Vapi,
   Elasticsearch, Kernel, Zapier, Redis (`fakeredis`).
3. Test against the verified response shape of each external API, not an invented one.
4. No sleeps. Everything is deterministic; a needed sleep means something is racing.

---

## Frontend suite

Vitest, configured in [`frontend/vitest.config.ts`](../frontend/vitest.config.ts):

| File | Covers |
| --- | --- |
| [`lib/utils/utils.test.ts`](../frontend/src/lib/utils/utils.test.ts) | Formatting and utility functions |
| [`lib/utils/timeline.test.ts`](../frontend/src/lib/utils/timeline.test.ts) | The pure mapping from procurement stages to Bryntum Gantt tasks |
| [`lib/studio/studio.test.ts`](../frontend/src/lib/studio/studio.test.ts) | AG Studio default report and adapter helpers |
| [`stores/compare.test.ts`](../frontend/src/stores/compare.test.ts) | The product comparison tray store |

```bash
cd frontend
npm run test          # vitest run
npm run typecheck     # tsc --noEmit
npm run lint          # next lint
npm run build         # production build of every page
```

`npm run build` catches server and client boundary mistakes that `tsc` alone does not.

---

## Lint, types and builds

| Command | Runs |
| --- | --- |
| `make lint` | `ruff check app tests` and `next lint` |
| `make format` | `ruff format`, `ruff check --fix`, Prettier |
| `make typecheck` | `tsc --noEmit`, then mypy on `app/` (advisory; the backend gate is ruff plus pytest) |
| `make build` | Backend compile and import check, then `next build` |

Ruff: line length 100, target Python 3.11, rule sets `E`, `F`, `I`, `UP`, `B`, `C4`, `SIM`, `RUF`.

---

## Calibration

Assertions check correctness; calibration checks meaning. `make calibrate` prints the figures the dashboard will show
from a fresh in-memory dataset. Run it after any change under `app/seed/generators/`. See
[Data: calibration](DATA.md#calibration) for the expected output and the bug it found that no test could.

---

## Writing tests

### An API permission test

```python
async def test_a_viewer_cannot_approve_a_purchase(client, viewer_headers, pending_approval_id):
    response = await client.post(
        f"/api/v1/approvals/{pending_approval_id}/decide",
        headers=viewer_headers,
        json={"approve": True},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"
```

Name the test after the rule it defends, not the function it calls.

### A tool authorization test

```python
async def test_my_tool_is_denied_without_the_permission(session, seeded):
    ctx = ToolContext(session=session, merchant_id=seeded["merchant_id"], permissions=frozenset())
    result = await registry.execute("my_tool", ctx, {})
    assert not result.ok
    assert "permission" in result.error.lower()
```

Every new tool needs one: it is the difference between a permission that is declared and one that is enforced.

### An isolation test

```python
async def test_the_new_resource_is_scoped(client, owner_headers, outsider_headers):
    created = await client.post("/api/v1/things", headers=owner_headers, json={...})
    thing_id = created.json()["data"]["id"]
    leaked = await client.get(f"/api/v1/things/{thing_id}", headers=outsider_headers)
    assert leaked.status_code == 404   # not 403: it does not exist in their scope
```

A `403` would confirm the resource exists, which is itself a disclosure.

---

<div align="center">

[Previous: Data](DATA.md) | [Docs index](README.md) | [Next: Contributing](CONTRIBUTING.md)

</div>
