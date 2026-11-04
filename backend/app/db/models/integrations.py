"""Outbound integration deliveries (Zapier and friends).

The transactional outbox (``domain_events``) tracks delivery to *one* target, n8n.
A second target must not piggy-back on that row's status - a Zapier outage would
otherwise re-deliver to n8n, or the reverse - so each (event, target) pair gets
its own row here. ``UNIQUE(event_id, target)`` is the idempotency guarantee: an
event is delivered to a target at most once, however often the relay ticks.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import BaseModel
from app.db.types import GUID, UTCDateTime


class DeliveryTarget:
    ZAPIER = "ZAPIER"


class IntegrationDeliveryStatus:
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


class IntegrationDelivery(BaseModel):
    __tablename__ = "integration_deliveries"
    __table_args__ = (
        UniqueConstraint("event_id", "target", name="uq_integration_deliveries_event_target"),
        Index("ix_integration_deliveries_due", "target", "status", "next_attempt_at"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("domain_events.id", ondelete="CASCADE"), nullable=False
    )
    target: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=IntegrationDeliveryStatus.PENDING, nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    http_status: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
