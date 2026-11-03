<div align="center">

# Testing

[![Docs index](https://img.shields.io/badge/-Docs_index-475569?style=flat-square&logo=markdown&logoColor=white)](README.md)
[![Contributing](https://img.shields.io/badge/-Contributing-64748b?style=flat-square)](CONTRIBUTING.md)
[![Architecture](https://img.shields.io/badge/-Architecture-2563eb?style=flat-square)](ARCHITECTURE.md)
[![Tests](https://img.shields.io/badge/tests-208_passing-16a34a?style=flat-square&logo=pytest&logoColor=white)](#the-suite)
[![Agent memory](https://img.shields.io/badge/-Agent_memory-7c3aed?style=flat-square)](MEMORY.md)

</div>

208 tests, roughly ten seconds, no Docker required.

```bash
make test
```

```
105 passed in 9.87s
```

---

## Contents

- [Running the suite](#running-the-suite)
- [The suite](#the-suite)
- [Fixtures](#fixtures)
- [What the tests are for](#what-the-tests-are-for)
- [Bugs the suite caught](#bugs-the-suite-caught)
- [What tests could not catch](#what-tests-could-not-catch)
- [Writing a test](#writing-a-test)
- [Lint and types](#lint-and-types)
- [Frontend checks](#frontend-checks)
- [Full verification](#full-verification)

---

## Running the suite

| Command | Does |
| --- | --- |
| `make test` | The whole backend suite |
| `make lint` | Ruff |
| `make format` | Ruff formatter |
| `make typecheck` | Mypy on `app/` |
| `make check` | Lint, typecheck and test together |

Direct invocations, from `backend/` with the venv active:

```bash
pytest                                        # everything
pytest tests/unit                             # one directory
pytest tests/api/test_auth.py                 # one file
pytest tests/api/test_auth.py::TestLogin      # one class
pytest -k "isolation"                         # by name
pytest -x                                     # stop at the first failure
pytest -vv                                    # per-test output
pytest --lf                                   # only what failed last time
```

### No database needed

Tests run on SQLite through `aiosqlite`, on a shared in-memory engine. Docker can
be stopped, Postgres can be uninstalled, and the suite still runs.

That portability is not free — it is what the `GUID`, `JSONB`, `StringArray`,
`Vector` and `UTCDateTime` type decorators in
[`app/db/types.py`](../backend/app/db/types.py) buy. The same models, the same
migrations and the same services run on both engines, so a test that passes here
is exercising the code that runs in production, not a parallel implementation.

Configuration is in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
testpaths = ["tests"]
addopts = "-q --disable-warnings"
```

`asyncio_mode = "auto"` means `async def test_...` needs no decorator.

---

## The suite

```
tests/
  conftest.py                             engine, session, seeded data, role clients
  unit/
    test_permissions_and_security.py      27 tests
    test_experiment_math.py               20 tests
  api/
    test_auth.py                          17 tests
    test_rbac_and_isolation.py            19 tests
  integration/
    test_analytics_and_agents.py          22 tests
```

### Unit — permissions and security (27)

No I/O. Pure functions and pure data.

| Group | Asserts |
| --- | --- |
| `TestRoleMap` | The lattice holds; VIEWER holds no write permission; ANALYST can propose but not execute; only OWNER manages users; STAFF cannot reach growth recommendations; every permission belongs to at least one role; an unknown role grants nothing; combining roles unions their permissions |
| `TestPasswordPolicy` | Strong passwords pass; weak ones fail; the error lists every unmet rule at once; hashing is salted; verification rejects the wrong password; a corrupt hash fails closed |
| `TestTokens` | Access tokens round-trip; expired tokens are rejected; tampered tokens are rejected; a refresh token cannot be used as an access token; refresh tokens are stored only as keyed hashes; each generated token is unique |
| `TestRedaction` | Secrets are removed from log payloads; redaction reaches into nested structures; redaction is case-insensitive |

`test_every_permission_belongs_to_at_least_one_role` is the one that earns its
keep over time: add a permission and forget to grant it, and the suite says so
immediately rather than a user discovering a dead capability.

### Unit — experiment math (20)

The statistics, checked against values computed by hand.

| Group | Asserts |
| --- | --- |
| `TestTwoProportionTest` | Identical proportions give p = 1; a large clear difference is significant; a small sample is not; groups below the minimum return `None`; zero conversions everywhere returns `None`; the test is two-sided; the z matches a hand-computed value |
| `TestRelativeChange` | Positive and negative change; a zero baseline is undefined, not infinite |
| `TestDecisionRule` | SCALE requires all three conditions; promising-but-not-significant is CONTINUE; a losing arm is STOPPED; negative incremental revenue stops even with a positive lift; below threshold is WATCH; tiny groups are unreadable regardless of lift |
| `TestDeterministicSplit` | The split is stable across calls; roughly balanced; honours an uneven allocation; and **ordering does not change assignment** |

`test_matches_a_hand_computed_z` is the anchor. The two-proportion z-test is
implemented with `math.erfc` rather than SciPy, which keeps the dependency list
short — and makes an independent check of the arithmetic mandatory rather than
optional.

`test_ordering_does_not_change_assignment` guards a subtle failure. Assigning by
slicing a list means the split depends on the order rows come back from the
database, which correlates with signup date, which correlates with tenure. The
implementation hashes the customer id instead, and this test is what keeps it that
way.

### API — authentication (17)

Full request cycle through `httpx.ASGITransport`.

| Group | Asserts |
| --- | --- |
| `TestLogin` | Valid credentials return a session; the wrong password is rejected; an unknown email gives the *same* error; the refresh token arrives as an `HttpOnly` cookie |
| `TestProtectedRoutes` | The dashboard requires authentication; a malformed token is rejected; `/auth/me` returns the caller's permissions |
| `TestSessionRotation` | Refresh rotates and revokes the old token; **reusing a token revokes the whole family** |
| `TestRegistration` | Registration creates an owned workspace; duplicate email is rejected; weak passwords are rejected |
| `TestLogout` | Logout revokes the refresh token |

`test_token_reuse_revokes_the_whole_family` is the highest-value test in the file.
It is the one that proves replay detection actually persists — which it did not,
before the independent-session fix described in
[SECURITY.md](SECURITY.md#why-the-independent-session-matters).

### API — RBAC and isolation (19)

| Group | Asserts |
| --- | --- |
| `TestTenantIsolation` | A user cannot address another merchant through the query parameter; the `X-Merchant-ID` header is scoped the same way; an unknown merchant id is refused; each tenant sees only its own figures; a resource id from another tenant is not found |
| `TestRolePermissions` | VIEWER can read but cannot create, execute or run an agent; ANALYST can create but not approve, and cannot execute; STAFF cannot change roles or read the audit log; OWNER can change roles; **the last owner cannot be demoted** |
| `TestApprovalGate` | Execution without approval is refused; execution succeeds once approved; VIEWER cannot approve an opportunity |
| `TestPermissionCatalogue` | `GET /admin/roles` matches the enforced map exactly |

`test_each_tenant_sees_only_its_own_figures` seeds a second merchant with
different data and asserts the numbers differ. A test that only checks for a 403
would pass against an implementation that returns the wrong tenant's data with the
right status code.

`test_roles_endpoint_matches_the_enforced_map` closes a gap that documentation
alone cannot: the API's own description of what a role can do is asserted against
what `require_permission` actually enforces.

### Integration — analytics and agents (22)

The real services, the real graph, the real seeded dataset.

| Group | Asserts |
| --- | --- |
| `TestAnalyticsDeterminism` | The same query returns the same numbers; revenue equals orders times AOV; the recent period is measurably worse; a decline is flagged as an anomaly; daypart revenue sums to the total; analytics are merchant-scoped |
| `TestToolAuthorization` | A tool runs for a permitted role; is denied without the permission; invalid arguments fail cleanly; an unknown tool does not raise; `execute_campaign` is gated on approval, not permission alone; **tools cannot be pointed at another merchant** |
| `TestGrowthLoopEndToEnd` | Detection produces quantified opportunities; detection is idempotent; the growth graph never claims causation; investigation runs the graph and records a trace; the recommendation is deterministic without an LLM; approval creates a campaign and a controlled experiment; rejecting an opportunity creates nothing |
| `TestProvenanceLabelling` | Competitor data is labelled; campaign delivery is labelled; the health endpoint is honest about which integrations are configured |

Three of these encode product rules that are easy to violate accidentally:

**`test_the_growth_graph_never_claims_causation`** walks every edge in the growth
graph and asserts its type is one of `decomposes_into`, `correlates_with` or
`evidenced_by`. Adding a `causes` edge fails the suite. The vocabulary constraint
from the brief is enforced by a test, not by a review comment.

**`test_the_recommendation_is_deterministic_without_an_llm`** runs the full
workflow with no `GROQ_API_KEY` and asserts a complete, quantified recommendation
comes back. This is why the demo cannot be broken by a missing key or a rate
limit.

**`TestProvenanceLabelling`** asserts the honesty rules. Simulated data must say
so; the health endpoint must report `not_configured` rather than implying an
integration that is not wired.

---

## Fixtures

[`tests/conftest.py`](../backend/tests/conftest.py)

| Fixture | Scope | Provides |
| --- | --- | --- |
| `engine` | session | SQLite in-memory engine with the full schema |
| `session` | function | `AsyncSession` rolled back after each test |
| `seeded` | session | A compact deterministic dataset, built once |
| `client` | function | `httpx.AsyncClient` over the real ASGI app |
| `owner_headers` | function | Authenticated as OWNER |
| `admin_headers` | function | Authenticated as ADMIN |
| `analyst_headers` | function | Authenticated as ANALYST |
| `staff_headers` | function | Authenticated as STAFF |
| `viewer_headers` | function | Authenticated as VIEWER |
| `outsider_headers` | function | A user belonging to a **different** merchant |

`outsider_headers` is what makes the isolation tests meaningful. Without a real
second tenant holding real second-tenant data, a cross-tenant test only proves
that a 403 is returned somewhere.

The seeded fixture is session-scoped and deliberately small — a few hundred
transactions, not the 14,800 the demo seeder produces. It is enough for the
analytics assertions and keeps the suite under ten seconds.

```python
async def login(client: httpx.AsyncClient, role: str) -> dict[str, str]:
    """Sign in as the seeded user for a role and return an auth header."""
```

Tests authenticate through the real login endpoint. No fixture manufactures a
token directly, so every test also exercises the path a user takes.

---

## What the tests are for

Coverage percentage is not the target. These tests exist to stop specific,
identified failures:

| Rule | Test that enforces it |
| --- | --- |
| Financial actions need approval | `test_execution_without_approval_is_refused` |
| The agent cannot execute | `test_execute_campaign_is_gated_on_approval_not_permission_alone` |
| Tenants are isolated | `test_each_tenant_sees_only_its_own_figures` |
| Tools cannot widen their scope | `test_tools_cannot_be_pointed_at_another_merchant` |
| No causal claims | `test_the_growth_graph_never_claims_causation` |
| Simulation is labelled | `TestProvenanceLabelling` |
| The product works without an LLM | `test_the_recommendation_is_deterministic_without_an_llm` |
| Analytics are reproducible | `test_the_same_query_returns_the_same_numbers` |
| Replay is detected and persisted | `test_token_reuse_revokes_the_whole_family` |
| Secrets never reach the logs | `TestRedaction` |
| An account cannot be orphaned | `test_the_last_owner_cannot_be_demoted` |

Every row is a rule from the brief, or a bug that was actually hit.

---

## Bugs the suite caught

Worth stating plainly, because it is the argument for the tests existing.

**`test_revenue_equals_orders_times_aov`** caught an AOV computed over a different
date window than the revenue it was divided into. The two figures were each
individually correct and jointly inconsistent — exactly the class of error a
dashboard displays confidently for months.

**`test_ordering_does_not_change_assignment`** caught the list-slice split. Control
and test groups were being formed by slicing an ordered result set, which
correlated allocation with signup date. Every experiment would have carried a
tenure bias that no amount of statistical rigour downstream could remove.

**`test_token_reuse_revokes_the_whole_family`** caught the rolled-back audit write,
and with it the two silent failures riding alongside it: lockout that never locked
and revocation that never revoked.

**`test_the_same_query_returns_the_same_numbers`** caught a `datetime.now()` inside
an analytics window boundary. Two calls a second apart could land either side of a
day boundary and return different figures for the same question.

---

## What tests could not catch

One bug mattered more than any of the above, and no unit test would ever have
found it.

The seeded dataset generated customer tenure as `rng.randint(5, HISTORY_DAYS)`,
so roughly 31% of customers "joined" during the comparison window itself. Their
arrival manufactured about +10% of apparent growth in the non-evening segments —
which partially masked the real decline the whole demo is built around.

Every test passed. The data was internally consistent, the arithmetic was right,
the API returned what it computed. The story was simply weaker than intended, and
nothing in the suite had an opinion about that.

It was found by [`app/seed/calibrate.py`](../backend/app/seed/calibrate.py), a
harness that generates the dataset in memory and prints the figures a merchant
would see:

```bash
make calibrate
```

```
  Revenue              -12.20%
  Orders                -4.85%
  AOV                   -7.72%
  Repeat rate           -7.65%
  Evening revenue      -31.85%
  Evening service time +24.50%
```

Three seconds, no database. The fix was `rng.randint(15, 1000)`.

The lesson generalises: **assertions check correctness, calibration checks
meaning.** A system can be entirely correct and still say the wrong thing. If you
change anything in `app/seed/generators/`, run `make calibrate` and read the
numbers — the test suite will not do it for you.

Details: [DATA.md](DATA.md#retuning-it).

---

## Writing a test

### An API test

```python
class TestSomething:
    async def test_a_viewer_cannot_do_the_new_thing(self, client, viewer_headers):
        response = await client.post("/api/v1/things", headers=viewer_headers, json={...})
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
```

Name the test after the rule it defends, not the function it calls.
`test_a_viewer_cannot_do_the_new_thing` tells you what broke when it fails;
`test_post_things` does not.

### A tool authorization test

```python
async def test_my_tool_is_denied_without_the_permission(self, session, seeded):
    ctx = ToolContext(
        session=session,
        merchant_id=seeded["merchant_id"],
        permissions=frozenset(),        # deliberately empty
    )
    result = await registry.execute("my_tool", ctx, {})
    assert not result.ok
    assert "permission" in result.error.lower()
```

Every new tool needs this. It is four lines, and it is the difference between a
permission that is declared and one that is enforced.

### An isolation test

```python
async def test_the_new_resource_is_scoped(self, client, owner_headers, outsider_headers):
    created = await client.post("/api/v1/things", headers=owner_headers, json={...})
    thing_id = created.json()["data"]["id"]

    leaked = await client.get(f"/api/v1/things/{thing_id}", headers=outsider_headers)
    assert leaked.status_code == 404      # not 403: it does not exist in their scope
```

404 rather than 403 is the assertion to make. A 403 confirms the resource exists,
which is itself a disclosure.

### Rules

1. **One behaviour per test.** A failure should name the cause.
2. **Assert on the thing you care about**, not on incidental structure.
3. **Do not mock what you own.** Services and repositories run for real against
   SQLite; mocks would test the mock.
4. **Mock at the network boundary only** — Groq, Vapi, Langfuse.
5. **No sleeps.** Everything is deterministic. If you need a sleep, something is
   racing and the sleep is hiding it.

---

## Lint and types

```bash
make lint        # ruff check .
make format      # ruff format .
make typecheck   # mypy app
```

Ruff is configured in `pyproject.toml` with a line length of 100 and the rule sets
`E`, `F`, `I`, `UP`, `B`, `SIM` and `C4`.

Mypy runs in strict-adjacent mode over `app/`. Third-party stubs that do not exist
are ignored explicitly, one module at a time, rather than globally.

---

## Frontend checks

```bash
cd frontend
npm run typecheck    # tsc --noEmit
npm run lint         # next lint
npm run build        # production build, all 18 routes
```

`npm run build` is the meaningful one. It does everything `typecheck` does and
then proves each route actually renders under the App Router, which catches a
class of server/client boundary mistakes that `tsc` alone will not.

There is no frontend test runner. For a hackathon build, the type checker plus a
successful production build plus the backend contract tests cover the ground that
matters most; adding Vitest and Playwright would have cost more than it returned
here. Stated rather than implied.

---

## Full verification

```bash
./scripts/verify.sh
```

Runs, in order: backend lint, backend typecheck, backend tests, frontend
typecheck, frontend build. Non-zero on the first failure. This is the same
sequence CI would run.

Verified state of the repository at the time of writing:

| Check | Result |
| --- | --- |
| `pytest` | 105 passed |
| `ruff check` | Clean |
| `mypy app` | Clean |
| `tsc --noEmit` | Clean |
| `next build` | 18 routes, no errors |
| End-to-end smoke | detect, investigate, RBAC, approve, execute, measure, SCALE |

---

<div align="center">

[Docs index](README.md) · [Contributing](CONTRIBUTING.md) ·
[Architecture](ARCHITECTURE.md) · [Security](SECURITY.md) · [Data](DATA.md)

</div>
