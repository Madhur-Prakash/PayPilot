"""integration deliveries: per-target outbound delivery state (Zapier)

Revision ID: 0006_integration_deliveries
Revises: 0005_supply_paypal_memory
Create Date: 2026-11-04 22:40:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db.types  # noqa: F401

revision: str = '0006_integration_deliveries'
down_revision: str | None = '0005_supply_paypal_memory'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('integration_deliveries',
    sa.Column('id', app.db.types.GUID(), nullable=False),
    sa.Column('merchant_id', app.db.types.GUID(), nullable=False),
    sa.Column('event_id', app.db.types.GUID(), nullable=False),
    sa.Column('target', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('next_attempt_at', app.db.types.UTCDateTime(), nullable=True),
    sa.Column('delivered_at', app.db.types.UTCDateTime(), nullable=True),
    sa.Column('http_status', sa.Integer(), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=False),
    sa.Column('created_at', app.db.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', app.db.types.UTCDateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['event_id'], ['domain_events.id'], name=op.f('fk_integration_deliveries_event_id_domain_events'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['merchant_id'], ['merchants.id'], name=op.f('fk_integration_deliveries_merchant_id_merchants'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_integration_deliveries')),
    sa.UniqueConstraint('event_id', 'target', name='uq_integration_deliveries_event_target')
    )
    with op.batch_alter_table('integration_deliveries', schema=None) as batch_op:
        batch_op.create_index('ix_integration_deliveries_due', ['target', 'status', 'next_attempt_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_integration_deliveries_merchant_id'), ['merchant_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('integration_deliveries', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_integration_deliveries_merchant_id'))
        batch_op.drop_index('ix_integration_deliveries_due')
    op.drop_table('integration_deliveries')
