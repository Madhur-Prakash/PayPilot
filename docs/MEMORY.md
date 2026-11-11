<div align="center">

# Agent memory

Long-term memory for the agents, stored in PostgreSQL with pgvector. No separate service, no LLM in the write
path, no API key.

[![Docs index](https://img.shields.io/badge/-Docs_index-0b2a6f?style=flat-square)](README.md)
[![Agents](https://img.shields.io/badge/-Agents-2563eb?style=flat-square)](AGENTS.md)
[![Architecture](https://img.shields.io/badge/-Architecture-003087?style=flat-square)](ARCHITECTURE.md)
[![Security](https://img.shields.io/badge/-Security-dc2626?style=flat-square)](SECURITY.md)
[![pgvector](https://img.shields.io/badge/pgvector-HNSW_cosine-4169E1?style=flat-square&logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector)

</div>

---

## Contents

- [What it is for](#what-it-is-for)
- [Storage](#storage)
- [What gets remembered](#what-gets-remembered)
- [Rules](#rules)
- [Recall](#recall)
- [API](#api)
- [Configuration](#configuration)
- [Why not a separate memory service](#why-not-a-separate-memory-service)

---

## What it is for

A later run should know what an earlier run concluded: which recommendation a person rejected and why, what an
experiment proved, which supplier delivered late, what price a negotiation closed at. Memory gives the agents
that context for their **wording and judgement**. It never feeds a calculation, a limit or an approval.

---

## Storage

| | |
| --- | --- |
| Table | `agent_memories` (migration `0005_supply_paypal_memory`) |
| Vectors | pgvector `vector(384)` column with an **HNSW** index using `vector_cosine_ops` |
| Embeddings | Local: deterministic hashing by default, `fastembed` (`BAAI/bge-small-en-v1.5`) optionally |
| Recall | Cosine distance (`<=>`) in Postgres; the identical cosine computed in-process on SQLite (tests) |
| Entity links | `tags` name what a memory is about (SKU, supplier agent key, opportunity slug) |
| Deduplication | `content_hash` unique per merchant |
| Code | [`integrations/vector_memory.py`](../backend/app/integrations/vector_memory.py), narratives in [`agents/memory.py`](../backend/app/agents/memory.py) |

---

## What gets remembered

| Kind | Written by | Example |
| --- | --- | --- |
| `recommendation` | Growth orchestrator | "Recover lost evening repeat customers: $724/month at 92% confidence..." |
| `outcome` | Approval decisions | "Jordan Ellis rejected ... Reason: kitchen cannot handle the evening rush." |
| `experiment` | Measurement | "Evening win-back: SCALE, +61% conversion lift, p = 0.042." |
| `procurement` | Reconciliation | "PR-00001 closed: Cascadia won at $1,455.00, saved $248.77, margin 35.6% -> 43.8%." |
| `supplier` | Reconciliation, seed | "Pacific Bean Exchange deliveries took 9+ days; one invoice billed short-shipped bags." |
| `inventory` | Seed, agents | "Beans sell mostly through the PayPal online store; demand rises after newsletters." |
| `note` | People, on the Memory page | Anything an Analyst or above wants the agents to know |

Narratives are full sentences that name the merchant, the action, the numbers and the date, because a memory is
read months later without its original context.

---

## Rules

1. **Tenant isolation is a `WHERE` clause.** Every read, write and erase filters on `merchant_id`; no public
   method takes anything wider than one merchant id. A test writes a memory for merchant B and asserts merchant A
   can never recall it, whatever the query.
2. **Memory never delays an answer.** Recall is bounded by `MEMORY_RECALL_TIMEOUT_SECONDS` and returns empty on
   timeout. Writes run off the request path.
3. **Memory never breaks a run.** Every method catches its own failures and degrades to "no memory".
4. **Memory never overrides policy.** Recalled text is context for language only. Budgets, ceilings, approvals and
   authorisation are computed by the deterministic engines.
5. **The same memory is stored once.**

---

## Recall

```python
from app.integrations.vector_memory import memory, MemoryKind

hits = await memory.recall(
    merchant_id,
    "which supplier was late with beans",
    top_k=5,
    kinds=(MemoryKind.SUPPLIER,),
    tags=("supplier.pacific",),
)
```

On Postgres this is one indexed query:

```sql
SELECT ..., embedding <=> :query_vector AS distance
FROM agent_memories
WHERE merchant_id = :merchant AND kind IN (...)
ORDER BY distance
LIMIT :k;
```

Agents reach memory through the `search_memory` tool, which is permission-checked, logged and traced like every
other tool.

---

## API

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/api/v1/memory/status` | `memory:read` |
| GET | `/api/v1/memory/search?q=&kind=&tag=` | `memory:read` |
| GET | `/api/v1/memory/recent` | `memory:read` |
| POST | `/api/v1/memory/remember` | `memory:write` |
| DELETE | `/api/v1/memory` with `{"confirm": true}` | `memory:admin` |

Scope always comes from the authenticated principal, never from a parameter. When memory is disabled, search
returns `available: false` rather than an error.

---

## Configuration

```dotenv
MEMORY_ENABLED=true
MEMORY_RECALL_TOP_K=6
MEMORY_RECALL_TIMEOUT_SECONDS=5
EMBEDDING_PROVIDER=hash        # or fastembed (pip install -r backend/requirements-optional.txt)
EMBEDDING_DIMENSIONS=384
```

Changing the embedding provider changes the vector space. Each row records its `embedding_model`, so stale
vectors can be identified and re-embedded. See [Configuration: embeddings and agent memory](CONFIGURATION.md#embeddings-and-agent-memory).

---

## Why not a separate memory service

An earlier version used an external knowledge-graph library. It was removed because it needed an LLM call to write
every memory, added about 75 transitive dependencies, and isolated tenants through a library flag that leaked rows
across merchants when off. pgvector is already part of the stack, keeps isolation inside PayPilot's own SQL, and
costs nothing to run. If richer relationship queries are needed later, the `tags` column already encodes entity
edges and can be projected into a graph store without changing callers.

---

<div align="center">

[Previous: Agents](AGENTS.md) | [Docs index](README.md) | [Next: Supply Agents](SUPPLY_AGENTS.md)

</div>
