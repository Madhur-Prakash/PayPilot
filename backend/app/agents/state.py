"""Shared state for the LangGraph growth workflow."""

from __future__ import annotations

import uuid
from typing import Any, TypedDict

from app.schemas.agent import (
    GrowthRecommendation,
    IntentClassification,
    MarketInsight,
    MeasurementVerdict,
    ReviewInsight,
)
from app.tools.base import ToolContext


class GraphState(TypedDict, total=False):
    """State threaded through every node.

    ``ctx`` carries the merchant scope, the caller's permissions and the trace, so
    a node can never act outside what the request was authorised to do.

    Channel semantics: every key is last-value-wins. Nodes accumulate into the
    state they receive and return it whole, which is correct because the graph is
    strictly sequential - ``growth_scientist`` routes to exactly one successor.

    If a genuinely concurrent fan-out is ever added, the accumulating keys
    (``steps``, ``tools_used``, ``evidence``) must switch to ``Annotated[list,
    operator.add]`` reducers *and* the nodes must return only their own delta.
    Doing one without the other silently duplicates every entry.
    """

    # ---- request ----
    ctx: ToolContext
    question: str
    workflow: str
    days: int
    opportunity_id: uuid.UUID | None
    channel: str

    # ---- routing ----
    intent: IntentClassification | None
    needs_reviews: bool
    needs_market: bool

    # ---- recalled from long-term memory (may be empty; never required) ----
    memory: list[dict[str, Any]]

    # ---- gathered facts (all deterministic) ----
    metrics: dict[str, Any]
    segments: dict[str, Any]
    products: dict[str, Any]
    opportunities: dict[str, Any]
    reviews: dict[str, Any]
    market: dict[str, Any]
    experiments: dict[str, Any]

    # ---- agent outputs ----
    review_insight: ReviewInsight | None
    market_insight: MarketInsight | None
    recommendation: GrowthRecommendation | None
    verdict: MeasurementVerdict | None
    answer: str
    followups: list[str]

    # ---- bookkeeping ----
    evidence: list[dict[str, Any]]
    steps: list[dict[str, Any]]
    tools_used: list[str]
    used_fallback: bool
    token_usage: dict[str, Any]
    error: str | None


def new_state(
    *,
    ctx: ToolContext,
    question: str,
    workflow: str,
    days: int = 30,
    opportunity_id: uuid.UUID | None = None,
    channel: str = "web",
) -> GraphState:
    return GraphState(
        ctx=ctx,
        question=question,
        workflow=workflow,
        days=days,
        opportunity_id=opportunity_id,
        channel=channel,
        intent=None,
        needs_reviews=False,
        needs_market=False,
        metrics={},
        segments={},
        products={},
        opportunities={},
        reviews={},
        market={},
        experiments={},
        memory=[],
        review_insight=None,
        market_insight=None,
        recommendation=None,
        verdict=None,
        answer="",
        followups=[],
        evidence=[],
        steps=[],
        tools_used=[],
        used_fallback=False,
        token_usage={},
        error=None,
    )
