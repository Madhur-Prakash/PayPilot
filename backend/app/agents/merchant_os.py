"""The Merchant OS orchestrator - seven agents on one LangGraph workflow.

    START
      -> orchestrator          (Orchestrator Agent: pick the specialist - explicit, LLM or keywords)
      -> <specialist>          (one of the six below; runs its plan through the tool registry)
      -> synthesize            (facts -> answer; the LLM may word it, never compute it)
      -> approval_gate         (anything consequential waits for a human; THE GRAPH ENDS HERE)
      -> END

==========================  ====================================================================
Business Intelligence       sales, product performance, assortment and inventory from SQL
Product Discovery           live Channel3 search, details, similar products, comparison
Supply Intelligence         assortment analysis -> complementary products -> open recommendations
Pricing Intelligence        merchant prices vs live retail listings
Growth Strategy             the Growth Autopilot: analyse -> discover -> recommend (to approval)
PayPal Transaction          payment history and insights; may *request* a purchase approval
==========================  ====================================================================

Every tool call goes through ``ToolRegistry.execute``: typed, permission-checked against
the human the agents act for, merchant-scoped, traced and persisted (Agent Activity shows
it). Transient tool failures (timeouts, 5xx, rate limits) are retried with backoff.
No agent can approve, pay or capture - those are authenticated endpoints only.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import bind_context, get_logger
from app.db.models.agent import AgentName, AgentRunStatus, AgentWorkflow
from app.db.models.audit import ActorType, AuditAction
from app.integrations.groq import llm_service
from app.integrations.langfuse import tracer
from app.repositories.agent import AgentRunRepository
from app.repositories.merchant import AuditLogRepository
from app.tools import (
    BUSINESS_INTELLIGENCE_TOOLS,
    GROWTH_STRATEGY_TOOLS,
    PAYPAL_TRANSACTION_TOOLS,
    PRICING_INTELLIGENCE_TOOLS,
    PRODUCT_DISCOVERY_TOOLS,
    SUPPLY_INTELLIGENCE_TOOLS,
    ToolContext,
    ToolResult,
    registry,
)

log = get_logger(__name__)

AgentKey = Literal["business_intelligence", "product_discovery", "supply_intelligence", "pricing_intelligence",
                   "growth_strategy", "paypal_transaction"]
_TRANSIENT = re.compile(r"did not respond|unreachable|timed? ?out|HTTP 5\d\d|rate limit|temporarily", re.I)
MAX_TOOL_RETRIES = 2


@dataclass(frozen=True, slots=True)
class AgentSpec:
    key: str
    name: str
    tools: tuple[str, ...]
    purpose: str
    keywords: tuple[str, ...]


AGENTS: dict[str, AgentSpec] = {
    "paypal_transaction": AgentSpec(
        "paypal_transaction", AgentName.PAYPAL_TRANSACTION, tuple(PAYPAL_TRANSACTION_TOOLS),
        "PayPal payments, orders, captures, payment history and purchase approval requests.",
        ("paypal", "payment", "payments", "transaction", "capture", "refund", "paid", "pay for", "order status", "checkout")),
    "pricing_intelligence": AgentSpec(
        "pricing_intelligence", AgentName.PRICING_INTELLIGENCE, tuple(PRICING_INTELLIGENCE_TOOLS),
        "The merchant's selling prices against live market listings.",
        ("price", "pricing", "priced", "overpriced", "underpriced", "market price", "charge", "competitor price")),
    "growth_strategy": AgentSpec(
        "growth_strategy", AgentName.GROWTH_STRATEGY, tuple(GROWTH_STRATEGY_TOOLS),
        "Growth Autopilot: analyse the business, discover products and produce approval-ready recommendations.",
        ("autopilot", "grow", "growth", "strategy", "recommendation", "recommend", "opportunit", "increase revenue",
         "what should i do")),
    "supply_intelligence": AgentSpec(
        "supply_intelligence", AgentName.SUPPLY_INTELLIGENCE, tuple(SUPPLY_INTELLIGENCE_TOOLS),
        "Assortment expansion: complementary products the merchant should stock, from sales data and Channel3.",
        ("assortment", "expand", "expansion", "stock", "new products", "what to sell", "sell next", "complementary",
         "supply", "inventory expansion", "add to my store")),
    "business_intelligence": AgentSpec(
        "business_intelligence", AgentName.BUSINESS_INTELLIGENCE, tuple(BUSINESS_INTELLIGENCE_TOOLS),
        "How the business is performing: sales, best sellers, categories, inventory.",
        ("sales", "revenue", "performance", "how is my", "how are my", "best seller", "bestseller", "top products",
         "kpi", "business doing", "inventory status", "turnover")),
    "product_discovery": AgentSpec(
        "product_discovery", AgentName.PRODUCT_DISCOVERY, tuple(PRODUCT_DISCOVERY_TOOLS),
        "Find, compare and explore products in Channel3's live catalog.",
        ("find", "search", "discover", "compare", "similar", "alternative", "look for", "looking for", "show me",
         "under $", "under ₹", "products")),
}


class RouteDecision(BaseModel):
    agent: AgentKey
    reason: str = Field(default="", max_length=240)


class Synthesis(BaseModel):
    answer: str = Field(default="", max_length=2000)


class MOSState(TypedDict, total=False):
    ctx: ToolContext
    message: str
    requested_agent: str | None
    params: dict[str, Any]
    agent: str
    route: dict[str, Any]
    calls: list[dict[str, Any]]
    steps: list[dict[str, Any]]
    answer: str
    products: list[dict[str, Any]]
    recommendations: list[dict[str, Any]]
    approvals: list[dict[str, Any]]
    comparison: dict[str, Any] | None
    suggestions: list[str]
    used_llm: bool
    requires_approval: bool


def keyword_route(message: str) -> tuple[str, str]:
    text = message.lower()
    best, best_hits = "product_discovery", 0
    for key, spec in AGENTS.items():
        hits = sum(1 for k in spec.keywords if k in text)
        if hits > best_hits:
            best, best_hits = key, hits
    if best_hits == 0:
        return "product_discovery", "No specialist keywords - treated as a product search."
    return best, f"Matched {best_hits} {AGENTS[best].name.replace('_', ' ')} keyword(s)."


async def _call(state: MOSState, agent: AgentSpec, tool: str, args: dict[str, Any]) -> ToolResult:
    """Run one tool as ``agent``, retrying transient failures with backoff."""
    ctx = state["ctx"]
    ctx.agent_name = agent.name
    result = await registry.execute(tool, ctx, args)
    attempt = 0
    while not result.ok and attempt < MAX_TOOL_RETRIES and _TRANSIENT.search(result.error or ""):
        attempt += 1
        await asyncio.sleep(0.5 * (3 ** (attempt - 1)))
        log.info("merchant_os_tool_retry", tool=tool, attempt=attempt)
        result = await registry.execute(tool, ctx, args)
    state.setdefault("calls", []).append({
        "agent": agent.name, "tool": tool, "args": args, "ok": result.ok, "summary": result.summary,
        "error": result.error, "attempts": attempt + 1, "duration_ms": result.duration_ms,
    })
    return result


def _step(state: MOSState, agent: AgentSpec, action: str, results: list[ToolResult], decision: str | None = None) -> None:
    ok = [r for r in results if r.ok]
    failed = [r for r in results if not r.ok]
    text = " ".join(r.summary for r in ok if r.summary)
    if failed:
        text += (" " if text else "") + " ".join(f"[{r.tool} failed: {r.error}]" for r in failed)
    state.setdefault("steps", []).append({
        "node": agent.key, "agent_name": agent.name, "action": action, "result": text.strip()[:4000],
        "decision": decision, "status": "COMPLETED" if ok or not results else "FAILED",
        "evidence": [{"metric": r.tool, "value": r.summary[:200], "source": "tool"} for r in ok][:8],
        "error": "; ".join(f"{r.tool}: {r.error}" for r in failed)[:2000] or None,
    })


# --------------------------------------------------------------------------- #
# Nodes
# --------------------------------------------------------------------------- #
async def orchestrator(state: MOSState) -> MOSState:
    message = state["message"]
    requested = state.get("requested_agent")
    if requested in AGENTS:
        route = {"agent": requested, "source": "explicit", "reason": "Requested by the caller."}
    else:
        key, reason = keyword_route(message)
        route = {"agent": key, "source": "keywords", "reason": reason}
        if llm_service.enabled:
            catalogue = "\n".join(f"- {k}: {s.purpose}" for k, s in AGENTS.items())
            decision, result = await llm_service.structured(
                system=f"You route a merchant's request to exactly one specialist agent.\n{catalogue}",
                user=message, schema=RouteDecision, fallback=RouteDecision(agent=key, reason=reason),  # type: ignore[arg-type]
                trace=state["ctx"].trace, trace_name="merchant_os_route", max_tokens=200,
            )
            if not result.used_fallback:
                route = {"agent": decision.agent, "source": "llm", "reason": decision.reason or reason}
                state["used_llm"] = True
    spec = AGENTS[route["agent"]]
    state.setdefault("steps", []).append({
        "node": "orchestrator", "agent_name": AgentName.MERCHANT_ORCHESTRATOR,
        "action": f"Routed the request to the {AgentName.LABELS[spec.name]}",
        "result": route["reason"], "decision": spec.key, "status": "COMPLETED", "evidence": [], "error": None,
    })
    return {**state, "agent": route["agent"], "route": route}


async def business_intelligence(state: MOSState) -> MOSState:
    agent = AGENTS["business_intelligence"]
    days = int(state.get("params", {}).get("days", 30))
    results = [await _call(state, agent, "get_sales_summary", {"days": days}),
               await _call(state, agent, "get_product_performance", {"days": days}),
               await _call(state, agent, "analyze_assortment", {"days": days})]
    _step(state, agent, f"Analysed the last {days} days of sales, products and inventory", results)
    return state


async def product_discovery(state: MOSState) -> MOSState:
    agent = AGENTS["product_discovery"]
    params = state.get("params", {})
    message = state["message"]
    results: list[ToolResult] = []
    ids = [str(i) for i in params.get("product_ids") or []][:4]
    if len(ids) >= 2:
        result = await _call(state, agent, "compare_products", {"product_ids": ids, "features": params.get("features") or []})
        results.append(result)
        if result.ok:
            state["comparison"] = result.data
            state["products"] = result.data.get("products", [])
        _step(state, agent, f"Compared {len(ids)} products side by side", results)
        return state
    if params.get("product_id"):
        detail = await _call(state, agent, "get_product_details", {"product_id": str(params["product_id"])})
        similar = await _call(state, agent, "find_similar_products", {"product_id": str(params["product_id"]), "limit": 6})
        results += [detail, similar]
        if similar.ok:
            state["products"] = similar.data.get("products", [])
        _step(state, agent, "Fetched the product and similar alternatives from Channel3", results)
        return state
    search = await _call(state, agent, "discover_products", {"query": message[:300], "max_results": int(params.get("max_results", 8))})
    results.append(search)
    products = search.data.get("products", []) if search.ok else []
    state["products"] = products
    lowered = message.lower()
    if products and re.search(r"\balternative|\bsimilar|\binstead of\b", lowered):
        similar = await _call(state, agent, "find_similar_products", {"product_id": products[0]["id"], "limit": 6})
        results.append(similar)
        if similar.ok:
            state["products"] = [products[0], *similar.data.get("products", [])]
    elif products and re.search(r"\bcompare\b|\bvs\.?\b|\bversus\b|different brands", lowered):
        picks, brands = [], set()
        for p in products:
            if p.get("brand") not in brands:
                picks.append(p["id"])
                brands.add(p.get("brand"))
            if len(picks) == 3:
                break
        if len(picks) >= 2:
            compared = await _call(state, agent, "compare_products", {"product_ids": picks})
            results.append(compared)
            if compared.ok:
                state["comparison"] = compared.data
    _step(state, agent, "Searched Channel3's live catalog and ranked the results", results)
    state["suggestions"] = ["Compare the top three", "Show similar products to the top pick",
                            "Generate assortment recommendations"]
    return state


async def supply_intelligence(state: MOSState) -> MOSState:
    agent = AGENTS["supply_intelligence"]
    analysis = await _call(state, agent, "analyze_assortment", {"days": int(state.get("params", {}).get("days", 30))})
    results = [analysis]
    candidates = analysis.data.get("expansion_candidates", []) if analysis.ok else []
    if candidates:
        top = candidates[0]
        search = await _call(state, agent, "discover_products", {"query": top["query"], "max_results": 6})
        results.append(search)
        if search.ok:
            state["products"] = search.data.get("products", [])
    recs = await _call(state, agent, "list_supply_recommendations", {})
    results.append(recs)
    if recs.ok:
        state["recommendations"] = recs.data.get("recommendations", [])
    _step(state, agent, "Analysed the assortment and searched Channel3 for the top expansion slot", results,
          decision=candidates[0]["slot"] if candidates else None)
    state["suggestions"] = ["Generate recommendations for these opportunities", "Compare the top products"]
    return state


async def pricing_intelligence(state: MOSState) -> MOSState:
    agent = AGENTS["pricing_intelligence"]
    result = await _call(state, agent, "get_market_price_intelligence", {"limit": int(state.get("params", {}).get("limit", 2))})
    _step(state, agent, "Compared your retail prices with live Channel3 listings", [result])
    return state


async def growth_strategy(state: MOSState) -> MOSState:
    """The Growth Autopilot: analyse -> identify -> discover -> recommend -> estimate -> present -> approval."""
    agent = AGENTS["growth_strategy"]
    params = state.get("params", {})
    days = int(params.get("days", 30))
    analysis = await _call(state, agent, "analyze_assortment", {"days": days})
    _step(state, agent, "1-2. Analysed performance and identified opportunities", [analysis])
    generated = await _call(state, agent, "generate_supply_recommendations",
                            {"days": days, "max_recommendations": int(params.get("max_recommendations", 4))})
    _step(state, agent, "3-5. Discovered products on Channel3, generated recommendations and estimated impact",
          [generated], decision="RECOMMENDED" if generated.ok and generated.data.get("recommendations") else None)
    opportunity = await _call(state, agent, "get_top_opportunity", {})
    listing = await _call(state, agent, "list_supply_recommendations", {"status": "RECOMMENDED"})
    if listing.ok:
        state["recommendations"] = listing.data.get("recommendations", [])
    _step(state, agent, "6-7. Presented the recommendations and requested merchant approval", [opportunity, listing],
          decision="AWAITING_APPROVAL" if state.get("recommendations") else None)
    state["suggestions"] = ["Review and approve recommendations", "Compare the recommended products"]
    return state


async def paypal_transaction(state: MOSState) -> MOSState:
    agent = AGENTS["paypal_transaction"]
    params = state.get("params", {})
    results = [await _call(state, agent, "get_payment_history", {"limit": 20}),
               await _call(state, agent, "get_paypal_transaction_insights", {"days": 30})]
    needed = ("recommendation_id", "quantity", "unit_cost", "payee_email")
    if all(params.get(k) for k in needed):
        request = await _call(state, agent, "request_purchase_payment", {k: params[k] for k in needed})
        results.append(request)
        if request.ok:
            state["approvals"] = [request.data]
    _step(state, agent, "Reviewed PayPal payments" + (" and requested a purchase approval" if len(results) > 2 else ""),
          results, decision="APPROVAL_REQUESTED" if state.get("approvals") else None)
    return state


async def synthesize(state: MOSState) -> MOSState:
    calls = state.get("calls", [])
    facts = [f"{c['tool']}: {c['summary']}" if c["ok"] else f"{c['tool']} failed: {c['error']}" for c in calls]
    fallback = " ".join(c["summary"] for c in calls if c["ok"] and c["summary"]) or (
        "The agents could not complete this request: " + "; ".join(c["error"] or "" for c in calls if not c["ok"]))
    answer = fallback
    if llm_service.enabled and calls:
        spec = AGENTS[state["agent"]]
        out, result = await llm_service.structured(
            system=(f"You are PayPilot's {AgentName.LABELS[spec.name]}. Answer the merchant in 2-5 sentences using ONLY "
                    "these tool results. Keep every number exactly as given and repeat any verdict exactly as the tool "
                    "stated it - never upgrade or contradict a computed verdict. Say plainly if something failed or is "
                    "not configured; never invent products or figures. Anything that moves money needs their approval."),
            user=f"Request: {state['message']}\nTool results:\n" + "\n".join(facts),
            schema=Synthesis, fallback=Synthesis(answer=fallback), trace=state["ctx"].trace,
            trace_name="merchant_os_synthesis", max_tokens=600,
        )
        if not result.used_fallback and out.answer.strip():
            answer = out.answer.strip()
            state["used_llm"] = True
    state.setdefault("steps", []).append({
        "node": "synthesize", "agent_name": AgentName.MERCHANT_ORCHESTRATOR, "action": "Summarised the evidence",
        "result": answer[:4000], "decision": None, "status": "COMPLETED", "evidence": [], "error": None,
    })
    return {**state, "answer": answer}


async def approval_gate(state: MOSState) -> MOSState:
    waiting = [r for r in state.get("recommendations", []) if r.get("status") in ("RECOMMENDED", "ANALYZED", "DETECTED")]
    requires = bool(waiting or state.get("approvals"))
    if requires:
        state.setdefault("steps", []).append({
            "node": "approval_gate", "agent_name": AgentName.MERCHANT_ORCHESTRATOR,
            "action": "Stopped at the human approval gate",
            "result": f"{len(waiting)} recommendation(s) and {len(state.get('approvals', []))} payment approval(s) "
                      "wait for a person. No agent can approve, pay or capture.",
            "decision": "AWAITING_APPROVAL", "status": "COMPLETED", "evidence": [], "error": None,
        })
    return {**state, "requires_approval": requires}


def _route(state: MOSState) -> str:
    return state["agent"]


def build_merchant_os_graph() -> Any:
    builder: StateGraph = StateGraph(MOSState)
    builder.add_node("orchestrator", orchestrator)
    for key, node in (("business_intelligence", business_intelligence), ("product_discovery", product_discovery),
                      ("supply_intelligence", supply_intelligence), ("pricing_intelligence", pricing_intelligence),
                      ("growth_strategy", growth_strategy), ("paypal_transaction", paypal_transaction)):
        builder.add_node(key, node)
        builder.add_edge(key, "synthesize")
    builder.add_node("synthesize", synthesize)
    builder.add_node("approval_gate", approval_gate)
    builder.add_edge(START, "orchestrator")
    builder.add_conditional_edges("orchestrator", _route, {k: k for k in AGENTS})
    builder.add_edge("synthesize", "approval_gate")
    builder.add_edge("approval_gate", END)
    compiled = builder.compile()
    log.info("merchant_os_graph_compiled", nodes=len(AGENTS) + 3)
    return compiled


@lru_cache(maxsize=1)
def get_merchant_os_graph() -> Any:
    return build_merchant_os_graph()


def agent_catalogue() -> list[dict[str, Any]]:
    out = [{"key": "orchestrator", "name": AgentName.MERCHANT_ORCHESTRATOR,
            "label": AgentName.LABELS[AgentName.MERCHANT_ORCHESTRATOR],
            "purpose": "Decides which specialist handles a request (explicit choice, LLM routing, or keywords).",
            "tools": [], "can_move_money": False}]
    for spec in AGENTS.values():
        out.append({"key": spec.key, "name": spec.name, "label": AgentName.LABELS[spec.name], "purpose": spec.purpose,
                    "tools": [{"name": t, "requires_approval": bool(registry.get(t) and registry.get(t).requires_approval)}  # type: ignore[union-attr]
                              for t in spec.tools],
                    "can_move_money": False})
    return out


class MerchantOS:
    def __init__(self, session: AsyncSession, *, merchant_id: uuid.UUID, merchant_name: str, user_id: uuid.UUID | None,
                 permissions: frozenset[str], actor_label: str = "") -> None:
        self.session = session
        self.merchant_id = merchant_id
        self.merchant_name = merchant_name
        self.user_id = user_id
        self.permissions = permissions
        self.actor_label = actor_label
        self.runs = AgentRunRepository(session, merchant_id)

    async def execute(self, message: str, *, agent: str | None = None, params: dict[str, Any] | None = None,
                      workflow: str = AgentWorkflow.MERCHANT_OS, channel: str = "web") -> dict[str, Any]:
        trace = tracer.trace(name=f"merchant_os_{workflow}", user_id=str(self.user_id) if self.user_id else None,
                             merchant_id=str(self.merchant_id), agent_name=AgentName.MERCHANT_ORCHESTRATOR,
                             workflow=workflow, input={"message": message, "agent": agent}, tags=[workflow, settings.app_env])
        run = await self.runs.start(
            agent_name=AgentName.MERCHANT_ORCHESTRATOR, workflow=workflow, input_text=message, user_id=self.user_id,
            channel=channel, trace_id=trace.trace_id, trace_url=trace.url,
            model=settings.groq_model if llm_service.enabled else None,
            metadata={"requested_agent": agent, "params": {k: str(v)[:200] for k, v in (params or {}).items()},
                      "trigger": "autopilot" if workflow == AgentWorkflow.AUTOPILOT else "merchant request"},
        )
        bind_context(agent_run_id=str(run.id), trace_id=trace.trace_id)
        ctx = ToolContext(session=self.session, merchant_id=self.merchant_id, merchant_name=self.merchant_name,
                          user_id=self.user_id, permissions=self.permissions, agent_name=AgentName.MERCHANT_ORCHESTRATOR,
                          run=run, trace=trace)
        state: MOSState = {"ctx": ctx, "message": message, "requested_agent": agent, "params": params or {}, "calls": [],
                           "steps": [], "products": [], "recommendations": [], "approvals": [], "comparison": None,
                           "suggestions": [], "used_llm": False, "requires_approval": False}
        try:
            with trace.span("merchant_os", input={"message": message}):
                final: MOSState = await get_merchant_os_graph().ainvoke(state, {"recursion_limit": 20})
        except Exception as exc:
            log.exception("merchant_os_failed", error_type=type(exc).__name__)
            await self.runs.finish(run, status=AgentRunStatus.FAILED, summary="The agents could not complete the request.",
                                   error=f"{type(exc).__name__}: {str(exc)[:400]}")
            trace.finish(output={"error": str(exc)[:400]})
            tracer.flush()
            raise
        for index, step in enumerate(final.get("steps", []), start=1):
            await self.runs.add_step(run=run, sequence=index, node=step["node"], agent_name=step["agent_name"],
                                     action=step["action"], result=step.get("result", ""), decision=step.get("decision"),
                                     status=step.get("status", "COMPLETED"), evidence=step.get("evidence") or [],
                                     error=step.get("error"))
        calls = final.get("calls", [])
        any_ok = any(c["ok"] for c in calls)
        spec = AGENTS[final["agent"]]
        output = {
            "agent": spec.key, "agent_name": spec.name, "route": final.get("route"), "answer": final.get("answer", ""),
            "products": final.get("products", [])[:12], "recommendations": final.get("recommendations", [])[:10],
            "approvals": final.get("approvals", []), "comparison": final.get("comparison"),
            "suggestions": final.get("suggestions", []),
            "tool_calls": [{k: c[k] for k in ("agent", "tool", "ok", "summary", "error", "attempts")} for c in calls],
        }
        status = (AgentRunStatus.FAILED if calls and not any_ok else
                  AgentRunStatus.AWAITING_APPROVAL if final.get("requires_approval") else AgentRunStatus.COMPLETED)
        await self.runs.finish(
            run, status=status, summary=final.get("answer", "")[:4000], output=_json_safe(output),
            decision=f"Handled by {AgentName.LABELS[spec.name]}", requires_approval=bool(final.get("requires_approval")),
            used_fallback=not final.get("used_llm"),
            error="; ".join(f"{c['tool']}: {c['error']}" for c in calls if not c["ok"])[:2000] or None,
        )
        trace.finish(output={"agent": spec.key, "tools": [c["tool"] for c in calls]})
        tracer.flush()
        await AuditLogRepository(self.session).record(
            action=AuditAction.AGENT_RUN, merchant_id=self.merchant_id, actor_id=self.user_id,
            actor_type=ActorType.USER if self.user_id else ActorType.SYSTEM, actor_label=self.actor_label,
            resource="agent_run", resource_id=str(run.id), agent_run_id=run.id,
            description=f"{AgentName.LABELS[spec.name]} handled: {message[:160]}",
            metadata={"workflow": workflow, "tools": [c["tool"] for c in calls], "status": status},
        )
        return {"run_id": str(run.id), "status": status, **output, "agent_label": AgentName.LABELS[spec.name],
                "steps": final.get("steps", []), "requires_approval": bool(final.get("requires_approval")),
                "used_llm": bool(final.get("used_llm")), "duration_ms": run.duration_ms}


def _json_safe(value: Any) -> Any:
    import json

    return json.loads(json.dumps(value, default=str))


__all__ = ["AGENTS", "MerchantOS", "agent_catalogue", "build_merchant_os_graph", "keyword_route"]
