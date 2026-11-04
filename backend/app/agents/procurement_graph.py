"""The LangGraph procurement workflow.

    START
      -> inventory_monitoring      (Inventory Intelligence: scan stock + demand)
      -> procurement_requirement   (deterministic policy: ceiling, budget, rounds)
      -> supplier_discovery + rfq  (Buyer Agent -> supplier agents, signed messages)
      -> supplier_responses        (independent quotes from private policies)
      -> negotiation  <-+          (rounds until every session is locked or the limit)
            |-----------+
      -> evaluation                (validation + deterministic scoring)
      -> approval_gate             (ApprovalRequest raised; THE GRAPH ENDS HERE)
      -> END

Purchase order, invoice, payment, receiving, matching, reconciliation and supplier
learning happen after a human approves, through authenticated, permission-checked
endpoints - never as graph edges a model could traverse.

The nodes are thin: each delegates to ``NegotiationService``, which records an
agent step for every stage, so this graph and the step-by-step UI produce the same
trace.
"""

from __future__ import annotations

import uuid
from functools import lru_cache
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.core.logging import get_logger
from app.db.models.inventory import InventoryItem
from app.db.models.supply import ProcurementStatus
from app.services.supply.demand import InventoryIntelligence
from app.services.supply.negotiation import NegotiationService

log = get_logger(__name__)


class ProcurementState(TypedDict, total=False):
    service: NegotiationService
    inventory_item_id: uuid.UUID | None
    quantity: Any
    request_id: uuid.UUID | None
    rounds: int
    stages: list[str]
    outcome: str
    error: str | None


async def inventory_monitoring(state: ProcurementState) -> ProcurementState:
    service = state["service"]
    if state.get("inventory_item_id") is None:
        scan = await InventoryIntelligence(service.session, service.merchant_id).scan()
        candidates = [a for a in scan if a.stockout_risk and not a.open_request_reference]
        if not candidates:
            return {**state, "outcome": "no_action", "stages": [*state.get("stages", []), "inventory_monitoring"]}
        state = {**state, "inventory_item_id": uuid.UUID(candidates[0].inventory_item_id)}
    return {**state, "stages": [*state.get("stages", []), "inventory_monitoring"]}


async def procurement_requirement(state: ProcurementState) -> ProcurementState:
    service = state["service"]
    item = await service.session.get(InventoryItem, state["inventory_item_id"])
    if item is None or item.merchant_id != service.merchant_id:
        raise BadRequestError("Inventory item not found.")
    request = await service.create_request(
        inventory_item_id=item.id, quantity=state.get("quantity"), source="AGENT"
    )
    return {**state, "request_id": request.id, "stages": [*state["stages"], "procurement_requirement"]}


async def sourcing(state: ProcurementState) -> ProcurementState:
    """Supplier discovery, RFQ and independent quotes."""
    result = await state["service"].advance(state["request_id"])
    return {**state, "stages": [*state["stages"], result["stage"]]}


async def negotiation(state: ProcurementState) -> ProcurementState:
    result = await state["service"].advance(state["request_id"])
    return {**state, "rounds": state.get("rounds", 0) + 1, "stages": [*state["stages"], result["stage"]],
            "outcome": result["status"]}


def _after_monitoring(state: ProcurementState) -> str:
    return END if state.get("outcome") == "no_action" else "procurement_requirement"


def _after_negotiation(state: ProcurementState) -> str:
    # ``advance`` evaluates and raises the approval once rounds are exhausted.
    if state.get("outcome") in (ProcurementStatus.NEGOTIATING,) and state.get("rounds", 0) <= settings.procurement_max_negotiation_rounds + 1:
        return "negotiation"
    return "approval_gate"


async def approval_gate(state: ProcurementState) -> ProcurementState:
    request = await state["service"].request(state["request_id"])
    return {**state, "outcome": request.status, "stages": [*state["stages"], "approval_gate"]}


def build_procurement_graph() -> Any:
    builder: StateGraph = StateGraph(ProcurementState)
    builder.add_node("inventory_monitoring", inventory_monitoring)
    builder.add_node("procurement_requirement", procurement_requirement)
    builder.add_node("sourcing", sourcing)
    builder.add_node("negotiation", negotiation)
    builder.add_node("approval_gate", approval_gate)

    builder.add_edge(START, "inventory_monitoring")
    builder.add_conditional_edges("inventory_monitoring", _after_monitoring,
                                  {"procurement_requirement": "procurement_requirement", END: END})
    builder.add_edge("procurement_requirement", "sourcing")
    builder.add_edge("sourcing", "negotiation")
    builder.add_conditional_edges("negotiation", _after_negotiation,
                                  {"negotiation": "negotiation", "approval_gate": "approval_gate"})
    builder.add_edge("approval_gate", END)
    compiled = builder.compile()
    log.info("procurement_graph_compiled", nodes=5)
    return compiled


@lru_cache(maxsize=1)
def get_procurement_graph() -> Any:
    return build_procurement_graph()


async def run_procurement_autopilot(
    service: NegotiationService, *, inventory_item_id: uuid.UUID | None = None, quantity: Any = None
) -> ProcurementState:
    """Run Inventory Intelligence -> negotiation -> approval gate for one item
    (or the item most at risk when none is given)."""
    state: ProcurementState = {
        "service": service,
        "inventory_item_id": inventory_item_id,
        "quantity": quantity,
        "request_id": None,
        "rounds": 0,
        "stages": [],
        "outcome": "",
        "error": None,
    }
    return await get_procurement_graph().ainvoke(state, {"recursion_limit": 25})
