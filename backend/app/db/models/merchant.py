"""Merchants and the memberships that bind a user to a merchant with a role.

Every tenant-scoped table carries ``merchant_id``; every query goes through a
repository that filters on it. Membership is the single source of truth for
"may this user see this merchant at all".
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import BaseModel
from app.db.types import GUID, JSONB, UTCDateTime

if TYPE_CHECKING:
    from app.db.models.auth import User


class Merchant(BaseModel):
    __tablename__ = "merchants"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_merchants_slug"),
        Index("ix_merchants_category", "category"),
    )

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    legal_name: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(64), default="cafe", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    city: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    state: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    country: Mapped[str] = mapped_column(String(80), default="United States", nullable=False)
    address: Mapped[str] = mapped_column(Text, default="", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="America/Los_Angeles", nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    locale: Mapped[str] = mapped_column(String(16), default="en-US", nullable=False)

    contact_email: Mapped[str | None] = mapped_column(String(320))
    contact_phone: Mapped[str | None] = mapped_column(String(32))
    logo_url: Mapped[str | None] = mapped_column(Text)

    monthly_target_revenue: Mapped[float | None] = mapped_column(Numeric(14, 2))
    opened_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    #: True for tenants not yet connected to a live PayPal merchant account.
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: Internal provenance token (not shown to users verbatim - the UI maps it to a label).
    data_source: Mapped[str] = mapped_column(String(32), default="SEEDED", nullable=False)
    settings_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    memberships: Mapped[list[MerchantMembership]] = relationship(
        back_populates="merchant", cascade="all, delete-orphan"
    )


class MembershipStatus:
    ACTIVE = "ACTIVE"
    INVITED = "INVITED"
    REVOKED = "REVOKED"


class MerchantMembership(BaseModel):
    __tablename__ = "merchant_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "merchant_id", name="uq_membership_user_merchant"),
        Index("ix_membership_merchant_status", "merchant_id", "status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default=MembershipStatus.ACTIVE, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    invited_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    joined_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    user: Mapped[User] = relationship(back_populates="memberships")
    merchant: Mapped[Merchant] = relationship(back_populates="memberships", lazy="selectin")

    @property
    def is_active(self) -> bool:
        return self.status == MembershipStatus.ACTIVE
