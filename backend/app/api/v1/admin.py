"""Merchant settings, user management, audit log and health."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select

from app.api.deps import DbSession, Principal, require_permission
from app.core.config import settings
from app.core.exceptions import BadRequestError, NotFoundError, PermissionDeniedError
from app.core.logging import logging_backend
from app.core.permissions import (
    ALL_PERMISSIONS,
    ALL_ROLES,
    PERMISSION_DESCRIPTIONS,
    ROLE_DESCRIPTIONS,
    Permission,
    permissions_for_role,
)
from app.core.redis import redis_store
from app.db.models.auth import CustomRole
from app.db.models.merchant import MerchantMembership
from app.db.session import ping_database
from app.integrations.email import email_service
from app.integrations.embeddings import embedding_service
from app.integrations.groq import llm_service
from app.integrations.langfuse import tracer
from app.integrations.vapi import vapi_client
from app.repositories.merchant import AuditLogRepository, MembershipRepository
from app.repositories.user import UserRepository
from app.schemas.auth import (
    ChangeRoleRequest,
    CustomRoleCreateRequest,
    InviteUserRequest,
    MerchantSummary,
    PermissionOut,
    RoleOut,
    UserOut,
)
from app.schemas.common import ActionAck, APIResponse, PageMeta, Paginated
from app.services.auth.service import AuthService

router = APIRouter(tags=["admin"])
health_router = APIRouter(tags=["health"])


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #
@health_router.get(
    "/health",
    summary="Health check",
    description="Reports database connectivity and which optional integrations are active.",
)
async def health() -> APIResponse[dict]:
    db_ok = await ping_database()
    # Redis is optional: never degrades the status, only reported. Configured but down
    # means rate limits and caches are running per-process.
    if redis_store.enabled:
        await redis_store.ping()
    return APIResponse(
        data={
            "status": "ok" if db_ok else "degraded",
            "app": settings.app_name,
            "version": settings.app_version,
            "environment": settings.app_env,
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "checks": {
                "database": "ok" if db_ok else "unreachable",
                "redis": redis_store.status(),
                "llm": "configured" if llm_service.enabled else "not_configured",
                "langfuse": "configured" if tracer.enabled else "not_configured",
                "vapi": "configured" if vapi_client.enabled else "not_configured",
                "email": email_service.status,
                "embeddings": embedding_service.provider,
                "logging_backend": logging_backend(),
            },
            "note": (
                "The dashboard, analytics, opportunities, experiments and agent workflow "
                "all run without any external integration configured."
            ),
        }
    )


@health_router.get("/health/live", summary="Liveness probe", include_in_schema=False)
async def liveness() -> dict:
    return {"status": "alive"}


# --------------------------------------------------------------------------- #
# Merchants
# --------------------------------------------------------------------------- #
@router.get("/merchants/current", summary="Active merchant")
async def current_merchant(
    principal: Principal = Depends(require_permission(Permission.DASHBOARD_READ)),
) -> APIResponse[MerchantSummary]:
    return APIResponse(
        data=MerchantSummary.model_validate(principal.merchant),
        meta={
            "role": principal.membership.role,
            "permissions": sorted(principal.permissions),
            "is_demo": principal.merchant.is_demo,
        },
    )


@router.get("/merchants/mine", summary="Merchants I can access")
async def my_merchants(
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.DASHBOARD_READ)),
) -> APIResponse[list[dict]]:
    memberships = await MembershipRepository(session).list_for_user(principal.user_id)
    return APIResponse(
        data=[
            {
                "merchant": MerchantSummary.model_validate(m.merchant).model_dump(mode="json"),
                "role": m.role,
                "is_default": m.is_default,
            }
            for m in memberships
        ]
    )


# --------------------------------------------------------------------------- #
# RBAC reference
# --------------------------------------------------------------------------- #
@router.get(
    "/roles",
    summary="Roles and their permissions",
    description="The canonical RBAC map the backend enforces.",
)
async def list_roles(
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.DASHBOARD_READ)),
) -> APIResponse[list[RoleOut]]:
    roles = [
        RoleOut(
            name=str(role),
            description=ROLE_DESCRIPTIONS[role],
            permissions=sorted(str(p) for p in permissions_for_role(role)),
        )
        for role in ALL_ROLES
    ]
    custom = (
        await session.execute(
            select(CustomRole)
            .where(CustomRole.merchant_id == principal.merchant_id)
            .order_by(CustomRole.name)
        )
    ).scalars()
    roles.extend(
        RoleOut(
            id=row.id,
            name=row.name,
            description=row.description,
            permissions=sorted(row.permission_codes or []),
            is_custom=True,
        )
        for row in custom
    )
    return APIResponse(data=roles)


@router.post(
    "/roles",
    status_code=status.HTTP_201_CREATED,
    summary="Create a custom role",
    description=(
        "Defines a merchant-scoped role from an explicit permission set. Every code "
        "is validated against the permission catalogue, and a creator can never grant "
        "a permission they do not hold themselves."
    ),
)
async def create_custom_role(
    payload: CustomRoleCreateRequest,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.USERS_MANAGE)),
) -> APIResponse[RoleOut]:
    name = payload.name.strip()

    if name.upper() in {str(r) for r in ALL_ROLES}:
        raise BadRequestError(f"'{name}' is a built-in role. Choose a different name.")

    requested = {code.strip() for code in payload.permissions if code.strip()}
    catalogue = {str(p) for p in ALL_PERMISSIONS}

    unknown = sorted(requested - catalogue)
    if unknown:
        raise BadRequestError(f"Unknown permissions: {', '.join(unknown)}")

    # Privilege escalation guard: you cannot mint a role more powerful than you.
    escalated = sorted(requested - principal.permissions)
    if escalated:
        raise PermissionDeniedError(
            "You cannot grant permissions you do not hold.",
            details={"permissions": escalated},
        )

    exists = (
        await session.execute(
            select(CustomRole).where(
                CustomRole.merchant_id == principal.merchant_id, CustomRole.name == name
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise BadRequestError(f"A role named '{name}' already exists.")

    role = CustomRole(
        merchant_id=principal.merchant_id,
        name=name,
        description=payload.description.strip(),
        permission_codes=sorted(requested),
        created_by_id=principal.user_id,
    )
    session.add(role)
    await session.flush()

    await AuditLogRepository(session).record(
        merchant_id=principal.merchant_id,
        action="role.create",
        actor_id=principal.user_id,
        actor_label=principal.label,
        resource="role",
        resource_id=str(role.id),
        description=f"Created custom role '{name}' with {len(requested)} permissions.",
    )
    await session.commit()

    return APIResponse(
        data=RoleOut(
            id=role.id,
            name=role.name,
            description=role.description,
            permissions=sorted(requested),
            is_custom=True,
        )
    )


@router.delete(
    "/roles/{role_id}",
    summary="Delete a custom role",
    description="Refuses while any member still holds the role.",
)
async def delete_custom_role(
    role_id: uuid.UUID,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.USERS_MANAGE)),
) -> APIResponse[ActionAck]:
    role = (
        await session.execute(
            select(CustomRole).where(
                CustomRole.id == role_id, CustomRole.merchant_id == principal.merchant_id
            )
        )
    ).scalar_one_or_none()
    if role is None:
        raise NotFoundError("Role not found.")

    holders = (
        await session.execute(
            select(func.count())
            .select_from(MerchantMembership)
            .where(
                MerchantMembership.merchant_id == principal.merchant_id,
                MerchantMembership.role == role.name,
            )
        )
    ).scalar_one()
    if holders:
        raise BadRequestError(
            f"{holders} member{'s' if holders > 1 else ''} still hold this role. "
            "Move them to another role first."
        )

    name = role.name
    await session.delete(role)
    await AuditLogRepository(session).record(
        merchant_id=principal.merchant_id,
        action="role.delete",
        actor_id=principal.user_id,
        actor_label=principal.label,
        resource="role",
        resource_id=str(role_id),
        description=f"Deleted custom role '{name}'.",
    )
    await session.commit()
    return APIResponse(data=ActionAck(message=f"Role '{name}' deleted."))


@router.get("/permissions", summary="Permission catalogue")
async def list_permissions(
    principal: Principal = Depends(require_permission(Permission.DASHBOARD_READ)),
) -> APIResponse[list[PermissionOut]]:
    return APIResponse(
        data=[
            PermissionOut(
                code=str(p),
                resource=str(p).split(":")[0],
                action=str(p).split(":")[1],
                description=PERMISSION_DESCRIPTIONS.get(p, ""),
            )
            for p in ALL_PERMISSIONS
        ]
    )


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
async def _assert_assignable_role(session: DbSession, merchant_id: uuid.UUID, role: str) -> str:
    """A role may be assigned only if it is built-in or belongs to THIS merchant.

    Scoping the lookup by merchant is what stops one tenant assigning another
    tenant's role name and inheriting its permissions.
    """
    name = role.strip()
    if name.upper() in {str(r) for r in ALL_ROLES}:
        return name.upper()

    exists = (
        await session.execute(
            select(CustomRole.id).where(
                CustomRole.merchant_id == merchant_id, CustomRole.name == name
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        raise BadRequestError(f"'{role}' is not a role in this workspace.")
    return name


@router.get("/users", summary="Team members")
async def list_users(
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.USERS_MANAGE)),
) -> APIResponse[list[dict]]:
    rows = await UserRepository(session).list_for_merchant(principal.merchant_id)
    return APIResponse(
        data=[
            {"user": UserOut.model_validate(user).model_dump(mode="json"), "role": role}
            for user, role in rows
        ]
    )


@router.post("/users/invite", summary="Invite a team member")
async def invite_user(
    payload: InviteUserRequest,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.USERS_MANAGE)),
) -> APIResponse[UserOut]:
    role = await _assert_assignable_role(session, principal.merchant_id, payload.role)
    user = await AuthService(session).invite_user(
        merchant_id=principal.merchant_id,
        email=payload.email,
        full_name=payload.full_name,
        role=role,
        temporary_password=payload.temporary_password,
        invited_by=principal.user,
    )

    # The account exists either way; the email is best-effort and the caller is
    # told whether it actually left, so the UI can fall back to sharing manually.
    emailed = await email_service.send_invitation(
        to=payload.email,
        full_name=payload.full_name,
        merchant_name=principal.merchant.name,
        role=role,
        temporary_password=payload.temporary_password,
        invited_by=principal.user.full_name or principal.user.email,
    )
    return APIResponse(
        data=UserOut.model_validate(user),
        meta={"emailed": emailed, "email_configured": email_service.enabled},
    )


@router.post(
    "/settings/email/test",
    summary="Send a test email",
    description="Proves the SMTP configuration end to end by mailing the signed-in user.",
)
async def send_test_email(
    principal: Principal = Depends(require_permission(Permission.SETTINGS_MANAGE)),
) -> APIResponse[ActionAck]:
    if not email_service.enabled:
        raise BadRequestError(
            "Email is not configured. Set GMAIL_CREDENTIALS_B64 (mint it with "
            "scripts/mint_gmail_token.py), then restart the backend."
        )
    sent = await email_service.send_test(to=principal.user.email)
    if not sent:
        raise BadRequestError(
            "Gmail rejected the message. The backend log carries Google's own reason."
        )
    return APIResponse(data=ActionAck(message=f"Test email sent to {principal.user.email}."))


@router.post(
    "/users/role",
    summary="Change a member's role",
    description="Refuses to demote the last remaining owner of a merchant.",
)
async def change_role(
    payload: ChangeRoleRequest,
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.USERS_MANAGE)),
) -> APIResponse[ActionAck]:
    role = await _assert_assignable_role(session, principal.merchant_id, payload.role)
    membership = await AuthService(session).change_role(
        merchant_id=principal.merchant_id,
        user_id=payload.user_id,
        role=role,
        actor=principal.user,
    )
    return APIResponse(
        data=ActionAck(
            message=f"Role updated to {membership.role}.", resource_id=str(membership.id)
        )
    )


# --------------------------------------------------------------------------- #
# Audit log
# --------------------------------------------------------------------------- #
@router.get(
    "/audit-logs",
    summary="Audit log",
    description="Every consequential action, with actor, resource and metadata.",
)
async def audit_logs(
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    action: Annotated[str | None, Query()] = None,
    principal: Principal = Depends(require_permission(Permission.AUDIT_READ)),
) -> APIResponse[Paginated[dict]]:
    repo = AuditLogRepository(session)
    rows = await repo.list_for_merchant(
        principal.merchant_id,
        limit=page_size,
        offset=(page - 1) * page_size,
        action=action,
    )
    total = await repo.count_for_merchant(principal.merchant_id, action=action)
    return APIResponse(
        data=Paginated(
            items=[
                {
                    "id": str(row.id),
                    "action": row.action,
                    "actor_type": row.actor_type,
                    "actor_label": row.actor_label,
                    "resource": row.resource,
                    "resource_id": row.resource_id,
                    "description": row.description,
                    "status": row.status,
                    "metadata": row.metadata_json,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ],
            pagination=PageMeta.build(page=page, page_size=page_size, total=total),
        )
    )


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
@router.get("/settings", summary="Merchant settings and integration status")
async def get_settings_view(
    principal: Principal = Depends(require_permission(Permission.SETTINGS_MANAGE)),
) -> APIResponse[dict]:
    return APIResponse(
        data={
            "merchant": MerchantSummary.model_validate(principal.merchant).model_dump(mode="json"),
            "integrations": {
                "llm": {
                    "configured": llm_service.enabled,
                    "model": settings.groq_model if llm_service.enabled else None,
                    "note": (
                        "Without a key the agents still run: metrics, opportunities, "
                        "experiments and decisions are all deterministic."
                    ),
                },
                "langfuse": {
                    "configured": tracer.enabled,
                    # The effective host, not the default: LANGFUSE_BASE_URL
                    # overrides it, and showing the wrong region sends people
                    # to a Langfuse project that does not hold their traces.
                    "host": settings.langfuse_effective_host,
                },
                "vapi": {"configured": vapi_client.enabled},
                "email": {
                    "configured": email_service.enabled,
                    "transport": "gmail_api",
                    "sender": settings.gmail_sender,
                },
                "embeddings": {
                    "provider": embedding_service.provider,
                    "dimensions": embedding_service.dimensions,
                },
                "logging": {"backend": logging_backend(), "format": settings.log_format},
            },
            "environment": settings.app_env,
        }
    )
