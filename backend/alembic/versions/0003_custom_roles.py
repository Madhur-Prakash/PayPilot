"""Merchant-defined custom roles.

Built-in roles stay in code. This table holds the per-merchant roles an owner
creates, with an explicit permission set that is validated against the Permission
enum before it is stored.

Revision ID: 0003_custom_roles
Revises: 0002_widen_decision
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db.types

revision: str = "0003_custom_roles"
down_revision: str | None = "0002_widen_decision"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "custom_roles",
        sa.Column("id", app.db.types.GUID(), nullable=False),
        sa.Column("created_at", app.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at", app.db.types.UTCDateTime(), nullable=False),
        sa.Column("merchant_id", app.db.types.GUID(), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("permission_codes", app.db.types.StringArray(), nullable=False),
        sa.Column("created_by_id", app.db.types.GUID(), nullable=True),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("merchant_id", "name", name="uq_custom_roles_merchant_name"),
    )
    op.create_index("ix_custom_roles_merchant", "custom_roles", ["merchant_id"])
    op.create_index(
        op.f("ix_custom_roles_merchant_id"), "custom_roles", ["merchant_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_custom_roles_merchant_id"), table_name="custom_roles")
    op.drop_index("ix_custom_roles_merchant", table_name="custom_roles")
    op.drop_table("custom_roles")
