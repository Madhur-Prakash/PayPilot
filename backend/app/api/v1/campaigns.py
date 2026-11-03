"""Campaign and experiment endpoints.

Approval and execution are separate permissions on purpose: ANALYST can create
and propose, ADMIN/OWNER can approve and run. The service layer refuses to
execute anything without a recorded approval regardless of who calls it.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DbSession, Principal, require_permission
from app.core.exceptions import NotFoundError
from app.core.permissions import Permission
from app.repositories.campaign import CampaignRepository
from app.repositories.experiment import ExperimentRepository
from app.schemas.campaign import (
    CampaignApprovalRequest,
    CampaignCreateRequest,
    CampaignDetail,
    CampaignOut,
    ExperimentApprovalRequest,
    ExperimentCreateRequest,
    ExperimentMeasureRequest,
    ExperimentOut,
    ExperimentSummary,
)
from app.schemas.common import APIResponse, PageMeta, Paginated
from app.services.campaigns.service import CampaignService
from app.services.experiments.service import ExperimentService

router = APIRouter(tags=["campaigns"])


# --------------------------------------------------------------------------- #
# Campaigns
# --------------------------------------------------------------------------- #
@router.get("/campaigns", summary="List campaigns")
async def list_campaigns(
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    campaign_status: Annotated[str | None, Query(alias="status")] = None,
    principal: Principal = Depends(require_permission(Permission.CAMPAIGN_READ)),
) -> APIResponse[Paginated[CampaignOut]]:
    repo = CampaignRepository(session, principal.merchant_id)
    rows = await repo.list_recent(
        limit=page_size, offset=(page - 1) * page_size, status=campaign_status
    )
    total = await repo.count()
    return APIResponse(
        data=Paginated(
            items=[CampaignOut.model_validate(row) for row in rows],
            pagination=PageMeta.build(page=page, page_size=page_size, total=total),
        ),
        meta={"status_counts": await repo.count_by_status()},
    )


@router.post(
    "/campaigns",
    status_code=status.HTTP_201_CREATED,
    summary="Create a campaign",
    description=(
        "Creates a campaign in PENDING_APPROVAL and builds its audience. Nothing is "
        "delivered until a user with campaign:approve approves it."
    ),
)
async def create_campaign(
    payload: CampaignCreateRequest,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.CAMPAIGN_CREATE)),
) -> APIResponse[CampaignDetail]:
    service = CampaignService(session, principal.merchant_id)
    campaign = await service.create(
        name=payload.name,
        objective=payload.objective,
        offer_type=payload.offer_type,
        offer_value=payload.offer_value,
        offer_description=payload.offer_description,
        message=payload.message,
        channel=payload.channel,
        start_date=payload.start_date,
        end_date=payload.end_date,
        budget=payload.budget,
        estimated_impact=payload.estimated_impact,
        opportunity_id=payload.opportunity_id,
        audience=payload.audience.model_dump() if payload.audience else None,
        tags=payload.tags,
        created_by_id=principal.user_id,
        actor_label=principal.label,
        surface=payload.surface,
        objective_type=payload.objective_type,
        business_budget=payload.business_budget,
        paypal_budget=payload.paypal_budget,
        paypal_surface=payload.paypal_surface,
        expected_incremental_revenue=payload.expected_incremental_revenue,
    )
    detail = await service.repo.get_with_detail(campaign.id)
    return APIResponse(data=CampaignDetail.model_validate(detail))


@router.get("/campaigns/{campaign_id}", summary="Campaign detail")
async def get_campaign(
    campaign_id: uuid.UUID,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.CAMPAIGN_READ)),
) -> APIResponse[CampaignDetail]:
    row = await CampaignRepository(session, principal.merchant_id).get_with_detail(campaign_id)
    if row is None:
        raise NotFoundError("Campaign not found.")
    return APIResponse(data=CampaignDetail.model_validate(row))


@router.post(
    "/campaigns/{campaign_id}/approve",
    summary="Approve or reject a campaign",
    description="Records the human decision that execution is gated on.",
)
async def approve_campaign(
    campaign_id: uuid.UUID,
    payload: CampaignApprovalRequest,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.CAMPAIGN_APPROVE)),
) -> APIResponse[CampaignDetail]:
    service = CampaignService(session, principal.merchant_id)
    await service.approve(
        campaign_id,
        approve=payload.approve,
        user_id=principal.user_id,
        actor_label=principal.label,
        note=payload.note,
    )
    detail = await service.repo.get_with_detail(campaign_id)
    return APIResponse(data=CampaignDetail.model_validate(detail))


@router.post(
    "/campaigns/{campaign_id}/execute",
    summary="Execute an approved campaign",
    description=(
        "Launches the campaign with **simulated** delivery. Refuses with "
        "APPROVAL_REQUIRED if no approval is on record."
    ),
)
async def execute_campaign(
    campaign_id: uuid.UUID,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.CAMPAIGN_EXECUTE)),
) -> APIResponse[CampaignDetail]:
    service = CampaignService(session, principal.merchant_id)
    await service.execute(campaign_id, user_id=principal.user_id, actor_label=principal.label)
    detail = await service.repo.get_with_detail(campaign_id)
    return APIResponse(
        data=CampaignDetail.model_validate(detail),
        meta={"simulated": True, "note": "Preview only - no messages were actually sent."},
    )


# --------------------------------------------------------------------------- #
# Experiments
# --------------------------------------------------------------------------- #
@router.get("/experiments", summary="List experiments")
async def list_experiments(
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    experiment_status: Annotated[str | None, Query(alias="status")] = None,
    principal: Principal = Depends(require_permission(Permission.EXPERIMENT_READ)),
) -> APIResponse[Paginated[ExperimentOut]]:
    repo = ExperimentRepository(session, principal.merchant_id)
    rows = await repo.list_recent(
        limit=page_size, offset=(page - 1) * page_size, status=experiment_status
    )
    total = await repo.count()
    return APIResponse(
        data=Paginated(
            items=[ExperimentOut.model_validate(row) for row in rows],
            pagination=PageMeta.build(page=page, page_size=page_size, total=total),
        ),
        meta={"status_counts": await repo.count_by_status()},
    )


@router.post(
    "/experiments",
    status_code=status.HTTP_201_CREATED,
    summary="Create an experiment",
    description="Creates a control/test pair with deterministic assignment, pending approval.",
)
async def create_experiment(
    payload: ExperimentCreateRequest,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.EXPERIMENT_CREATE)),
) -> APIResponse[ExperimentOut]:
    service = ExperimentService(session, principal.merchant_id)
    experiment = await service.create(
        name=payload.name,
        hypothesis=payload.hypothesis,
        success_metric=payload.success_metric,
        success_threshold_pct=payload.success_threshold_pct,
        duration_days=payload.duration_days,
        start_date=payload.start_date,
        opportunity_id=payload.opportunity_id,
        campaign_id=payload.campaign_id,
        control_split_pct=payload.control_split_pct,
        test_offer_description=payload.test_offer_description,
        unit_cost=payload.unit_cost,
        audience=payload.audience.model_dump(exclude={"name"}) if payload.audience else None,
        created_by_id=principal.user_id,
        extra_arms=(
            [arm.model_dump() for arm in payload.extra_arms] if payload.extra_arms else None
        ),
    )
    detail = await service.repo.get_with_detail(experiment.id)
    return APIResponse(data=ExperimentOut.model_validate(detail))


@router.get("/experiments/{experiment_id}", summary="Experiment detail")
async def get_experiment(
    experiment_id: uuid.UUID,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.EXPERIMENT_READ)),
) -> APIResponse[ExperimentOut]:
    row = await ExperimentRepository(session, principal.merchant_id).get_with_detail(experiment_id)
    if row is None:
        raise NotFoundError("Experiment not found.")
    return APIResponse(data=ExperimentOut.model_validate(row))


@router.post(
    "/experiments/{experiment_id}/approve",
    summary="Approve and launch an experiment",
)
async def approve_experiment(
    experiment_id: uuid.UUID,
    payload: ExperimentApprovalRequest,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.EXPERIMENT_APPROVE)),
) -> APIResponse[ExperimentOut]:
    service = ExperimentService(session, principal.merchant_id)
    await service.approve(
        experiment_id,
        approve=payload.approve,
        user_id=principal.user_id,
        actor_label=principal.label,
        note=payload.note,
    )
    detail = await service.repo.get_with_detail(experiment_id)
    return APIResponse(data=ExperimentOut.model_validate(detail))


@router.post(
    "/experiments/{experiment_id}/measure",
    summary="Measure an experiment",
    description=(
        "Recomputes conversion, lift, incremental revenue and profit, ROI and a "
        "two-proportion z-test from the transaction ledger, then records the "
        "SCALE / STOP / CONTINUE / WATCH decision."
    ),
)
async def measure_experiment(
    experiment_id: uuid.UUID,
    payload: ExperimentMeasureRequest,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.EXPERIMENT_MEASURE)),
) -> APIResponse[ExperimentSummary]:
    summary = await ExperimentService(session, principal.merchant_id).measure(
        experiment_id,
        window_start=payload.window_start,
        window_end=payload.window_end,
        user_id=principal.user_id,
    )
    return APIResponse(data=summary)


@router.get(
    "/experiments/{experiment_id}/summary",
    summary="Experiment results",
    description="The stored control-vs-test comparison, as the results screen renders it.",
)
async def experiment_summary(
    experiment_id: uuid.UUID,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.EXPERIMENT_READ)),
) -> APIResponse[ExperimentSummary]:
    service = ExperimentService(session, principal.merchant_id)
    summary = await service.summary_for(experiment_id)
    if summary is None:
        raise NotFoundError("This experiment has not been measured yet.")
    return APIResponse(data=summary)
