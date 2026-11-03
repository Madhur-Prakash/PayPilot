"""Auth, user, role and membership schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import EmailStr, Field, field_validator

from app.core.permissions import Role
from app.schemas.common import SchemaBase


class RegisterRequest(SchemaBase):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field(min_length=2, max_length=160)
    #: Optional - when omitted a personal merchant workspace is created for the user.
    merchant_name: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=32)

    @field_validator("email")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.lower().strip()


class LoginRequest(SchemaBase):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.lower().strip()


class RefreshRequest(SchemaBase):
    """Body is optional: the refresh token normally arrives in an HttpOnly cookie."""

    refresh_token: str | None = None


class PasswordResetRequest(SchemaBase):
    email: EmailStr


class PasswordResetConfirm(SchemaBase):
    token: str
    new_password: str = Field(min_length=10, max_length=128)


class ChangePasswordRequest(SchemaBase):
    current_password: str
    new_password: str = Field(min_length=10, max_length=128)


class TokenPair(SchemaBase):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    expires_at: datetime
    #: Also returned in the body so non-browser clients can use the API.
    refresh_token: str | None = None


class MerchantSummary(SchemaBase):
    id: uuid.UUID
    name: str
    slug: str
    category: str
    city: str
    currency: str
    logo_url: str | None = None
    is_demo: bool = False
    data_source: str = "SEEDED"


class MembershipOut(SchemaBase):
    merchant: MerchantSummary
    #: Built-in or merchant-defined role name.
    role: str
    status: str
    is_default: bool = False
    joined_at: datetime | None = None


class UserOut(SchemaBase):
    id: uuid.UUID
    email: EmailStr
    full_name: str
    phone: str | None = None
    avatar_url: str | None = None
    status: str
    email_verified: bool = False
    last_login_at: datetime | None = None
    created_at: datetime


class CurrentUser(SchemaBase):
    """Everything the frontend needs to render the shell and gate UI affordances.

    The frontend uses `permissions` only to hide controls. The backend re-checks
    every permission on every request.
    """

    user: UserOut
    active_merchant: MerchantSummary | None = None
    #: Built-in or merchant-defined role name.
    role: str | None = None
    permissions: list[str] = Field(default_factory=list)
    memberships: list[MembershipOut] = Field(default_factory=list)


class AuthSession(SchemaBase):
    tokens: TokenPair
    user: CurrentUser


class RoleOut(SchemaBase):
    #: A built-in role name, or a merchant-defined one. Plain `str` because a
    #: custom role is not a member of the `Role` enum.
    name: str
    description: str
    permissions: list[str] = Field(default_factory=list)
    is_custom: bool = False
    id: uuid.UUID | None = None


class CustomRoleCreateRequest(SchemaBase):
    """A merchant-defined role.

    `permissions` is validated against the Permission enum server-side, and a
    creator can never grant a permission they do not themselves hold.
    """

    name: str = Field(min_length=2, max_length=32, pattern=r"^[A-Za-z][A-Za-z0-9 _-]*$")
    description: str = Field(default="", max_length=500)
    permissions: list[str] = Field(min_length=1)


class PermissionOut(SchemaBase):
    code: str
    resource: str
    action: str
    description: str


class UpdateProfileRequest(SchemaBase):
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    phone: str | None = Field(default=None, max_length=32)
    avatar_url: str | None = None


class InviteUserRequest(SchemaBase):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=160)
    #: Built-in role name or one of this merchant's custom roles. Checked server-side.
    role: str = Field(default=str(Role.VIEWER), max_length=32)
    temporary_password: str = Field(min_length=10, max_length=128)


class ChangeRoleRequest(SchemaBase):
    user_id: uuid.UUID
    #: Built-in role name or one of this merchant's custom roles. Checked server-side.
    role: str = Field(max_length=32)
