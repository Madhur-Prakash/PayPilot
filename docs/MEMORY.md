# Agent memory (Postgres + pgvector)

[Back to docs](README.md)

The agents keep long-term memory so a later run knows what an earlier run
concluded: which recommendation a human rejected (and why), what an experiment
proved, which supplier delivered late, what price a negotiation closed at.

Memory lives in the application's own database. There is no separate memory
service, no LLM in the write path, and no API key required.

| | |
| --- | --- |
| Storage | `agent_memories` table (migration `0005_supply_paypal_memory`) |
| Vectors | pgvector `vector(384)` column, **HNSW** index with `vector_cosine_ops` |
| Embeddings | Local: deterministic hashing by default, `fastembed` (BAAI/bge-small-en-v1.5) optionally |
| Recall | Cosine distance `<=>` in Postgres; identical in-process cosine on SQLite (tests) |
| Graph links | `tags` name the entities a memory is about (SKU, supplier agent key, opportunity slug) |
| Code | [`app/integrations/vector_memory.py`](../backend/app/integrations/vector_memory.py) |

## What gets remembered

| Kind | Written by | Example |
| --- | --- | --- |
| `recommendation` | Growth orchestrator | "Recover lost evening repeat customers - $724/month at 92% confidence…" |
| `outcome` | Approval decisions | "Jordan Ellis rejected … Reason: kitchen cannot handle the evening rush." |
| `experiment` | Measurement agent | "Evening win-back: SCALE, +61% conversion lift, p = 0.042." |
| `procurement` | Reconciliation | "PR-00001 closed: Cascadia won at $1,455.00, saved $248.77, margin 35.6% -> 43.8%." |
| `supplier` | Reconciliation, seed | "Pacific Bean Exchange deliveries took 9+ days; one invoice billed short-shipped bags." |
| `inventory` | Seed, agents | "Beans sell mostly through the PayPal online store; demand rises after newsletters." |
| `note` | People (Memory page) | Anything an Analyst+ wants the agents to know. |

Narratives are written in full sentences that name the merchant, the action, the
numbers and the date ([`app/agents/memory.py`](../backend/app/agents/memory.py)),
because a memory is read months later without its original context.

## Rules

1. **Tenant isolation is a `WHERE` clause.** Every read, write and erase filters on
   `merchant_id`; no public method takes anything wider than one merchant id. A
   test writes a "confidential" memory for merchant B and asserts merchant A can
   never recall it, whatever the query.
2. **Memory never delays an answer.** Recall is bounded by
   `MEMORY_RECALL_TIMEOUT_SECONDS` (5s) and returns empty on timeout. Writes run
   off the request path (`remember_later`).
3. **Memory never breaks a run.** Every method catches its own failures and
   degrades to "no memory".
4. **Memory never overrides policy.** Recalled text is context for a model's
   *language*. It never feeds a financial calculation, a budget, an approval or an
   authorisation - those are computed by the deterministic engines.
5. **The same memory is stored once** (`content_hash` unique per merchant).

## Recall

```python
from app.integrations.vector_memory import memory, MemoryKind

hits = await memory.recall(merchant_id, "which supplier was late with beans",
                           top_k=5, kinds=(MemoryKind.SUPPLIER,), tags=("supplier.pacific",))
```

On Postgres this is one indexed query:

```sql
SELECT …, embedding <=> :query_vector AS distance
FROM agent_memories
WHERE merchant_id = :merchant AND kind IN (…)
ORDER BY distance
LIMIT :k;
```

## API

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/api/v1/memory/status` | `memory:read` |
| GET | `/api/v1/memory/search?q=&kind=&tag=` | `memory:read` |
| GET | `/api/v1/memory/recent` | `memory:read` |
| POST | `/api/v1/memory/remember` | `memory:write` |
| DELETE | `/api/v1/memory` (`{"confirm": true}`) | `memory:admin` |

Agents reach memory through the `search_memory` tool (permission-checked, logged,
traced like every other tool).

## Configuration

```env
MEMORY_ENABLED=true            # on by default - no external dependency
MEMORY_RECALL_TOP_K=6
MEMORY_RECALL_TIMEOUT_SECONDS=5
EMBEDDING_PROVIDER=hash        # or fastembed (pip install -r requirements-optional.txt)
EMBEDDING_DIMENSIONS=384
```

Changing the embedding provider changes the vector space: each row records
`embedding_model`, so stale vectors can be identified and re-embedded.

## Why not a separate graph or memory service

The earlier version of this project used an external knowledge-graph library
(Cognee). It was removed: it needed an LLM to write every memory, added ~75
transitive dependencies, and isolated tenants through a library flag that, when
off, leaked rows across merchants. pgvector is already part of the stack, keeps
isolation inside our own SQL, and makes memory free to run. If richer
relationship queries are ever needed, the `tags` column is the seam: it already
encodes entity edges and can be projected into a graph store without changing
callers.
