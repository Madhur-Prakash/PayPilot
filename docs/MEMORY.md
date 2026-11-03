<div align="center">

# Agent memory

[![Docs index](https://img.shields.io/badge/-Docs_index-475569?style=flat-square&logo=markdown&logoColor=white)](README.md)
[![Agents](https://img.shields.io/badge/-Agents-64748b?style=flat-square)](AGENTS.md)
[![Architecture](https://img.shields.io/badge/-Architecture-2563eb?style=flat-square)](ARCHITECTURE.md)
[![Configuration](https://img.shields.io/badge/-Configuration-16a34a?style=flat-square)](CONFIGURATION.md)

</div>

The growth agents were amnesiac. Every run recomputed the same facts and could
re-propose, word for word, something a human had rejected last month. This layer
gives them somewhere to put what a run *concluded* — and, more importantly, what
happened next.

It is built on [cognee](https://docs.cognee.ai/), which turns prose into a
knowledge graph and searches it semantically.

**It is on in this deployment** (`MEMORY_ENABLED=true`). It needs no extra
credentials — it reuses the Groq key and embeds locally — but it does spend
tokens on each write, so `MEMORY_ENABLED=false` turns everything here off
and the agents fall back to starting each run from scratch.

## What gets remembered

Three things, written automatically. Nobody has to remember to record anything.

| When | What is written | Why it is worth keeping |
|---|---|---|
| An agent run finishes | The question, the opportunity, the recommended action, the evidence and the projected impact | So the next run knows this ground has been covered |
| A human approves or rejects | The decision, who made it, and any reason given | A rejection is the only record of a judgement the numbers do not explain |
| An experiment is measured | The decision, the rationale, the learning and the measured figures | The one memory grounded in a result rather than a forecast |

A rejection memory carries an explicit instruction not to re-propose the same
action without new evidence. That sentence is the point of the whole layer.

## What gets recalled

At the `intake` node, before any specialist gathers anything, the agent asks
memory what it already knows about the merchant and the question. Anything found
is threaded into the state, shown in the trace UI as a **recall** step, and
handed to the model at `synthesize` — clearly labelled as *prior conclusions,
not fresh measurements*, with the computed figures explicitly winning any
disagreement. A stale conclusion must never override today's numbers.

## Tenant isolation, and why it needs two mechanisms

This is the part to understand before changing anything.

Every merchant gets **its own cognee dataset** *and* **its own cognee user**, and
`ENABLE_BACKEND_ACCESS_CONTROL` is forced on in code — assigned, never
defaulted, so an operator who exports it as `false` for some other tool cannot
silently re-open the hole.

Passing `datasets=[...]` on its own **does not isolate anything**. With access
control off, cognee keeps a single shared vector collection: a search scoped to
merchant A returns merchant B's chunks *and stamps them with merchant A's
`dataset_name` on the way out*, so the leak is invisible to any check that
trusts the response.

Measured, not assumed — the same two-tenant write then read:

| `ENABLE_BACKEND_ACCESS_CONTROL` | Rows returned to merchant A |
|---|---|
| `false` | **2** — one of them merchant B's |
| `true` | **1** — only its own |

`tests/unit/test_agent_memory.py::TestTenantIsolation::test_access_control_is_forced_on`
is the regression test. Do not weaken it.

No function in `app/integrations/cognee_memory.py` accepts a dataset or a user.
They accept a merchant id and derive both, so there is no call site that can get
the scope wrong.

## Three properties it must keep

**Memory never delays an answer.** Recall is bounded by
`MEMORY_RECALL_TIMEOUT_SECONDS` and returns an empty list when it expires.
Measured at roughly **195 ms** median on a warm process — it is a pure vector
search, with `auto_route=False` and `scope="graph"` so cognee spends no LLM call
deciding how to search.

**Memory never blocks a request.** Writing runs cognee's full extraction
pipeline (10–30 s), so it is queued as a background task and drained on
shutdown. `remember_later()` is the normal entry point; `remember()` is for
when a caller genuinely needs to wait.

**Memory never breaks a run.** Every public method catches its own failures and
degrades to "no memory", so the agent behaves exactly as it did before this
layer existed. A failed import marks the backend broken once rather than
retrying on every request.

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `MEMORY_ENABLED` | `false` | Master switch |
| `MEMORY_LLM_PROVIDER` | `openai` | cognee routes via litellm |
| `MEMORY_LLM_MODEL` | *(blank)* | Blank reuses `GROQ_MODEL` as `groq/<model>` |
| `MEMORY_LLM_API_KEY` | *(blank)* | Blank reuses `GROQ_API_KEY` |
| `MEMORY_EMBEDDING_PROVIDER` | `fastembed` | Local, no API key, nothing leaves the host |
| `MEMORY_EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Downloaded once on first use |
| `MEMORY_STORAGE_DIR` | *(blank)* | Blank means `backend/.cognee` |
| `MEMORY_RECALL_TOP_K` | `6` | Prior conclusions pulled into a run |
| `MEMORY_RECALL_TIMEOUT_SECONDS` | `10` | Recall is abandoned past this |
| `MEMORY_WRITE_TIMEOUT_SECONDS` | `180` | Writes are off the request path |
| `MEMORY_TRACING_ENABLED` | `false` | cognee's own OTLP exporter |

Two defaults are deliberate and worth not "fixing":

* **`fastembed`, not cognee's default `hash`.** The hash embedder is not
  semantic; recall with it returns near-noise.
* **cognee's session cache is forced off.** It runs a `SessionTurnAnalysis` LLM
  call on every recall to maintain conversational state. Nothing here passes a
  `session_id`, so it buys nothing — and on a rate-limited key it was enough to
  push recall from ~195 ms past its own 10 s timeout.

Installation is an optional extra, because cognee pulls in roughly 75 packages:

```bash
cd backend && uv pip install ".[memory]"
```

Without it the app runs normally and memory reports itself unavailable.

## API

| Method | Path | Permission |
|---|---|---|
| `GET` | `/api/v1/memory/status` | `memory:read` |
| `GET` | `/api/v1/memory/search?q=&limit=&kind=` | `memory:read` |
| `POST` | `/api/v1/memory/remember` | `memory:write` |
| `DELETE` | `/api/v1/memory` | `memory:admin` |

`search` returns `available: false` rather than an error when memory is off, so
the UI can say "memory is off" instead of "nothing found". `DELETE` is
irreversible and requires `{"confirm": true}`.

Roles: viewer and staff read; analyst and above write; owner and admin erase.

## The page

**Agent Memory** in the sidebar, under Agents. It exists because memory is only
worth having if a human can check it — an agent quietly carrying a wrong
conclusion forward is worse than one carrying nothing.

* **Search** it in plain language, filtered by kind.
* **Teach the agents** something they should know, written as a standalone note.
* **Erase** everything for this merchant, behind a typed confirmation, because
  there is no undo and no backup of a knowledge graph.

When memory is off the page says so plainly rather than rendering an empty
search result, and when it is on but unreachable it says that instead — the two
look identical from a result list, and they need different fixes.

## Cost

Recall is free — local embeddings, no LLM. Writing costs one extraction pass per
agent run, per approval and per measurement. On a rate-limited Groq key that is
the thing to watch: the free tier's 8 000 TPM was enough to make writes queue
behind each other during testing. `MEMORY_ENABLED=false` stops all of it.

## Files

| Path | What it holds |
|---|---|
| `backend/app/integrations/cognee_memory.py` | The cognee adapter; isolation lives here |
| `backend/app/agents/memory.py` | What gets written, and in what words |
| `backend/app/api/v1/memory.py` | The four endpoints |
| `frontend/src/app/(dashboard)/memory/page.tsx` | Search, teach and erase |
| `backend/tests/unit/test_agent_memory.py` | Isolation, degradation, narrative |
| `backend/tests/api/test_memory_api.py` | Permissions and the disabled path |
| `backend/.cognee/` | The graph, vectors and metadata — git-ignored business data |
