"""User, role, permission and refresh-token repositories."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.permissions import ALL_PERMISSIONS, permissions_for_role
from app.db.models.auth import CustomRole, Permission, RefreshToken, Role, User, UserStatus
from app.db.models.merchant import MerchantMembership
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_email(self, email: str) -> User | None:
        stmt = (
            select(User)
            .where(User.email == email.lower().strip())
            .options(selectinload(User.memberships).selectinload(MerchantMembership.merchant))
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def get_with_memberships(self, user_id: uuid.UUID) -> User | None:
        stmt = (
            select(User)
            .where(User.id == user_id)
            .options(selectinload(User.memberships).selectinload(MerchantMembership.merchant))
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def email_exists(self, email: str) -> bool:
        stmt = select(User.id).where(User.email == email.lower().strip())
        return (await self.session.execute(stmt)).first() is not None

    async def record_login(self, user: User) -> None:
        user.last_login_at = datetime.now(tz=UTC)
        user.failed_login_attempts = 0
        user.locked_until = None
        await self.session.flush()

    async def record_failed_login(self, user: User, *, max_attempts: int = 8) -> None:
        """Soft account lock: slows credential stuffing without locking people out for long."""
        from datetime import timedelta

        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        if user.failed_login_attempts >= max_attempts:
            user.locked_until = datetime.now(tz=UTC) + timedelta(minutes=15)
        await self.session.flush()

    def is_locked(self, user: User) -> bool:
        return bool(user.locked_until and user.locked_until > datetime.now(tz=UTC))

    async def set_password(self, user: User, password_hash: str) -> None:
        user.password_hash = password_hash
        user.failed_login_attempts = 0
        user.locked_until = None
        await self.session.flush()

    async def list_for_merchant(self, merchant_id: uuid.UUID) -> list[tuple[User, str]]:
        stmt = (
            select(User, MerchantMembership.role)
            .join(MerchantMembership, MerchantMembership.user_id == User.id)
            .where(MerchantMembership.merchant_id == merchant_id)
            .where(User.status != UserStatus.DISABLED)
            .order_by(User.full_name)
        )
        return [(row[0], row[1]) for row in (await self.session.execute(stmt)).all()]


class RoleRepository(BaseRepository[Role]):
    model = Role

    async def get_by_name(self, name: str) -> Role | None:
        stmt = select(Role).where(Role.name == name).options(selectinload(Role.permissions))
        return (await self.session.execute(stmt)).scalars().first()

    async def list_with_permissions(self) -> list[Role]:
        stmt = select(Role).options(selectinload(Role.permissions)).order_by(Role.name)
        return list((await self.session.execute(stmt)).scalars().all())


class PermissionRepository(BaseRepository[Permission]):
    model = Permission

    async def get_by_code(self, code: str) -> Permission | None:
        stmt = select(Permission).where(Permission.code == code)
        return (await self.session.execute(stmt)).scalars().first()

    async def list_codes(self) -> list[str]:
        stmt = select(Permission.code).order_by(Permission.code)
        return [row[0] for row in (await self.session.execute(stmt)).all()]


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    model = RefreshToken

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        return (await self.session.execute(stmt)).scalars().first()

    async def revoke(
        self, token: RefreshToken, *, reason: str, replaced_by: uuid.UUID | None = None
    ) -> None:
        token.revoked_at = datetime.now(tz=UTC)
        token.revoked_reason = reason
        token.replaced_by_id = replaced_by
        await self.session.flush()

    async def revoke_family(self, family_id: str, *, reason: str) -> int:
        """Revoke every token in a rotation chain - the response to replay detection."""
        stmt = select(RefreshToken).where(
            RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None)
        )
        tokens = list((await self.session.execute(stmt)).scalars().all())
        now = datetime.now(tz=UTC)
        for token in tokens:
            token.revoked_at = now
            token.revoked_reason = reason
        await self.session.flush()
        return len(tokens)

    async def revoke_all_for_user(self, user_id: uuid.UUID, *, reason: str) -> int:
        stmt = select(RefreshToken).where(
            RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
        )
        tokens = list((await self.session.execute(stmt)).scalars().all())
        now = datetime.now(tz=UTC)
        for token in tokens:
            token.revoked_at = now
            token.revoked_reason = reason
        await self.session.flush()
        return len(tokens)

    async def purge_expired(self) -> int:
        from sqlalchemy import delete

        stmt = delete(RefreshToken).where(RefreshToken.expires_at < datetime.now(tz=UTC))
        return int((await self.session.execute(stmt)).rowcount or 0)


class CustomRoleRepository(BaseRepository[CustomRole]):
    """Merchant-defined roles.

    The single place that turns a role *name* into a permission set, so the
    request path, the login response and any background caller can never drift
    apart on what a role is allowed to do.
    """

    model = CustomRole

    async def list_for_merchant(self, merchant_id: uuid.UUID) -> list[CustomRole]:
        stmt = (
            select(CustomRole)
            .where(CustomRole.merchant_id == merchant_id)
            .order_by(CustomRole.name)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_by_name(self, merchant_id: uuid.UUID, name: str) -> CustomRole | None:
        stmt = select(CustomRole).where(
            CustomRole.merchant_id == merchant_id, CustomRole.name == name
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def permissions_for(self, merchant_id: uuid.UUID, role: str) -> frozenset[str]:
        """Built-in roles resolve from code; anything else from this merchant's rows.

        A name that resolves to nothing yields an empty set, so an unknown or
        deleted role can do nothing at all.
        """
        builtin = permissions_for_role(role)
        if builtin:
            return frozenset(str(p) for p in builtin)

        stmt = select(CustomRole.permission_codes).where(
            CustomRole.merchant_id == merchant_id, CustomRole.name == role
        )
        codes = (await self.session.execute(stmt)).scalar_one_or_none()
        if not codes:
            return frozenset()

        # Re-validated on every read: a permission dropped from the enum since the
        # role was created must stop granting access immediately.
        catalogue = {str(p) for p in ALL_PERMISSIONS}
        return frozenset(code for code in codes if code in catalogue)
