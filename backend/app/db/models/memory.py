"""Agent long-term memory, stored in Postgres with pgvector.

One row per memory. ``embedding`` is a pgvector column on Postgres (cosine search
with the ``<=>`` operator, HNSW-indexed by the migration) and a JSON list on
SQLite, where recall falls back to in-Python cosine. ``tags`` are the lightweight
graph: every memory is linked to the entities it is about (a SKU, a supplier
agent key, an opportunity slug), so recall can follow an entity as well as a
meaning.

Every row is merchant-scoped and every query filters on ``merchant_id`` - there is
no code path that reads memory without a merchant.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import BaseModel
from app.db.types import GUID, JSONB, StringArray, Vector


class AgentMemory(BaseModel):
    __tablename__ = "agent_memories"
    __table_args__ = (
        UniqueConstraint("merchant_id", "content_hash", name="uq_agent_memories_content"),
        Index("ix_agent_memories_merchant_kind", "merchant_id", "kind"),
        Index("ix_agent_memories_merchant_created", "merchant_id", "created_at"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: recommendation | outcome | experiment | review | inventory | note | procurement | supplier
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    #: Entities this memory is about - the edges of the memory graph.
    tags: Mapped[list[str]] = mapped_column(StringArray, default=list, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector())
    #: Which embedding produced the vector, so a provider change can re-embed.
    embedding_model: Mapped[str] = mapped_column(String(96), default="", nullable=False)
    #: agent | user | system
    source: Mapped[str] = mapped_column(String(16), default="agent", nullable=False)
    author_label: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    #: SHA-256 of kind + text: the same memory is never stored twice.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
