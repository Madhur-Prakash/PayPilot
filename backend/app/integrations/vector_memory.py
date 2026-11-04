"""Long-term agent memory on Postgres + pgvector.

The agents would otherwise be amnesiac: every run recomputes the same facts and
re-proposes things that were tried and rejected last month. This module gives
them somewhere to keep what a run *concluded* - a recommendation, whether a human
approved it, what an experiment proved, which supplier delivered late - so a later
run can recall it.

Storage is one table (``agent_memories``) in the application's own database:

* **Semantic recall** - each memory is embedded locally (``EmbeddingService``:
  deterministic hashing by default, fastembed optionally; no API key either way)
  and searched with pgvector's cosine-distance operator ``<=>`` behind an HNSW
  index. On SQLite (tests, quick local runs) the same ranking is computed in
  Python, so behaviour is identical.
* **Graph links** - ``tags`` name the entities a memory is about (a SKU, a
  supplier agent key, an opportunity slug). Recall can be narrowed to an entity,
  which is how "everything we know about supplier X" works.

Three rules:

**Tenant isolation is structural.** Every read and write filters on
``merchant_id``; no public method accepts anything wider than one merchant id.
There is no shared index to leak across - unlike an external memory service, the
isolation is a ``WHERE`` clause in our own database, covered by tests.

**Memory never delays an answer.** Recall is bounded by a timeout and returns
empty on expiry. Writes are cheap (one embedding + one insert) but still run off
the request path via ``remember_later``.

**Memory never breaks a run, and never overrides policy.** Every public method
catches its own failures and degrades to "no memory". Recalled text is context for
a model's *language*; it never feeds a financial calculation or an authorisation.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Float, delete, func, select

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

#: A Python-side scan on SQLite stops here; Postgres uses the index instead.
_FALLBACK_SCAN_LIMIT = 2000
#: Below this cosine similarity a hit is noise, not memory.
_MIN_SCORE = 0.05


class MemoryKind(StrEnum):
    """What a memory is about. Recall can be narrowed to one or more kinds."""

    RECOMMENDATION = "recommendation"
    OUTCOME = "outcome"
    EXPERIMENT = "experiment"
    REVIEW = "review"
    INVENTORY = "inventory"
    NOTE = "note"
    #: Negotiation outcomes, accepted prices, invoice discrepancies.
    PROCUREMENT = "procurement"
    #: Supplier delivery performance and reliability.
    SUPPLIER = "supplier"


@dataclass(frozen=True, slots=True)
class MemoryHit:
    text: str
    source: str = "pgvector"
    kind: str = ""
    score: float | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    memory_id: str = ""
    created_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "source": self.source,
            "kind": self.kind,
            "score": self.score,
            "tags": list(self.tags),
            "memory_id": self.memory_id,
            "created_at": self.created_at,
        }


def content_hash(kind: str, text: str) -> str:
    return hashlib.sha256(f"{kind}::{text.strip()}".encode()).hexdigest()


def _session_factory() -> Any:
    # Resolved at call time: the test harness swaps the factory for its own engine.
    import app.db.session as db_session

    return db_session.SessionLocal


def _is_postgres(session: Any) -> bool:
    try:
        return session.get_bind().dialect.name == "postgresql"
    except Exception:
        return settings.is_postgres


class VectorMemory:
    def __init__(self) -> None:
        self._broken = False
        self._reason = ""
        #: Background writes, held so they are not garbage collected mid-flight
        #: and so shutdown can wait for them.
        self._writes: set[asyncio.Task[Any]] = set()

    # ------------------------------------------------------------------ setup
    @property
    def enabled(self) -> bool:
        return bool(settings.memory_enabled) and not self._broken

    def dataset_for(self, merchant_id: uuid.UUID | str) -> str:
        """The merchant's memory namespace - shown in the UI, used in logs."""
        return f"merchant-{merchant_id}"

    @staticmethod
    def _uuid(merchant_id: uuid.UUID | str) -> uuid.UUID:
        return merchant_id if isinstance(merchant_id, uuid.UUID) else uuid.UUID(str(merchant_id))

    @staticmethod
    async def _embed(text: str) -> list[float]:
        from app.integrations.embeddings import embedding_service

        return await asyncio.to_thread(embedding_service.embed, text)

    # ----------------------------------------------------------------- recall
    async def recall(
        self,
        merchant_id: uuid.UUID | str,
        query: str,
        *,
        top_k: int | None = None,
        kinds: tuple[MemoryKind | str, ...] = (),
        tags: tuple[str, ...] = (),
    ) -> list[MemoryHit]:
        """What this merchant's agents already know that bears on ``query``.

        Empty for every failure mode - disabled, empty query, slow, or broken - so
        callers need no fallback branch of their own.
        """
        query = (query or "").strip()
        if not query or not self.enabled:
            return []
        try:
            return await asyncio.wait_for(
                self._recall(self._uuid(merchant_id), query, top_k or settings.memory_recall_top_k,
                             tuple(str(k) for k in kinds), tuple(t.lower() for t in tags)),
                timeout=settings.memory_recall_timeout_seconds,
            )
        except TimeoutError:
            log.warning("memory_recall_timeout", dataset=self.dataset_for(merchant_id))
            return []
        except Exception as exc:
            log.info("memory_recall_failed", dataset=self.dataset_for(merchant_id),
                     reason=f"{type(exc).__name__}: {exc}"[:200])
            return []

    async def _recall(
        self, merchant_id: uuid.UUID, query: str, top_k: int, kinds: tuple[str, ...], tags: tuple[str, ...]
    ) -> list[MemoryHit]:
        from app.db.models.memory import AgentMemory
        from app.integrations.embeddings import cosine_similarity

        vector = await self._embed(query)
        async with _session_factory()() as session:
            stmt = select(AgentMemory).where(AgentMemory.merchant_id == merchant_id)
            if kinds:
                stmt = stmt.where(AgentMemory.kind.in_(kinds))
            scored: list[tuple[float, Any]] = []
            if _is_postgres(session):
                distance = AgentMemory.embedding.op("<=>", return_type=Float)(vector)
                rows = (await session.execute(
                    stmt.add_columns(distance.label("distance"))
                    .where(AgentMemory.embedding.isnot(None))
                    .order_by(distance)
                    .limit(top_k * 4 if tags else top_k * 2)
                )).all()
                scored = [(1.0 - float(d), row) for row, d in rows]
            else:
                rows = (await session.execute(
                    stmt.order_by(AgentMemory.created_at.desc()).limit(_FALLBACK_SCAN_LIMIT)
                )).scalars().all()
                scored = [(cosine_similarity(vector, row.embedding or []), row) for row in rows]

        if tags:
            wanted = set(tags)
            scored = [(s, r) for s, r in scored if wanted & {t.lower() for t in (r.tags or [])}]
        scored = [(s, r) for s, r in scored if s >= _MIN_SCORE]
        scored.sort(key=lambda pair: (-pair[0], -(pair[1].created_at.timestamp() if pair[1].created_at else 0)))
        return [self._hit(row, score) for score, row in scored[:top_k]]

    @staticmethod
    def _hit(row: Any, score: float | None) -> MemoryHit:
        return MemoryHit(
            text=row.text,
            source="pgvector",
            kind=row.kind,
            score=round(score, 4) if score is not None else None,
            tags=tuple(row.tags or ()),
            memory_id=str(row.id),
            created_at=row.created_at.isoformat() if isinstance(row.created_at, datetime) else None,
        )

    async def recent(
        self, merchant_id: uuid.UUID | str, *, limit: int = 25, kind: str = ""
    ) -> list[MemoryHit]:
        """The latest memories, newest first - for browsing in the UI."""
        if not self.enabled:
            return []
        from app.db.models.memory import AgentMemory

        try:
            async with _session_factory()() as session:
                stmt = select(AgentMemory).where(AgentMemory.merchant_id == self._uuid(merchant_id))
                if kind:
                    stmt = stmt.where(AgentMemory.kind == kind)
                rows = (await session.execute(stmt.order_by(AgentMemory.created_at.desc()).limit(limit))).scalars().all()
            return [self._hit(r, None) for r in rows]
        except Exception as exc:
            log.info("memory_recent_failed", reason=f"{type(exc).__name__}: {exc}"[:200])
            return []

    # --------------------------------------------------------------- remember
    async def remember(
        self,
        merchant_id: uuid.UUID | str,
        text: str,
        *,
        kind: MemoryKind | str = MemoryKind.NOTE,
        tags: tuple[str, ...] = (),
        source: str = "agent",
        author_label: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Write one memory and wait for it. Prefer :meth:`remember_later`."""
        text = (text or "").strip()
        if not text or not self.enabled:
            return False
        from app.db.models.memory import AgentMemory
        from app.integrations.embeddings import embedding_service

        merchant = self._uuid(merchant_id)
        digest = content_hash(str(kind), text)
        try:
            vector = await self._embed(text)
            async with _session_factory()() as session:
                exists = (await session.execute(
                    select(AgentMemory.id).where(AgentMemory.merchant_id == merchant, AgentMemory.content_hash == digest)
                )).first()
                if exists is not None:
                    return True
                session.add(
                    AgentMemory(
                        merchant_id=merchant,
                        kind=str(kind)[:32],
                        text=text[:8000],
                        tags=[t.lower()[:64] for t in tags if t][:12],
                        embedding=vector,
                        embedding_model=f"{embedding_service.provider}:{settings.embedding_model if embedding_service.provider == 'fastembed' else 'hash'}"[:96],
                        source=source[:16],
                        author_label=author_label[:160],
                        content_hash=digest,
                        metadata_json=metadata or {},
                    )
                )
                await session.commit()
        except Exception as exc:
            log.error("memory_write_failed", dataset=self.dataset_for(merchant_id), kind=str(kind),
                      error=f"{type(exc).__name__}: {exc}"[:300])
            return False
        log.info("memory_written", dataset=self.dataset_for(merchant_id), kind=str(kind), characters=len(text))
        return True

    def remember_later(
        self,
        merchant_id: uuid.UUID | str,
        text: str,
        *,
        kind: MemoryKind | str = MemoryKind.NOTE,
        tags: tuple[str, ...] = (),
        source: str = "agent",
        author_label: str = "",
    ) -> None:
        """Queue a memory without waiting for it."""
        if not self.enabled or not (text or "").strip():
            return
        try:
            task = asyncio.create_task(
                self.remember(merchant_id, text, kind=kind, tags=tags, source=source, author_label=author_label),
                name=f"memory-write-{kind}",
            )
        except RuntimeError:
            # No running loop (a management command). Dropping the memory is right.
            return
        self._writes.add(task)
        task.add_done_callback(self._writes.discard)

    async def drain(self, timeout: float = 30.0) -> None:
        """Let queued writes finish, for a clean shutdown (and deterministic tests)."""
        if not self._writes:
            return
        pending = list(self._writes)
        try:
            await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), timeout=timeout)
        except TimeoutError:
            log.warning("memory_drain_timeout", pending=len(self._writes))

    # ----------------------------------------------------------------- forget
    async def forget(self, merchant_id: uuid.UUID | str) -> bool:
        """Erase one merchant's memory. Irreversible."""
        from app.db.models.memory import AgentMemory

        try:
            async with _session_factory()() as session:
                await session.execute(delete(AgentMemory).where(AgentMemory.merchant_id == self._uuid(merchant_id)))
                await session.commit()
        except Exception as exc:
            log.error("memory_forget_failed", dataset=self.dataset_for(merchant_id), error=f"{type(exc).__name__}: {exc}"[:300])
            return False
        log.info("memory_forgotten", dataset=self.dataset_for(merchant_id))
        return True

    # ----------------------------------------------------------------- status
    async def status(self, merchant_id: uuid.UUID | str | None = None) -> dict[str, Any]:
        from app.db.models.memory import AgentMemory
        from app.integrations.embeddings import embedding_service

        state: dict[str, Any] = {
            "enabled": bool(settings.memory_enabled),
            "available": False,
            "broken": self._broken,
            "reason": self._reason,
            "backend": "pgvector" if settings.is_postgres else "sqlite (in-process cosine)",
            "embedding_provider": embedding_service.provider,
            "embedding_dimensions": settings.embedding_dimensions,
            "pending_writes": len(self._writes),
        }
        if merchant_id is not None:
            state["dataset"] = self.dataset_for(merchant_id)
        try:
            async with _session_factory()() as session:
                stmt = select(AgentMemory.kind, func.count()).group_by(AgentMemory.kind)
                if merchant_id is not None:
                    stmt = stmt.where(AgentMemory.merchant_id == self._uuid(merchant_id))
                counts = {k: int(v) for k, v in (await session.execute(stmt)).all()}
            state["available"] = True
            state["memories"] = sum(counts.values())
            state["by_kind"] = counts
        except Exception as exc:
            state["reason"] = f"{type(exc).__name__}: {exc}"[:200]
        return state


#: Module-level singleton, matching ``tracer`` and ``llm_service``.
memory = VectorMemory()
