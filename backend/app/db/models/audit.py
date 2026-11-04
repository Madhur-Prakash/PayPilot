"""Append-only audit log."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import BaseModel
from app.db.types import GUID, JSONB


class AuditAction:
    LOGIN = "LOGIN"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGOUT = "LOGOUT"
    TOKEN_REFRESHED = "TOKEN_REFRESHED"
    TOKEN_REUSE_DETECTED = "TOKEN_REUSE_DETECTED"
    PASSWORD_RESET_REQUESTED = "PASSWORD_RESET_REQUESTED"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"

    USER_CREATED = "USER_CREATED"
    ROLE_CHANGED = "ROLE_CHANGED"
    MEMBERSHIP_REVOKED = "MEMBERSHIP_REVOKED"

    CAMPAIGN_CREATED = "CAMPAIGN_CREATED"
    CAMPAIGN_APPROVED = "CAMPAIGN_APPROVED"
    CAMPAIGN_REJECTED = "CAMPAIGN_REJECTED"
    CAMPAIGN_EXECUTED = "CAMPAIGN_EXECUTED"

    EXPERIMENT_CREATED = "EXPERIMENT_CREATED"
    EXPERIMENT_STARTED = "EXPERIMENT_STARTED"
    EXPERIMENT_COMPLETED = "EXPERIMENT_COMPLETED"
    EXPERIMENT_STOPPED = "EXPERIMENT_STOPPED"

    OPPORTUNITY_DETECTED = "OPPORTUNITY_DETECTED"
    OPPORTUNITY_DISMISSED = "OPPORTUNITY_DISMISSED"

    AGENT_RUN = "AGENT_RUN"
    AGENT_ACTION = "AGENT_ACTION"
    INVENTORY_ACTION = "INVENTORY_ACTION"

    PROCUREMENT_REQUESTED = "PROCUREMENT_REQUESTED"
    NEGOTIATION_COMPLETED = "NEGOTIATION_COMPLETED"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVAL_GRANTED = "APPROVAL_GRANTED"
    APPROVAL_REJECTED = "APPROVAL_REJECTED"
    APPROVAL_INVALIDATED = "APPROVAL_INVALIDATED"
    PURCHASE_ORDER_CREATED = "PURCHASE_ORDER_CREATED"
    GOODS_RECEIVED = "GOODS_RECEIVED"
    INVOICE_MATCHED = "INVOICE_MATCHED"
    PAYMENT_EXECUTED = "PAYMENT_EXECUTED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    PROCUREMENT_RECONCILED = "PROCUREMENT_RECONCILED"
    PAYPAL_SYNC = "PAYPAL_SYNC"
    PAYPAL_WEBHOOK = "PAYPAL_WEBHOOK"
    PAYPAL_INVOICE_SENT = "PAYPAL_INVOICE_SENT"
    INTEGRATION_ACTION = "INTEGRATION_ACTION"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    MERCHANT_SCOPE_VIOLATION = "MERCHANT_SCOPE_VIOLATION"


class ActorType:
    USER = "USER"
    AGENT = "AGENT"
    SYSTEM = "SYSTEM"
    ANONYMOUS = "ANONYMOUS"


class AuditLog(BaseModel):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_merchant_created", "merchant_id", "created_at"),
        Index("ix_audit_logs_action", "action"),
        Index("ix_audit_logs_actor", "actor_id", "created_at"),
    )

    merchant_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), index=True)
    actor_type: Mapped[str] = mapped_column(String(16), default=ActorType.USER, nullable=False)
    actor_label: Mapped[str] = mapped_column(String(160), default="", nullable=False)

    action: Mapped[str] = mapped_column(String(48), nullable=False)
    resource: Mapped[str] = mapped_column(String(48), default="", nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(64), index=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="SUCCESS", nullable=False)

    request_id: Mapped[str | None] = mapped_column(String(64))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(256))
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
