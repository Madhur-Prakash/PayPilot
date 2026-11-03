"""Agent run / step / tool-call repository."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import selectinload

from app.db.models.agent import (
    AgentRun,
    AgentRunStatus,
    AgentStep,
    AgentStepStatus,
    AgentToolCall,
)
from app.repositories.base import MerchantScopedRepository


class AgentRunRepository(MerchantScopedRepository[AgentRun]):
    model = AgentRun

    async def get_with_detail(self, run_id: uuid.UUID) -> AgentRun | None:
        stmt = (
            self.scoped()
            .where(AgentRun.id == run_id)
            .options(selectinload(AgentRun.steps), selectinload(AgentRun.tool_calls))
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def list_recent(
        self,
        *,
        limit: int = 25,
        offset: int = 0,
        agent_name: str | None = None,
        status: str | None = None,
        channel: str | None = None,
    ) -> list[AgentRun]:
        stmt = self.scoped().options(selectinload(AgentRun.tool_calls))
        if agent_name:
            stmt = stmt.where(AgentRun.agent_name == agent_name)
        if status:
            stmt = stmt.where(AgentRun.status == status)
        if channel:
            stmt = stmt.where(AgentRun.channel == channel)
        stmt = stmt.order_by(desc(AgentRun.created_at)).limit(limit).offset(offset)
        return list((await self.session.execute(stmt)).scalars().all())

    async def start(
        self,
        *,
        agent_name: str,
        workflow: str,
        input_text: str,
        user_id: uuid.UUID | None = None,
        channel: str = "web",
        opportunity_id: uuid.UUID | None = None,
        trace_id: str | None = None,
        trace_url: str | None = None,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentRun:
        run = AgentRun(
            merchant_id=self.merchant_id,
            user_id=user_id,
            agent_name=agent_name,
            workflow=workflow,
            input_text=input_text[:4000],
            channel=channel,
            status=AgentRunStatus.RUNNING,
            opportunity_id=opportunity_id,
            trace_id=trace_id,
            trace_url=trace_url,
            model=model,
            started_at=datetime.now(tz=UTC),
            metadata_json=metadata or {},
        )
        self.session.add(run)
        await self.session.flush()
        return run

    async def finish(
        self,
        run: AgentRun,
        *,
        status: str = AgentRunStatus.COMPLETED,
        summary: str = "",
        output: dict[str, Any] | None = None,
        decision: str | None = None,
        confidence: float | None = None,
        requires_approval: bool = False,
        error: str | None = None,
        used_fallback: bool = False,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        **links: Any,
    ) -> AgentRun:
        now = datetime.now(tz=UTC)
        run.status = status
        run.summary = summary
        run.output = output or {}
        run.decision = decision
        run.confidence = confidence
        run.requires_approval = requires_approval
        run.error = error
        run.used_fallback = used_fallback
        run.prompt_tokens = prompt_tokens
        run.completion_tokens = completion_tokens
        run.total_tokens = total_tokens
        run.finished_at = now
        if run.started_at:
            started = run.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            run.duration_ms = int((now - started).total_seconds() * 1000)
        for field, value in links.items():
            if value is not None and hasattr(run, field):
                setattr(run, field, value)
        await self.session.flush()
        return run

    # ------------------------------------------------------------------ steps
    async def add_step(
        self,
        *,
        run: AgentRun,
        sequence: int,
        node: str,
        agent_name: str,
        action: str,
        result: str = "",
        decision: str | None = None,
        status: str = AgentStepStatus.COMPLETED,
        evidence: list[dict[str, Any]] | None = None,
        duration_ms: int | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentStep:
        step = AgentStep(
            merchant_id=self.merchant_id,
            agent_run_id=run.id,
            sequence=sequence,
            node=node,
            agent_name=agent_name,
            action=action,
            result=result,
            decision=decision,
            status=status,
            evidence=evidence or [],
            duration_ms=duration_ms,
            error=error,
            metadata_json=metadata or {},
        )
        self.session.add(step)
        await self.session.flush()
        return step

    async def add_tool_call(
        self,
        *,
        run: AgentRun,
        sequence: int,
        tool_name: str,
        agent_name: str = "",
        arguments: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        result_summary: str = "",
        status: str = "COMPLETED",
        duration_ms: int | None = None,
        error: str | None = None,
        agent_step_id: uuid.UUID | None = None,
    ) -> AgentToolCall:
        call = AgentToolCall(
            merchant_id=self.merchant_id,
            agent_run_id=run.id,
            agent_step_id=agent_step_id,
            sequence=sequence,
            tool_name=tool_name,
            agent_name=agent_name,
            arguments=arguments or {},
            result=result or {},
            result_summary=result_summary[:2000],
            status=status,
            duration_ms=duration_ms,
            error=error,
        )
        self.session.add(call)
        await self.session.flush()
        return call

    # ------------------------------------------------------------------ stats
    async def stats(self) -> dict[str, Any]:
        total = await self.count()
        completed = await self.count(AgentRun.status == AgentRunStatus.COMPLETED)
        failed = await self.count(AgentRun.status == AgentRunStatus.FAILED)
        avg_stmt = select(func.avg(AgentRun.duration_ms)).where(
            AgentRun.merchant_id == self.merchant_id, AgentRun.duration_ms.is_not(None)
        )
        avg_duration = (await self.session.execute(avg_stmt)).scalar_one_or_none()
        return {
            "total_runs": total,
            "completed_runs": completed,
            "failed_runs": failed,
            "avg_duration_ms": round(float(avg_duration), 2) if avg_duration else None,
        }

    async def top_tools(self, *, limit: int = 8) -> list[dict[str, Any]]:
        stmt = (
            select(AgentToolCall.tool_name, func.count(AgentToolCall.id))
            .where(AgentToolCall.merchant_id == self.merchant_id)
            .group_by(AgentToolCall.tool_name)
            .order_by(func.count(AgentToolCall.id).desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()
        return [{"tool": row[0], "calls": int(row[1] or 0)} for row in rows]

    async def tools_for_run(self, run_id: uuid.UUID) -> list[str]:
        stmt = (
            select(AgentToolCall.tool_name)
            .where(
                AgentToolCall.merchant_id == self.merchant_id,
                AgentToolCall.agent_run_id == run_id,
            )
            .order_by(AgentToolCall.sequence)
        )
        seen: list[str] = []
        for row in (await self.session.execute(stmt)).all():
            if row[0] not in seen:
                seen.append(row[0])
        return seen
