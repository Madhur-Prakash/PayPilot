"""Campaign lifecycle.

Delivery is **simulated**: no message is sent to a real customer and no money
moves. Every campaign, audience and action is stamped ``is_simulated`` and the
API returns that provenance so the UI can label it honestly.

Execution is gated on a recorded human approval - the agent may create and
recommend, but only a permitted user can approve and launch.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ApprovalRequiredError, BadRequestError, NotFoundError
from app.core.logging import get_logger
from app.db.models.audit import AuditAction
from app.db.models.campaign import (
    AudienceRole,
    Campaign,
    CampaignActionType,
    CampaignStatus,
    CampaignSurface,
)
from app.db.models.growth import OpportunityStatus
from app.repositories.campaign import CampaignRepository
from app.repositories.customer import CustomerRepository
from app.repositories.merchant import AuditLogRepository
from app.repositories.opportunity import OpportunityRepository

log = get_logger(__name__)

#: Simulated per-recipient delivery cost, used for ROI arithmetic.
SIMULATED_MESSAGE_COST = 0.02


class CampaignService:
    def __init__(self, session: AsyncSession, merchant_id: uuid.UUID) -> None:
        self.session = session
        self.merchant_id = merchant_id
        self.repo = CampaignRepository(session, merchant_id)
        self.customers = CustomerRepository(session, merchant_id)
        self.opportunities = OpportunityRepository(session, merchant_id)
        self.audit = AuditLogRepository(session)

    # ------------------------------------------------------------------ create
    async def create(
        self,
        *,
        name: str,
        objective: str = "",
        offer_type: str = "COMBO",
        offer_value: float = 0.0,
        offer_description: str = "",
        message: str = "",
        channel: str = "paypal_app",
        start_date: date | None = None,
        end_date: date | None = None,
        budget: float = 0.0,
        estimated_impact: float = 0.0,
        opportunity_id: uuid.UUID | None = None,
        audience: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        created_by_id: uuid.UUID | None = None,
        actor_label: str = "",
        agent_run_id: uuid.UUID | None = None,
        # ---- dual-market growth intelligence (all optional, backward compatible) ----
        surface: str = CampaignSurface.BUSINESS,
        objective_type: str = "",
        business_budget: float = 0.0,
        paypal_budget: float = 0.0,
        paypal_surface: str = "",
        expected_incremental_revenue: float | None = None,
        created_by_agent: str = "",
    ) -> Campaign:
        start = start_date or date.today()
        # A hybrid campaign's total budget is the sum of its two legs, not a third
        # number a caller could let drift out of sync with them.
        if surface == CampaignSurface.HYBRID:
            budget = round(business_budget + paypal_budget, 2)
        elif surface == CampaignSurface.PAYPAL:
            budget = paypal_budget or budget
        elif surface == CampaignSurface.BUSINESS and business_budget:
            budget = business_budget or budget

        campaign = await self.repo.create(
            name=name,
            objective=objective,
            offer_type=offer_type,
            offer_value=offer_value,
            offer_description=offer_description,
            message=message,
            channel=channel,
            start_date=start,
            end_date=end_date or start + timedelta(days=13),
            budget=budget,
            estimated_impact=estimated_impact,
            opportunity_id=opportunity_id,
            agent_run_id=agent_run_id,
            created_by_id=created_by_id,
            status=CampaignStatus.DRAFT,
            requires_approval=True,
            is_simulated=True,
            tags=tags or [],
            surface=surface,
            objective_type=objective_type,
            business_budget=business_budget,
            paypal_budget=paypal_budget,
            paypal_surface=paypal_surface,
            expected_incremental_revenue=expected_incremental_revenue,
            created_by_agent=created_by_agent or ("growth_scientist" if agent_run_id else ""),
        )
        await self.repo.log_action(
            campaign=campaign,
            action_type=CampaignActionType.CREATED,
            description=f"Campaign '{name}' created.",
            actor_type="AGENT" if agent_run_id else "USER",
            actor_id=created_by_id,
            actor_label=actor_label or ("Action Agent" if agent_run_id else "Merchant"),
            agent_run_id=agent_run_id,
        )

        if audience is not None:
            await self.build_audience(
                campaign,
                audience,
                agent_run_id=agent_run_id,
                actor_id=created_by_id,
                actor_label=actor_label,
            )

        campaign.status = CampaignStatus.PENDING_APPROVAL
        await self.repo.log_action(
            campaign=campaign,
            action_type=CampaignActionType.SUBMITTED_FOR_APPROVAL,
            description="Awaiting merchant approval before anything is executed.",
            actor_type="AGENT" if agent_run_id else "USER",
            actor_id=created_by_id,
            actor_label=actor_label or ("Action Agent" if agent_run_id else "Merchant"),
            agent_run_id=agent_run_id,
        )
        await self.session.flush()

        await self.audit.record(
            action=AuditAction.CAMPAIGN_CREATED,
            merchant_id=self.merchant_id,
            actor_id=created_by_id,
            actor_type="AGENT" if agent_run_id else "USER",
            actor_label=actor_label,
            resource="campaign",
            resource_id=str(campaign.id),
            description=f"Campaign '{name}' created and submitted for approval.",
            agent_run_id=agent_run_id,
        )
        log.info("campaign_created", campaign_id=str(campaign.id), name=name)
        return campaign

    async def build_audience(
        self,
        campaign: Campaign,
        definition: dict[str, Any],
        *,
        agent_run_id: uuid.UUID | None = None,
        actor_id: uuid.UUID | None = None,
        actor_label: str = "",
    ) -> int:
        """Materialise the campaign's audience from a validated segment filter."""
        filters = dict(definition)
        name = filters.pop("name", None) or f"{campaign.name} audience"
        customers = await self.customers.resolve_segment(**filters)
        customer_ids = [customer.id for customer in customers]

        await self.repo.add_audience(
            campaign=campaign,
            name=name,
            role=AudienceRole.FULL,
            customer_ids=customer_ids,
            definition=definition,
        )
        campaign.estimated_cost = round(len(customer_ids) * SIMULATED_MESSAGE_COST, 2)
        await self.session.flush()

        await self.repo.log_action(
            campaign=campaign,
            action_type=CampaignActionType.AUDIENCE_BUILT,
            description=f"Audience '{name}' built with {len(customer_ids)} customers.",
            actor_type="AGENT" if agent_run_id else "USER",
            actor_id=actor_id,
            actor_label=actor_label or ("Action Agent" if agent_run_id else "Merchant"),
            agent_run_id=agent_run_id,
            payload={"size": len(customer_ids), "definition": definition},
        )
        return len(customer_ids)

    # ------------------------------------------------------------------ approval
    async def approve(
        self,
        campaign_id: uuid.UUID,
        *,
        approve: bool,
        user_id: uuid.UUID,
        actor_label: str = "",
        note: str = "",
    ) -> Campaign:
        campaign = await self.repo.get_with_detail(campaign_id)
        if campaign is None:
            raise NotFoundError("Campaign not found.")
        if campaign.status not in (CampaignStatus.PENDING_APPROVAL, CampaignStatus.DRAFT):
            raise BadRequestError(f"Campaign is {campaign.status} and cannot be approved again.")

        now = datetime.now(tz=UTC)
        if not approve:
            campaign.status = CampaignStatus.REJECTED
            campaign.rejected_reason = note or "Rejected by merchant."
            await self.session.flush()
            await self.repo.log_action(
                campaign=campaign,
                action_type=CampaignActionType.REJECTED,
                description=campaign.rejected_reason,
                actor_type="USER",
                actor_id=user_id,
                actor_label=actor_label,
            )
            await self.audit.record(
                action=AuditAction.CAMPAIGN_REJECTED,
                merchant_id=self.merchant_id,
                actor_id=user_id,
                actor_label=actor_label,
                resource="campaign",
                resource_id=str(campaign.id),
                description="Campaign rejected.",
                metadata={"note": note},
            )
            return campaign

        campaign.status = CampaignStatus.APPROVED
        campaign.approved_by_id = user_id
        campaign.approved_at = now
        await self.session.flush()

        await self.repo.log_action(
            campaign=campaign,
            action_type=CampaignActionType.APPROVED,
            description="Approved by merchant.",
            actor_type="USER",
            actor_id=user_id,
            actor_label=actor_label,
            payload={"note": note},
        )
        await self.audit.record(
            action=AuditAction.CAMPAIGN_APPROVED,
            merchant_id=self.merchant_id,
            actor_id=user_id,
            actor_label=actor_label,
            resource="campaign",
            resource_id=str(campaign.id),
            description=f"Campaign '{campaign.name}' approved.",
            metadata={"note": note},
        )
        log.info("campaign_approved", campaign_id=str(campaign.id))
        return campaign

    # ------------------------------------------------------------------ execute
    async def execute(
        self,
        campaign_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        actor_label: str = "",
        agent_run_id: uuid.UUID | None = None,
    ) -> Campaign:
        """Launch an approved campaign (simulated delivery).

        Refuses to run without a recorded approval. This is the enforcement point
        for the human-approval rule - not the UI, and not the agent.
        """
        campaign = await self.repo.get_with_detail(campaign_id)
        if campaign is None:
            raise NotFoundError("Campaign not found.")
        if campaign.requires_approval and campaign.approved_at is None:
            raise ApprovalRequiredError(
                "This campaign has not been approved by the merchant, so it cannot be executed."
            )
        if campaign.status in (CampaignStatus.RUNNING, CampaignStatus.COMPLETED):
            return campaign
        if campaign.status not in (CampaignStatus.APPROVED, CampaignStatus.SCHEDULED):
            raise BadRequestError(f"Campaign is {campaign.status} and cannot be launched.")

        now = datetime.now(tz=UTC)
        campaign.status = CampaignStatus.RUNNING
        campaign.launched_at = now

        audience = await self.repo.get_audience(campaign.id, AudienceRole.FULL)
        recipients = audience.size if audience else 0
        campaign.actual_cost = round(recipients * SIMULATED_MESSAGE_COST, 2)
        await self.session.flush()

        await self.repo.log_action(
            campaign=campaign,
            action_type=CampaignActionType.LAUNCHED,
            description=f"Campaign launched to {recipients} customers.",
            actor_type="AGENT" if agent_run_id else "USER",
            actor_id=user_id,
            actor_label=actor_label,
            agent_run_id=agent_run_id,
            payload={"recipients": recipients},
        )
        await self.repo.log_action(
            campaign=campaign,
            action_type=CampaignActionType.MESSAGE_SIMULATED,
            description=(
                f"Delivery preview: {recipients} offer messages were prepared for the "
                f"{campaign.channel} channel. No messaging provider is connected, so nothing "
                "was sent and no funds moved."
            ),
            actor_type="SYSTEM",
            actor_label="System",
            agent_run_id=agent_run_id,
            payload={"channel": campaign.channel, "recipients": recipients, "simulated": True},
        )

        if campaign.opportunity_id:
            opportunity = await self.opportunities.get(campaign.opportunity_id)
            if opportunity is not None:
                opportunity.status = OpportunityStatus.RUNNING
                opportunity.campaign_id = campaign.id
                await self.session.flush()

        await self.audit.record(
            action=AuditAction.CAMPAIGN_EXECUTED,
            merchant_id=self.merchant_id,
            actor_id=user_id,
            actor_type="AGENT" if agent_run_id else "USER",
            actor_label=actor_label,
            resource="campaign",
            resource_id=str(campaign.id),
            description=f"Campaign '{campaign.name}' executed (simulated) to {recipients} customers.",
            agent_run_id=agent_run_id,
            metadata={"recipients": recipients, "simulated": True},
        )
        log.info("campaign_executed", campaign_id=str(campaign.id), recipients=recipients)
        return campaign

    async def complete(self, campaign_id: uuid.UUID) -> Campaign:
        campaign = await self.repo.get(campaign_id)
        if campaign is None:
            raise NotFoundError("Campaign not found.")
        campaign.status = CampaignStatus.COMPLETED
        campaign.completed_at = datetime.now(tz=UTC)
        await self.session.flush()
        await self.repo.log_action(
            campaign=campaign,
            action_type=CampaignActionType.COMPLETED,
            description="Campaign completed.",
            actor_type="SYSTEM",
            actor_label="Scheduler",
        )
        return campaign
