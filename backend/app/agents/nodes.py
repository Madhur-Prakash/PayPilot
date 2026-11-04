"""LangGraph nodes.

Each node follows the same discipline:

  1. call deterministic tools to gather *computed* facts,
  2. hand those facts to the LLM only to interpret and phrase,
  3. validate the model's output against a Pydantic schema,
  4. fall back to a deterministic answer if the model is unavailable or invalid.

That last point is what lets the whole demo run with no GROQ_API_KEY set: the
numbers, the opportunity, the experiment and the decision are all still real,
only the prose is simpler.
"""

from __future__ import annotations

import json
from typing import Any

from app.agents import memory as agent_memory
from app.agents import prompts
from app.agents.state import GraphState
from app.core.logging import get_logger
from app.db.models.agent import AgentName
from app.integrations.groq import llm_service
from app.integrations.vector_memory import memory as memory_store
from app.schemas.agent import (
    GrowthRecommendation,
    IntentClassification,
    MarketInsight,
    MerchantAnswer,
    ReviewInsight,
)
from app.schemas.common import EvidenceItem
from app.tools import registry

log = get_logger(__name__)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
async def _call(state: GraphState, tool: str, **arguments: Any) -> dict[str, Any]:
    """Run a tool and fold its bookkeeping into state."""
    result = await registry.execute(tool, state["ctx"], arguments)
    state.setdefault("tools_used", [])
    if tool not in state["tools_used"]:
        state["tools_used"].append(tool)
    if not result.ok:
        log.warning("node_tool_failed", tool=tool, detail=result.error)
        return {}
    return result.data


def _step(
    state: GraphState,
    *,
    node: str,
    agent: str,
    action: str,
    result: str,
    decision: str | None = None,
    evidence: list[dict[str, Any]] | None = None,
) -> None:
    state.setdefault("steps", []).append(
        {
            "node": node,
            "agent_name": agent,
            "action": action,
            "result": result,
            "decision": decision,
            "evidence": evidence or [],
        }
    )


def _track_usage(state: GraphState, result: Any) -> None:
    usage = state.setdefault("token_usage", {})
    usage["prompt_tokens"] = usage.get("prompt_tokens", 0) + getattr(result, "prompt_tokens", 0)
    usage["completion_tokens"] = usage.get("completion_tokens", 0) + getattr(
        result, "completion_tokens", 0
    )
    usage["total_tokens"] = usage.get("total_tokens", 0) + getattr(result, "total_tokens", 0)
    if getattr(result, "used_fallback", False) or getattr(result, "error", None):
        state["used_fallback"] = True


def _money(value: float) -> str:
    return f"${value:,.0f}"


def _facts(payload: dict[str, Any]) -> str:
    return json.dumps(payload, default=str, indent=2)[:12000]


# --------------------------------------------------------------------------- #
# 1. Intent / context analysis
# --------------------------------------------------------------------------- #
_INTENT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("diagnose_decline", ("why", "drop", "down", "fell", "declin", "losing", "worse", "slow")),
    ("find_opportunity", ("opportunit", "grow", "improve", "should i do", "biggest", "upside")),
    ("review_insight", ("review", "complain", "feedback", "rating", "unhappy")),
    ("competitor_insight", ("competitor", "rival", "nearby", "compare", "market")),
    ("product_performance", ("product", "item", "menu", "selling", "sku")),
    ("customer_insight", ("customer", "retention", "repeat", "churn", "loyal")),
    ("experiment_status", ("experiment", "test", "result", "lift", "roi", "campaign")),
    ("launch_action", ("launch", "run it", "approve", "start the", "go ahead")),
    ("daily_briefing", ("today", "briefing", "summary", "how am i", "overview")),
)


def _classify_heuristically(question: str) -> IntentClassification:
    text = question.lower()
    intent = "general_question"
    for candidate, keywords in _INTENT_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            intent = candidate
            break
    diagnostic = intent in ("diagnose_decline", "find_opportunity")
    return IntentClassification(
        intent=intent,  # type: ignore[arg-type]
        confidence=0.6,
        needs_reviews=diagnostic or intent == "review_insight",
        needs_market=diagnostic or intent == "competitor_insight",
        needs_products=diagnostic or intent == "product_performance",
        rationale="Keyword routing (deterministic fallback).",
    )


async def intake(state: GraphState) -> GraphState:
    question = state.get("question") or "What is my biggest growth opportunity?"
    fallback = _classify_heuristically(question)

    if state.get("workflow") == "investigate":
        # An explicit investigation always fans out to every specialist.
        fallback.intent = "diagnose_decline"  # type: ignore[assignment]
        fallback.needs_reviews = True
        fallback.needs_market = True
        fallback.needs_products = True
        classification = fallback
    elif llm_service.enabled:
        classification, result = await llm_service.structured(
            system=prompts.INTENT_CLASSIFIER,
            user=f"Merchant question: {question}",
            schema=IntentClassification,
            fallback=fallback,
            trace=state["ctx"].trace,
            trace_name="intent_classification",
            max_tokens=400,
        )
        _track_usage(state, result)
    else:
        classification = fallback
        state["used_fallback"] = True

    state["intent"] = classification
    state["needs_reviews"] = classification.needs_reviews
    state["needs_market"] = classification.needs_market

    # What has this system already concluded for this merchant? Recall is
    # bounded and fails to an empty list, so this can only ever add context -
    # the run below is identical whether memory is off, empty or slow.
    ctx = state["ctx"]
    recalled = await memory_store.recall(ctx.merchant_id, question)
    state["memory"] = [hit.as_dict() for hit in recalled]
    if recalled:
        _step(
            state,
            node="recall",
            agent=AgentName.ORCHESTRATOR,
            action="Checked what we already know about this merchant",
            result=(
                f"Recalled {len(recalled)} prior conclusion"
                f"{'s' if len(recalled) != 1 else ''} from long-term memory."
            ),
            decision="memory_hit",
            evidence=[
                {"label": hit.kind or hit.source, "value": hit.text[:280]} for hit in recalled[:3]
            ],
        )

    _step(
        state,
        node="intake",
        agent=AgentName.ORCHESTRATOR,
        action=f'Interpreted the request: "{question[:160]}"',
        result=(
            f"Routed as '{classification.intent}'. "
            f"Specialists engaged: "
            f"{'reviews' if classification.needs_reviews else ''}"
            f"{', market' if classification.needs_market else ''}".strip(", ")
            or "core analytics only"
        ),
        decision=f"intent={classification.intent}",
    )
    return state


# --------------------------------------------------------------------------- #
# 2. Growth Scientist - gather the computed facts
# --------------------------------------------------------------------------- #
async def growth_scientist(state: GraphState) -> GraphState:
    days = state.get("days", 30)

    metrics = await _call(state, "get_growth_metrics", days=days)
    segments = await _call(state, "get_customer_segments", days=days)
    opportunities = await _call(state, "detect_growth_opportunities", days=days)
    anomalies = await _call(state, "detect_anomalies", days=days)

    state["metrics"] = metrics
    state["segments"] = segments
    state["opportunities"] = opportunities

    headline = metrics.get("headline", {})
    revenue = headline.get("revenue", {})
    worst_segment = None
    rows = segments.get("segments") or []
    scored = [r for r in rows if r.get("revenue_change_pct") is not None]
    if scored:
        worst_segment = min(scored, key=lambda r: r["revenue_change_pct"])

    evidence: list[dict[str, Any]] = []
    if revenue.get("change_pct") is not None:
        evidence.append(
            {
                "metric": "Revenue",
                "value": _money(revenue.get("value", 0)),
                "change": f"{revenue['change_pct']:+.1f}%",
                "source": "analytics",
                "reference": "dashboard",
            }
        )
    if worst_segment:
        evidence.append(
            {
                "metric": f"{worst_segment['label']} revenue",
                "value": _money(worst_segment["revenue"]),
                "change": f"{worst_segment['revenue_change_pct']:+.1f}%",
                "source": "analytics",
                "detail": (
                    f"Repeat customers in this slot "
                    f"{worst_segment.get('repeat_customers_change_pct', 0):+.1f}%."
                ),
                "reference": f"customers?daypart={worst_segment['daypart']}",
            }
        )
        if worst_segment.get("service_minutes_change_pct"):
            evidence.append(
                {
                    "metric": f"{worst_segment['label']} service time",
                    "value": f"{worst_segment.get('avg_service_minutes', 0):.1f} min",
                    "change": f"{worst_segment['service_minutes_change_pct']:+.1f}%",
                    "source": "analytics",
                    "reference": "dashboard",
                }
            )
    state.setdefault("evidence", []).extend(evidence)

    detected = opportunities.get("opportunities") or []
    result_text = (
        f"Revenue {revenue.get('change_pct', 0):+.1f}%. "
        f"{len(detected)} opportunities worth "
        f"{_money(opportunities.get('total_value_monthly', 0))}/month. "
        f"{len(anomalies.get('anomalies') or [])} anomalies flagged."
    )
    _step(
        state,
        node="growth_scientist",
        agent=AgentName.GROWTH_SCIENTIST,
        action="Computed the period metrics, segmented them and ran opportunity detection",
        result=result_text,
        evidence=evidence,
    )
    return state


# --------------------------------------------------------------------------- #
# 3. Review Intelligence
# --------------------------------------------------------------------------- #
async def review_intelligence(state: GraphState) -> GraphState:
    days = state.get("days", 30)
    summary = await _call(state, "get_review_summary", days=days)
    state["reviews"] = summary

    emerging = summary.get("emerging_complaints") or []
    quotes: dict[str, Any] = {}
    if emerging:
        quotes = await _call(
            state,
            "search_reviews",
            query=f"{emerging[0]['label']} complaints",
            topic=emerging[0]["topic"],
            limit=4,
        )

    fallback = ReviewInsight(
        headline=(
            f"{emerging[0]['label']} complaints are rising ({emerging[0]['rate_change_pct']:+.0f}% "
            "per order)."
            if emerging
            else "No emerging complaints in this period."
        ),
        emerging_complaints=[c["label"] for c in emerging],
        positive_themes=[t["label"] for t in (summary.get("positive_themes") or [])],
        interpretation=(
            "Complaint rates are normalised per 100 orders, so this is a genuine rise in how "
            "often customers complain rather than an artefact of order volume."
        ),
        evidence=[
            EvidenceItem(
                metric=f"{c['label']} complaints",
                value=f"{c['negative_reviews']} reviews",
                change=f"{c['rate_change_pct']:+.0f}%",
                source="reviews",
                reference=f"reviews?topic={c['topic']}",
            )
            for c in emerging[:3]
        ],
    )

    insight = fallback
    if llm_service.enabled and summary:
        insight, result = await llm_service.structured(
            system=prompts.REVIEW_AGENT,
            user=(
                "Review data (already aggregated):\n"
                f"{_facts(summary)}\n\n"
                f"Representative customer wording:\n{_facts(quotes)}"
            ),
            schema=ReviewInsight,
            fallback=fallback,
            trace=state["ctx"].trace,
            trace_name="review_intelligence",
        )
        _track_usage(state, result)
    else:
        state["used_fallback"] = True

    state["review_insight"] = insight
    state.setdefault("evidence", []).extend(
        item.model_dump(mode="json") for item in insight.evidence
    )
    _step(
        state,
        node="review_intelligence",
        agent=AgentName.REVIEW_INTELLIGENCE,
        action="Analysed the review corpus for emerging complaints and positive themes",
        result=insight.headline or "Review analysis complete.",
        evidence=[item.model_dump(mode="json") for item in insight.evidence],
    )
    return state


# --------------------------------------------------------------------------- #
# 4. Market Intelligence
# --------------------------------------------------------------------------- #
async def market_intelligence(state: GraphState) -> GraphState:
    days = state.get("days", 30)
    competitors = await _call(state, "get_competitor_summary", days=days)
    signals = await _call(state, "get_external_signals", days=days)
    state["market"] = {"competitors": competitors, "signals": signals}

    gap = competitors.get("biggest_gap")
    fallback = MarketInsight(
        headline=(
            f"Competitors lead on {gap['dimension'].lower()} "
            f"({gap['competitor_avg']:.0f} versus {gap['merchant_score']:.0f})."
            if gap
            else "No material competitor gap identified."
        ),
        competitor_edge=[gap["dimension"]] if gap else [],
        merchant_edge=[
            d["dimension"] for d in (competitors.get("dimensions") or []) if d.get("gap", 0) > 0
        ][:3],
        external_context=[s["title"] for s in (signals.get("signals") or [])][:3],
        interpretation=(
            "Competitor perception scores are representative benchmark data, not yet from a "
            "live competitor integration; the merchant's own scores are computed from its "
            "real review corpus."
        ),
        evidence=(
            [
                EvidenceItem(
                    metric=f"{gap['dimension']} perception",
                    value=f"{gap['merchant_score']:.0f}/100",
                    change=f"{gap['gap']:+.1f} vs competitor average",
                    source="competitors",
                    reference="competitors",
                )
            ]
            if gap
            else []
        ),
    )

    insight = fallback
    if llm_service.enabled and competitors:
        insight, result = await llm_service.structured(
            system=prompts.MARKET_AGENT,
            user=(
                f"Competitor comparison:\n{_facts(competitors)}\n\n"
                f"External signals:\n{_facts(signals)}"
            ),
            schema=MarketInsight,
            fallback=fallback,
            trace=state["ctx"].trace,
            trace_name="market_intelligence",
        )
        _track_usage(state, result)
    else:
        state["used_fallback"] = True

    state["market_insight"] = insight
    state.setdefault("evidence", []).extend(
        item.model_dump(mode="json") for item in insight.evidence
    )
    _step(
        state,
        node="market_intelligence",
        agent=AgentName.MARKET_INTELLIGENCE,
        action="Compared competitor perception and screened external market signals",
        result=insight.headline or "Market analysis complete.",
        evidence=[item.model_dump(mode="json") for item in insight.evidence],
    )
    return state


# --------------------------------------------------------------------------- #
# 5. Evidence synthesis + recommendation
# --------------------------------------------------------------------------- #
def _deterministic_recommendation(state: GraphState) -> GrowthRecommendation:
    """The answer the system gives with no LLM at all.

    Built entirely from the detector's output, so the figures, the hypothesis and
    the recommended action are identical whether or not a model is configured.
    """
    detected = (state.get("opportunities") or {}).get("opportunities") or []
    evidence = [EvidenceItem.model_validate(e) for e in state.get("evidence", [])[:8]]

    if not detected:
        headline = (state.get("metrics") or {}).get("headline", {})
        revenue = headline.get("revenue", {})
        return GrowthRecommendation(
            opportunity="No material opportunity detected",
            summary=(
                "Revenue is "
                + (f"{revenue.get('change_pct', 0):+.1f}% " if revenue else "")
                + "and no segment is moving far enough from the rest of the business to act on."
            ),
            evidence=evidence,
            hypothesis="",
            recommended_action="Keep monitoring. Re-run detection after the next trading week.",
            estimated_impact=0.0,
            confidence=0.5,
            risk="low",
            requires_approval=False,
        )

    top = detected[0]
    return GrowthRecommendation(
        opportunity=top["title"],
        summary=top["summary"],
        evidence=[EvidenceItem.model_validate(e) for e in (top.get("evidence") or [])[:8]]
        or evidence,
        hypothesis=top.get("hypothesis", ""),
        recommended_action=top.get("recommended_action", ""),
        reasoning=(
            "A blanket discount would cut margin across customers who were never at risk and "
            "would not address the signal the evidence actually points to. A targeted test on "
            "the affected segment, with a held-out control, measures whether the intervention "
            "works before it is rolled out."
        ),
        estimated_impact=float(top.get("estimated_value_monthly", 0)),
        confidence=float(top.get("confidence", 0.6)),
        risk="medium",
        requires_approval=True,
        action_key="create_targeted_experiment",
        alternatives_considered=[
            "Blanket percentage discount to all customers",
            "Do nothing and continue monitoring",
        ],
    )


async def synthesize(state: GraphState) -> GraphState:
    """Combine every specialist's evidence into one recommendation."""
    fallback = _deterministic_recommendation(state)

    recommendation = fallback
    if llm_service.enabled:
        payload = {
            "computed_metrics": state.get("metrics"),
            "segments": state.get("segments"),
            "detected_opportunities": (state.get("opportunities") or {}).get("opportunities", [])[
                :3
            ],
            "review_evidence": (
                state["review_insight"].model_dump(mode="json")
                if state.get("review_insight")
                else None
            ),
            "market_evidence": (
                state["market_insight"].model_dump(mode="json")
                if state.get("market_insight")
                else None
            ),
            "merchant_question": state.get("question"),
            "prior_conclusions": [
                item.get("text", "") for item in (state.get("memory") or [])[:5]
            ],
            "locked_values": {
                "estimated_impact": fallback.estimated_impact,
                "confidence": fallback.confidence,
            },
        }
        recommendation, result = await llm_service.structured(
            system=prompts.GROWTH_SCIENTIST,
            user=(
                "Every figure below is already computed. Use them exactly as given.\n\n"
                f"{_facts(payload)}"
                + (
                    f"\n\n{recalled_context}"
                    if (
                        recalled_context := agent_memory.format_for_prompt(
                            state.get("memory") or []
                        )
                    )
                    else ""
                )
            ),
            schema=GrowthRecommendation,
            fallback=fallback,
            trace=state["ctx"].trace,
            trace_name="growth_recommendation",
            max_tokens=1600,
        )
        _track_usage(state, result)
        # The model may only phrase; the money and the confidence stay deterministic.
        recommendation.estimated_impact = fallback.estimated_impact
        recommendation.confidence = fallback.confidence
        recommendation.requires_approval = fallback.requires_approval
        if not recommendation.evidence:
            recommendation.evidence = fallback.evidence
    else:
        state["used_fallback"] = True

    state["recommendation"] = recommendation
    _step(
        state,
        node="synthesize",
        agent=AgentName.GROWTH_SCIENTIST,
        action="Synthesised the evidence into a single recommendation",
        result=(
            f"{recommendation.opportunity} - {_money(recommendation.estimated_impact)}/month at "
            f"{recommendation.confidence:.0%} confidence."
        ),
        decision=recommendation.recommended_action[:200],
        evidence=[item.model_dump(mode="json") for item in recommendation.evidence],
    )
    return state


# --------------------------------------------------------------------------- #
# 6. Approval gate
# --------------------------------------------------------------------------- #
async def approval_gate(state: GraphState) -> GraphState:
    """Stop before anything financially consequential happens.

    The graph deliberately ends here. Execution resumes only through the approval
    endpoint, driven by a permitted human, so an approval is always on record.
    """
    recommendation = state.get("recommendation")
    requires = bool(recommendation and recommendation.requires_approval)
    _step(
        state,
        node="approval_gate",
        agent=AgentName.ACTION,
        action="Checked whether the recommended action needs merchant approval",
        result=(
            "This action is financially consequential, so it is held for merchant approval. "
            "Nothing has been created, sent or charged."
            if requires
            else "No approval needed - this is an analysis-only result."
        ),
        decision="AWAITING_APPROVAL" if requires else "NO_ACTION_REQUIRED",
    )
    return state


# --------------------------------------------------------------------------- #
# 7. Respond
# --------------------------------------------------------------------------- #
async def respond(state: GraphState) -> GraphState:
    recommendation = state.get("recommendation")
    intent = state.get("intent")

    if recommendation and recommendation.estimated_impact > 0:
        deterministic_answer = (
            f"{recommendation.summary}\n\n"
            f"Opportunity: {recommendation.opportunity} - "
            f"{_money(recommendation.estimated_impact)}/month at "
            f"{recommendation.confidence:.0%} confidence.\n"
            f"Recommended: {recommendation.recommended_action}"
        )
    elif recommendation:
        deterministic_answer = recommendation.summary
    else:
        deterministic_answer = "I could not complete the analysis for this period."

    followups = [
        "Show me the evidence behind this",
        "What happens if I do nothing?",
        "Launch the recommended experiment",
    ]

    answer = deterministic_answer
    if llm_service.enabled and state.get("workflow") == "ask":
        fallback = MerchantAnswer(answer=deterministic_answer, suggested_followups=followups)
        payload = {
            "question": state.get("question"),
            "recommendation": recommendation.model_dump(mode="json") if recommendation else None,
            "metrics": (state.get("metrics") or {}).get("headline"),
            "segments": (state.get("segments") or {}).get("segments"),
            "reviews": state.get("reviews"),
        }
        merchant_answer, result = await llm_service.structured(
            system=prompts.MERCHANT_AGENT,
            user=f"{_facts(payload)}",
            schema=MerchantAnswer,
            fallback=fallback,
            trace=state["ctx"].trace,
            trace_name="merchant_answer",
            max_tokens=900,
        )
        _track_usage(state, result)
        answer = merchant_answer.answer
        followups = merchant_answer.suggested_followups or followups

    state["answer"] = answer
    state["followups"] = followups[:3]
    _step(
        state,
        node="respond",
        agent=AgentName.MERCHANT,
        action="Composed the reply for the merchant",
        result=answer[:400],
        decision=(intent.intent if intent else None),
    )
    return state
