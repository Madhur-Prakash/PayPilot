"""FastAPI dependencies: authentication, merchant scope and permission checks.

The three guarantees every protected endpoint gets for free:

1. **Authenticated** - a valid, unexpired access token for an active account.
2. **Scoped**       - the merchant comes from the user's membership, never from a
   client-supplied id, so a caller cannot address another tenant at all.
3. **Permitted**    - ``require_permission("campaign:execute")`` re-derives the
   permission set server-side from the stored role. Nothing trusts the frontend.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AuthenticationError,
    InactiveAccountError,
    MerchantScopeError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.logging import bind_context, get_logger
from app.core.permissions import Permission, Role
from app.core.security import decode_token
from app.db.models.audit import AuditAction
from app.db.models.auth import User
from app.db.models.merchant import Merchant, MerchantMembership
from app.db.session import get_db
from app.repositories.merchant import MembershipRepository
from app.repositories.user import CustomRoleRepository, UserRepository
from app.services.auth.security_events import record_security_event

log = get_logger(__name__)

bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")

DbSession = Annotated[AsyncSession, Depends(get_db)]


# --------------------------------------------------------------------------- #
# Principal
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class Principal:
    """The authenticated caller, already resolved to one merchant."""

    user: User
    merchant: Merchant
    membership: MerchantMembership
    permissions: frozenset[str]
    request_id: str | None = None

    @property
    def role(self) -> Role | str:
        """The built-in enum member where it is one, else the raw custom name."""
        try:
            return Role(self.membership.role)
        except ValueError:
            return self.membership.role

    @property
    def merchant_id(self) -> uuid.UUID:
        return self.merchant.id

    @property
    def user_id(self) -> uuid.UUID:
        return self.user.id

    @property
    def label(self) -> str:
        return f"{self.user.full_name} <{self.user.email}>"

    def has(self, permission: Permission | str) -> bool:
        return str(permission) in self.permissions

    def require(self, permission: Permission | str) -> None:
        if not self.has(permission):
            raise PermissionDeniedError(
                f"Your role ({self.membership.role}) cannot perform this action.",
                details={"required_permission": str(permission), "role": self.membership.role},
            )


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #
async def get_current_user(
    session: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> User:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Sign in to continue.")

    payload = decode_token(credentials.credentials)
    try:
        user_id = uuid.UUID(payload.subject)
    except (ValueError, TypeError):
        raise AuthenticationError("Malformed token subject.")

    user = await UserRepository(session).get_with_memberships(user_id)
    if user is None:
        raise AuthenticationError("Account not found.")
    if not user.is_active:
        raise InactiveAccountError()

    bind_context(user_id=str(user.id))
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


# --------------------------------------------------------------------------- #
# Merchant scope
# --------------------------------------------------------------------------- #
async def get_principal(
    request: Request,
    session: DbSession,
    user: CurrentUserDep,
    merchant_id: Annotated[
        uuid.UUID | None,
        Query(description="Optional merchant to act on. Must be one you are a member of."),
    ] = None,
    header_merchant: Annotated[str | None, Header(alias="X-Merchant-ID")] = None,
) -> Principal:
    """Resolve the caller to exactly one merchant they are a member of.

    A merchant id supplied by the client is treated as a *request*, never as
    authority: it is only honoured if an active membership exists for it.
    """
    memberships = MembershipRepository(session)
    requested = merchant_id
    if requested is None and header_merchant:
        try:
            requested = uuid.UUID(header_merchant)
        except ValueError:
            requested = None

    if requested is not None:
        membership = await memberships.get_for_user_and_merchant(user.id, requested)
        if membership is None:
            # Written on its own connection: this request is about to raise, and
            # the request session will be rolled back.
            await record_security_event(
                action=AuditAction.MERCHANT_SCOPE_VIOLATION,
                actor_id=user.id,
                actor_label=user.email,
                resource="merchant",
                resource_id=str(requested),
                description="Attempted to access a merchant without membership.",
                request_id=getattr(request.state, "request_id", None),
                ip_address=client_ip(request),
            )
            log.warning(
                "merchant_scope_violation",
                user_id=str(user.id),
                requested_merchant=str(requested),
            )
            raise MerchantScopeError()
    else:
        membership = await memberships.default_for_user(user.id)
        if membership is None:
            raise NotFoundError("You are not a member of any merchant workspace yet.")

    bind_context(merchant_id=str(membership.merchant_id))
    return Principal(
        user=user,
        merchant=membership.merchant,
        membership=membership,
        permissions=await CustomRoleRepository(session).permissions_for(
            membership.merchant_id, membership.role
        ),
        request_id=getattr(request.state, "request_id", None),
    )


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


# --------------------------------------------------------------------------- #
# Permissions
# --------------------------------------------------------------------------- #
def require_permission(
    *permissions: Permission | str,
) -> Callable[[Principal, AsyncSession], Awaitable[Principal]]:
    """Dependency factory enforcing that the caller holds every listed permission.

    Usage::

        @router.post("/campaigns/{id}/execute")
        async def execute(principal: Principal = Depends(require_permission("campaign:execute"))):
            ...
    """
    required = tuple(str(p) for p in permissions)

    async def dependency(
        principal: CurrentPrincipal,
        session: DbSession,
    ) -> Principal:
        missing = [p for p in required if p not in principal.permissions]
        if missing:
            await record_security_event(
                action=AuditAction.PERMISSION_DENIED,
                merchant_id=principal.merchant_id,
                actor_id=principal.user_id,
                actor_label=principal.user.email,
                resource="permission",
                resource_id=missing[0],
                description=f"Denied: role {principal.membership.role} lacks {', '.join(missing)}.",
                request_id=principal.request_id,
                metadata={"required": list(required), "role": principal.membership.role},
            )
            log.warning(
                "permission_denied",
                user_id=str(principal.user_id),
                role=principal.membership.role,
                required=list(required),
            )
            raise PermissionDeniedError(
                f"Your role ({principal.membership.role}) cannot perform this action.",
                details={"required_permissions": list(required), "role": principal.membership.role},
            )
        return principal

    return dependency


def require_any_permission(
    *permissions: Permission | str,
) -> Callable[[Principal, AsyncSession], Awaitable[Principal]]:
    options = tuple(str(p) for p in permissions)

    async def dependency(principal: CurrentPrincipal, session: DbSession) -> Principal:
        if any(p in principal.permissions for p in options):
            return principal
        raise PermissionDeniedError(
            "You do not have permission to perform this action.",
            details={"any_of": list(options), "role": principal.membership.role},
        )

    return dependency


# --------------------------------------------------------------------------- #
# Convenience
# --------------------------------------------------------------------------- #
def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")
