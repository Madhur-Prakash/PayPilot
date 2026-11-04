<div align="center">

# The agent system

[![Docs index](https://img.shields.io/badge/-Docs_index-475569?style=flat-square&logo=markdown&logoColor=white)](README.md)
[![Architecture](https://img.shields.io/badge/-Architecture-64748b?style=flat-square)](ARCHITECTURE.md)
[![API](https://img.shields.io/badge/-API_reference-2563eb?style=flat-square)](API.md)
[![Agent memory](https://img.shields.io/badge/-Agent_memory-7c3aed?style=flat-square)](MEMORY.md)

</div>

Seven agents, one LangGraph workflow, 23 tools, and a hard rule: **the model
interprets, it never calculates.**

---

## Contents

- [The rule that shapes the design](#the-rule-that-shapes-the-design)
- [The seven agents](#the-seven-agents)
- [The graph](#the-graph)
- [State](#state)
- [The tool registry](#the-tool-registry)
- [Tool catalogue](#tool-catalogue)
- [Prompts](#prompts)
- [Structured output](#structured-output)
- [LLM failure handling](#llm-failure-handling)
- [The deterministic path](#the-deterministic-path)
- [Traces](#traces)
- [Voice](#voice)
- [Extending it](#extending-it)

---

## The rule that shapes the design

> The LLM never calculates a business number.

```
PostgreSQL / Python                    LLM
-------------------                    ---
revenue        = $24.7K      ---->   reads structured metrics
repeat_rate    = 38.3%                 chooses which tool to call next
evening change = -32.3%                writes the hypothesis
opportunity    = $724/mo          phrases the recommendation
confidence     = 0.92
```

Enforced in three places:

**1. Tools return computed results.** No tool hands raw rows to a model. The
largest payload any tool produces is an aggregated fact sheet.

**2. The detector sizes opportunities.**
[`OpportunityDetector`](../backend/app/services/growth/detector.py) computes
`estimated_value_monthly` and `confidence` from explicit formulas, with the
modelling assumptions stated as named constants:

```python
RECOVERY_RATE         = 0.35   # share of lapsed customers a win-back recovers
BUNDLE_CAPTURE_RATE   = 0.30   # share of observed co-purchase lift capturable
PRODUCT_RECOVERY_RATE = 0.25   # share of a declining product's loss recoverable
MIN_OPPORTUNITY_VALUE = 800.0  # below this, not worth a merchant's attention
```

**3. The orchestrator overwrites the model.** In `nodes.synthesize`, after the LLM
returns a `GrowthRecommendation`:

```python
recommendation.estimated_impact   = fallback.estimated_impact
recommendation.confidence         = fallback.confidence
recommendation.requires_approval  = fallback.requires_approval
```

The model may phrase. It may not price.

---

## The seven agents

Each is a node or an orchestrator method, with an explicit tool allow-list so one
agent cannot reach for another's capabilities.

### 1. Merchant Agent

Understands the question, maintains context, routes, and summarises the result.

| | |
| --- | --- |
| Node | `intake`, `respond` |
| Tools | The read surface — sales, segments, products, reviews, competitors, inventory, top opportunity, experiments |
| Output | `MerchantAnswer` — answer, key points, suggested follow-ups |

Handles "Why are sales down?", "What should I do today?", "Show me my biggest
growth opportunity."

### 2. Growth Scientist

The core agent. Analyses performance, finds anomalies, identifies opportunities,
investigates root causes, forms hypotheses, estimates impact, explains with
evidence.

| | |
| --- | --- |
| Node | `growth_scientist`, `synthesize` |
| Tools | `get_growth_metrics`, `get_sales_summary`, `get_revenue_trend`, `get_customer_segments`, `get_customer_metrics`, `get_product_performance`, `analyze_product_mix`, `detect_anomalies`, `detect_growth_opportunities`, `calculate_opportunity_value`, `get_growth_graph` |
| Output | `GrowthRecommendation` |

### 3. Review Intelligence Agent

Classifies topics, tracks sentiment, spots emerging complaints, surfaces positive
themes, and supplies quotable evidence.

| | |
| --- | --- |
| Node | `review_intelligence` |
| Tools | `get_review_summary`, `search_reviews` |
| Output | `ReviewInsight` |

Topics: `taste`, `quality`, `price`, `packaging`, `waiting_time`, `service`,
`staff`, `delivery`, `availability`, `ambience`.

> This agent works on **complaints per 100 orders**, not raw counts. When a
> segment loses a third of its orders, its complaint count can fall while the
> experience gets materially worse. The rate is the signal.

### 4. Market Intelligence Agent

Competitor perception and contextual external signals.

| | |
| --- | --- |
| Node | `market_intelligence` |
| Tools | `get_competitor_summary`, `get_external_signals` |
| Output | `MarketInsight` |

Signals are scored against the merchant's **actual revenue exposure**, so a
coffee-price story ranks differently for a cafe than for a sandwich shop. This is
deliberately not a news feed.

### 5. Action Agent

Builds the segment, creates the campaign, records every action, enforces approval.

| | |
| --- | --- |
| Node | `approval_gate`, then `GrowthOrchestrator.approve_and_execute` |
| Tools | `create_customer_segment`, `create_campaign` |
| Cannot | Approve or execute. `execute_campaign` refuses and points at the human endpoint |

### 6. Experiment Agent

Creates the experiment, splits control and test deterministically, defines the
hypothesis, success metric and duration.

| | |
| --- | --- |
| Tools | `create_experiment`, `list_active_experiments` |
| Assignment | Hash of the customer id, so allocation is stable across re-runs and free of ordering bias |

### 7. Measurement / Learning Agent

Compares control against test, computes lift, incremental revenue and profit, ROI
and significance, decides, and records what was learned.

| | |
| --- | --- |
| Method | `GrowthOrchestrator.measure_and_learn` |
| Tools | `get_experiment_results` |
| Output | `MeasurementVerdict` — but the *decision* is computed, not chosen by the model |

```python
verdict.decision = fallback.decision   # the model explains; the rule decides
```

---

## The graph

[`app/agents/graph.py`](../backend/app/agents/graph.py)

```
START
  |
  v
intake                    intent classification
  |                       LLM when configured, keyword routing otherwise
  v
growth_scientist          get_growth_metrics
  |                       get_customer_segments
  |                       detect_growth_opportunities
  |                       detect_anomalies
  |
  |--> review_intelligence      (conditional: needs_reviews)
  |--> market_intelligence      (conditional: needs_market)
  |
  v
synthesize                evidence -> GrowthRecommendation (schema-validated)
  |
  v
approval_gate             <=== THE GRAPH ENDS HERE for money-moving actions
  |
  v
respond -> END
```

Routing is conditional, not parallel:

```python
def _route_after_growth(state):
    if state.get("needs_reviews"):  return "review_intelligence"
    if state.get("needs_market"):   return "market_intelligence"
    return "synthesize"
```

An explicit `workflow="investigate"` forces the full fan-out; a conversational
`ask` engages only the specialists the intent classifier judged relevant.

### After the gate

The graph terminates at `approval_gate`. Execution resumes only through
`POST /agents/opportunities/{id}/approve` — authenticated, and requiring **both**
`campaign:execute` and `experiment:approve`:

```
approve_and_execute()
  |- Action Agent      build segment -> create campaign -> record approval
  |- Experiment Agent  create experiment, split control/test
  |- launch campaign   (simulated delivery, labelled)
  `- demo tenants      generate the experiment trading window

measure_and_learn()
  |- Measurement Agent recompute everything from the ledger
  `- Learning Agent    record what the business learned
```

**This is not a path the model can take.** It is reachable only from an
authenticated request by a permitted human.

---

## State

[`app/agents/state.py`](../backend/app/agents/state.py)

```python
class GraphState(TypedDict, total=False):
    ctx: ToolContext              # merchant scope, permissions, trace
    question: str
    workflow: str
    intent: IntentClassification | None
    metrics / segments / products / opportunities / reviews / market: dict
    review_insight / market_insight / recommendation / verdict
    answer: str
    evidence / steps / tools_used: list
    used_fallback: bool
    token_usage: dict
```

`ctx` carries merchant scope, the caller's permission set and the trace, so a node
can never act outside what the request was authorised to do.

### Channel semantics, and a trap

Every key is **last-value-wins**, and nodes return the whole state. Correct here
because the graph is strictly sequential — `growth_scientist` routes to exactly
one successor.

> **Warning.** An earlier version used `Annotated[list, operator.add]` reducers
> *and* had nodes return the full accumulated state. LangGraph then appended the
> accumulated list to itself at every node: 7 steps became 70+, and 8 tool calls
> became 352.
>
> If a genuinely concurrent fan-out is ever added, the reducers must come back
> **and** nodes must return only their own delta. Doing one without the other
> silently duplicates everything.

---

## The tool registry

[`app/tools/base.py`](../backend/app/tools/base.py)

A tool is the only way an agent touches the business. Every call is:

| Guarantee | How |
| --- | --- |
| **Typed** | Arguments validated against a Pydantic model |
| **Authorized** | `ctx.require(permission)` before execution |
| **Scoped** | Bound to one merchant, with no argument to widen it |
| **Logged** | Structured line with duration and status |
| **Traced** | A Langfuse span with inputs and outputs |
| **Recorded** | Persisted to `agent_tool_calls` for the trace UI |
| **Error-safe** | Failures return a `ToolResult`, never an exception |

```python
result = await registry.execute("get_sales_summary", ctx, {"days": 30})
if not result.ok:
    # a denied permission or bad argument degrades the answer,
    # it does not crash the run
```

### Registration

```python
@registry.register(
    "detect_growth_opportunities",
    description="Run the deterministic opportunity detector...",
    args_model=WindowArgs,
    permission=Permission.GROWTH_READ,
)
async def detect_growth_opportunities(ctx, args) -> tuple[dict, str]:
    ...
    return data, human_readable_summary
```

Each handler returns `(data, summary)`. The summary is what appears in the trace
UI and what the model reads first.

### Per-agent allow-lists

[`app/tools/__init__.py`](../backend/app/tools/__init__.py) defines
`GROWTH_SCIENTIST_TOOLS`, `REVIEW_AGENT_TOOLS`, `MARKET_AGENT_TOOLS`,
`ACTION_AGENT_TOOLS`, `EXPERIMENT_AGENT_TOOLS`, `MEASUREMENT_AGENT_TOOLS`,
`MERCHANT_AGENT_TOOLS` and `VOICE_TOOLS`.

---

## Tool catalogue

All 23, with the permission each requires. Live at
`GET /api/v1/agents/tools`.

### Analytics

| Tool | Permission | Returns |
| --- | --- | --- |
| `get_sales_summary` | `dashboard:read` | Revenue, orders, AOV, repeat rate, margin, with deltas |
| `get_revenue_trend` | `growth:read` | Daily revenue and orders |
| `get_customer_segments` | `customers:read` | Per-slot revenue, repeat customers, service time |
| `get_customer_metrics` | `customers:read` | Base health, retention, churn risk |
| `get_product_performance` | `products:read` | Per-product revenue, units, margin, attach rate |
| `analyze_product_mix` | `products:read` | Market-basket pairs with support, confidence, lift |
| `detect_anomalies` | `growth:read` | Metrics outside normal variation |
| `get_growth_metrics` | `growth:read` | The complete computed fact sheet |
| `detect_growth_opportunities` | `growth:read` | Quantified, evidence-backed opportunities |
| `get_growth_graph` | `growth:read` | The decomposition with typed edges |
| `calculate_opportunity_value` | `growth:read` | Explicit arithmetic, so the model never does it |

### Intelligence

| Tool | Permission | Returns |
| --- | --- | --- |
| `get_review_summary` | `reviews:read` | Sentiment, topics, emerging complaints per 100 orders |
| `search_reviews` | `reviews:read` | Vector similarity over review embeddings |
| `get_competitor_summary` | `competitors:read` | Perception comparison across seven dimensions |
| `get_external_signals` | `signals:read` | Signals scored against revenue exposure |
| `get_inventory_status` | `inventory:read` | Days of cover, stockout risk, revenue at risk |

### Actions

| Tool | Permission | Notes |
| --- | --- | --- |
| `create_customer_segment` | `customers:read` | Read-only preview of who would be targeted |
| `create_campaign` | `campaign:create` | Created `PENDING_APPROVAL`, never delivered |
| `create_experiment` | `experiment:create` | Control/test pair, pending approval |
| `get_experiment_results` | `experiment:read` | Recomputed from the ledger |
| `list_active_experiments` | `experiment:read` | Status of running experiments |
| `get_top_opportunity` | `growth:read` | Highest-priority open opportunity |
| `execute_campaign` | `campaign:execute` | **Always refuses.** Points at the human endpoint |

`execute_campaign` is registered deliberately. An agent that reaches for it gets a
clear structured refusal explaining that execution requires a recorded human
approval — better than the capability silently not existing.

---

## Prompts

[`app/agents/prompts.py`](../backend/app/agents/prompts.py)

Every prompt inherits the same base rules:

```
1. Never calculate, estimate or invent a number. Every figure you may use is
   supplied to you already computed.
2. Never claim that one thing caused another. Use "correlates with", "moved in
   step with", "the evidence suggests". A controlled experiment is what turns a
   hypothesis into a finding.
3. Currency is US dollars, written as "$9,840".
4. Be concrete and specific.
5. This is a demo environment with a seeded dataset. Never claim access to live
   PayPal systems, real customer messaging, or competitor platforms.
```

Specialised prompts: `INTENT_CLASSIFIER`, `GROWTH_SCIENTIST`, `REVIEW_AGENT`,
`MARKET_AGENT`, `MERCHANT_AGENT`, `MEASUREMENT_AGENT`, `VOICE_AGENT`.

The Growth Scientist prompt asks explicitly for the rejected alternative — a
recommendation that has not considered the obvious cheaper option is not a
recommendation, it is a suggestion.

---

## Structured output

[`app/schemas/agent.py`](../backend/app/schemas/agent.py)

```python
class GrowthRecommendation(SchemaBase):
    opportunity: str
    summary: str
    evidence: list[EvidenceItem]
    hypothesis: str
    recommended_action: str
    reasoning: str
    estimated_impact: float          # overwritten by the detector
    confidence: float                # overwritten by the detector
    risk: Literal["low", "medium", "high"]
    requires_approval: bool
    action_key: str | None
    alternatives_considered: list[str]
```

Nothing downstream parses prose. If the model's JSON does not validate, the
deterministic fallback is used instead.

Two validators handle what models actually get wrong:

```python
confidence: 82        ->  0.82      # percentage instead of a fraction
"$9,840"            ->  9840.0    # currency string instead of a number
```

---

## LLM failure handling

[`app/integrations/groq.py`](../backend/app/integrations/groq.py) is the only
place the Groq SDK is imported.

```
complete()
  |- attempt 1 with GROQ_MODEL
  |- attempt 2 with GROQ_MODEL            (GROQ_MAX_RETRIES)
  |- attempt 1 with GROQ_FALLBACK_MODEL
  |- attempt 2 with GROQ_FALLBACK_MODEL
  `- return LLMResult(error=..., used_fallback=True)

structured()
  |- complete()
  |- extract_json()          bare JSON, fenced block, or prose-wrapped
  |- schema.model_validate()
  `- on any failure -> return the caller's fallback, unchanged
```

Authentication errors break out of the retry loop immediately — they will not
improve with another attempt.

A malformed or schema-invalid response can never raise into an API handler. The
worst case is a simpler answer.

---

## The deterministic path

Every node has a fallback, so the product runs with no `GROQ_API_KEY`.

| Node | With an LLM | Without |
| --- | --- | --- |
| `intake` | Model classification | Keyword routing over an intent table |
| `growth_scientist` | Identical (tools only) | Identical |
| `review_intelligence` | Model interpretation | Template built from the same figures |
| `market_intelligence` | Model interpretation | Template built from the same figures |
| `synthesize` | Model phrasing, detector's numbers | Detector's recommendation verbatim |
| `approval_gate` | Identical | Identical |
| `respond` | Conversational prose | Structured summary |

The deterministic recommendation is not a stub — it is the detector's full output,
with evidence, hypothesis, recommended action and the rejected alternative:

```python
reasoning = (
    "A blanket discount would cut margin across customers who were never at risk "
    "and would not address the signal the evidence actually points to. A targeted "
    "test on the affected segment, with a held-out control, measures whether the "
    "intervention works before it is rolled out."
)
```

Runs taken this way set `used_fallback: true` and are badged "Deterministic mode".

---

## Traces

Two layers, for two audiences.

### Persisted trace, for the merchant

`agent_runs` -> `agent_steps` -> `agent_tool_calls`. Rendered by the Agent Trace
screen as: action, tools used, evidence, result, decision.

```
1  Growth Orchestrator   Interpreted the request
2  Growth Scientist      Computed the period metrics, segmented them, ran detection
3  Review Intelligence   Analysed the review corpus for emerging complaints
4  Market Intelligence   Compared competitor perception, screened market signals
5  Growth Scientist      Synthesised the evidence into a single recommendation
6  Action Agent          Checked whether the action needs merchant approval
7  Merchant Agent        Composed the reply
```

> **Raw chain-of-thought is never recorded or displayed.** Not hidden — never
> captured. The UI states this explicitly so nobody assumes it is being withheld.

### Langfuse, for the engineer

Spans for nodes, generations for LLM calls with token usage, spans for tool calls
with arguments and results. Every method is exception-safe: observability must
never break the request it observes.

---

## Voice

Vapi owns speech only. Every capability the assistant exposes is a server tool
that calls the **same** backend agents as the web UI. There is no second copy of
the business logic.

```
Voice -> Vapi -> POST /api/v1/voice/tool
                   |- authenticate the 30-minute scoped session token
                   |- resolve the merchant from membership
                   |- "investigate_growth" -> the full LangGraph workflow
                   `- everything else      -> registry.execute(...)
                 -> Vapi -> Voice
```

The assistant is instructed that it may recommend but can never approve or
execute; anything money-moving is directed to the dashboard.

Setup: [CONFIGURATION.md](CONFIGURATION.md#vapi-voice).

---

## Extending it

### Adding a tool

1. Define an args model and handler in `app/tools/`:

   ```python
   class MyArgs(BaseModel):
       days: int = Field(default=30, ge=7, le=180)

   @registry.register(
       "my_tool",
       description="What it returns, in one sentence the model can act on.",
       args_model=MyArgs,
       permission=Permission.GROWTH_READ,
   )
   async def my_tool(ctx: ToolContext, args: MyArgs) -> tuple[dict, str]:
       service = MyService(ctx.session, ctx.merchant_id)
       data = await service.compute(days=args.days)
       return data, f"One-line summary with the key figure: {data['headline']}."
   ```

2. Add it to the relevant allow-list in `app/tools/__init__.py`.
3. Add a test in `tests/integration/` asserting it is denied without the
   permission.

Keep it deterministic. If the tool computes a number, compute it in SQL or Python.

### Adding a graph node

1. Write the node in `app/agents/nodes.py`, following the pattern: call tools,
   hand computed facts to the LLM for interpretation, validate against a schema,
   fall back deterministically.
2. Register it in `app/agents/graph.py` and wire its edges.
3. Emit a `_step(...)` so it appears in the trace.
4. Remember the [state warning](#state) if you introduce concurrency.

### Adding an opportunity detector

Add a `_detect_*` method to
[`OpportunityDetector`](../backend/app/services/growth/detector.py) that returns
`DetectedOpportunity` objects, and call it from `detect()`. State the modelling
assumption as a named constant with a comment explaining the reasoning — every
number this class produces is one a merchant may act on.

---

<div align="center">

[Docs index](README.md) · [Architecture](ARCHITECTURE.md) ·
[API reference](API.md) · [Security](SECURITY.md) · [Testing](TESTING.md)

</div>
