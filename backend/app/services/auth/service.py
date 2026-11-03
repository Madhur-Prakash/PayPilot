"""Authentication and membership management.

Refresh tokens are opaque, stored hashed, and rotated on every use. Reusing a
token that has already been rotated revokes the entire family - the standard
response to a stolen-token replay.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    ConflictError,
    InactiveAccountError,
    InvalidCredentialsError,
    InvalidTokenError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.core.logging import get_logger
from app.core.permissions import Role, permissions_for_role
from app.core.security import (
    RefreshToken as RefreshTokenValue,
)
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    password_needs_rehash,
    verify_password,
)
from app.db.models.audit import ActorType, AuditAction
from app.db.models.auth import RefreshToken, User, UserStatus
from app.db.models.merchant import MembershipStatus, Merchant, MerchantMembership
from app.repositories.merchant import AuditLogRepository, MembershipRepository, MerchantRepository
from app.repositories.user import CustomRoleRepository, RefreshTokenRepository, UserRepository
from app.schemas.auth import (
    AuthSession,
    CurrentUser,
    MembershipOut,
    MerchantSummary,
    TokenPair,
    UserOut,
)
from app.services.auth.security_events import (
    record_failed_login,
    record_security_event,
    revoke_token_family,
)

log = get_logger(__name__)

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    return _SLUG_STRIP.sub("-", value.lower()).strip("-") or "merchant"


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.merchants = MerchantRepository(session)
        self.memberships = MembershipRepository(session)
        self.tokens = RefreshTokenRepository(session)
        self.audit = AuditLogRepository(session)

    # ------------------------------------------------------------------ register
    async def register(
        self,
        *,
        email: str,
        password: str,
        full_name: str,
        merchant_name: str | None = None,
        phone: str | None = None,
        request_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuthSession:
        email = email.lower().strip()
        if await self.users.email_exists(email):
            raise ConflictError("An account with this email already exists.")

        user = await self.users.create(
            email=email,
            password_hash=hash_password(password),
            full_name=full_name.strip(),
            phone=phone,
            status=UserStatus.ACTIVE,
            email_verified=False,
        )

        merchant = await self._create_workspace(merchant_name or f"{full_name}'s workspace")
        await self.memberships.create(
            user_id=user.id,
            merchant_id=merchant.id,
            role=Role.OWNER,
            status=MembershipStatus.ACTIVE,
            is_default=True,
            joined_at=datetime.now(tz=UTC),
        )

        await self.audit.record(
            action=AuditAction.USER_CREATED,
            merchant_id=merchant.id,
            actor_id=user.id,
            actor_label=user.email,
            resource="user",
            resource_id=str(user.id),
            description="Account registered.",
            request_id=request_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        log.info("user_registered", user_id=str(user.id), merchant_id=str(merchant.id))

        return await self._issue_session(
            user, merchant_id=merchant.id, ip_address=ip_address, user_agent=user_agent
        )

    async def _create_workspace(self, name: str) -> Merchant:
        base = slugify(name)
        slug = base
        suffix = 2
        while await self.merchants.slug_exists(slug):
            slug = f"{base}-{suffix}"
            suffix += 1
        return await self.merchants.create(
            name=name.strip()[:160],
            slug=slug,
            category="cafe",
            city="",
            country="India",
            currency="INR",
            is_demo=False,
            data_source="LIVE",
        )

    # ------------------------------------------------------------------ login
    async def login(
        self,
        *,
        email: str,
        password: str,
        request_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuthSession:
        user = await self.users.get_by_email(email)

        if user is None:
            # Same error and roughly the same work either way, so the response does
            # not reveal whether the address is registered.
            hash_password("dummy-Password-1!")
            raise InvalidCredentialsError()

        if self.users.is_locked(user):
            raise InactiveAccountError(
                "Too many failed attempts. Please try again in a few minutes.",
                code="ACCOUNT_LOCKED",
            )

        if not verify_password(password, user.password_hash):
            # Both of these must outlive the rollback that the raise below triggers,
            # otherwise the lockout counter resets on every attempt and brute-force
            # protection silently does nothing.
            await record_failed_login(user_id=user.id)
            await record_security_event(
                action=AuditAction.LOGIN_FAILED,
                actor_id=user.id,
                actor_label=user.email,
                resource="user",
                resource_id=str(user.id),
                description="Failed login attempt.",
                request_id=request_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise InvalidCredentialsError()

        if not user.is_active:
            raise InactiveAccountError()

        if password_needs_rehash(user.password_hash):
            await self.users.set_password(user, hash_password(password))
        await self.users.record_login(user)

        membership = await self.memberships.default_for_user(user.id)
        merchant_id = membership.merchant_id if membership else None

        await self.audit.record(
            action=AuditAction.LOGIN,
            merchant_id=merchant_id,
            actor_id=user.id,
            actor_label=user.email,
            resource="user",
            resource_id=str(user.id),
            description="Signed in.",
            request_id=request_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        log.info("user_login", user_id=str(user.id))
        return await self._issue_session(
            user, merchant_id=merchant_id, ip_address=ip_address, user_agent=user_agent
        )

    # ------------------------------------------------------------------ refresh
    async def refresh(
        self,
        raw_token: str,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
    ) -> AuthSession:
        stored = await self.tokens.get_by_hash(hash_refresh_token(raw_token))
        if stored is None:
            raise InvalidTokenError("This session is no longer valid. Please sign in again.")

        if stored.revoked_at is not None:
            # Replay of an already-rotated token: assume compromise, kill the family.
            # Written on its own connection so it survives the rollback caused by
            # the rejection below.
            revoked = await revoke_token_family(stored.family_id, reason="reuse_detected")
            await self.audit.record(
                action=AuditAction.TOKEN_REUSE_DETECTED,
                actor_id=stored.user_id,
                actor_type=ActorType.SYSTEM,
                resource="refresh_token",
                resource_id=str(stored.id),
                description="Refresh token reuse detected. Token family revoked.",
                status="FAILURE",
                request_id=request_id,
                ip_address=ip_address,
                metadata={"revoked_tokens": revoked},
            )
            log.warning("refresh_token_reuse", user_id=str(stored.user_id), revoked=revoked)
            raise InvalidTokenError("This session has been revoked. Please sign in again.")

        if stored.expires_at <= datetime.now(tz=UTC):
            await self.tokens.revoke(stored, reason="expired")
            raise InvalidTokenError("Your session has expired. Please sign in again.")

        user = await self.users.get_with_memberships(stored.user_id)
        if user is None or not user.is_active:
            raise InactiveAccountError()

        membership = await self.memberships.default_for_user(user.id)
        session = await self._issue_session(
            user,
            merchant_id=membership.merchant_id if membership else None,
            family_id=stored.family_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        # Rotate: the presented token is retired and points at its replacement.
        new_token = await self.tokens.get_by_hash(
            hash_refresh_token(session.tokens.refresh_token or "")
        )
        await self.tokens.revoke(
            stored, reason="rotated", replaced_by=new_token.id if new_token else None
        )
        await self.audit.record(
            action=AuditAction.TOKEN_REFRESHED,
            merchant_id=membership.merchant_id if membership else None,
            actor_id=user.id,
            actor_label=user.email,
            resource="refresh_token",
            resource_id=str(stored.id),
            description="Access token refreshed.",
            request_id=request_id,
            ip_address=ip_address,
        )
        return session

    # ------------------------------------------------------------------ logout
    async def logout(
        self,
        raw_token: str | None,
        *,
        user_id: uuid.UUID | None = None,
        all_sessions: bool = False,
        request_id: str | None = None,
    ) -> None:
        if all_sessions and user_id:
            await self.tokens.revoke_all_for_user(user_id, reason="logout_all")
        elif raw_token:
            stored = await self.tokens.get_by_hash(hash_refresh_token(raw_token))
            if stored is not None and stored.revoked_at is None:
                await self.tokens.revoke(stored, reason="logout")
        if user_id:
            await self.audit.record(
                action=AuditAction.LOGOUT,
                actor_id=user_id,
                resource="user",
                resource_id=str(user_id),
                description="Signed out.",
                request_id=request_id,
            )
        log.info("user_logout", user_id=str(user_id) if user_id else None)

    # ------------------------------------------------------------------ passwords
    async def change_password(
        self, user: User, *, current_password: str, new_password: str
    ) -> None:
        if not verify_password(current_password, user.password_hash):
            raise InvalidCredentialsError("Your current password is incorrect.")
        if current_password == new_password:
            raise ValidationError("The new password must be different from the current one.")
        await self.users.set_password(user, hash_password(new_password))
        await self.tokens.revoke_all_for_user(user.id, reason="password_changed")
        await self.audit.record(
            action=AuditAction.PASSWORD_CHANGED,
            actor_id=user.id,
            actor_label=user.email,
            resource="user",
            resource_id=str(user.id),
            description="Password changed. All sessions revoked.",
        )

    async def reset_password(self, user_id: uuid.UUID, new_password: str) -> None:
        user = await self.users.get(user_id)
        if user is None:
            raise NotFoundError("Account not found.")
        await self.users.set_password(user, hash_password(new_password))
        await self.tokens.revoke_all_for_user(user.id, reason="password_reset")
        await self.audit.record(
            action=AuditAction.PASSWORD_CHANGED,
            actor_id=user.id,
            resource="user",
            resource_id=str(user.id),
            description="Password reset completed.",
        )

    # ------------------------------------------------------------------ membership
    async def invite_user(
        self,
        *,
        merchant_id: uuid.UUID,
        email: str,
        full_name: str,
        role: Role,
        temporary_password: str,
        invited_by: User,
    ) -> User:
        email = email.lower().strip()
        existing = await self.users.get_by_email(email)
        if existing is None:
            existing = await self.users.create(
                email=email,
                password_hash=hash_password(temporary_password),
                full_name=full_name.strip(),
                status=UserStatus.ACTIVE,
            )
        else:
            current = await self.memberships.get_for_user_and_merchant(existing.id, merchant_id)
            if current is not None:
                raise ConflictError("This user already has access to this merchant.")

        await self.memberships.create(
            user_id=existing.id,
            merchant_id=merchant_id,
            role=role,
            status=MembershipStatus.ACTIVE,
            invited_by_id=invited_by.id,
            joined_at=datetime.now(tz=UTC),
        )
        await self.audit.record(
            action=AuditAction.USER_CREATED,
            merchant_id=merchant_id,
            actor_id=invited_by.id,
            actor_label=invited_by.email,
            resource="user",
            resource_id=str(existing.id),
            description=f"User invited as {role}.",
            metadata={"role": str(role)},
        )
        return existing

    async def change_role(
        self, *, merchant_id: uuid.UUID, user_id: uuid.UUID, role: Role, actor: User
    ) -> MerchantMembership:
        membership = await self.memberships.get_for_user_and_merchant(user_id, merchant_id)
        if membership is None:
            raise NotFoundError("This user is not a member of this merchant.")

        # Never let the last owner be demoted - it would orphan the account.
        demoting_an_owner = membership.role == Role.OWNER and role != Role.OWNER
        if demoting_an_owner and await self.memberships.count_owners(merchant_id) <= 1:
            raise PermissionDeniedError(
                "This is the only owner of this merchant. Promote another owner first."
            )
        previous = membership.role
        membership.role = role
        await self.session.flush()

        await self.audit.record(
            action=AuditAction.ROLE_CHANGED,
            merchant_id=merchant_id,
            actor_id=actor.id,
            actor_label=actor.email,
            resource="merchant_membership",
            resource_id=str(membership.id),
            description=f"Role changed from {previous} to {role}.",
            metadata={"from": previous, "to": str(role)},
        )
        log.info("role_changed", user_id=str(user_id), role=str(role))
        return membership

    # ------------------------------------------------------------------ sessions
    async def _issue_session(
        self,
        user: User,
        *,
        merchant_id: uuid.UUID | None,
        family_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuthSession:
        memberships = await self.memberships.list_for_user(user.id)
        active = next((m for m in memberships if m.merchant_id == merchant_id), None)
        if active is None and memberships:
            active = memberships[0]

        roles = [active.role] if active else []
        access_token, expires_at = create_access_token(
            user.id,
            merchant_id=active.merchant_id if active else None,
            roles=roles,
        )
        refresh: RefreshTokenValue = generate_refresh_token(family_id=family_id)
        self.session.add(
            RefreshToken(
                user_id=user.id,
                token_hash=refresh.token_hash,
                family_id=refresh.family_id,
                expires_at=refresh.expires_at,
                ip_address=ip_address,
                user_agent=(user_agent or "")[:256] or None,
            )
        )
        await self.session.flush()

        return AuthSession(
            tokens=TokenPair(
                access_token=access_token,
                expires_in=settings.jwt_access_token_expire_minutes * 60,
                expires_at=expires_at,
                refresh_token=refresh.token,
            ),
            user=self.build_current_user(
                user,
                memberships,
                active,
                permissions=(
                    await CustomRoleRepository(self.session).permissions_for(
                        active.merchant_id, active.role
                    )
                    if active
                    else None
                ),
            ),
        )

    @staticmethod
    def build_current_user(
        user: User,
        memberships: list[MerchantMembership],
        active: MerchantMembership | None,
        permissions: frozenset[str] | None = None,
    ) -> CurrentUser:
        """Shape the signed-in user for the client.

        ``permissions`` is passed in by callers that can resolve a merchant-defined
        role against the database. Without it we fall back to the built-in map, so
        a custom role reports no permissions rather than guessing at some.
        """
        if permissions is None:
            resolved = (
                sorted(str(p) for p in permissions_for_role(active.role)) if active else []
            )
        else:
            resolved = sorted(permissions)
        return CurrentUser(
            user=UserOut.model_validate(user),
            active_merchant=(MerchantSummary.model_validate(active.merchant) if active else None),
            role=active.role if active else None,
            permissions=resolved,
            memberships=[
                MembershipOut(
                    merchant=MerchantSummary.model_validate(m.merchant),
                    role=m.role,
                    status=m.status,
                    is_default=m.is_default,
                    joined_at=m.joined_at,
                )
                for m in memberships
            ],
        )
