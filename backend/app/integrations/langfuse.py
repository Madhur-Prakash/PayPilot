"""Langfuse tracing wrapper.

Presents one small surface (``tracer.trace(...)`` -> spans / generations / events)
that degrades to a no-op when keys are absent, so agent code never branches on
"is observability configured".

Nothing secret is ever sent: payloads pass through the same redaction used by the
structured logger.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger, redact

log = get_logger(__name__)


class _NoopSpan:
    """Stands in for a Langfuse span/generation when tracing is disabled."""

    __slots__ = ("id",)

    def __init__(self) -> None:
        self.id = uuid.uuid4().hex

    def update(self, **_: Any) -> _NoopSpan:
        return self

    def end(self, **_: Any) -> _NoopSpan:
        return self

    def span(self, **_: Any) -> _NoopSpan:
        return _NoopSpan()

    def generation(self, **_: Any) -> _NoopSpan:
        return _NoopSpan()

    def event(self, **_: Any) -> _NoopSpan:
        return _NoopSpan()

    def score(self, **_: Any) -> _NoopSpan:
        return self

    def get_trace_url(self) -> str | None:
        return None


class AgentTrace:
    """A single agent workflow trace.

    Wraps either a real Langfuse trace client or a no-op. Every method is
    exception-safe: observability must never break the request it observes.
    """

    def __init__(self, handle: Any, *, trace_id: str, enabled: bool) -> None:
        self._handle = handle
        self.trace_id = trace_id
        self.enabled = enabled

    @property
    def url(self) -> str | None:
        if not self.enabled:
            return None
        try:
            return self._handle.get_trace_url()
        except Exception:
            return None

    @contextmanager
    def span(
        self, name: str, *, input: Any = None, metadata: dict[str, Any] | None = None
    ) -> Iterator[Any]:
        """Record a unit of work (a graph node, a tool call, a DB aggregation)."""
        handle: Any = _NoopSpan()
        if self.enabled:
            try:
                handle = self._handle.span(
                    name=name, input=redact(input), metadata=redact(metadata or {})
                )
            except Exception:
                handle = _NoopSpan()
        try:
            yield handle
        except Exception as exc:
            with suppress(Exception):
                handle.end(level="ERROR", status_message=str(exc)[:500])
            raise
        else:
            with suppress(Exception):
                handle.end()

    def generation(
        self,
        *,
        name: str,
        model: str,
        input: Any = None,
        output: Any = None,
        usage: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        level: str | None = None,
        status_message: str | None = None,
    ) -> None:
        """Record one LLM call with its token usage."""
        if not self.enabled:
            return
        try:
            payload: dict[str, Any] = {
                "name": name,
                "model": model,
                "input": redact(input),
                "output": redact(output),
                "metadata": redact(metadata or {}),
            }
            if usage:
                payload["usage"] = usage
            if level:
                payload["level"] = level
            if status_message:
                payload["status_message"] = status_message[:500]
            self._handle.generation(**payload)
        except Exception as exc:
            log.debug("langfuse_generation_failed", detail=str(exc)[:200])

    def event(self, name: str, **fields: Any) -> None:
        """Record a discrete decision or milestone."""
        if not self.enabled:
            return
        try:
            self._handle.event(name=name, metadata=redact(fields))
        except Exception as exc:
            log.debug("langfuse_event_failed", detail=str(exc)[:200])

    def tool_call(
        self,
        *,
        tool: str,
        arguments: dict[str, Any],
        result: Any,
        duration_ms: float | None = None,
        error: str | None = None,
    ) -> None:
        if not self.enabled:
            return
        try:
            span = self._handle.span(
                name=f"tool:{tool}",
                input=redact(arguments),
                metadata={"duration_ms": duration_ms, "kind": "tool"},
            )
            span.end(
                output=redact(result),
                level="ERROR" if error else "DEFAULT",
                status_message=error[:500] if error else None,
            )
        except Exception as exc:
            log.debug("langfuse_tool_span_failed", detail=str(exc)[:200])

    def finish(self, *, output: Any = None, **metadata: Any) -> None:
        if not self.enabled:
            return
        try:
            self._handle.update(output=redact(output), metadata=redact(metadata))
        except Exception as exc:
            log.debug("langfuse_trace_update_failed", detail=str(exc)[:200])


class LangfuseTracer:
    """Process-wide Langfuse client holder."""

    def __init__(self) -> None:
        self._client: Any = None
        self._initialised = False

    @property
    def enabled(self) -> bool:
        """Whether traces will actually reach Langfuse.

        Forces initialisation, so a health check or settings screen reports the
        truth rather than "not configured" merely because no agent has run yet.
        """
        if settings.langfuse_active and not self._initialised:
            self._ensure_client()
        return settings.langfuse_active and self._client is not None

    def _ensure_client(self) -> None:
        if self._initialised:
            return
        self._initialised = True
        if not settings.langfuse_active:
            log.info(
                "langfuse_disabled",
                reason="missing_keys" if settings.langfuse_enabled else "disabled_by_config",
            )
            return
        try:
            import inspect

            from langfuse import Langfuse

            # The constructor differs across major SDK versions - `environment` and
            # `release` only exist on v3. Passing one the installed SDK does not know
            # raises a TypeError that used to be swallowed here, which disabled
            # tracing silently while the keys looked perfectly valid. Offer the extras
            # only when the signature actually accepts them.
            kwargs: dict[str, Any] = {
                "public_key": settings.langfuse_public_key,
                "secret_key": settings.langfuse_secret_key,
                "host": settings.langfuse_effective_host,
            }
            accepted = inspect.signature(Langfuse.__init__).parameters
            if "environment" in accepted:
                kwargs["environment"] = settings.app_env

            self._client = Langfuse(**kwargs)
            log.info(
                "langfuse_enabled",
                host=settings.langfuse_effective_host,
                sdk=getattr(__import__("langfuse"), "__version__", "unknown"),
            )
        except Exception as exc:
            self._client = None
            # Warning, not debug: valid keys that fail to initialise is a
            # configuration fault someone has to see.
            log.warning(
                "langfuse_init_failed",
                detail=f"{type(exc).__name__}: {exc}"[:300],
                host=settings.langfuse_effective_host,
            )

    def trace(
        self,
        *,
        name: str,
        user_id: str | None = None,
        merchant_id: str | None = None,
        agent_name: str | None = None,
        workflow: str | None = None,
        session_id: str | None = None,
        input: Any = None,
        tags: list[str] | None = None,
        **metadata: Any,
    ) -> AgentTrace:
        self._ensure_client()
        trace_id = uuid.uuid4().hex
        if not self.enabled:
            return AgentTrace(_NoopSpan(), trace_id=trace_id, enabled=False)

        meta = {
            "merchant_id": merchant_id,
            "agent_name": agent_name,
            "workflow": workflow,
            "environment": settings.app_env,
            "service": settings.app_name,
            **metadata,
        }
        try:
            handle = self._client.trace(
                id=trace_id,
                name=name,
                user_id=user_id,
                session_id=session_id,
                input=redact(input),
                metadata=redact(meta),
                tags=tags or [],
            )
            return AgentTrace(handle, trace_id=trace_id, enabled=True)
        except Exception as exc:
            log.warning("langfuse_trace_failed", detail=str(exc)[:200])
            return AgentTrace(_NoopSpan(), trace_id=trace_id, enabled=False)

    def flush(self) -> None:
        if self._client is None:
            return
        with suppress(Exception):
            self._client.flush()

    def shutdown(self) -> None:
        self.flush()
        try:
            if self._client is not None and hasattr(self._client, "shutdown"):
                self._client.shutdown()
        except Exception:
            pass


tracer = LangfuseTracer()
