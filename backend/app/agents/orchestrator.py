"""Agent orchestration.

Owns everything around a graph run: the AgentRun record, the Langfuse trace, step
and tool-call persistence, error containment, and the post-approval execution
path (Action -> Experiment -> Measurement -> Learning).

Nothing here lets an agent approve its own recommendation. The approval path is
entered only from an authenticated request by a user holding the right permission.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import memory as agent_memory
from app.agents import prompts
from app.agents.graph import get_graph
from app.agents.state import GraphState, new_state
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.logging import bind_context, get_logger
from app.db.models.agent import AgentName, AgentRun, AgentRunStatus, AgentWorkflow
from app.db.models.audit import ActorType, AuditAction
from app.db.models.growth import GrowthOpportunity, OpportunityStatus
from app.db.models.merchant import Merchant
from app.integrations.groq import llm_service
from app.integrations.langfuse import tracer
from app.repositories.agent import AgentRunRepository
from app.repositories.campaign import CampaignRepository
from app.repositories.merchant import AuditLogRepository
from app.repositories.opportunity import OpportunityRepository
from app.schemas.agent import ApprovalOutcome, GrowthRecommendation, MeasurementVerdict
from app.services.campaigns.service import CampaignService
from app.services.experiments.service import ExperimentService
from app.services.experiments.simulation import simulate_experiment_traffic
from app.tools.base import ToolContext

log = get_logger(__name__)


class GrowthOrchestrator:
    def __init__(
        self,
        session: AsyncSession,
        *,
        merchant_id: uuid.UUID,
        merchant_name: str,
        user_id: uuid.UUID | None,
        permissions: frozenset[str],
        actor_label: str = "",
    ) -> None:
        self.session = session
        self.merchant_id = merchant_id
        self.merchant_name = merchant_name
        self.user_id = user_id
        self.permissions = permissions
        self.actor_label = actor_label
        self.runs = AgentRunRepository(session, merchant_id)
        self.opportunities = OpportunityRepository(session, merchant_id)
        self.audit = AuditLogRepository(session)

    # ------------------------------------------------------------------ run
    async def run(
        self,
        *,
        question: str,
        workflow: str = AgentWorkflow.INVESTIGATE,
        days: int = 30,
        opportunity_id: uuid.UUID | None = None,
        channel: str = "web",
    ) -> tuple[AgentRun, GraphState]:
        """Execute the graph, recording the run, its steps and its tool calls."""
        trace = tracer.trace(
            name=f"growth_{workflow}",
            user_id=str(self.user_id) if self.user_id else None,
            merchant_id=str(self.merchant_id),
            agent_name=AgentName.ORCHESTRATOR,
            workflow=workflow,
            input={"question": question, "days": days, "channel": channel},
            tags=[workflow, channel, settings.app_env],
        )

        run = await self.runs.start(
            agent_name=AgentName.ORCHESTRATOR,
            workflow=workflow,
            input_text=question,
            user_id=self.user_id,
            channel=channel,
            opportunity_id=opportunity_id,
            trace_id=trace.trace_id,
            trace_url=trace.url,
            model=settings.groq_model if llm_service.enabled else None,
            metadata={"days": days, "llm_enabled": llm_service.enabled},
        )
        bind_context(agent_run_id=str(run.id), trace_id=trace.trace_id)

        ctx = ToolContext(
            session=self.session,
            merchant_id=self.merchant_id,
            merchant_name=self.merchant_name,
            user_id=self.user_id,
            permissions=self.permissions,
            agent_name=AgentName.GROWTH_SCIENTIST,
            run=run,
            trace=trace,
        )
        state = new_state(
            ctx=ctx,
            question=question,
            workflow=workflow,
            days=days,
            opportunity_id=opportunity_id,
            channel=channel,
        )

        try:
            with trace.span("growth_workflow", input={"question": question}):
                final: GraphState = await get_graph().ainvoke(state)
        except Exception as exc:
            log.exception("agent_run_failed", workflow=workflow, error_type=type(exc).__name__)
            await self.runs.finish(
                run,
                status=AgentRunStatus.FAILED,
                summary="The investigation could not be completed.",
                error=f"{type(exc).__name__}: {str(exc)[:400]}",
            )
            trace.finish(output={"error": str(exc)[:400]})
            tracer.flush()
            raise

        await self._persist_steps(run, final)
        recommendation = final.get("recommendation")
        linked_opportunity = await self._link_opportunity(run, final, recommendation)

        usage = final.get("token_usage") or {}
        await self.runs.finish(
            run,
            status=(
                AgentRunStatus.AWAITING_APPROVAL
                if recommendation and recommendation.requires_approval
                else AgentRunStatus.COMPLETED
            ),
            summary=final.get("answer", "")[:4000],
            output=recommendation.model_dump(mode="json") if recommendation else {},
            decision=recommendation.recommended_action[:200] if recommendation else None,
            confidence=recommendation.confidence if recommendation else None,
            requires_approval=bool(recommendation and recommendation.requires_approval),
            used_fallback=bool(final.get("used_fallback")),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            opportunity_id=linked_opportunity.id if linked_opportunity else None,
        )

        trace.finish(
            output={
                "opportunity": recommendation.opportunity if recommendation else None,
                "estimated_impact": recommendation.estimated_impact if recommendation else None,
                "confidence": recommendation.confidence if recommendation else None,
            },
            tools_used=final.get("tools_used", []),
            used_fallback=bool(final.get("used_fallback")),
        )
        tracer.flush()

        await self.audit.record(
            action=AuditAction.AGENT_RUN,
            merchant_id=self.merchant_id,
            actor_id=self.user_id,
            actor_type=ActorType.USER if self.user_id else ActorType.SYSTEM,
            actor_label=self.actor_label,
            resource="agent_run",
            resource_id=str(run.id),
            description=f"Agent workflow '{workflow}' completed.",
            agent_run_id=run.id,
            metadata={
                "tools_used": final.get("tools_used", []),
                "used_fallback": bool(final.get("used_fallback")),
            },
        )
        # Write the conclusion to long-term memory. Queued, not awaited: building
        # the knowledge graph is an LLM pipeline, and no one should wait through
        # it to see an answer that is already computed.
        if recommendation is not None:
            agent_memory.record_recommendation(
                merchant_id=self.merchant_id,
                merchant_name=self.merchant_name,
                question=question,
                recommendation=recommendation,
            )

        log.info(
            "agent_run_complete",
            workflow=workflow,
            tools=len(final.get("tools_used", [])),
            used_fallback=bool(final.get("used_fallback")),
            duration_ms=run.duration_ms,
        )
        return run, final

    async def _persist_steps(self, run: AgentRun, state: GraphState) -> None:
        for index, step in enumerate(state.get("steps", []), start=1):
            await self.runs.add_step(
                run=run,
                sequence=index,
                node=step["node"],
                agent_name=step["agent_name"],
                action=step["action"],
                result=step.get("result", ""),
                decision=step.get("decision"),
                evidence=step.get("evidence") or [],
            )

    async def _link_opportunity(
        self,
        run: AgentRun,
        state: GraphState,
        recommendation: GrowthRecommendation | None,
    ) -> GrowthOpportunity | None:
        """Persist the detected opportunities and attach this run to the top one."""
        if not recommendation or recommendation.estimated_impact <= 0:
            return None

        from app.services.growth.detector import OpportunityDetector

        detector = OpportunityDetector(self.session, self.merchant_id)
        stored = await detector.detect_and_store(days=state.get("days", 30))
        if not stored:
            return None

        target = next((o for o in stored if o.title == recommendation.opportunity), stored[0])
        target.agent_run_id = run.id
        # Narrative fields are the model's contribution; the money is not.
        if recommendation.hypothesis:
            target.hypothesis = recommendation.hypothesis
        if recommendation.reasoning:
            target.reasoning = recommendation.reasoning
        if target.status == OpportunityStatus.DETECTED:
            target.status = OpportunityStatus.RECOMMENDED
        await self.session.flush()
        return target

    # ------------------------------------------------------------------ approve
    async def approve_and_execute(
        self,
        opportunity_id: uuid.UUID,
        *,
        approve: bool,
        note: str = "",
        execute_now: bool = True,
    ) -> ApprovalOutcome:
        """The human approval gate.

        Only reachable from an authenticated request by a user holding
        ``campaign:execute`` and ``experiment:approve``. This is where the growth
        loop resumes: Action Agent -> Experiment Agent -> Measurement Agent.
        """
        opportunity = await self.opportunities.get(opportunity_id)
        if opportunity is None:
            raise NotFoundError("Opportunity not found.")

        if not approve:
            opportunity.status = OpportunityStatus.DISMISSED
            await self.session.flush()
            await self.audit.record(
                action=AuditAction.OPPORTUNITY_DISMISSED,
                merchant_id=self.merchant_id,
                actor_id=self.user_id,
                actor_label=self.actor_label,
                resource="growth_opportunity",
                resource_id=str(opportunity.id),
                description="Opportunity rejected by merchant.",
                metadata={"note": note},
            )
            return ApprovalOutcome(
                approved=False,
                opportunity_id=opportunity.id,
                status=opportunity.status,
                message="Recommendation rejected. Nothing was created or executed.",
            )

        trace = tracer.trace(
            name="growth_execute",
            user_id=str(self.user_id) if self.user_id else None,
            merchant_id=str(self.merchant_id),
            agent_name=AgentName.ACTION,
            workflow=AgentWorkflow.EXECUTE,
            input={"opportunity": opportunity.title},
            tags=["execute", settings.app_env],
        )
        run = await self.runs.start(
            agent_name=AgentName.ACTION,
            workflow=AgentWorkflow.EXECUTE,
            input_text=f"Approved: {opportunity.title}",
            user_id=self.user_id,
            opportunity_id=opportunity.id,
            trace_id=trace.trace_id,
            trace_url=trace.url,
        )
        bind_context(agent_run_id=str(run.id))

        steps: list[str] = []
        sequence = 0
        campaigns = CampaignService(self.session, self.merchant_id)
        experiments = ExperimentService(self.session, self.merchant_id)

        # ---- Action Agent: segment + campaign -------------------------------
        segment = dict(opportunity.target_segment or {}) or {"opted_in_only": True}
        campaign_name = f"{opportunity.title} - {date.today():%b %Y}"
        campaign = await campaigns.create(
            name=campaign_name[:200],
            objective=opportunity.summary[:1000],
            offer_type="COMBO",
            offer_description=opportunity.recommended_action[:500],
            message=(
                "Your usual is waiting. Grab the Quick Combo on your next visit - ready in "
                "under 5 minutes."
            ),
            channel="paypal_app",
            estimated_impact=float(opportunity.estimated_value_monthly or 0),
            opportunity_id=opportunity.id,
            audience={**segment, "name": f"{opportunity.title} audience"},
            created_by_id=self.user_id,
            actor_label=self.actor_label or "Action Agent",
            agent_run_id=run.id,
        )
        audience = await CampaignRepository(self.session, self.merchant_id).get_audience(
            campaign.id, "FULL"
        )
        audience_size = audience.size if audience else 0
        sequence += 1
        await self.runs.add_step(
            run=run,
            sequence=sequence,
            node="action_agent",
            agent_name=AgentName.ACTION,
            action="Built the target segment and created the campaign",
            result=f"Campaign '{campaign.name}' created for {audience_size} customers.",
            decision="PENDING_APPROVAL",
        )
        steps.append(f"Created campaign '{campaign.name}' targeting {audience_size} customers")

        # ---- Merchant approval is already on record --------------------------
        await campaigns.approve(
            campaign.id,
            approve=True,
            user_id=self.user_id,  # type: ignore[arg-type]
            actor_label=self.actor_label,
            note=note or "Approved via opportunity approval.",
        )

        # ---- Experiment Agent: control / test -------------------------------
        experiment = await experiments.create(
            name=f"{opportunity.title} experiment",
            hypothesis=(
                opportunity.hypothesis
                or f"A targeted intervention will recover the segment behind '{opportunity.title}'."
            )[:1000],
            success_metric="conversion_rate",
            success_threshold_pct=10.0,
            duration_days=14,
            opportunity_id=opportunity.id,
            campaign_id=campaign.id,
            audience=segment,
            test_offer_description=opportunity.recommended_action[:500],
            unit_cost=40.0,
            created_by_id=self.user_id,
            agent_run_id=run.id,
        )
        variants = await experiments.repo.get_variants(experiment.id)
        sizes = {v.role: v.audience_size for v in variants}
        sequence += 1
        await self.runs.add_step(
            run=run,
            sequence=sequence,
            node="experiment_agent",
            agent_name=AgentName.EXPERIMENT,
            action="Created the experiment with a held-out control group",
            result=(
                f"{sizes.get('CONTROL', 0)} control and {sizes.get('TEST', 0)} test customers "
                "assigned deterministically."
            ),
            decision="CONTROLLED_TEST",
        )
        steps.append(
            f"Created experiment with {sizes.get('CONTROL', 0)} control / {sizes.get('TEST', 0)} test"
        )

        campaign_id = campaign.id
        experiment_id = experiment.id

        if execute_now:
            await experiments.approve(
                experiment.id,
                approve=True,
                user_id=self.user_id,  # type: ignore[arg-type]
                actor_label=self.actor_label,
                note=note,
            )
            await campaigns.execute(
                campaign.id,
                user_id=self.user_id,  # type: ignore[arg-type]
                actor_label=self.actor_label,
                agent_run_id=run.id,
            )
            sequence += 1
            await self.runs.add_step(
                run=run,
                sequence=sequence,
                node="action_agent",
                agent_name=AgentName.ACTION,
                action="Launched the approved campaign (no messaging provider connected)",
                result=(
                    f"Delivery preview: prepared for {audience_size} customers. No messaging "
                    "provider is connected, so no messages were sent and no funds moved."
                ),
                decision="LAUNCHED",
            )
            steps.append(f"Launched campaign to {audience_size} customers (preview only)")

            # A real experiment accrues transactions over its run. Without live traffic yet
            # we generate that window's transactions from a declared ground truth so the
            # loop can be measured now; the measurement itself is the ordinary one.
            merchant = await self.session.get(Merchant, self.merchant_id)
            if merchant is not None and merchant.is_demo:
                await simulate_experiment_traffic(
                    self.session, merchant_id=self.merchant_id, experiment=experiment
                )
                sequence += 1
                await self.runs.add_step(
                    run=run,
                    sequence=sequence,
                    node="experiment_agent",
                    agent_name=AgentName.EXPERIMENT,
                    action="Generated the experiment's trading window",
                    result=(
                        "Controlled transactions written for both arms so results "
                        "can be measured immediately. Every figure is still computed from "
                        "those rows, not asserted."
                    ),
                    decision="READY_TO_MEASURE",
                )
                steps.append("Generated the experiment trading window so results are measurable")

            opportunity.status = OpportunityStatus.RUNNING
            opportunity.campaign_id = campaign.id
            opportunity.experiment_id = experiment.id
            await self.session.flush()

        trace.event(
            "approval_executed",
            campaign_id=str(campaign_id),
            experiment_id=str(experiment_id),
            audience_size=audience_size,
        )
        await self.runs.finish(
            run,
            status=AgentRunStatus.COMPLETED,
            summary=" -> ".join(steps),
            decision="EXECUTED" if execute_now else "PREPARED",
            requires_approval=False,
            campaign_id=campaign_id,
            experiment_id=experiment_id,
            opportunity_id=opportunity.id,
        )
        trace.finish(output={"steps": steps})
        tracer.flush()

        await self.audit.record(
            action=AuditAction.AGENT_ACTION,
            merchant_id=self.merchant_id,
            actor_id=self.user_id,
            actor_label=self.actor_label,
            resource="growth_opportunity",
            resource_id=str(opportunity.id),
            description=f"Opportunity approved and executed: {opportunity.title}.",
            agent_run_id=run.id,
            metadata={"campaign_id": str(campaign_id), "experiment_id": str(experiment_id)},
        )

        # A human agreed to spend money on this. That judgement is worth more to
        # a later run than the projection that prompted it.
        agent_memory.record_approval(
            merchant_id=self.merchant_id,
            merchant_name=self.merchant_name,
            opportunity=opportunity.title,
            approved=True,
            decided_by=self.actor_label,
        )

        return ApprovalOutcome(
            approved=True,
            opportunity_id=opportunity.id,
            campaign_id=campaign_id,
            experiment_id=experiment_id,
            agent_run_id=run.id,
            status=opportunity.status,
            message=(
                "Approved. The campaign and a controlled experiment are live (simulated "
                "delivery). Results can be measured once the window has data."
            ),
            steps=steps,
        )

    # ------------------------------------------------------------------ measure
    async def measure_and_learn(
        self,
        experiment_id: uuid.UUID,
        *,
        window_start: date | None = None,
        window_end: date | None = None,
    ) -> tuple[AgentRun, Any]:
        """Measurement + Learning agent: compute results, then record the learning."""
        trace = tracer.trace(
            name="growth_measure",
            user_id=str(self.user_id) if self.user_id else None,
            merchant_id=str(self.merchant_id),
            agent_name=AgentName.MEASUREMENT,
            workflow=AgentWorkflow.MEASURE,
            input={"experiment_id": str(experiment_id)},
            tags=["measure", settings.app_env],
        )
        run = await self.runs.start(
            agent_name=AgentName.MEASUREMENT,
            workflow=AgentWorkflow.MEASURE,
            input_text=f"Measure experiment {experiment_id}",
            user_id=self.user_id,
            trace_id=trace.trace_id,
            trace_url=trace.url,
        )

        service = ExperimentService(self.session, self.merchant_id)
        summary = await service.measure(
            experiment_id,
            window_start=window_start,
            window_end=window_end,
            user_id=self.user_id,
        )

        await self.runs.add_step(
            run=run,
            sequence=1,
            node="measurement_agent",
            agent_name=AgentName.MEASUREMENT,
            action="Recomputed every result from the transaction ledger",
            result=(
                f"Control {summary.control_conversion_rate:.1f}% vs test "
                f"{summary.test_conversion_rate:.1f}% "
                f"({summary.conversion_lift_pct:+.1f}% lift). Incremental revenue "
                f"${summary.incremental_revenue:,.0f}, ROI {summary.roi:.1f}x."
            ),
            decision=summary.decision,
            evidence=[
                {
                    "metric": "Conversion lift",
                    "value": f"{summary.conversion_lift_pct:+.1f}%",
                    "source": "experiments",
                },
                {
                    "metric": "Incremental revenue",
                    "value": f"${summary.incremental_revenue:,.0f}",
                    "source": "experiments",
                },
                {
                    "metric": "Statistical significance",
                    "value": (
                        f"p={summary.p_value:.3f}"
                        if summary.p_value is not None
                        else "insufficient sample"
                    ),
                    "source": "experiments",
                },
            ],
        )

        # ---- Learning agent -------------------------------------------------
        fallback = MeasurementVerdict(
            decision=summary.decision if summary.decision != "PENDING" else "WATCH",  # type: ignore[arg-type]
            rationale=summary.decision_rationale,
            learning=(
                "A targeted intervention on the affected segment, measured against a held-out "
                "control, produced a readable result. Keep the control group in future tests - "
                "without it the lift is not attributable."
            ),
            confidence=0.8 if summary.is_significant else 0.55,
        )
        verdict = fallback
        if llm_service.enabled:
            verdict, _result = await llm_service.structured(
                system=prompts.MEASUREMENT_AGENT,
                user=(
                    "Experiment results (already computed - do not change any figure):\n"
                    f"{summary.model_dump_json(indent=2)}"
                ),
                schema=MeasurementVerdict,
                fallback=fallback,
                trace=trace,
                trace_name="measurement_verdict",
                max_tokens=900,
            )
            # The decision is computed, not chosen by the model.
            verdict.decision = fallback.decision

        await service.record_learning(experiment_id, verdict.learning)
        await self.runs.add_step(
            run=run,
            sequence=2,
            node="learning_agent",
            agent_name=AgentName.MEASUREMENT,
            action="Recorded what the business learned",
            result=verdict.learning,
            decision=verdict.decision,
        )

        await self.runs.finish(
            run,
            status=AgentRunStatus.COMPLETED,
            summary=verdict.rationale,
            output=summary.model_dump(mode="json"),
            decision=verdict.decision,
            confidence=verdict.confidence,
            experiment_id=experiment_id,
            used_fallback=not llm_service.enabled,
        )
        trace.finish(output=summary.model_dump(mode="json"))
        tracer.flush()

        # The one memory grounded in a measured result rather than a forecast.
        agent_memory.record_measurement(
            merchant_id=self.merchant_id,
            merchant_name=self.merchant_name,
            experiment_name=getattr(summary, "name", "") or str(experiment_id),
            verdict=verdict,
            metrics=summary.model_dump(mode="json").get("metrics"),
        )

        log.info(
            "experiment_measured_by_agent",
            experiment_id=str(experiment_id),
            decision=verdict.decision,
        )
        summary.learning = verdict.learning
        return run, summary


def utcnow() -> datetime:
    return datetime.now(tz=UTC)
