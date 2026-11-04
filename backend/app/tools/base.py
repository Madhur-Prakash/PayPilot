"""Agent tool infrastructure.

A tool is the *only* way an agent touches the business. Every call is:

  * typed        - arguments validated against a Pydantic model,
  * authorized   - the caller's permission set is checked before execution,
  * scoped       - bound to one merchant, with no way to widen it,
  * logged       - structured log line with duration,
  * traced       - a Langfuse span with inputs and outputs,
  * recorded     - persisted to agent_tool_calls for the trace UI,
  * error-safe   - failures return a structured error, never an exception into the graph.

Tools are deterministic wherever possible. The LLM chooses *which* tool to call
and interprets the structured result; it never computes the result itself.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, PermissionDeniedError
from app.core.logging import get_logger
from app.core.permissions import Permission
from app.db.models.agent import AgentRun
from app.integrations.langfuse import AgentTrace
from app.repositories.agent import AgentRunRepository

log = get_logger(__name__)

TArgs = TypeVar("TArgs", bound=BaseModel)


@dataclass
class ToolContext:
    """Everything a tool is allowed to know about its caller."""

    session: AsyncSession
    merchant_id: uuid.UUID
    merchant_name: str = ""
    user_id: uuid.UUID | None = None
    permissions: frozenset[str] = field(default_factory=frozenset)
    agent_name: str = "growth_scientist"
    run: AgentRun | None = None
    trace: AgentTrace | None = None
    #: Monotonic counter so the trace UI can order tool calls.
    sequence: int = 0

    def has(self, permission: Permission | str) -> bool:
        return str(permission) in self.permissions

    def require(self, permission: Permission | str) -> None:
        if not self.has(permission):
            raise PermissionDeniedError(
                f"This action requires the '{permission}' permission.",
                details={"required_permission": str(permission)},
            )

    def next_sequence(self) -> int:
        self.sequence += 1
        return self.sequence


class ToolResult(BaseModel):
    """Uniform envelope returned by every tool."""

    tool: str
    ok: bool = True
    data: dict[str, Any] = {}
    summary: str = ""
    error: str | None = None
    duration_ms: float = 0.0

    def for_llm(self) -> dict[str, Any]:
        """Compact representation handed to the model."""
        if not self.ok:
            return {"tool": self.tool, "ok": False, "error": self.error}
        return {"tool": self.tool, "ok": True, "summary": self.summary, "data": self.data}


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Callable[..., Awaitable[tuple[dict[str, Any], str]]]
    permission: Permission | None = None
    #: Financially consequential tools additionally require a recorded approval.
    requires_approval: bool = False

    def json_schema(self) -> dict[str, Any]:
        """OpenAI/Groq-compatible function definition."""
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema,
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(
        self,
        name: str,
        *,
        description: str,
        args_model: type[BaseModel],
        permission: Permission | None = None,
        requires_approval: bool = False,
    ) -> Callable[[Callable[..., Awaitable[tuple[dict[str, Any], str]]]], Callable[..., Any]]:
        def decorator(handler: Callable[..., Awaitable[tuple[dict[str, Any], str]]]):
            if name in self._tools:
                raise RuntimeError(f"Tool '{name}' is already registered.")
            self._tools[name] = ToolSpec(
                name=name,
                description=description,
                args_model=args_model,
                handler=handler,
                permission=permission,
                requires_approval=requires_approval,
            )
            return handler

        return decorator

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self, names: list[str] | None = None) -> list[ToolSpec]:
        if names is None:
            return [self._tools[n] for n in sorted(self._tools)]
        return [self._tools[n] for n in names if n in self._tools]

    def schemas(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        return [spec.json_schema() for spec in self.specs(names)]

    def catalogue(self) -> list[dict[str, Any]]:
        """Human-readable tool list for the Agent Activity screen."""
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "permission": str(spec.permission) if spec.permission else None,
                "requires_approval": spec.requires_approval,
            }
            for spec in self.specs()
        ]

    # ------------------------------------------------------------------ execute
    async def execute(
        self, name: str, context: ToolContext, arguments: dict[str, Any] | None = None
    ) -> ToolResult:
        """Run a tool end to end. Never raises - failures come back as ToolResult."""
        spec = self._tools.get(name)
        raw_args = arguments or {}
        if spec is None:
            return await self._record_failure(
                context, name, raw_args, f"Unknown tool '{name}'.", 0.0
            )

        started = time.perf_counter()
        try:
            if spec.permission is not None:
                context.require(spec.permission)
            args = spec.args_model.model_validate(raw_args)
        except PermissionDeniedError as exc:
            return await self._record_failure(
                context, name, raw_args, exc.message, _elapsed(started), status="DENIED"
            )
        except ValidationError as exc:
            detail = "; ".join(
                f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()[:4]
            )
            return await self._record_failure(
                context, name, raw_args, f"Invalid arguments - {detail}", _elapsed(started)
            )

        try:
            data, summary = await spec.handler(context, args)
        except AppError as exc:
            return await self._record_failure(
                context, name, raw_args, exc.message, _elapsed(started)
            )
        except Exception as exc:
            log.exception("tool_failed", tool=name, error_type=type(exc).__name__)
            return await self._record_failure(
                context,
                name,
                raw_args,
                f"{type(exc).__name__}: {str(exc)[:200]}",
                _elapsed(started),
            )

        duration = _elapsed(started)
        result = ToolResult(tool=name, ok=True, data=data, summary=summary, duration_ms=duration)

        log.info(
            "agent_tool_call",
            tool=name,
            agent=context.agent_name,
            merchant_id=str(context.merchant_id),
            duration_ms=duration,
            status="ok",
        )
        if context.trace is not None:
            context.trace.tool_call(
                tool=name,
                arguments=args.model_dump(mode="json"),
                result={"summary": summary, **_trim(data)},
                duration_ms=duration,
            )
        await self._persist(
            context, name, args.model_dump(mode="json"), data, summary, duration, None
        )
        return result

    async def _record_failure(
        self,
        context: ToolContext,
        name: str,
        arguments: dict[str, Any],
        error: str,
        duration: float,
        *,
        status: str = "FAILED",
    ) -> ToolResult:
        log.warning(
            "agent_tool_call",
            tool=name,
            agent=context.agent_name,
            merchant_id=str(context.merchant_id),
            duration_ms=duration,
            status=status.lower(),
            detail=error,
        )
        if context.trace is not None:
            context.trace.tool_call(
                tool=name, arguments=arguments, result={}, duration_ms=duration, error=error
            )
        await self._persist(context, name, arguments, {}, "", duration, error, status=status)
        return ToolResult(tool=name, ok=False, error=error, duration_ms=duration)

    @staticmethod
    async def _persist(
        context: ToolContext,
        name: str,
        arguments: dict[str, Any],
        data: dict[str, Any],
        summary: str,
        duration: float,
        error: str | None,
        *,
        status: str = "COMPLETED",
    ) -> None:
        if context.run is None:
            return
        try:
            repo = AgentRunRepository(context.session, context.merchant_id)
            await repo.add_tool_call(
                run=context.run,
                sequence=context.next_sequence(),
                tool_name=name,
                agent_name=context.agent_name,
                arguments=arguments,
                result=_trim(data),
                result_summary=summary,
                status=status if error else "COMPLETED",
                duration_ms=int(duration),
                error=error,
            )
        except Exception as exc:  # persistence must never break an agent run
            log.warning("tool_call_persist_failed", tool=name, detail=str(exc)[:200])


def _elapsed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


def _trim(data: dict[str, Any], *, max_items: int = 40) -> dict[str, Any]:
    """Keep persisted/traced payloads small without losing their shape."""
    trimmed: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, list) and len(value) > max_items:
            trimmed[key] = [*value[:max_items], f"...{len(value) - max_items} more"]
        else:
            trimmed[key] = value
    return trimmed


registry = ToolRegistry()
