"""Experiment lifecycle and measurement.

Every number on the results screen is recomputed here from the transaction ledger:
conversion, lift, incremental revenue, incremental profit, ROI and a two-proportion
z-test. The LLM is only ever asked to phrase the learning, never to produce a figure.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ApprovalRequiredError, BadRequestError, NotFoundError
from app.core.logging import get_logger
from app.db.models.audit import AuditAction
from app.db.models.experiment import (
    Experiment,
    ExperimentDecision,
    ExperimentStatus,
    VariantRole,
)
from app.db.models.growth import OpportunityStatus
from app.repositories.campaign import CampaignRepository
from app.repositories.customer import CustomerRepository
from app.repositories.experiment import ExperimentRepository
from app.repositories.merchant import AuditLogRepository
from app.repositories.opportunity import OpportunityRepository
from app.repositories.transaction import TransactionRepository
from app.schemas.campaign import ExperimentSummary

log = get_logger(__name__)

#: Conventional significance threshold. Reported as a signal, never as proof.
SIGNIFICANCE_ALPHA = 0.05
#: Lift below which an experiment is not worth scaling even if statistically clean.
MIN_MATERIAL_LIFT_PCT = 5.0


def _norm_sf(z: float) -> float:
    """Upper-tail probability of the standard normal (no SciPy dependency)."""
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def two_proportion_p_value(
    conversions_a: int, size_a: int, conversions_b: int, size_b: int
) -> float | None:
    """Two-sided two-proportion z-test.

    Returns None when either group is too small for the normal approximation to
    mean anything - better to say "not enough data" than to print a fake p-value.
    """
    if size_a < 5 or size_b < 5:
        return None
    p_a = conversions_a / size_a
    p_b = conversions_b / size_b
    pooled = (conversions_a + conversions_b) / (size_a + size_b)
    if pooled in (0.0, 1.0):
        return None
    standard_error = math.sqrt(pooled * (1 - pooled) * (1 / size_a + 1 / size_b))
    if standard_error == 0:
        return None
    z = (p_b - p_a) / standard_error
    return round(2 * _norm_sf(abs(z)), 6)


@dataclass(slots=True)
class VariantMeasurement:
    variant_id: uuid.UUID
    variant_key: str
    variant_role: str
    audience_size: int
    converted_customers: int
    conversion_rate: float
    orders: int
    revenue: float
    gross_margin: float
    avg_order_value: float
    revenue_per_customer: float
    cost: float


class ExperimentService:
    def __init__(self, session: AsyncSession, merchant_id: uuid.UUID) -> None:
        self.session = session
        self.merchant_id = merchant_id
        self.repo = ExperimentRepository(session, merchant_id)
        self.campaigns = CampaignRepository(session, merchant_id)
        self.customers = CustomerRepository(session, merchant_id)
        self.transactions = TransactionRepository(session, merchant_id)
        self.opportunities = OpportunityRepository(session, merchant_id)
        self.audit = AuditLogRepository(session)

    # ------------------------------------------------------------------ create
    async def create(
        self,
        *,
        name: str,
        hypothesis: str,
        success_metric: str = "conversion_rate",
        success_threshold_pct: float = 10.0,
        duration_days: int = 14,
        start_date: date | None = None,
        opportunity_id: uuid.UUID | None = None,
        campaign_id: uuid.UUID | None = None,
        control_split_pct: float = 50.0,
        test_offer_description: str = "",
        unit_cost: float = 0.0,
        audience: dict[str, Any] | None = None,
        created_by_id: uuid.UUID | None = None,
        agent_run_id: uuid.UUID | None = None,
        extra_arms: list[dict[str, Any]] | None = None,
    ) -> Experiment:
        """Create an experiment with a deterministically split control/test pair.

        ``extra_arms`` is the multi-arm extension for dual-market growth missions:
        each entry is ``{key, name, description, offer_description, allocation_pct,
        unit_cost}`` for one more TEST-role variant (e.g. "business", "paypal",
        "hybrid") alongside the ordinary one. Omit it and this behaves exactly as
        it always has - a plain control/test pair.
        """
        start = start_date or date.today()
        experiment = await self.repo.create(
            name=name,
            hypothesis=hypothesis,
            success_metric=success_metric,
            success_threshold_pct=success_threshold_pct,
            duration_days=duration_days,
            start_date=start,
            end_date=start + timedelta(days=duration_days - 1),
            status=ExperimentStatus.PENDING_APPROVAL,
            campaign_id=campaign_id,
            opportunity_id=opportunity_id,
            agent_run_id=agent_run_id,
            created_by_id=created_by_id,
            requires_approval=True,
            decision=ExperimentDecision.PENDING,
        )

        members = await self._resolve_audience(audience)

        arms = extra_arms or [
            {
                "key": "test",
                "name": f"Test - {test_offer_description or name}",
                "description": test_offer_description,
                "offer_description": test_offer_description,
                "allocation_pct": round(100 - control_split_pct, 2),
                "unit_cost": unit_cost,
            }
        ]
        buckets = self._split_n(members, control_split_pct, len(arms))
        control_ids = buckets[0]

        await self.repo.add_variant(
            experiment=experiment,
            key="control",
            name="Control - current experience",
            role=VariantRole.CONTROL,
            customer_ids=control_ids,
            description="No change. Baseline for comparison.",
            allocation_pct=control_split_pct,
        )
        for arm, arm_ids in zip(arms, buckets[1:], strict=True):
            await self.repo.add_variant(
                experiment=experiment,
                key=arm["key"],
                name=arm["name"][:160],
                role=VariantRole.TEST,
                customer_ids=arm_ids,
                description=arm.get("description", ""),
                offer_description=arm.get("offer_description", ""),
                allocation_pct=arm.get("allocation_pct", round(100 - control_split_pct, 2) / len(arms)),
                unit_cost=arm.get("unit_cost", 0.0),
            )

        await self.audit.record(
            action=AuditAction.EXPERIMENT_CREATED,
            merchant_id=self.merchant_id,
            actor_id=created_by_id,
            actor_type="AGENT" if agent_run_id else "USER",
            resource="experiment",
            resource_id=str(experiment.id),
            description=f"Experiment '{name}' created with {len(members)} customers.",
            agent_run_id=agent_run_id,
            metadata={
                "control": len(control_ids),
                "arms": {arm["key"]: len(ids) for arm, ids in zip(arms, buckets[1:], strict=True)},
            },
        )
        log.info(
            "experiment_created",
            experiment_id=str(experiment.id),
            control=len(control_ids),
            arms=len(arms),
        )
        return experiment

    async def _resolve_audience(self, audience: dict[str, Any] | None) -> list[uuid.UUID]:
        definition = dict(audience or {})
        definition.pop("name", None)
        customers = await self.customers.resolve_segment(**definition)
        return [customer.id for customer in customers]

    @staticmethod
    def _split(
        members: list[uuid.UUID], control_pct: float
    ) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
        """Deterministic two-way assignment. Kept for any caller still using it
        directly; ``create()`` itself now goes through ``_split_n``."""
        buckets = ExperimentService._split_n(members, control_pct, 1)
        return buckets[0], buckets[1]

    @staticmethod
    def _split_n(
        members: list[uuid.UUID], control_pct: float, arm_count: int
    ) -> list[list[uuid.UUID]]:
        """Deterministic assignment into control + ``arm_count`` equal-sized arms.

        Hashing the customer id keeps allocation stable across re-runs and free of
        ordering bias, which a simple slice of a sorted list would not be. The
        remaining ``100 - control_pct`` is split evenly across the treatment arms.
        Returns ``[control, arm_0, arm_1, ...]``.
        """
        buckets: list[list[uuid.UUID]] = [[] for _ in range(arm_count + 1)]
        control_threshold = max(0.0, min(control_pct, 100.0)) / 100.0
        for member in members:
            bucket = (int(uuid.UUID(str(member)).hex[-8:], 16) % 10_000) / 10_000
            if bucket < control_threshold:
                buckets[0].append(member)
            else:
                # Spread the remainder evenly across the treatment arms using a
                # second, independent slice of the same hash - stable and
                # order-free for the same reason the control split is.
                arm_index = int(uuid.UUID(str(member)).hex[:8], 16) % arm_count
                buckets[1 + arm_index].append(member)
        return buckets

    # ------------------------------------------------------------------ approval
    async def approve(
        self,
        experiment_id: uuid.UUID,
        *,
        approve: bool,
        user_id: uuid.UUID,
        actor_label: str = "",
        note: str = "",
    ) -> Experiment:
        experiment = await self.repo.get_with_detail(experiment_id)
        if experiment is None:
            raise NotFoundError("Experiment not found.")
        if experiment.status not in (ExperimentStatus.PENDING_APPROVAL, ExperimentStatus.DRAFT):
            raise BadRequestError(
                f"Experiment is {experiment.status} and cannot be approved again."
            )

        now = datetime.now(tz=UTC)
        if not approve:
            experiment.status = ExperimentStatus.REJECTED
            experiment.decision_rationale = note or "Rejected by merchant."
            await self.session.flush()
            await self.audit.record(
                action=AuditAction.EXPERIMENT_STOPPED,
                merchant_id=self.merchant_id,
                actor_id=user_id,
                actor_label=actor_label,
                resource="experiment",
                resource_id=str(experiment.id),
                description="Experiment rejected by merchant.",
                metadata={"note": note},
            )
            return experiment

        experiment.status = ExperimentStatus.RUNNING
        experiment.approved_by_id = user_id
        experiment.approved_at = now
        experiment.launched_at = now
        await self.session.flush()

        await self.audit.record(
            action=AuditAction.EXPERIMENT_STARTED,
            merchant_id=self.merchant_id,
            actor_id=user_id,
            actor_label=actor_label,
            resource="experiment",
            resource_id=str(experiment.id),
            description=f"Experiment '{experiment.name}' approved and launched.",
            metadata={"note": note},
        )
        log.info("experiment_launched", experiment_id=str(experiment.id))
        return experiment

    # ------------------------------------------------------------------ measure
    async def measure(
        self,
        experiment_id: uuid.UUID,
        *,
        window_start: date | None = None,
        window_end: date | None = None,
        user_id: uuid.UUID | None = None,
    ) -> ExperimentSummary:
        """Recompute every result from transactions and store the outcome."""
        experiment = await self.repo.get_with_detail(experiment_id)
        if experiment is None:
            raise NotFoundError("Experiment not found.")
        if experiment.status in (ExperimentStatus.DRAFT, ExperimentStatus.PENDING_APPROVAL):
            raise ApprovalRequiredError(
                "This experiment has not been approved, so there is nothing to measure yet."
            )

        variants = await self.repo.get_variants(experiment_id)
        control = next((v for v in variants if v.role == VariantRole.CONTROL), None)
        treatments = [v for v in variants if v.role == VariantRole.TEST]
        if control is None or not treatments:
            raise BadRequestError("Experiment is missing a control or test variant.")

        start = window_start or experiment.start_date or date.today()
        end = window_end or experiment.end_date or date.today()

        control_m = await self._measure_variant(experiment, control, start, end)
        measured_at = datetime.now(tz=UTC)
        await self.repo.upsert_result(
            experiment_id=experiment.id,
            variant_id=control.id,
            variant_key=control.key,
            variant_role=control.role,
            **_result_fields(control_m),
            measured_at=measured_at,
            window_start=start,
            window_end=end,
        )

        # One measurement per treatment arm, each compared against the same
        # control - this is what makes a 3+ arm growth mission (business / paypal /
        # hybrid) work: every arm gets its own lift, incremental revenue and ROI,
        # not just the first one. A plain 2-arm experiment has exactly one arm here
        # and behaves identically to before.
        arm_measurements: list[tuple[Any, VariantMeasurement, float | None, float | None]] = []
        for treatment in treatments:
            test_m = await self._measure_variant(experiment, treatment, start, end)
            conversion_lift = _relative_change(test_m.conversion_rate, control_m.conversion_rate)
            revenue_lift = _relative_change(
                test_m.revenue_per_customer, control_m.revenue_per_customer
            )
            # Incremental revenue is the arm's revenue minus what the *same number
            # of customers* would have produced at the control rate.
            counterfactual_revenue = control_m.revenue_per_customer * test_m.audience_size
            incremental_revenue = round(test_m.revenue - counterfactual_revenue, 2)

            control_margin_per_customer = (
                control_m.gross_margin / control_m.audience_size if control_m.audience_size else 0.0
            )
            counterfactual_margin = control_margin_per_customer * test_m.audience_size
            incremental_profit = round(test_m.gross_margin - counterfactual_margin - test_m.cost, 2)
            roi = round(incremental_revenue / test_m.cost, 4) if test_m.cost > 0 else None

            p_value = two_proportion_p_value(
                control_m.converted_customers,
                control_m.audience_size,
                test_m.converted_customers,
                test_m.audience_size,
            )
            is_significant = bool(p_value is not None and p_value < SIGNIFICANCE_ALPHA)

            await self.repo.upsert_result(
                experiment_id=experiment.id,
                variant_id=treatment.id,
                variant_key=treatment.key,
                variant_role=treatment.role,
                **_result_fields(test_m),
                conversion_lift_pct=conversion_lift,
                revenue_lift_pct=revenue_lift,
                incremental_revenue=incremental_revenue,
                incremental_profit=incremental_profit,
                roi=roi,
                p_value=p_value,
                is_significant=is_significant,
                measured_at=measured_at,
                window_start=start,
                window_end=end,
            )
            arm_measurements.append((treatment, test_m, incremental_revenue, roi))

        # The headline `ExperimentSummary` this method returns stays a plain
        # control-vs-one-arm shape for backward compatibility - every existing
        # caller and test expects that. For a single-arm experiment that arm is
        # the obvious choice; for a multi-arm one it's the highest incremental
        # revenue, so "the decision" still means something concrete rather than
        # an arbitrary pick. The full per-arm breakdown is always available via
        # `experiment.results` (`GET /experiments/{id}`), which now holds one row
        # per arm instead of just one.
        primary_treatment, test_m, incremental_revenue, roi = max(
            arm_measurements, key=lambda row: row[2]
        )
        conversion_lift = _relative_change(test_m.conversion_rate, control_m.conversion_rate)
        revenue_lift = _relative_change(test_m.revenue_per_customer, control_m.revenue_per_customer)
        control_margin_per_customer = (
            control_m.gross_margin / control_m.audience_size if control_m.audience_size else 0.0
        )
        counterfactual_margin = control_margin_per_customer * test_m.audience_size
        incremental_profit = round(test_m.gross_margin - counterfactual_margin - test_m.cost, 2)
        p_value = two_proportion_p_value(
            control_m.converted_customers,
            control_m.audience_size,
            test_m.converted_customers,
            test_m.audience_size,
        )
        is_significant = bool(p_value is not None and p_value < SIGNIFICANCE_ALPHA)

        decision, rationale = self.decide(
            conversion_lift_pct=conversion_lift,
            incremental_revenue=incremental_revenue,
            roi=roi,
            p_value=p_value,
            is_significant=is_significant,
            threshold_pct=float(experiment.success_threshold_pct or MIN_MATERIAL_LIFT_PCT),
            control_size=control_m.audience_size,
            test_size=test_m.audience_size,
        )
        if len(treatments) > 1:
            rationale = f"Best-performing arm ('{primary_treatment.name}'): {rationale}"
        experiment.decision = decision
        experiment.decision_rationale = rationale
        experiment.status = (
            ExperimentStatus.COMPLETED
            if decision in (ExperimentDecision.SCALE, ExperimentDecision.STOP)
            else ExperimentStatus.MEASURING
        )
        if experiment.status == ExperimentStatus.COMPLETED:
            experiment.completed_at = measured_at
        await self.session.flush()

        await self._sync_opportunity(experiment, decision)
        await self._sync_campaign(experiment, incremental_revenue=incremental_revenue, roi=roi)

        await self.audit.record(
            action=AuditAction.EXPERIMENT_COMPLETED,
            merchant_id=self.merchant_id,
            actor_id=user_id,
            actor_type="USER" if user_id else "SYSTEM",
            resource="experiment",
            resource_id=str(experiment.id),
            description=f"Experiment measured. Decision: {decision}.",
            metadata={
                "conversion_lift_pct": conversion_lift,
                "incremental_revenue": incremental_revenue,
                "roi": roi,
                "p_value": p_value,
            },
        )
        log.info(
            "experiment_measured",
            experiment_id=str(experiment.id),
            decision=decision,
            conversion_lift_pct=conversion_lift,
            incremental_revenue=incremental_revenue,
            roi=roi,
            p_value=p_value,
        )

        return ExperimentSummary(
            experiment_id=experiment.id,
            name=experiment.name,
            status=experiment.status,  # type: ignore[arg-type]
            hypothesis=experiment.hypothesis,
            control_conversion_rate=control_m.conversion_rate,
            test_conversion_rate=test_m.conversion_rate,
            conversion_lift_pct=conversion_lift or 0.0,
            control_revenue=control_m.revenue,
            test_revenue=test_m.revenue,
            incremental_revenue=incremental_revenue,
            incremental_profit=incremental_profit,
            roi=roi or 0.0,
            cost=test_m.cost,
            p_value=p_value,
            is_significant=is_significant,
            decision=decision,  # type: ignore[arg-type]
            decision_rationale=rationale,
            learning=experiment.learning,
            window_start=start,
            window_end=end,
        )

    async def _measure_variant(
        self, experiment: Experiment, variant: Any, start: date, end: date
    ) -> VariantMeasurement:
        member_ids = [uuid.UUID(str(cid)) for cid in (variant.customer_ids or [])]
        aggregate = await self.transactions.experiment_aggregate(
            experiment_id=experiment.id,
            variant_key=variant.key,
            customer_ids=member_ids,
            start=start,
            end=end,
        )
        size = len(member_ids)
        converted = aggregate["converted_customers"]
        revenue = aggregate["revenue"]
        orders = aggregate["orders"]
        return VariantMeasurement(
            variant_id=variant.id,
            variant_key=variant.key,
            variant_role=variant.role,
            audience_size=size,
            converted_customers=converted,
            conversion_rate=round((converted / size) * 100, 4) if size else 0.0,
            orders=orders,
            revenue=revenue,
            gross_margin=aggregate["gross_margin"],
            avg_order_value=round(revenue / orders, 2) if orders else 0.0,
            revenue_per_customer=round(revenue / size, 2) if size else 0.0,
            # Cost is only incurred where an offer was actually served.
            cost=round(float(variant.unit_cost or 0) * converted, 2),
        )

    # ------------------------------------------------------------------ decision
    @staticmethod
    def decide(
        *,
        conversion_lift_pct: float | None,
        incremental_revenue: float,
        roi: float | None,
        p_value: float | None,
        is_significant: bool,
        threshold_pct: float,
        control_size: int,
        test_size: int,
    ) -> tuple[str, str]:
        """SCALE / STOP / CONTINUE / WATCH, with the reason stated plainly."""
        if control_size < 20 or test_size < 20:
            return (
                ExperimentDecision.CONTINUE,
                (
                    f"Groups are too small to read ({control_size} control, {test_size} test). "
                    "Keep the experiment running until each arm has at least 20 customers."
                ),
            )
        lift = conversion_lift_pct or 0.0

        if lift >= threshold_pct and incremental_revenue > 0 and is_significant:
            roi_text = f" ROI is {roi:.1f}x." if roi else ""
            return (
                ExperimentDecision.SCALE,
                (
                    f"Conversion lift of {lift:+.1f}% clears the {threshold_pct:.0f}% success "
                    f"threshold, incremental revenue is ${incremental_revenue:,.0f}, and the "
                    f"difference is statistically significant (p={p_value:.3f}).{roi_text}"
                ),
            )
        if lift >= threshold_pct and incremental_revenue > 0:
            return (
                ExperimentDecision.CONTINUE,
                (
                    f"Conversion lift of {lift:+.1f}% looks promising and incremental revenue is "
                    f"${incremental_revenue:,.0f}, but the result is not yet statistically "
                    f"significant"
                    + (f" (p={p_value:.3f})" if p_value is not None else "")
                    + ". Keep running to accumulate sample."
                ),
            )
        if lift <= -MIN_MATERIAL_LIFT_PCT or incremental_revenue < 0:
            certainty = (
                f" The difference is statistically significant (p={p_value:.3f})."
                if is_significant
                else (
                    f" The difference is not statistically significant (p={p_value:.3f}), but "
                    "there is no upside to keep paying for."
                    if p_value is not None
                    else ""
                )
            )
            return (
                ExperimentDecision.STOP,
                (
                    f"The test arm underperformed control ({lift:+.1f}% conversion, "
                    f"${incremental_revenue:,.0f} incremental revenue). Stop and keep the "
                    f"current experience.{certainty}"
                ),
            )
        return (
            ExperimentDecision.WATCH,
            (
                f"Conversion lift of {lift:+.1f}% is below the {threshold_pct:.0f}% threshold and "
                "not clearly different from control. Hold, and revisit with a stronger offer."
            ),
        )

    async def _sync_opportunity(self, experiment: Experiment, decision: str) -> None:
        """Move the originating opportunity along the growth loop."""
        if not experiment.opportunity_id:
            return
        opportunity = await self.opportunities.get(experiment.opportunity_id)
        if opportunity is None:
            return
        mapping = {
            ExperimentDecision.SCALE: OpportunityStatus.SCALED,
            ExperimentDecision.STOP: OpportunityStatus.STOPPED,
            ExperimentDecision.CONTINUE: OpportunityStatus.MEASURING,
            ExperimentDecision.WATCH: OpportunityStatus.MEASURING,
        }
        opportunity.status = mapping.get(decision, OpportunityStatus.MEASURING)
        opportunity.experiment_id = experiment.id
        await self.session.flush()

    async def _sync_campaign(
        self, experiment: Experiment, *, incremental_revenue: float, roi: float | None
    ) -> None:
        """Write the measured result back onto the linked campaign.

        This is what lets the Growth Allocation Engine compare surfaces later
        (`services/growth/allocation.py`): it reads `Campaign.actual_incremental_revenue`
        and `.incremental_roi` across a merchant's past campaigns, grouped by
        `surface` - real numbers, because every one of them was written here from
        an actual measured experiment, never guessed at.
        """
        if not experiment.campaign_id:
            return
        campaign = await self.campaigns.get(experiment.campaign_id)
        if campaign is None:
            return
        campaign.actual_incremental_revenue = incremental_revenue
        campaign.incremental_roi = roi
        campaign.measurement_status = (
            "MEASURED" if experiment.status == ExperimentStatus.COMPLETED else "MEASURING"
        )
        await self.session.flush()

    async def record_learning(self, experiment_id: uuid.UUID, learning: str) -> Experiment:
        experiment = await self.repo.get(experiment_id)
        if experiment is None:
            raise NotFoundError("Experiment not found.")
        experiment.learning = learning[:4000]
        await self.session.flush()
        return experiment

    async def summary_for(self, experiment_id: uuid.UUID) -> ExperimentSummary | None:
        """Read back a stored measurement without recomputing it.

        For a multi-arm experiment, picks the same "primary" arm ``measure()``
        used for its headline decision - the one with the highest incremental
        revenue - so this never disagrees with what was just measured. Every
        arm's own numbers are still in ``experiment.results`` (one row each).
        """
        experiment = await self.repo.get_with_detail(experiment_id)
        if experiment is None:
            return None
        control = next((r for r in experiment.results if r.variant_role == VariantRole.CONTROL), None)
        treatments = [r for r in experiment.results if r.variant_role == VariantRole.TEST]
        test = max(treatments, key=lambda r: r.incremental_revenue or 0) if treatments else None
        if control is None or test is None:
            return None
        return ExperimentSummary(
            experiment_id=experiment.id,
            name=experiment.name,
            status=experiment.status,  # type: ignore[arg-type]
            hypothesis=experiment.hypothesis,
            control_conversion_rate=float(control.conversion_rate or 0),
            test_conversion_rate=float(test.conversion_rate or 0),
            conversion_lift_pct=float(test.conversion_lift_pct or 0),
            control_revenue=float(control.revenue or 0),
            test_revenue=float(test.revenue or 0),
            incremental_revenue=float(test.incremental_revenue or 0),
            incremental_profit=float(test.incremental_profit or 0),
            roi=float(test.roi or 0),
            cost=float(test.cost or 0),
            p_value=float(test.p_value) if test.p_value is not None else None,
            is_significant=bool(test.is_significant),
            decision=experiment.decision,  # type: ignore[arg-type]
            decision_rationale=experiment.decision_rationale,
            learning=experiment.learning,
            window_start=test.window_start,
            window_end=test.window_end,
        )


def _relative_change(current: float, baseline: float) -> float | None:
    if baseline == 0:
        return None
    return round(((current - baseline) / abs(baseline)) * 100, 2)


def _result_fields(measurement: VariantMeasurement) -> dict[str, Any]:
    return {
        "audience_size": measurement.audience_size,
        "converted_customers": measurement.converted_customers,
        "conversion_rate": measurement.conversion_rate,
        "orders": measurement.orders,
        "revenue": measurement.revenue,
        "gross_margin": measurement.gross_margin,
        "avg_order_value": measurement.avg_order_value,
        "revenue_per_customer": measurement.revenue_per_customer,
        "cost": measurement.cost,
    }
