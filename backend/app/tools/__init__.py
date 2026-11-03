"""Agent tool registry.

Importing this package registers every tool. Import it (not the individual
modules) wherever the registry is needed.
"""

from __future__ import annotations

from app.tools import actions, analytics, intelligence  # noqa: F401  (registration side effect)
from app.tools.base import ToolContext, ToolRegistry, ToolResult, ToolSpec, registry

#: Tool sets per agent. Keeping these explicit stops one agent from reaching for
#: another's capabilities just because the model felt like it.
GROWTH_SCIENTIST_TOOLS: list[str] = [
    "get_growth_metrics",
    "get_sales_summary",
    "get_revenue_trend",
    "get_customer_segments",
    "get_customer_metrics",
    "get_product_performance",
    "analyze_product_mix",
    "detect_anomalies",
    "detect_growth_opportunities",
    "calculate_opportunity_value",
    "get_growth_graph",
    "get_growth_allocation",
]

REVIEW_AGENT_TOOLS: list[str] = ["get_review_summary", "search_reviews"]

MARKET_AGENT_TOOLS: list[str] = ["get_competitor_summary", "get_external_signals"]

ACTION_AGENT_TOOLS: list[str] = [
    "create_customer_segment",
    "create_campaign",
]

EXPERIMENT_AGENT_TOOLS: list[str] = [
    "create_experiment",
    "list_active_experiments",
]

MEASUREMENT_AGENT_TOOLS: list[str] = ["get_experiment_results", "list_active_experiments"]

MERCHANT_AGENT_TOOLS: list[str] = [
    "get_sales_summary",
    "get_customer_segments",
    "get_product_performance",
    "get_review_summary",
    "get_competitor_summary",
    "get_inventory_status",
    "get_external_signals",
    "get_top_opportunity",
    "list_active_experiments",
    "get_experiment_results",
    "get_growth_allocation",
]

#: Everything the voice assistant may reach, via the same backend agents.
VOICE_TOOLS: list[str] = [
    "get_sales_summary",
    "get_top_opportunity",
    "list_active_experiments",
    "get_experiment_results",
    "get_growth_allocation",
]

__all__ = [
    "ACTION_AGENT_TOOLS",
    "EXPERIMENT_AGENT_TOOLS",
    "GROWTH_SCIENTIST_TOOLS",
    "MARKET_AGENT_TOOLS",
    "MEASUREMENT_AGENT_TOOLS",
    "MERCHANT_AGENT_TOOLS",
    "REVIEW_AGENT_TOOLS",
    "VOICE_TOOLS",
    "ToolContext",
    "ToolRegistry",
    "ToolResult",
    "ToolSpec",
    "registry",
]
