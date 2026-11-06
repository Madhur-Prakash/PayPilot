"""Agent tool registry.

Importing this package registers every tool. Import it (not the individual
modules) wherever the registry is needed.
"""

from __future__ import annotations

from app.tools import (  # noqa: F401  (registration side effect)
    actions,
    analytics,
    discovery,
    intelligence,
    sponsors,
    supply,
)
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

#: Supply Agents. The buyer can source and negotiate; it has no tool that moves money.
INVENTORY_AGENT_TOOLS: list[str] = ["get_stockout_risks", "get_inventory_status"]

BUYER_AGENT_TOOLS: list[str] = [
    "list_supplier_agents",
    "start_procurement",
    "run_negotiation",
    "get_procurement_status",
    "get_market_benchmark",
    "search_memory",
]

PROCUREMENT_AGENT_TOOLS: list[str] = [
    "get_procurement_overview",
    "get_procurement_status",
    "get_pending_approvals",
]

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
    "get_stockout_risks",
    "get_procurement_overview",
    "get_pending_approvals",
    "get_paypal_transaction_insights",
    "paypal_mcp_read",
    "search_evidence",
    "get_market_benchmark",
    "search_memory",
]

#: Merchant operating-system agents (see agents/merchant_os.py). None of them can move money:
#: the PayPal Transaction Agent can only *request* an approval.
BUSINESS_INTELLIGENCE_TOOLS: list[str] = [
    "get_sales_summary",
    "get_product_performance",
    "analyze_assortment",
    "get_inventory_status",
]

PRODUCT_DISCOVERY_TOOLS: list[str] = [
    "discover_products",
    "get_product_details",
    "find_similar_products",
    "compare_products",
]

SUPPLY_INTELLIGENCE_TOOLS: list[str] = [
    "analyze_assortment",
    "discover_products",
    "find_similar_products",
    "list_supply_recommendations",
]

PRICING_INTELLIGENCE_TOOLS: list[str] = [
    "get_market_price_intelligence",
    "get_market_benchmark",
]

GROWTH_STRATEGY_TOOLS: list[str] = [
    "analyze_assortment",
    "generate_supply_recommendations",
    "list_supply_recommendations",
    "get_top_opportunity",
]

PAYPAL_TRANSACTION_TOOLS: list[str] = [
    "get_payment_history",
    "get_paypal_transaction_insights",
    "request_purchase_payment",
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
    "BUSINESS_INTELLIGENCE_TOOLS",
    "BUYER_AGENT_TOOLS",
    "EXPERIMENT_AGENT_TOOLS",
    "GROWTH_SCIENTIST_TOOLS",
    "GROWTH_STRATEGY_TOOLS",
    "INVENTORY_AGENT_TOOLS",
    "MARKET_AGENT_TOOLS",
    "MEASUREMENT_AGENT_TOOLS",
    "MERCHANT_AGENT_TOOLS",
    "PAYPAL_TRANSACTION_TOOLS",
    "PRICING_INTELLIGENCE_TOOLS",
    "PROCUREMENT_AGENT_TOOLS",
    "PRODUCT_DISCOVERY_TOOLS",
    "SUPPLY_INTELLIGENCE_TOOLS",
    "REVIEW_AGENT_TOOLS",
    "VOICE_TOOLS",
    "ToolContext",
    "ToolRegistry",
    "ToolResult",
    "ToolSpec",
    "registry",
]
