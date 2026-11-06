"""Agent endpoints: ask, investigate, approve, measure, and the trace UI."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import Field

from app.agents.orchestrator import GrowthOrchestrator
from app.api.deps import DbSession, Principal, require_permission
from app.core.exceptions import NotFoundError
from app.core.permissions import Permission
from app.db.models.agent import AgentName, AgentWorkflow
from app.repositories.agent import AgentRunRepository
from app.schemas.agent import (
    AgentActivityFeed,
    AgentActivityItem,
    AgentAskRequest,
    AgentRunDetail,
    AgentRunResponse,
    AgentStepOut,
    ApprovalOutcome,
    ApproveActionRequest,
    GrowthRecommendation,
    InvestigateRequest,
    ToolCallOut,
)
from app.schemas.campaign import ExperimentSummary
from app.schemas.common import APIResponse, SchemaBase
from app.tools import registry

router = APIRouter(prefix="/agents", tags=["agents"])


def _to_detail(run, tools_used: list[str]) -> AgentRunDetail:
    recommendation = None
    if run.output:
        try:
            recommendation = GrowthRecommendation.model_validate(run.output)
        except Exception:
            recommendation = None
    return AgentRunDetail(
        id=run.id,
        agent_name=run.agent_name,
        agent_label=AgentName.LABELS.get(run.agent_name, run.agent_name),
        workflow=run.workflow,
        status=run.status,
        intent=run.intent,
        channel=run.channel,
        input_text=run.input_text,
        summary=run.summary,
        output=run.output or {},
        decision=run.decision,
        confidence=float(run.confidence) if run.confidence is not None else None,
        requires_approval=run.requires_approval,
        opportunity_id=run.opportunity_id,
        campaign_id=run.campaign_id,
        experiment_id=run.experiment_id,
        trace_id=run.trace_id,
        trace_url=run.trace_url,
        model=run.model,
        used_fallback=run.used_fallback,
        duration_ms=run.duration_ms,
        total_tokens=run.total_tokens,
        error=run.error,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
        steps=[
            AgentStepOut(
                id=s.id,
                sequence=s.sequence,
                node=s.node,
                agent_name=s.agent_name,
                agent_label=AgentName.LABELS.get(s.agent_name, s.agent_name),
                action=s.action,
                result=s.result,
                decision=s.decision,
                status=s.status,
                evidence=s.evidence or [],
                duration_ms=s.duration_ms,
                error=s.error,
            )
            for s in sorted(run.steps, key=lambda s: s.sequence)
        ],
        tool_calls=[
            ToolCallOut(
                id=t.id,
                sequence=t.sequence,
                tool_name=t.tool_name,
                agent_name=t.agent_name,
                arguments=t.arguments or {},
                result_summary=t.result_summary,
                status=t.status,
                duration_ms=t.duration_ms,
                error=t.error,
            )
            for t in sorted(run.tool_calls, key=lambda t: t.sequence)
        ],
        tools_used=tools_used,
        recommendation=recommendation,
    )


async def _load_detail(session, merchant_id, run_id, tools_used: list[str]) -> AgentRunDetail:
    """Re-read the run with steps and tool calls eagerly loaded.

    The object the orchestrator returns was built during the run, so its
    collections are unloaded; touching them would trigger implicit IO on an async
    session (MissingGreenlet). One extra read keeps the handler honest.
    """
    repo = AgentRunRepository(session, merchant_id)
    run = await repo.get_with_detail(run_id)
    if run is None:
        raise NotFoundError("Agent run not found.")
    return _to_detail(run, tools_used or await repo.tools_for_run(run_id))


@router.post(
    "/ask",
    summary="Ask the Growth Scientist",
    description=(
        "Runs the LangGraph workflow: intent analysis, deterministic metric "
        "gathering, specialist fan-out, evidence synthesis and a structured "
        "recommendation. Works without an LLM key - the figures and the "
        "recommendation are deterministic either way, only the prose is simpler."
    ),
)
async def ask(
    payload: AgentAskRequest,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.AGENTS_RUN)),
) -> APIResponse[AgentRunResponse]:
    orchestrator = GrowthOrchestrator(
        session,
        merchant_id=principal.merchant_id,
        merchant_name=principal.merchant.name,
        user_id=principal.user_id,
        permissions=principal.permissions,
        actor_label=principal.label,
    )
    run, state = await orchestrator.run(
        question=payload.message,
        workflow=payload.workflow or AgentWorkflow.ASK,
        opportunity_id=payload.opportunity_id,
        channel=payload.channel,
    )
    detail = await _load_detail(session, principal.merchant_id, run.id, state.get("tools_used", []))
    recommendation = state.get("recommendation")
    return APIResponse(
        data=AgentRunResponse(
            run=detail,
            answer=state.get("answer", ""),
            recommendation=recommendation,
            opportunity_id=run.opportunity_id,
            suggested_followups=state.get("followups", []),
            requires_approval=bool(recommendation and recommendation.requires_approval),
        ),
        meta={"used_fallback": run.used_fallback, "model": run.model},
    )


@router.post(
    "/investigate",
    summary="Run a full investigation",
    description=(
        "Forces the complete fan-out: analytics, review intelligence and market "
        "intelligence, then synthesis and the approval gate."
    ),
)
async def investigate(
    payload: InvestigateRequest,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.GROWTH_RECOMMEND)),
) -> APIResponse[AgentRunResponse]:
    orchestrator = GrowthOrchestrator(
        session,
        merchant_id=principal.merchant_id,
        merchant_name=principal.merchant.name,
        user_id=principal.user_id,
        permissions=principal.permissions,
        actor_label=principal.label,
    )
    run, state = await orchestrator.run(
        question=payload.question or "Why did my revenue change, and what should I do about it?",
        workflow=AgentWorkflow.INVESTIGATE,
        days=payload.days,
        opportunity_id=payload.opportunity_id,
    )
    detail = await _load_detail(session, principal.merchant_id, run.id, state.get("tools_used", []))
    recommendation = state.get("recommendation")
    return APIResponse(
        data=AgentRunResponse(
            run=detail,
            answer=state.get("answer", ""),
            recommendation=recommendation,
            opportunity_id=run.opportunity_id,
            suggested_followups=state.get("followups", []),
            requires_approval=bool(recommendation and recommendation.requires_approval),
        )
    )


@router.post(
    "/opportunities/{opportunity_id}/approve",
    summary="Approve a recommendation and execute it",
    description=(
        "The human approval gate. On approval the Action Agent builds the segment and "
        "campaign, the Experiment Agent creates the control/test split, and the "
        "campaign is launched with simulated delivery. Requires both "
        "campaign:execute and experiment:approve."
    ),
)
async def approve_opportunity(
    opportunity_id: uuid.UUID,
    payload: ApproveActionRequest,
    session: DbSession,
    principal: Principal = Depends(
        require_permission(Permission.CAMPAIGN_EXECUTE, Permission.EXPERIMENT_APPROVE)
    ),
) -> APIResponse[ApprovalOutcome]:
    orchestrator = GrowthOrchestrator(
        session,
        merchant_id=principal.merchant_id,
        merchant_name=principal.merchant.name,
        user_id=principal.user_id,
        permissions=principal.permissions,
        actor_label=principal.label,
    )
    outcome = await orchestrator.approve_and_execute(
        opportunity_id,
        approve=payload.approve,
        note=payload.note,
        execute_now=payload.execute_now,
    )
    return APIResponse(
        data=outcome,
        meta={"simulated": True, "note": "Preview only - no real delivery or charges."},
    )


@router.post(
    "/experiments/{experiment_id}/measure",
    summary="Measurement and learning agent",
    description=(
        "Recomputes the results deterministically, decides SCALE/STOP/CONTINUE/WATCH, "
        "then records what the business learned."
    ),
)
async def measure(
    experiment_id: uuid.UUID,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.EXPERIMENT_MEASURE)),
) -> APIResponse[ExperimentSummary]:
    orchestrator = GrowthOrchestrator(
        session,
        merchant_id=principal.merchant_id,
        merchant_name=principal.merchant.name,
        user_id=principal.user_id,
        permissions=principal.permissions,
        actor_label=principal.label,
    )
    _, summary = await orchestrator.measure_and_learn(experiment_id)
    return APIResponse(data=summary)


@router.get(
    "/runs",
    summary="Agent activity feed",
    description="Recent agent runs with the tools each used and the decision it reached.",
)
async def list_runs(
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    agent_name: Annotated[str | None, Query()] = None,
    channel: Annotated[str | None, Query(pattern="^(web|voice)$")] = None,
    principal: Principal = Depends(require_permission(Permission.AGENTS_VIEW)),
) -> APIResponse[AgentActivityFeed]:
    repo = AgentRunRepository(session, principal.merchant_id)
    runs = await repo.list_recent(
        limit=limit, offset=offset, agent_name=agent_name, channel=channel
    )
    stats = await repo.stats()
    items = [
        AgentActivityItem(
            run_id=run.id,
            agent_name=run.agent_name,
            agent_label=AgentName.LABELS.get(run.agent_name, run.agent_name),
            workflow=run.workflow,
            status=run.status,
            title=run.input_text[:200] or run.summary[:200],
            channel=run.channel,
            decision=run.decision,
            confidence=float(run.confidence) if run.confidence is not None else None,
            tools_used=sorted({t.tool_name for t in run.tool_calls}),
            duration_ms=run.duration_ms,
            used_fallback=run.used_fallback,
            created_at=run.created_at,
        )
        for run in runs
    ]
    return APIResponse(
        data=AgentActivityFeed(
            items=items,
            total_runs=stats["total_runs"],
            completed_runs=stats["completed_runs"],
            failed_runs=stats["failed_runs"],
            avg_duration_ms=stats["avg_duration_ms"],
            top_tools=await repo.top_tools(),
        )
    )


@router.get(
    "/runs/{run_id}",
    summary="Agent trace",
    description=(
        "Human-readable trace: the actions taken, tools called, evidence gathered and "
        "decisions reached. Raw model reasoning is never recorded or exposed."
    ),
)
async def get_run(
    run_id: uuid.UUID,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.AGENTS_VIEW)),
) -> APIResponse[AgentRunDetail]:
    repo = AgentRunRepository(session, principal.merchant_id)
    run = await repo.get_with_detail(run_id)
    if run is None:
        raise NotFoundError("Agent run not found.")
    tools = await repo.tools_for_run(run_id)
    return APIResponse(data=_to_detail(run, tools))


@router.get(
    "/tools",
    summary="Tool catalogue",
    description="Every tool the agents can call, with the permission each requires.",
)
async def list_tools(
    principal: Principal = Depends(require_permission(Permission.AGENTS_VIEW)),
) -> APIResponse[list[dict]]:
    return APIResponse(data=registry.catalogue())


# --------------------------------------------------------------------------- #
# Merchant OS - the seven-agent orchestrator
# --------------------------------------------------------------------------- #
class ExecuteRequest(SchemaBase):
    message: str = Field(min_length=2, max_length=2000)
    agent: str | None = Field(
        default=None,
        pattern="^(business_intelligence|product_discovery|supply_intelligence|pricing_intelligence|"
        "growth_strategy|paypal_transaction)$",
        description="Force a specialist; omit to let the Orchestrator Agent decide.",
    )
    params: dict[str, Any] = Field(default_factory=dict, description="Optional structured inputs, e.g. product_ids.")


@router.post(
    "/execute",
    summary="Ask the Merchant OS (Orchestrator -> specialist agent -> approval gate)",
    description=(
        "The Orchestrator Agent routes the request to Business Intelligence, Product Discovery, Supply "
        "Intelligence, Pricing Intelligence, Growth Strategy or the PayPal Transaction Agent. Every tool call is "
        "permission-checked, traced and recorded. Nothing that moves money happens without a human approval."
    ),
)
async def execute(
    payload: ExecuteRequest,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.AGENTS_RUN)),
) -> APIResponse[dict[str, Any]]:
    from app.agents.merchant_os import MerchantOS

    params = {k: v for k, v in payload.params.items() if k in _ALLOWED_PARAMS}
    result = await MerchantOS(
        session, merchant_id=principal.merchant_id, merchant_name=principal.merchant.name,
        user_id=principal.user_id, permissions=principal.permissions, actor_label=principal.label,
    ).execute(payload.message, agent=payload.agent, params=params)
    return APIResponse(data=result)


_ALLOWED_PARAMS = {"days", "max_results", "product_id", "product_ids", "features", "limit", "max_recommendations",
                   "recommendation_id", "quantity", "unit_cost", "payee_email"}


@router.get("/catalogue", summary="The Merchant OS agents, what each does, and its tools")
async def catalogue(
    principal: Principal = Depends(require_permission(Permission.AGENTS_VIEW)),
) -> APIResponse[list[dict[str, Any]]]:
    from app.agents.merchant_os import agent_catalogue

    return APIResponse(data=agent_catalogue())


@router.get(
    "/activity",
    summary="Agent activity: agent, task, trigger, tools invoked, status, results and errors",
)
async def activity(
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 40,
    agent_name: Annotated[str | None, Query(max_length=48)] = None,
    status: Annotated[str | None, Query(max_length=24)] = None,
    principal: Principal = Depends(require_permission(Permission.AGENTS_VIEW)),
) -> APIResponse[dict[str, Any]]:
    from sqlalchemy import select

    from app.db.models.agent import AgentRun

    stmt = select(AgentRun).where(AgentRun.merchant_id == principal.merchant_id)
    if agent_name:
        stmt = stmt.where(AgentRun.agent_name == agent_name)
    if status:
        stmt = stmt.where(AgentRun.status == status)
    runs = (await session.execute(stmt.order_by(AgentRun.created_at.desc()).limit(limit))).scalars().all()
    items = []
    per_agent: dict[str, dict[str, Any]] = {}
    for run in runs:
        calls = sorted(run.tool_calls, key=lambda t: t.sequence)
        specialists = sorted({s.agent_name for s in run.steps if s.agent_name != run.agent_name})
        meta = run.metadata_json or {}
        items.append({
            "run_id": str(run.id),
            "agent_name": run.agent_name,
            "agent_label": AgentName.LABELS.get(run.agent_name, run.agent_name),
            "specialists": [AgentName.LABELS.get(s, s) for s in specialists],
            "task": run.input_text[:300],
            "trigger": meta.get("trigger") or ("voice" if run.channel == "voice" else f"{run.workflow} ({run.channel})"),
            "workflow": run.workflow,
            "status": run.status,
            "tools": [{"tool": t.tool_name, "agent": AgentName.LABELS.get(t.agent_name, t.agent_name), "status": t.status,
                       "duration_ms": t.duration_ms, "summary": t.result_summary[:300], "error": t.error} for t in calls],
            "result": run.summary[:600],
            "error": run.error,
            "requires_approval": run.requires_approval,
            "used_fallback": run.used_fallback,
            "duration_ms": run.duration_ms,
            "created_at": run.created_at.isoformat() if run.created_at else None,
        })
        for name in [run.agent_name, *specialists]:
            agg = per_agent.setdefault(name, {"agent_name": name, "label": AgentName.LABELS.get(name, name),
                                              "runs": 0, "failed": 0, "tool_calls": 0})
            agg["runs"] += 1
            agg["failed"] += int(run.status == "FAILED")
        for call in calls:
            agg = per_agent.setdefault(call.agent_name, {"agent_name": call.agent_name,
                                                         "label": AgentName.LABELS.get(call.agent_name, call.agent_name),
                                                         "runs": 0, "failed": 0, "tool_calls": 0})
            agg["tool_calls"] += 1
    return APIResponse(data={"items": items, "agents": sorted(per_agent.values(), key=lambda a: -a["runs"])})
