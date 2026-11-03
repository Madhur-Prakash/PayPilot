"""Long-term memory for the agents, backed by cognee.

The growth agents are otherwise amnesiac: every run recomputes the same facts and
re-proposes things that were tried and rejected last month. This module gives
them somewhere to put what a run *concluded* - the recommendation, whether a
human approved it, and what the experiment actually proved - so a later run can
recall it.

Three rules shape everything here.

**Tenant isolation is structural, and it is not free.** Every merchant gets its
own cognee dataset *and its own cognee user*, and ``ENABLE_BACKEND_ACCESS_CONTROL``
is forced on. Both halves are load-bearing. Passing ``datasets=[...]`` alone does
**not** isolate anything: with access control off, cognee keeps one shared vector
collection, a search for merchant A returns merchant B's chunks, and it stamps
them with merchant A's ``dataset_name`` on the way out - so the leak is invisible
to any check that trusts the response. Measured, not assumed: the same two-tenant
write/read returns 1 row with access control on and 2 (one of them the other
tenant's) with it off.

No method here takes a dataset or a user; they take a merchant id and derive
both. There is deliberately no way to call this module and read across merchants.

**Memory never delays an answer.** Recall is bounded by a timeout and returns
empty on expiry. Writing runs cognee's full extraction pipeline - seconds to
minutes - so it happens in a background task, never on the request path.

**Memory never breaks a run.** Every public method catches its own failures and
degrades to "no memory": the agent then behaves exactly as it did before this
module existed. An agent that cannot remember is worse; an agent that crashes
because it could not remember is unacceptable.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


class MemoryKind(StrEnum):
    """What a memory is about.

    Stored as a cognee node set, so recall can be narrowed to one kind - "what
    did our experiments prove" rather than everything ever written.
    """

    RECOMMENDATION = "recommendation"
    OUTCOME = "outcome"
    EXPERIMENT = "experiment"
    REVIEW = "review"
    INVENTORY = "inventory"
    NOTE = "note"


@dataclass(frozen=True, slots=True)
class MemoryHit:
    """One recalled memory, flattened out of cognee's union of response types."""

    text: str
    source: str = "graph"
    kind: str = ""
    score: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"text": self.text, "source": self.source, "kind": self.kind, "score": self.score}


def _storage_root() -> Path:
    """Where cognee keeps its graph, vectors and metadata.

    Without this cognee writes inside ``site-packages``, which is wiped by the
    next ``uv sync`` and is not somewhere anyone thinks to look for data.
    """
    if settings.memory_storage_dir:
        return Path(settings.memory_storage_dir).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / ".cognee"


def _harden_environment() -> None:
    """Settings cognee reads at import time.

    Pulled out of the class so the isolation invariant can be asserted directly
    in a test, without importing the whole cognee tree.
    """
    # Read at import time, so they have to be set first.
    #
    # Access control is what actually partitions one merchant's memory from
    # another's - see the module docstring. Assigned, never setdefault: an
    # operator who exports ENABLE_BACKEND_ACCESS_CONTROL=false for some other
    # tool must not silently turn cross-tenant leakage back on here.
    os.environ["ENABLE_BACKEND_ACCESS_CONTROL"] = "true"
    # cognee's own login flow stays off: callers are already authenticated at
    # this application's API boundary, and the per-merchant cognee user is
    # derived from that principal rather than from a second password.
    os.environ["REQUIRE_AUTHENTICATION"] = "false"
    # cognee's session cache runs a "SessionTurnAnalysis" LLM call on every
    # recall to maintain conversational state. Nothing here passes a
    # session_id, so that call buys nothing and costs a round trip - which on
    # a rate-limited key was enough to push recall past its own timeout.
    os.environ["CACHING"] = "false"
    if not settings.memory_tracing_enabled:
        # cognee ships its own OTLP exporter pointed at Langfuse. Left on it
        # would silently duplicate the tracing this app already does.
        os.environ["COGNEE_TRACING_ENABLED"] = "false"
        os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
        os.environ.pop("OTEL_EXPORTER_OTLP_HEADERS", None)


class CogneeMemory:
    """A small surface over cognee that fails soft.

    Import is deferred: cognee pulls in litellm, lancedb and friends, which is a
    slow and heavy import to pay for on a deployment that has memory switched
    off.
    """

    def __init__(self) -> None:
        self._cognee: Any | None = None
        self._ready = False
        self._broken = False
        #: Why initialisation failed, in words a reader can act on.
        self._reason = ""
        self._lock = asyncio.Lock()
        #: merchant id -> cognee user. Looking one up hits cognee's own database,
        #: so it is cached for the process lifetime.
        self._users: dict[str, Any] = {}
        self._user_lock = asyncio.Lock()
        #: Background writes. Held so they are not garbage collected mid-flight,
        #: and so shutdown can wait for them.
        self._writes: set[asyncio.Task[Any]] = set()
        #: cognee's pipeline is LLM-bound; a burst of runs should queue, not
        #: stampede the provider.
        self._write_slots = asyncio.Semaphore(2)

    # ------------------------------------------------------------------ setup
    @property
    def enabled(self) -> bool:
        return bool(settings.memory_enabled) and not self._broken

    def dataset_for(self, merchant_id: uuid.UUID | str) -> str:
        """One dataset per merchant. The only place this name is constructed."""
        return f"merchant-{merchant_id}"

    def _identity_for(self, merchant_id: uuid.UUID | str) -> str:
        """The cognee account that owns this merchant's memory.

        cognee identifies users by email address. Nothing is ever sent here - it
        is an internal primary key that happens to be shaped like an address, on
        a subdomain that exists only to make that obvious.
        """
        return f"merchant-{merchant_id}@memory.paypilot.internal"

    async def _user_for(self, merchant_id: uuid.UUID | str) -> Any | None:
        """Fetch or create this merchant's cognee user."""
        key = str(merchant_id)
        if key in self._users:
            return self._users[key]

        async with self._user_lock:
            if key in self._users:
                return self._users[key]
            try:
                from cognee.modules.users.methods import (
                    create_user,
                    get_user_by_email,
                )

                email = self._identity_for(merchant_id)
                user = await get_user_by_email(email)
                if user is None:
                    # The password is never used to log in - cognee requires one,
                    # and this account is only ever reached through this process.
                    user = await create_user(
                        email=email,
                        password=uuid.uuid4().hex,
                        is_verified=True,
                    )
                    log.info("memory_tenant_created", merchant_id=key)
                self._users[key] = user
                return user
            except Exception as exc:
                log.error(
                    "memory_tenant_unavailable",
                    merchant_id=key,
                    error=f"{type(exc).__name__}: {exc}"[:300],
                )
                return None

    def _configure(self) -> Any:
        """Import and configure cognee. Called once, under the lock."""
        root = _storage_root()
        (root / "data").mkdir(parents=True, exist_ok=True)
        (root / "system").mkdir(parents=True, exist_ok=True)
        _harden_environment()

        import cognee

        cognee.config.system_root_directory(str(root / "system"))
        cognee.config.data_root_directory(str(root / "data"))

        # cognee talks to models through litellm, so a Groq model is spelled
        # "groq/<model>" and needs the Groq key. Falling back to the app's own
        # LLM settings means memory works off one set of credentials.
        model = settings.memory_llm_model or f"groq/{settings.groq_model}"
        api_key = settings.memory_llm_api_key or settings.groq_api_key
        cognee.config.set_llm_provider(settings.memory_llm_provider)
        cognee.config.set_llm_model(model)
        if api_key:
            cognee.config.set_llm_api_key(api_key)

        # Local embeddings. cognee's default provider is "hash", which is fast,
        # free and not semantic at all - recall with it returns near-noise.
        cognee.config.set_embedding_provider(settings.memory_embedding_provider)
        cognee.config.set_embedding_model(settings.memory_embedding_model)
        cognee.config.set_embedding_dimensions(settings.memory_embedding_dimensions)

        log.info(
            "cognee_configured",
            root=str(root),
            llm_model=model,
            embedding_provider=settings.memory_embedding_provider,
            has_llm_key=bool(api_key),
        )
        return cognee

    async def _client(self) -> Any | None:
        """The configured cognee module, or None if it is unusable."""
        if not self.enabled:
            return None
        if self._ready:
            return self._cognee

        async with self._lock:
            if self._ready:
                return self._cognee
            try:
                # Configuration touches the filesystem and imports a large tree,
                # so keep it off the event loop.
                self._cognee = await asyncio.to_thread(self._configure)
                # Creates cognee's own tables. Without it the first user lookup
                # opens a database file that does not exist yet.
                import cognee.low_level

                await cognee.low_level.setup()
                self._ready = True
            except ModuleNotFoundError as exc:
                # The commonest cause by far, and the least obvious: a dependency
                # sync dropped the library while MEMORY_ENABLED stayed true.
                self._broken = True
                self._reason = (
                    "cognee is not installed. Run `pip install -r requirements.txt` "
                    "in backend/, or set MEMORY_ENABLED=false."
                )
                log.error("cognee_not_installed", error=str(exc), hint=self._reason)
                return None
            except Exception as exc:
                # One failure is enough: retrying a broken import on every agent
                # run would add latency to every request to no purpose.
                self._broken = True
                self._reason = f"{type(exc).__name__}: {exc}"[:300]
                log.error("cognee_unavailable", error=self._reason)
                return None
        return self._cognee

    # ----------------------------------------------------------------- recall
    async def recall(
        self,
        merchant_id: uuid.UUID | str,
        query: str,
        *,
        top_k: int | None = None,
        kinds: tuple[MemoryKind | str, ...] = (),
    ) -> list[MemoryHit]:
        """What this merchant's agents already know that bears on ``query``.

        Returns an empty list for every failure mode - disabled, unconfigured,
        slow, or broken - so callers need no fallback branch of their own.
        """
        query = (query or "").strip()
        if not query:
            return []

        cognee = await self._client()
        if cognee is None:
            return []

        user = await self._user_for(merchant_id)
        if user is None:
            # Without the owning user cognee would search the shared store, which
            # is precisely the cross-tenant read this module exists to prevent.
            return []

        dataset = self.dataset_for(merchant_id)
        try:
            responses = await asyncio.wait_for(
                cognee.recall(
                    query,
                    # CHUNKS returns the stored text. The completion retrievers
                    # spend a second LLM call rewriting it into prose, which for
                    # a prompt injection is both slower and worse - the agent
                    # wants the original wording, not a summary of it.
                    query_type=cognee.SearchType.CHUNKS,
                    # Without this cognee still spends an LLM call deciding which
                    # retriever to use, then overrides itself with the type above.
                    # Off, recall is pure vector search: no tokens, no rate limit,
                    # and fast enough to sit on the request path.
                    auto_route=False,
                    # Graph only. There is no session to consult, and asking for
                    # one makes cognee do session bookkeeping on every call.
                    scope="graph",
                    datasets=[dataset],
                    top_k=top_k or settings.memory_recall_top_k,
                    node_name=[str(k) for k in kinds] or None,
                    user=user,
                ),
                timeout=settings.memory_recall_timeout_seconds,
            )
        except TimeoutError:
            log.warning("memory_recall_timeout", dataset=dataset, seconds=settings.memory_recall_timeout_seconds)
            return []
        except Exception as exc:
            # A merchant with no memory yet is the common case on a fresh
            # install, and cognee signals it by raising rather than returning [].
            log.info("memory_recall_empty", dataset=dataset, reason=f"{type(exc).__name__}: {exc}"[:200])
            return []

        return _flatten(responses)

    # --------------------------------------------------------------- remember
    async def remember(
        self,
        merchant_id: uuid.UUID | str,
        text: str,
        *,
        kind: MemoryKind | str = MemoryKind.NOTE,
        tags: tuple[str, ...] = (),
    ) -> bool:
        """Write one memory, waiting for it. Prefer :meth:`remember_later`."""
        text = (text or "").strip()
        if not text:
            return False

        cognee = await self._client()
        if cognee is None:
            return False

        user = await self._user_for(merchant_id)
        if user is None:
            return False

        dataset = self.dataset_for(merchant_id)
        node_set = [str(kind), *tags]
        try:
            async with self._write_slots:
                await asyncio.wait_for(
                    cognee.remember(text, dataset, node_set=node_set, user=user),
                    timeout=settings.memory_write_timeout_seconds,
                )
        except TimeoutError:
            log.warning("memory_write_timeout", dataset=dataset, kind=str(kind))
            return False
        except Exception as exc:
            log.error("memory_write_failed", dataset=dataset, kind=str(kind), error=f"{type(exc).__name__}: {exc}"[:300])
            return False

        log.info("memory_written", dataset=dataset, kind=str(kind), characters=len(text))
        return True

    def remember_later(
        self,
        merchant_id: uuid.UUID | str,
        text: str,
        *,
        kind: MemoryKind | str = MemoryKind.NOTE,
        tags: tuple[str, ...] = (),
    ) -> None:
        """Queue a memory without waiting for it.

        Building the graph is an LLM pipeline measured in seconds; no user should
        wait through it to see an answer they already have.
        """
        if not self.enabled or not (text or "").strip():
            return
        try:
            task = asyncio.create_task(
                self.remember(merchant_id, text, kind=kind, tags=tags),
                name=f"memory-write-{kind}",
            )
        except RuntimeError:
            # No running loop - a management command, or a test using asyncio.run
            # on an already-closed loop. Dropping the memory is the right call.
            return
        self._writes.add(task)
        task.add_done_callback(self._writes.discard)

    async def drain(self, timeout: float = 30.0) -> None:
        """Let queued writes finish, for a clean shutdown."""
        if not self._writes:
            return
        pending = list(self._writes)
        log.info("memory_draining", pending=len(pending))
        with_timeout = asyncio.gather(*pending, return_exceptions=True)
        try:
            await asyncio.wait_for(with_timeout, timeout=timeout)
        except TimeoutError:
            log.warning("memory_drain_timeout", pending=len(self._writes))

    # ----------------------------------------------------------------- forget
    async def forget(self, merchant_id: uuid.UUID | str) -> bool:
        """Erase one merchant's memory. Irreversible."""
        cognee = await self._client()
        if cognee is None:
            return False
        user = await self._user_for(merchant_id)
        if user is None:
            return False

        dataset = self.dataset_for(merchant_id)
        try:
            await cognee.forget(dataset=dataset, user=user)
        except Exception as exc:
            log.error("memory_forget_failed", dataset=dataset, error=f"{type(exc).__name__}: {exc}"[:300])
            return False
        log.info("memory_forgotten", dataset=dataset)
        return True

    # ----------------------------------------------------------------- status
    async def status(self, merchant_id: uuid.UUID | str | None = None) -> dict[str, Any]:
        """Enough to answer "is memory actually on?" from the UI."""
        state: dict[str, Any] = {
            "enabled": bool(settings.memory_enabled),
            "available": False,
            "broken": self._broken,
            "embedding_provider": settings.memory_embedding_provider,
            "llm_model": settings.memory_llm_model or f"groq/{settings.groq_model}",
            "storage": str(_storage_root()),
            "pending_writes": len(self._writes),
        }
        if merchant_id is not None:
            state["dataset"] = self.dataset_for(merchant_id)
        state["available"] = await self._client() is not None
        # Read after the probe: initialisation happens inside it, so sampling
        # `broken` beforehand can report False for a client that just failed.
        state["broken"] = self._broken
        state["reason"] = self._reason
        return state


def _flatten(responses: Any) -> list[MemoryHit]:
    """cognee returns a discriminated union of response models per source.

    Rather than match each variant - and break when a new one is added - pull the
    first field that reads like prose and label it with its source.
    """
    hits: list[MemoryHit] = []
    for item in responses or []:
        text = ""
        for field in ("text", "answer", "content", "summary", "context"):
            value = getattr(item, field, None)
            if isinstance(value, str) and value.strip():
                text = value.strip()
                break
        if not text:
            value = getattr(item, "result", None)
            text = str(value).strip() if value else ""
        if not text:
            continue

        node_sets = getattr(item, "node_set", None) or []
        hits.append(
            MemoryHit(
                text=text,
                source=str(getattr(item, "source", "graph")),
                kind=str(node_sets[0]) if node_sets else "",
                score=getattr(item, "score", None),
            )
        )
    return hits


#: Module-level singleton, matching ``tracer`` and ``llm_service``.
memory = CogneeMemory()
