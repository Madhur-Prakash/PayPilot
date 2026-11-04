"""The negotiation orchestrator: requirement -> RFQ -> quotes -> rounds -> recommendation.

It is a resumable state machine (``advance``) so the Negotiation Workspace can
watch it move one stage at a time, and ``run_to_recommendation`` simply loops it.
Each stage is idempotent: message idempotency keys are derived from the stage, so
re-running a stage after a crash re-uses what was already recorded.

Who decides what:

* **Inventory Intelligence** decides *that* and *how much* to buy (deterministic).
* **The financial engine** decides the limits (deterministic, frozen into the request).
* **Supplier agents** decide their own prices from their own private policies.
* **The Buyer Agent** decides its counters (deterministic; an LLM may propose
  alternatives, which are bounds-checked and otherwise refused).
* **Evaluation** decides the recommendation (deterministic scoring).
* **A human** decides whether to buy. The workflow stops at the approval request.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.exceptions import BadRequestError, ConflictError
from app.core.logging import get_logger
from app.core.permissions import Permission
from app.db.models.agent import AgentName, AgentRunStatus
from app.db.models.audit import ActorType, AuditAction
from app.db.models.governance import AgentMessageType, ApprovalAction
from app.db.models.procurement import Vendor, VendorProduct
from app.db.models.supply import (
    NegotiationOffer,
    NegotiationSession,
    NegotiationStatus,
    OfferDirection,
    OfferKind,
    OfferValidation,
    ProcurementRequest,
    ProcurementStatus,
    ProcurementTrigger,
    SupplierAgent,
    SupplierAgentStatus,
    SupplierStrategy,
)
from app.services.intelligence.events import BusinessEvent, emit_business_event
from app.services.inventory.events import new_correlation_id
from app.services.supply.approvals import ApprovalService
from app.services.supply.buyer_agent import (
    BuyerMove,
    BuyerStrategy,
    OfferSnapshot,
    apply_strategist,
    strategist_review,
)
from app.services.supply.context import SupplyContext
from app.services.supply.demand import InventoryIntelligence
from app.services.supply.evaluation import Candidate, evaluate
from app.services.supply.policy import (
    ZERO,
    D,
    ProcurementConstraints,
    compute_constraints,
    money,
    savings,
    serialisable,
    sha256,
    validate_offer,
)
from app.services.supply.supplier_agent import (
    CounterView,
    RFQView,
    SupplierAgentEngine,
    SupplierMove,
    SupplierPrivatePolicy,
    policy_from_rows,
)

log = get_logger(__name__)

ACTIVE_SESSION = (NegotiationStatus.QUOTED, NegotiationStatus.COUNTERED)
LOCKED_SESSION = (NegotiationStatus.FINAL_OFFER,)


class NegotiationService(SupplyContext):
    # ================================================================== create
    async def create_request(
        self,
        *,
        inventory_item_id: uuid.UUID,
        quantity: Decimal | None = None,
        trigger: str | None = None,
        target_margin: Decimal | None = None,
        max_delivery_days: int | None = None,
        min_reliability: Decimal | None = None,
        max_rounds: int | None = None,
        budget_cap: Decimal | None = None,
        source: str = "USER",
        note: str = "",
    ) -> ProcurementRequest:
        item = await self.item(inventory_item_id)
        open_request = (
            await self.session.execute(
                select(ProcurementRequest).where(
                    ProcurementRequest.merchant_id == self.merchant_id,
                    ProcurementRequest.inventory_item_id == item.id,
                    ProcurementRequest.status.in_(ProcurementStatus.OPEN),
                )
            )
        ).scalars().first()
        if open_request is not None:
            raise ConflictError(
                f"{open_request.reference} is already in progress for {item.product_name}.",
                details={"procurement_request_id": str(open_request.id), "reference": open_request.reference},
            )

        assessment = await InventoryIntelligence(self.session, self.merchant_id).assess(item)
        qty = D(quantity) if quantity is not None else assessment.suggested_quantity
        if qty <= 0:
            qty = D(item.reorder_quantity or 0)
        if qty <= 0:
            raise BadRequestError("Nothing to buy: the item has enough cover. Pass a quantity to override.")
        if assessment.selling_price <= 0:
            raise BadRequestError("The product has no selling price, so a margin-based budget cannot be set.")

        resolved_trigger = trigger or (
            ProcurementTrigger.STOCKOUT_RISK if assessment.stockout_risk
            else ProcurementTrigger.DEMAND_SPIKE if assessment.demand_increased
            else ProcurementTrigger.MANUAL
        )
        delivery_days = max_delivery_days or max(
            1, min(assessment.required_within_days if assessment.required_within_days is not None else 7, 7)
        )
        constraints = compute_constraints(
            expected_selling_price=assessment.selling_price,
            quantity=qty,
            target_margin=target_margin,
            max_delivery_days=delivery_days,
            min_reliability=min_reliability if min_reliability is not None else Decimal("0.80"),
            max_rounds=max_rounds,
            budget_cap=budget_cap,
        )

        now = datetime.now(tz=UTC)
        reference = await self.next_reference(ProcurementRequest, "PR")
        request = ProcurementRequest(
            merchant_id=self.merchant_id,
            reference=reference,
            rfq_reference=reference.replace("PR-", "RFQ-"),
            inventory_item_id=item.id,
            product_id=item.product_id,
            sku=item.sku,
            product_name=item.product_name,
            unit=item.unit,
            quantity=qty,
            required_by=assessment.required_by or (now.date() + timedelta(days=delivery_days)),
            max_delivery_days=delivery_days,
            trigger=resolved_trigger,
            status=ProcurementStatus.SOURCING,
            source=source,
            created_by_id=self.actor_id,
            correlation_id=new_correlation_id("PROC"),
            conversation_id=f"conv-{uuid.uuid4().hex[:16]}",
            currency=constraints.currency,
            expected_selling_price=constraints.expected_selling_price,
            target_margin=constraints.target_margin,
            max_unit_cost=constraints.max_unit_cost,
            target_unit_cost=constraints.target_unit_cost,
            max_budget=constraints.max_budget,
            min_reliability=constraints.min_reliability,
            max_rounds=constraints.max_rounds,
            policy_version=constraints.version,
            policy=constraints.as_dict(),
            demand_snapshot=assessment.as_dict(),
            metadata_json={"note": note} if note else {},
        )
        self.session.add(request)
        await self.session.flush()

        await self.send(
            sender=self.system,
            recipient=self.buyer,
            message_type=AgentMessageType.PROCUREMENT_REQUEST,
            payload={
                "procurement_reference": reference,
                "sku": item.sku,
                "product_name": item.product_name,
                "quantity": str(qty),
                "trigger": resolved_trigger,
                "required_by": request.required_by,
                "evidence": {
                    "velocity_per_day": str(assessment.velocity_recent),
                    "demand_change_pct": str(assessment.demand_change_pct),
                    "days_of_cover": str(assessment.days_of_cover) if assessment.days_of_cover is not None else None,
                    "lead_time_days": assessment.lead_time_days,
                },
            },
            request=request,
            key="procurement-request",
            summary=f"Inventory Intelligence raised {reference}: buy {qty:f} {item.unit} of {item.product_name}.",
        )

        if assessment.demand_increased:
            await emit_business_event(
                self.session, merchant_id=self.merchant_id,
                event_type=BusinessEvent.PRODUCT_DEMAND_INCREASED, correlation_id=request.correlation_id,
                entity_type="product", entity_id=item.product_id,
                payload={"sku": item.sku, "product_name": item.product_name,
                         "velocity_per_day": assessment.velocity_recent,
                         "demand_change_pct": assessment.demand_change_pct},
            )
        if assessment.stockout_risk:
            await emit_business_event(
                self.session, merchant_id=self.merchant_id,
                event_type=BusinessEvent.STOCKOUT_RISK_DETECTED, correlation_id=request.correlation_id,
                entity_type="inventory_item", entity_id=item.id,
                payload={"sku": item.sku, "days_of_cover": assessment.days_of_cover,
                         "lead_time_days": assessment.lead_time_days,
                         "revenue_at_risk": assessment.revenue_at_risk},
            )
        await emit_business_event(
            self.session, merchant_id=self.merchant_id,
            event_type=BusinessEvent.PROCUREMENT_REQUIRED, correlation_id=request.correlation_id,
            entity_type="procurement_request", entity_id=request.id,
            payload={"reference": reference, "sku": item.sku, "quantity": qty,
                     "max_budget": constraints.max_budget, "trigger": resolved_trigger},
        )
        await self.audit.record(
            action=AuditAction.PROCUREMENT_REQUESTED,
            merchant_id=self.merchant_id,
            actor_id=self.actor_id,
            actor_type=ActorType.USER if self.actor_id and source == "USER" else ActorType.AGENT,
            actor_label=self.actor_label if source == "USER" else "Inventory Intelligence",
            resource="procurement_request",
            resource_id=str(request.id),
            description=f"{reference}: {qty:f} x {item.product_name}, budget {constraints.currency} {constraints.max_budget:,.2f}",
            request_id=self.request_id,
            metadata={"policy_version": constraints.version, "trigger": resolved_trigger},
        )
        await self.step(
            request, node="inventory_monitoring", agent_name=AgentName.INVENTORY_INTELLIGENCE,
            action="Assessed stock and demand", result=assessment.reason,
            decision=f"Procure {qty:f} {item.unit}",
            evidence=[
                {"metric": "Sales velocity", "value": f"{assessment.velocity_recent}/day", "source": "transactions"},
                {"metric": "Demand change", "value": f"{assessment.demand_change_pct}%", "source": "transactions"},
                {"metric": "Days of cover", "value": str(assessment.days_of_cover), "source": "inventory"},
            ],
        )
        await self.step(
            request, node="procurement_requirement", agent_name=AgentName.PROCUREMENT_ORCHESTRATOR,
            action="Computed deterministic purchase policy",
            result=(
                f"Max landed unit cost {constraints.max_unit_cost:.2f} "
                f"({constraints.expected_selling_price:.2f} x (1 - {constraints.target_margin:.0%})), "
                f"budget {constraints.max_budget:,.2f}, delivery within {constraints.max_delivery_days} days, "
                f"{constraints.max_rounds} rounds max."
            ),
            decision=f"Policy {constraints.version}",
        )
        return request

    # ================================================================== state machine
    async def advance(self, request_id: uuid.UUID) -> dict[str, Any]:
        request = await self.request(request_id)
        if request.status == ProcurementStatus.SOURCING:
            await self._discover_and_rfq(request)
            await self._collect_quotes(request)
            request.status = ProcurementStatus.NEGOTIATING
            stage = "quotes_collected"
        elif request.status == ProcurementStatus.NEGOTIATING:
            sessions = await self.sessions_for(request.id)
            open_sessions = [s for s in sessions if s.status in ACTIVE_SESSION]
            current = max((s.current_round for s in sessions), default=0)
            if open_sessions and current < request.max_rounds:
                await self._negotiate_round(request, current + 1)
                stage = f"round_{current + 1}"
            else:
                await self._close_rounds(request)
                await self._evaluate(request)
                stage = "evaluated"
        else:
            stage = "idle"
        await self.session.flush()
        return {"stage": stage, "status": request.status}

    async def run_to_recommendation(self, request_id: uuid.UUID) -> ProcurementRequest:
        for _ in range(2 + settings.procurement_max_negotiation_rounds + 2):
            result = await self.advance(request_id)
            if result["stage"] in ("evaluated", "idle"):
                break
        return await self.request(request_id)

    def constraints(self, request: ProcurementRequest) -> ProcurementConstraints:
        return ProcurementConstraints.from_dict(request.policy)

    # ================================================================== discovery + RFQ
    async def _discover_and_rfq(self, request: ProcurementRequest) -> None:
        constraints = self.constraints(request)
        rows = (
            await self.session.execute(
                select(SupplierAgent, VendorProduct)
                .join(Vendor, Vendor.id == SupplierAgent.vendor_id)
                .join(
                    VendorProduct,
                    (VendorProduct.vendor_id == SupplierAgent.vendor_id)
                    & (VendorProduct.inventory_item_id == request.inventory_item_id),
                )
                .where(
                    SupplierAgent.merchant_id == self.merchant_id,
                    Vendor.is_active.is_(True),
                )
                .order_by(SupplierAgent.display_name)
            )
        ).all()

        candidates: list[tuple[SupplierAgent, VendorProduct]] = []
        excluded: list[dict[str, Any]] = []
        for agent, supply in rows:
            if agent.status != SupplierAgentStatus.ONLINE:
                excluded.append({"agent_key": agent.agent_key, "supplier": agent.display_name, "reason": f"Agent is {agent.status.lower()}."})
            elif D(agent.reliability_score) < constraints.min_reliability:
                excluded.append({
                    "agent_key": agent.agent_key, "supplier": agent.display_name,
                    "reason": f"Reliability {D(agent.reliability_score):.0%} below the {constraints.min_reliability:.0%} minimum.",
                })
            else:
                candidates.append((agent, supply))

        await self.send(
            sender=self.buyer,
            recipient=self.system,
            message_type=AgentMessageType.SUPPLIER_DISCOVERY,
            payload={
                "rfq_reference": request.rfq_reference,
                "sku": request.sku,
                "candidates": [
                    {"agent_key": a.agent_key, "supplier": a.display_name, "region": a.region,
                     "reliability": str(a.reliability_score), "is_simulated": a.is_simulated}
                    for a, _ in candidates
                ],
                "excluded": excluded,
            },
            request=request,
            key="discovery",
            summary=f"Buyer Agent found {len(candidates)} eligible supplier agent(s) for {request.sku}"
            + (f"; {len(excluded)} excluded." if excluded else "."),
        )
        await self.step(
            request, node="supplier_discovery", agent_name=AgentName.BUYER,
            action="Discovered supplier agents",
            result=", ".join(a.display_name for a, _ in candidates) or "No eligible suppliers",
            decision=f"{len(candidates)} invited",
            evidence=[{"metric": "Excluded", "value": e["supplier"], "detail": e["reason"]} for e in excluded],
        )
        if not candidates:
            request.status = ProcurementStatus.NO_ELIGIBLE_OFFER
            request.failure_reason = "No online supplier agent supplies this item within policy."
            return

        now = datetime.now(tz=UTC)
        request.rfq_issued_at = now
        request.rfq_deadline = now + timedelta(hours=settings.procurement_quote_ttl_hours)
        for agent, _supply in candidates:
            session = NegotiationSession(
                merchant_id=self.merchant_id,
                procurement_request_id=request.id,
                supplier_agent_id=agent.id,
                vendor_id=agent.vendor_id,
                status=NegotiationStatus.INVITED,
                max_rounds=min(request.max_rounds, agent.max_rounds or request.max_rounds),
                expires_at=request.rfq_deadline,
                is_simulated=agent.is_simulated,
            )
            self.session.add(session)
            await self.session.flush()
            agent.negotiations_total = (agent.negotiations_total or 0) + 1
            await self.send(
                sender=self.buyer,
                recipient=self.supplier(agent),
                message_type=AgentMessageType.RFQ_CREATED,
                payload={
                    "rfq_reference": request.rfq_reference,
                    "sku": request.sku,
                    "product_name": request.product_name,
                    "quantity": str(request.quantity),
                    "unit": request.unit,
                    "currency": request.currency,
                    "required_by": request.required_by,
                    "delivery_region": "US-West",
                    "response_deadline": request.rfq_deadline,
                },
                request=request,
                key=f"rfq:{agent.agent_key}",
                session_id=session.id,
                summary=f"RFQ {request.rfq_reference} sent to {agent.display_name}: {request.quantity:f} {request.unit}, needed by {request.required_by}.",
            )
        await emit_business_event(
            self.session, merchant_id=self.merchant_id, event_type=BusinessEvent.RFQ_STARTED,
            correlation_id=request.correlation_id, entity_type="procurement_request", entity_id=request.id,
            payload={"rfq_reference": request.rfq_reference, "suppliers": [a.display_name for a, _ in candidates]},
        )
        await self.step(
            request, node="rfq", agent_name=AgentName.BUYER, action="Issued RFQ",
            result=f"{request.rfq_reference} to {len(candidates)} supplier agents. The RFQ carries no budget or ceiling.",
        )

    # ================================================================== quotes
    async def _engine(self, request: ProcurementRequest, session: NegotiationSession) -> tuple[SupplierAgent, SupplierPrivatePolicy, SupplierAgentEngine]:
        agent = await self.supplier_agent(session.supplier_agent_id)
        supply = await self.supply_link(agent, request.inventory_item_id)
        if supply is None:
            raise BadRequestError(f"{agent.display_name} no longer supplies {request.sku}.")
        policy = policy_from_rows(agent, supply)
        return agent, policy, SupplierAgentEngine(policy)

    async def _collect_quotes(self, request: ProcurementRequest) -> None:
        if request.status == ProcurementStatus.NO_ELIGIBLE_OFFER:
            return
        constraints = self.constraints(request)
        rfq = RFQView(
            rfq_reference=request.rfq_reference,
            sku=request.sku,
            product_name=request.product_name,
            quantity=D(request.quantity),
            unit=request.unit,
            required_within_days=request.max_delivery_days,
        )
        opening_totals: list[Decimal] = []
        for session in await self.sessions_for(request.id):
            if session.status != NegotiationStatus.INVITED:
                continue
            agent, policy, engine = await self._engine(request, session)
            move = engine.respond_to_rfq(rfq)
            if move.kind == OfferKind.DECLINE:
                session.status = NegotiationStatus.DECLINED
                session.outcome_reason = move.rationale
                await self.send(
                    sender=self.supplier(agent), recipient=self.buyer,
                    message_type=AgentMessageType.RFQ_RESPONSE,
                    payload={"rfq_reference": request.rfq_reference, "reason": move.rationale},
                    request=request, key=f"rfq-response:{agent.agent_key}", session_id=session.id,
                    summary=f"{agent.display_name} declined: {move.rationale}",
                )
                continue
            offer = await self._record_supplier_move(request, session, agent, policy, move, constraints, round_no=0)
            session.status = NegotiationStatus.QUOTED
            if offer.quantity >= request.quantity:
                opening_totals.append(D(offer.landed_total))
        if opening_totals:
            request.baseline_landed_total = min(opening_totals)
        await self.step(
            request, node="supplier_responses", agent_name=AgentName.SUPPLIER_NETWORK,
            action="Collected independent quotes",
            result=f"{len(opening_totals)} full-quantity quote(s); best opening landed total "
            f"{money(min(opening_totals)) if opening_totals else 'n/a'}.",
        )

    async def _record_supplier_move(
        self,
        request: ProcurementRequest,
        session: NegotiationSession,
        agent: SupplierAgent,
        policy: SupplierPrivatePolicy,
        move: SupplierMove,
        constraints: ProcurementConstraints,
        *,
        round_no: int,
        accepted_counter: NegotiationOffer | None = None,
    ) -> NegotiationOffer:
        check = validate_offer(
            constraints=constraints,
            unit_price=move.unit_price,
            quantity=move.quantity,
            shipping=move.shipping,
            tax_rate=policy.tax_rate,
            lead_time_days=move.lead_time_days,
            reliability=agent.reliability_score,
            available_quantity=policy.available_quantity,
        )
        offer = await self._persist_offer(
            request=request, session=session, agent=agent, round_no=round_no,
            direction=OfferDirection.SUPPLIER_TO_BUYER, kind=move.kind,
            unit_price=move.unit_price, quantity=move.quantity, shipping=move.shipping,
            lead_time_days=move.lead_time_days, payment_terms=move.payment_terms,
            check=check, proposed_by="SUPPLIER_POLICY", rationale=move.rationale,
            extra={"expedited": move.expedited, "shipping_waived": move.shipping_waived,
                   "concessions": move.concessions},
        )
        landed = check.landed
        if move.kind == OfferKind.ACCEPT and accepted_counter is not None:
            await self.send(
                sender=self.supplier(agent), recipient=self.buyer,
                message_type=AgentMessageType.OFFER_ACCEPTED,
                payload={"rfq_reference": request.rfq_reference, "offer_id": str(accepted_counter.id),
                         "reason": move.rationale, "conditional_on_approval": False},
                request=request, key=f"supplier-accept:{agent.agent_key}:{round_no}", session_id=session.id,
                summary=f"{agent.display_name} accepted the buyer's counter at {move.unit_price:.2f}/unit "
                f"(landed {landed.total:,.2f})." if landed else f"{agent.display_name} accepted.",
            )
        else:
            await self.send(
                sender=self.supplier(agent), recipient=self.buyer,
                message_type=AgentMessageType.QUOTE_SUBMITTED,
                payload={
                    "rfq_reference": request.rfq_reference,
                    "round": round_no,
                    "kind": move.kind,
                    "unit_price": str(move.unit_price),
                    "quantity": str(move.quantity),
                    "shipping": str(move.shipping),
                    "tax": str(landed.tax if landed else ZERO),
                    "landed_total": str(landed.total if landed else ZERO),
                    "lead_time_days": move.lead_time_days,
                    "payment_terms": move.payment_terms,
                    "valid_until": offer.valid_until,
                    "note": move.rationale[:500],
                },
                request=request, key=f"quote:{agent.agent_key}:{round_no}", session_id=session.id,
                summary=(
                    f"{agent.display_name} {'final offer' if move.kind == OfferKind.FINAL else 'quote' if round_no == 0 else 'revised quote'}: "
                    f"{move.unit_price:.2f}/unit x {move.quantity:f}, shipping {move.shipping:.2f}, "
                    f"{move.lead_time_days} days - landed {landed.total:,.2f}"
                    + ("" if check.within_policy else f" (outside policy: {check.errors[0]['code']})")
                ) if landed else f"{agent.display_name} submitted an invalid quote.",
            )
        session.latest_offer_id = offer.id
        if check.within_policy:
            best = await self.offer(session.best_offer_id) if session.best_offer_id else None
            if best is None or D(offer.landed_total) < D(best.landed_total):
                session.best_offer_id = offer.id
        return offer

    async def _persist_offer(
        self,
        *,
        request: ProcurementRequest,
        session: NegotiationSession,
        agent: SupplierAgent,
        round_no: int,
        direction: str,
        kind: str,
        unit_price: Decimal,
        quantity: Decimal,
        shipping: Decimal,
        lead_time_days: int,
        payment_terms: str,
        check: Any,
        proposed_by: str,
        rationale: str,
        ai_proposal: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> NegotiationOffer:
        existing = await self.offers_for(session.id)
        landed = check.landed
        terms = {
            "supplier": agent.agent_key,
            "unit_price": unit_price,
            "quantity": quantity,
            "shipping": shipping,
            "lead_time_days": lead_time_days,
            "payment_terms": payment_terms,
            "currency": request.currency,
        }
        offer = NegotiationOffer(
            merchant_id=self.merchant_id,
            session_id=session.id,
            procurement_request_id=request.id,
            supplier_agent_id=agent.id,
            round=round_no,
            sequence=len(existing) + 1,
            direction=direction,
            kind=kind,
            currency=request.currency,
            unit_price=unit_price,
            quantity=quantity,
            subtotal=landed.subtotal if landed else ZERO,
            shipping_cost=money(shipping),
            tax_amount=landed.tax if landed else ZERO,
            landed_total=landed.total if landed else ZERO,
            landed_unit_cost=landed.unit_cost if landed else ZERO,
            lead_time_days=lead_time_days,
            payment_terms=payment_terms,
            valid_until=datetime.now(tz=UTC) + timedelta(hours=settings.procurement_quote_ttl_hours),
            validation_status=check.status,
            validation_errors=check.errors,
            within_policy=check.within_policy,
            proposed_by=proposed_by,
            ai_proposal=serialisable(ai_proposal or {}),
            rationale=rationale[:2000],
            score=serialisable(extra or {}),
            terms_hash=sha256(terms),
        )
        self.session.add(offer)
        await self.session.flush()
        return offer

    # ================================================================== rounds
    @staticmethod
    def _last_move(offer: NegotiationOffer, policy: SupplierPrivatePolicy) -> SupplierMove:
        flags = offer.score or {}
        return SupplierMove(
            kind=offer.kind,
            unit_price=D(offer.unit_price),
            quantity=D(offer.quantity),
            shipping=D(offer.shipping_cost),
            lead_time_days=offer.lead_time_days,
            payment_terms=offer.payment_terms,
            expedited=bool(flags.get("expedited")),
            shipping_waived=bool(flags.get("shipping_waived")),
        )

    async def _latest_supplier_offer(self, session: NegotiationSession) -> NegotiationOffer | None:
        offers = [o for o in await self.offers_for(session.id) if o.direction == OfferDirection.SUPPLIER_TO_BUYER]
        return offers[-1] if offers else None

    async def _negotiate_round(self, request: ProcurementRequest, round_no: int) -> None:
        constraints = self.constraints(request)
        buyer = BuyerStrategy(constraints)
        sessions = [s for s in await self.sessions_for(request.id) if s.status in ACTIVE_SESSION]

        snapshots: dict[str, tuple[NegotiationSession, NegotiationOffer, SupplierAgent, SupplierPrivatePolicy, SupplierAgentEngine, OfferSnapshot]] = {}
        for session in sessions:
            latest = await self._latest_supplier_offer(session)
            if latest is None:
                continue
            agent, policy, engine = await self._engine(request, session)
            snapshots[str(session.id)] = (
                session, latest, agent, policy, engine,
                OfferSnapshot(
                    session_id=str(session.id),
                    supplier_label=agent.display_name,
                    unit_price=D(latest.unit_price),
                    quantity=D(latest.quantity),
                    shipping=D(latest.shipping_cost),
                    tax_rate=policy.tax_rate,
                    lead_time_days=latest.lead_time_days,
                    landed_total=D(latest.landed_total),
                    landed_unit_cost=D(latest.landed_unit_cost),
                    within_policy=latest.within_policy,
                    violations=tuple(e.get("code", "") for e in (latest.validation_errors or [])),
                ),
            )

        valid_units = [snap[5].landed_unit_cost for snap in snapshots.values() if snap[5].within_policy]
        planned: dict[str, BuyerMove] = {}
        for key, (_s, _o, _a, _p, _e, snap) in snapshots.items():
            others = [u for u in valid_units if u != snap.landed_unit_cost] or None
            planned[key] = buyer.counter(
                snap, round_number=round_no, best_competing_landed_unit=min(others) if others else None
            )

        plan, used_llm = await strategist_review(
            product_name=request.product_name,
            quantity=D(request.quantity),
            round_number=round_no,
            offers=[snap[5] for snap in snapshots.values()],
            planned={k: m for k, m in planned.items() if m.kind == "COUNTER"},
        )
        proposals = {m.session_id: m for m in (plan.moves if plan else [])}

        narrative: list[str] = []
        for key, (session, latest, agent, policy, engine, snap) in snapshots.items():
            move = planned[key]
            if used_llm:
                move = apply_strategist(move, proposals.get(key), offer=snap, ceiling=buyer.ceiling_price(snap))

            if move.kind == "HOLD":
                session.status = NegotiationStatus.FINAL_OFFER
                session.outcome_reason = "Buyer Agent: offer meets the target - terms locked for evaluation."
                session.current_round = round_no
                narrative.append(f"{agent.display_name}: held at {snap.unit_price:.2f} (meets target)")
                continue

            # The buyer's counter, validated like any other offer.
            counter_shipping = ZERO if move.request_free_shipping else snap.shipping
            counter_check = validate_offer(
                constraints=constraints, unit_price=move.unit_price, quantity=move.quantity,
                shipping=counter_shipping, tax_rate=policy.tax_rate,
                lead_time_days=min(snap.lead_time_days, constraints.max_delivery_days),
                reliability=agent.reliability_score,
            )
            if counter_check.status == OfferValidation.INVALID:
                session.status = NegotiationStatus.FINAL_OFFER
                session.outcome_reason = "Buyer counter failed validation; supplier's last offer stands."
                continue
            counter = await self._persist_offer(
                request=request, session=session, agent=agent, round_no=round_no,
                direction=OfferDirection.BUYER_TO_SUPPLIER, kind=OfferKind.COUNTER,
                unit_price=move.unit_price, quantity=move.quantity, shipping=counter_shipping,
                lead_time_days=min(snap.lead_time_days, constraints.max_delivery_days),
                payment_terms=latest.payment_terms, check=counter_check,
                proposed_by=move.proposed_by, rationale=move.note, ai_proposal=move.ai_proposal,
                extra={"request_free_shipping": move.request_free_shipping,
                       "request_expedite": move.request_expedite,
                       "competitive_pressure": move.competitive_pressure},
            )
            await self.send(
                sender=self.buyer, recipient=self.supplier(agent),
                message_type=AgentMessageType.COUNTEROFFER,
                payload={
                    "rfq_reference": request.rfq_reference,
                    "round": round_no,
                    "unit_price": str(move.unit_price),
                    "quantity": str(move.quantity),
                    "request_free_shipping": move.request_free_shipping,
                    "request_expedite": move.request_expedite,
                    "competitive_pressure": move.competitive_pressure,
                    "note": move.note[:500],
                },
                request=request, key=f"counter:{agent.agent_key}:{round_no}", session_id=session.id,
                summary=f"Buyer Agent countered {agent.display_name} at {move.unit_price:.2f}/unit"
                + (" (AI-proposed, validated)" if move.proposed_by == "LLM" else "")
                + (", asked for free shipping" if move.request_free_shipping else "")
                + (", asked to expedite" if move.request_expedite else "") + ".",
            )

            response = engine.respond_to_counter(
                CounterView(
                    round=round_no,
                    unit_price=move.unit_price,
                    quantity=move.quantity,
                    request_free_shipping=move.request_free_shipping,
                    request_expedite=move.request_expedite,
                    competitive_pressure=move.competitive_pressure,
                ),
                self._last_move(latest, policy),
            )
            await self._record_supplier_move(
                request, session, agent, policy, response, constraints,
                round_no=round_no, accepted_counter=counter,
            )
            session.current_round = round_no
            if response.kind in (OfferKind.ACCEPT, OfferKind.FINAL):
                session.status = NegotiationStatus.FINAL_OFFER
                session.outcome_reason = (
                    "Supplier accepted the buyer's counter." if response.kind == OfferKind.ACCEPT
                    else "Supplier made its final offer."
                )
            else:
                session.status = NegotiationStatus.COUNTERED
            narrative.append(
                f"{agent.display_name}: buyer {move.unit_price:.2f} -> supplier {response.unit_price:.2f} ({response.kind.lower()})"
            )

        await self.step(
            request, node="negotiation", agent_name=AgentName.NEGOTIATION,
            action=f"Negotiation round {round_no}",
            result="; ".join(narrative) or "No open sessions.",
            decision="LLM strategist proposals validated" if used_llm else "Deterministic buyer strategy",
            metadata={"used_llm": used_llm, "strategist_summary": plan.summary if plan else ""},
        )

    async def _close_rounds(self, request: ProcurementRequest) -> None:
        for session in await self.sessions_for(request.id):
            if session.status in ACTIVE_SESSION:
                session.status = NegotiationStatus.FINAL_OFFER
                session.outcome_reason = "Round limit reached; the supplier's last offer stands."

    # ================================================================== evaluation
    async def _evaluate(self, request: ProcurementRequest) -> None:
        constraints = self.constraints(request)
        candidates: list[Candidate] = []
        offers_by_session: dict[str, NegotiationOffer] = {}
        for session in await self.sessions_for(request.id):
            if session.status not in LOCKED_SESSION:
                continue
            latest = await self._latest_supplier_offer(session)
            if latest is None:
                continue
            agent = await self.supplier_agent(session.supplier_agent_id)
            offers = await self.offers_for(session.id)
            opening = next((o for o in offers if o.direction == OfferDirection.SUPPLIER_TO_BUYER), None)
            offers_by_session[str(session.id)] = latest
            candidates.append(
                Candidate(
                    session_id=str(session.id),
                    offer_id=str(latest.id),
                    supplier_agent_id=str(agent.id),
                    agent_key=agent.agent_key,
                    supplier_name=agent.display_name,
                    unit_price=D(latest.unit_price),
                    quantity=D(latest.quantity),
                    shipping=D(latest.shipping_cost),
                    tax=D(latest.tax_amount),
                    landed_total=D(latest.landed_total),
                    landed_unit_cost=D(latest.landed_unit_cost),
                    lead_time_days=latest.lead_time_days,
                    payment_terms=latest.payment_terms,
                    reliability=D(agent.reliability_score),
                    quality=D(agent.quality_score),
                    within_policy=latest.within_policy,
                    violations=tuple(e.get("message", "") for e in (latest.validation_errors or [])),
                    opening_landed_total=D(opening.landed_total) if opening else None,
                )
            )

        result = evaluate(candidates, constraints)
        for row in result.ranking:
            offer = offers_by_session.get(row["session_id"])
            if offer is not None:
                offer.score = {**(offer.score or {}), "evaluation": {"rank": row["rank"], "score": row["score"], "criteria": row["criteria"]}}

        await self.step(
            request, node="offer_validation", agent_name=AgentName.PROCUREMENT_EVALUATION,
            action="Validated final offers against policy",
            result=f"{len(result.ranking)} eligible, {len(result.ineligible)} outside policy.",
            evidence=[{"metric": r["supplier_name"], "value": "outside policy", "detail": "; ".join(r["violations"])} for r in result.ineligible],
        )

        if result.winner is None:
            request.status = ProcurementStatus.NO_ELIGIBLE_OFFER
            request.failure_reason = result.explanation
            request.recommendation = result.as_dict()
            for session in await self.sessions_for(request.id):
                if session.status not in NegotiationStatus.TERMINAL:
                    session.status = NegotiationStatus.EXPIRED
                    agent = await self.supplier_agent(session.supplier_agent_id)
                    await self.send(
                        sender=self.buyer, recipient=self.supplier(agent),
                        message_type=AgentMessageType.NEGOTIATION_EXPIRED,
                        payload={"rfq_reference": request.rfq_reference, "reason": "No offer met the buyer's requirements."},
                        request=request, key=f"expired:{agent.agent_key}", session_id=session.id,
                        summary=f"Negotiation with {agent.display_name} closed without agreement.",
                    )
            await self.finish_run(request, status=AgentRunStatus.COMPLETED, summary=result.explanation,
                                  requires_approval=False, output=result.as_dict())
            return

        winner = result.winner
        offer = offers_by_session[winner.session_id]
        request.recommendation = result.as_dict()
        request.recommended_session_id = uuid.UUID(winner.session_id)
        request.recommended_offer_id = offer.id
        request.selected_supplier_agent_id = uuid.UUID(winner.supplier_agent_id)
        request.final_landed_total = money(winner.landed_total)
        if request.baseline_landed_total is not None:
            saved, _ = savings(baseline_total=request.baseline_landed_total, final_total=winner.landed_total)
            request.savings_amount = max(saved, ZERO)
        request.status = ProcurementStatus.RECOMMENDED

        await emit_business_event(
            self.session, merchant_id=self.merchant_id, event_type=BusinessEvent.SUPPLIER_SELECTED,
            correlation_id=request.correlation_id, entity_type="procurement_request", entity_id=request.id,
            payload={"reference": request.reference, "supplier": winner.supplier_name,
                     "landed_total": winner.landed_total, "savings": request.savings_amount},
        )
        await self.step(
            request, node="evaluation", agent_name=AgentName.PROCUREMENT_EVALUATION,
            action="Scored eligible offers", result=result.explanation,
            decision=f"Recommend {winner.supplier_name}",
            evidence=[{"metric": r["supplier_name"], "value": f"score {r['score']}", "detail": f"landed {r['landed_total']}"} for r in result.ranking],
        )
        approval = await self.request_purchase_approval(request)
        await self.step(
            request, node="approval_gate", agent_name=AgentName.PROCUREMENT_ORCHESTRATOR,
            action="Stopped for human approval",
            result=f"{approval.reference} raised: {request.currency} {approval.amount:,.2f} to {winner.supplier_name}. "
            "No purchase order exists until a person with procurement:approve approves.",
            decision="AWAITING_APPROVAL",
        )
        await self.finish_run(
            request, status=AgentRunStatus.AWAITING_APPROVAL, summary=result.explanation,
            requires_approval=True, output={**result.as_dict(), "approval_reference": approval.reference},
        )
        await self.audit.record(
            action=AuditAction.NEGOTIATION_COMPLETED,
            merchant_id=self.merchant_id, actor_type=ActorType.AGENT, actor_label="Buyer Agent",
            resource="procurement_request", resource_id=str(request.id),
            description=f"{request.reference}: recommend {winner.supplier_name} at {request.currency} {winner.landed_total:,.2f}",
            metadata={"savings": str(request.savings_amount or 0), "policy_version": request.policy_version},
        )

    # ================================================================== approval binding
    async def purchase_details(self, request: ProcurementRequest) -> dict[str, Any]:
        """The exact terms a purchase approval authorises - rebuilt from live rows."""
        if request.recommended_offer_id is None:
            raise BadRequestError("No recommended offer to approve.")
        offer = await self.offer(request.recommended_offer_id)
        agent = await self.supplier_agent(offer.supplier_agent_id)
        return serialisable({
            "procurement_reference": request.reference,
            "rfq_reference": request.rfq_reference,
            "supplier_agent": agent.agent_key,
            "supplier_name": agent.display_name,
            "vendor_id": str(agent.vendor_id),
            "payee_email": agent.paypal_email,
            "sku": request.sku,
            "product_name": request.product_name,
            "quantity": D(offer.quantity),
            "unit_price": D(offer.unit_price),
            "shipping": D(offer.shipping_cost),
            "tax": D(offer.tax_amount),
            "landed_total": D(offer.landed_total),
            "landed_unit_cost": D(offer.landed_unit_cost),
            "lead_time_days": offer.lead_time_days,
            "payment_terms": offer.payment_terms,
            "currency": request.currency,
            "offer_id": str(offer.id),
            "terms_hash": offer.terms_hash,
            "policy_version": request.policy_version,
            "max_budget": D(request.max_budget),
            "max_unit_cost": D(request.max_unit_cost),
        })

    async def request_purchase_approval(self, request: ProcurementRequest):  # type: ignore[no-untyped-def]
        details = await self.purchase_details(request)
        risks: list[str] = []
        recommendation = request.recommendation or {}
        winner = recommendation.get("winner") or {}
        if D(details["landed_total"]) > D(request.max_budget) * Decimal("0.9"):
            risks.append("Uses more than 90% of the budget.")
        if D(winner.get("reliability", "1")) < Decimal("0.9"):
            risks.append("Supplier reliability below 90%.")
        if not details.get("payee_email"):
            risks.append("Supplier has no PayPal payee email on file - payment will need one.")
        agent = await self.supplier_agent(uuid.UUID(winner["supplier_agent_id"])) if winner.get("supplier_agent_id") else None
        if agent is not None and agent.is_simulated:
            risks.append("Supplier agent is simulated (demo network).")
        approval = await ApprovalService(self.session, self.merchant_id).request(
            action=ApprovalAction.PROCUREMENT_PURCHASE,
            resource_type="procurement_request",
            resource_id=request.id,
            title=f"Buy {D(details['quantity']):f} x {request.product_name} from {details['supplier_name']}",
            summary=(recommendation.get("explanation") or "")[:2000],
            amount=D(details["landed_total"]),
            currency=request.currency,
            details=details,
            policy_version=request.policy_version,
            required_permission=str(Permission.PROCUREMENT_APPROVE),
            risk_flags=risks,
            requested_by_type=ActorType.AGENT,
            requested_by_label="Buyer Agent",
            correlation_id=request.correlation_id,
            procurement_request_id=request.id,
        )
        request.approval_request_id = approval.id
        request.status = ProcurementStatus.AWAITING_APPROVAL
        await self.session.flush()
        return approval


__all__ = ["NegotiationService", "SupplierStrategy"]
