"""Dual-market campaign fields (Growth Allocation Engine).

Adds the BUSINESS / PAYPAL / HYBRID surface split to `campaigns`. Every column is
additive with a backwards-compatible default - `surface` defaults to BUSINESS,
which is accurate for every campaign created before this migration (they were
all merchant-funded). No existing column is touched.

Revision ID: 0004_dual_market_campaigns
Revises: a7b8cba56c55
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_dual_market_campaigns"
down_revision: str | None = "a7b8cba56c55"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column("surface", sa.String(length=16), nullable=False, server_default="BUSINESS"),
    )
    op.add_column(
        "campaigns",
        sa.Column("objective_type", sa.String(length=32), nullable=False, server_default=""),
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "business_budget", sa.Numeric(14, 2), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "campaigns",
        sa.Column("paypal_budget", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "campaigns",
        sa.Column("paypal_surface", sa.String(length=24), nullable=False, server_default=""),
    )
    op.add_column("campaigns", sa.Column("expected_incremental_revenue", sa.Numeric(14, 2)))
    op.add_column("campaigns", sa.Column("actual_incremental_revenue", sa.Numeric(14, 2)))
    op.add_column("campaigns", sa.Column("incremental_roi", sa.Numeric(10, 4)))
    op.add_column(
        "campaigns",
        sa.Column("measurement_status", sa.String(length=16), nullable=False, server_default=""),
    )
    op.add_column(
        "campaigns",
        sa.Column("created_by_agent", sa.String(length=48), nullable=False, server_default=""),
    )
    op.create_index("ix_campaigns_merchant_surface", "campaigns", ["merchant_id", "surface"])


def downgrade() -> None:
    op.drop_index("ix_campaigns_merchant_surface", table_name="campaigns")
    op.drop_column("campaigns", "created_by_agent")
    op.drop_column("campaigns", "measurement_status")
    op.drop_column("campaigns", "incremental_roi")
    op.drop_column("campaigns", "actual_incremental_revenue")
    op.drop_column("campaigns", "expected_incremental_revenue")
    op.drop_column("campaigns", "paypal_surface")
    op.drop_column("campaigns", "paypal_budget")
    op.drop_column("campaigns", "business_budget")
    op.drop_column("campaigns", "objective_type")
    op.drop_column("campaigns", "surface")
