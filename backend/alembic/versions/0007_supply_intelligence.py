"""supply intelligence: product discovery history, discovered products, comparisons,
merchant recommendations and shopping conversations

Revision ID: 0007_supply_intelligence
Revises: 0006_integration_deliveries
Create Date: 2026-11-06 10:00:00.000000

Additive only - no existing table is altered, so it is safe on a database that already
holds production or demo data.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db.types

revision: str = "0007_supply_intelligence"
down_revision: str | None = "0006_integration_deliveries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", app.db.types.UTCDateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", app.db.types.UTCDateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
    ]


def _merchant_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], name=op.f(f"fk_{table}_merchant_id_merchants"),
                                   ondelete="CASCADE")


def upgrade() -> None:
    op.create_table(
        "product_searches",
        sa.Column("id", app.db.types.GUID(), nullable=False),
        sa.Column("merchant_id", app.db.types.GUID(), nullable=False),
        sa.Column("user_id", app.db.types.GUID(), nullable=True),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("intent", app.db.types.JSONB(), nullable=False),
        sa.Column("request", app.db.types.JSONB(), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("product_ids", app.db.types.JSONB(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("used_llm", sa.Boolean(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("agent_run_id", app.db.types.GUID(), nullable=True),
        *_timestamps(),
        _merchant_fk("product_searches"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_searches")),
    )
    with op.batch_alter_table("product_searches", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_product_searches_merchant_id"), ["merchant_id"], unique=False)
        batch_op.create_index("ix_product_searches_merchant_created", ["merchant_id", "created_at"], unique=False)

    op.create_table(
        "discovered_products",
        sa.Column("id", app.db.types.GUID(), nullable=False),
        sa.Column("merchant_id", app.db.types.GUID(), nullable=False),
        sa.Column("channel3_product_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("brand", sa.String(length=120), nullable=False),
        sa.Column("category_slug", sa.String(length=80), nullable=False),
        sa.Column("category_title", sa.String(length=120), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("min_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("max_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("offers_count", sa.Integer(), nullable=False),
        sa.Column("retailer", sa.String(length=120), nullable=False),
        sa.Column("in_stock", sa.Boolean(), nullable=True),
        sa.Column("snapshot", app.db.types.JSONB(), nullable=False),
        sa.Column("first_seen_at", app.db.types.UTCDateTime(), nullable=False),
        sa.Column("last_seen_at", app.db.types.UTCDateTime(), nullable=False),
        sa.Column("times_seen", sa.Integer(), nullable=False),
        sa.Column("last_source", sa.String(length=24), nullable=False),
        sa.Column("is_shortlisted", sa.Boolean(), nullable=False),
        *_timestamps(),
        _merchant_fk("discovered_products"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_discovered_products")),
        sa.UniqueConstraint("merchant_id", "channel3_product_id", name="uq_discovered_products_product"),
    )
    with op.batch_alter_table("discovered_products", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_discovered_products_merchant_id"), ["merchant_id"], unique=False)
        batch_op.create_index("ix_discovered_products_merchant_seen", ["merchant_id", "last_seen_at"], unique=False)

    op.create_table(
        "product_comparisons",
        sa.Column("id", app.db.types.GUID(), nullable=False),
        sa.Column("merchant_id", app.db.types.GUID(), nullable=False),
        sa.Column("user_id", app.db.types.GUID(), nullable=True),
        sa.Column("product_ids", app.db.types.JSONB(), nullable=False),
        sa.Column("titles", app.db.types.JSONB(), nullable=False),
        sa.Column("analysis", app.db.types.JSONB(), nullable=False),
        sa.Column("narrative", sa.Text(), nullable=False),
        sa.Column("used_llm", sa.Boolean(), nullable=False),
        *_timestamps(),
        _merchant_fk("product_comparisons"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_comparisons")),
    )
    with op.batch_alter_table("product_comparisons", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_product_comparisons_merchant_id"), ["merchant_id"], unique=False)
        batch_op.create_index("ix_product_comparisons_merchant_created", ["merchant_id", "created_at"], unique=False)

    op.create_table(
        "merchant_recommendations",
        sa.Column("id", app.db.types.GUID(), nullable=False),
        sa.Column("merchant_id", app.db.types.GUID(), nullable=False),
        sa.Column("reference", sa.String(length=24), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("evidence", app.db.types.JSONB(), nullable=False),
        sa.Column("recommended_action", sa.Text(), nullable=False),
        sa.Column("expected_impact", app.db.types.JSONB(), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("confidence_reasons", app.db.types.JSONB(), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("lifecycle", app.db.types.JSONB(), nullable=False),
        sa.Column("anchor_product_id", app.db.types.GUID(), nullable=True),
        sa.Column("anchor_product_name", sa.String(length=160), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=False),
        sa.Column("products", app.db.types.JSONB(), nullable=False),
        sa.Column("suggested_test_quantity", sa.Integer(), nullable=True),
        sa.Column("suggested_retail_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("narrative_source", sa.String(length=16), nullable=False),
        sa.Column("dedupe_key", sa.String(length=160), nullable=False),
        sa.Column("agent_run_id", app.db.types.GUID(), nullable=True),
        sa.Column("decided_by_id", app.db.types.GUID(), nullable=True),
        sa.Column("decided_by_label", sa.String(length=160), nullable=False),
        sa.Column("decided_at", app.db.types.UTCDateTime(), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=False),
        sa.Column("executed_at", app.db.types.UTCDateTime(), nullable=True),
        sa.Column("execution", app.db.types.JSONB(), nullable=False),
        sa.Column("measured_at", app.db.types.UTCDateTime(), nullable=True),
        sa.Column("measurement", app.db.types.JSONB(), nullable=False),
        *_timestamps(),
        _merchant_fk("merchant_recommendations"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_merchant_recommendations")),
    )
    with op.batch_alter_table("merchant_recommendations", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_merchant_recommendations_merchant_id"), ["merchant_id"], unique=False)
        batch_op.create_index("ix_merchant_recommendations_merchant_status", ["merchant_id", "status"], unique=False)
        batch_op.create_index("ix_merchant_recommendations_dedupe", ["merchant_id", "dedupe_key"], unique=False)

    op.create_table(
        "shopping_conversations",
        sa.Column("id", app.db.types.GUID(), nullable=False),
        sa.Column("merchant_id", app.db.types.GUID(), nullable=False),
        sa.Column("user_id", app.db.types.GUID(), nullable=True),
        sa.Column("channel3_conversation_id", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("constraints", app.db.types.JSONB(), nullable=False),
        sa.Column("messages", app.db.types.JSONB(), nullable=False),
        sa.Column("turn_count", sa.Integer(), nullable=False),
        sa.Column("credits_used", sa.Integer(), nullable=False),
        sa.Column("last_turn_at", app.db.types.UTCDateTime(), nullable=True),
        *_timestamps(),
        _merchant_fk("shopping_conversations"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shopping_conversations")),
    )
    with op.batch_alter_table("shopping_conversations", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_shopping_conversations_merchant_id"), ["merchant_id"], unique=False)
        batch_op.create_index("ix_shopping_conversations_merchant_updated", ["merchant_id", "updated_at"], unique=False)


def downgrade() -> None:
    for table, indexes in (
        ("shopping_conversations", ("ix_shopping_conversations_merchant_updated", "ix_shopping_conversations_merchant_id")),
        ("merchant_recommendations", ("ix_merchant_recommendations_dedupe", "ix_merchant_recommendations_merchant_status",
                                      "ix_merchant_recommendations_merchant_id")),
        ("product_comparisons", ("ix_product_comparisons_merchant_created", "ix_product_comparisons_merchant_id")),
        ("discovered_products", ("ix_discovered_products_merchant_seen", "ix_discovered_products_merchant_id")),
        ("product_searches", ("ix_product_searches_merchant_created", "ix_product_searches_merchant_id")),
    ):
        with op.batch_alter_table(table, schema=None) as batch_op:
            for index in indexes:
                batch_op.drop_index(index)
        op.drop_table(table)
