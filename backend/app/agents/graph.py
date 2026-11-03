"""The LangGraph growth workflow.

    START
      -> intake (intent / context analysis)
      -> growth_scientist              (deterministic metrics + opportunity detection)
      -> review_intelligence *         (conditional fan-out)
      -> market_intelligence *         (conditional fan-out)
      -> synthesize                    (evidence -> structured recommendation)
      -> approval_gate                 (human approval required for money-moving actions)
      -> respond
      -> END

The graph deliberately terminates at the approval gate for anything financially
consequential. Execution (campaign, experiment, measurement) resumes through the
approval endpoint so a human decision is always on record - it is not a path the
model can take on its own.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.nodes import (
    approval_gate,
    growth_scientist,
    intake,
    market_intelligence,
    respond,
    review_intelligence,
    synthesize,
)
from app.agents.state import GraphState
from app.core.logging import get_logger

log = get_logger(__name__)


def _route_after_growth(state: GraphState) -> str:
    if state.get("needs_reviews"):
        return "review_intelligence"
    if state.get("needs_market"):
        return "market_intelligence"
    return "synthesize"


def _route_after_reviews(state: GraphState) -> str:
    return "market_intelligence" if state.get("needs_market") else "synthesize"


def build_graph() -> Any:
    """Compile the growth workflow."""
    builder: StateGraph = StateGraph(GraphState)

    builder.add_node("intake", intake)
    builder.add_node("growth_scientist", growth_scientist)
    builder.add_node("review_intelligence", review_intelligence)
    builder.add_node("market_intelligence", market_intelligence)
    builder.add_node("synthesize", synthesize)
    builder.add_node("approval_gate", approval_gate)
    builder.add_node("respond", respond)

    builder.add_edge(START, "intake")
    builder.add_edge("intake", "growth_scientist")

    builder.add_conditional_edges(
        "growth_scientist",
        _route_after_growth,
        {
            "review_intelligence": "review_intelligence",
            "market_intelligence": "market_intelligence",
            "synthesize": "synthesize",
        },
    )
    builder.add_conditional_edges(
        "review_intelligence",
        _route_after_reviews,
        {"market_intelligence": "market_intelligence", "synthesize": "synthesize"},
    )
    builder.add_edge("market_intelligence", "synthesize")
    builder.add_edge("synthesize", "approval_gate")
    builder.add_edge("approval_gate", "respond")
    builder.add_edge("respond", END)

    compiled = builder.compile()
    log.info("agent_graph_compiled", nodes=7)
    return compiled


@lru_cache(maxsize=1)
def get_graph() -> Any:
    """Compile once per process - building the graph is not free."""
    return build_graph()
