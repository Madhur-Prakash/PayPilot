"""Agent runs, their steps and every tool call - the data behind the Agent
Activity and Agent Trace screens.

Only *observable* facts are stored: which tool ran, with what inputs, what it
returned, and what decision followed. Raw model chain-of-thought is never
persisted or exposed.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import BaseModel
from app.db.types import GUID, JSONB, UTCDateTime


class AgentName:
    MERCHANT = "merchant_agent"
    GROWTH_SCIENTIST = "growth_scientist"
    REVIEW_INTELLIGENCE = "review_agent"
    MARKET_INTELLIGENCE = "market_agent"
    EXPERIMENT = "experiment_agent"
    ACTION = "action_agent"
    MEASUREMENT = "measurement_agent"
    ORCHESTRATOR = "growth_orchestrator"

    # supply agents
    INVENTORY_INTELLIGENCE = "inventory_agent"
    BUYER = "buyer_agent"
    NEGOTIATION = "negotiation_agent"
    PROCUREMENT_EVALUATION = "procurement_agent"
    SUPPLIER_NETWORK = "supplier_network"
    PROCUREMENT_ORCHESTRATOR = "procurement_orchestrator"
    RECONCILIATION = "reconciliation_agent"

    # merchant operating system (agents/merchant_os.py)
    MERCHANT_ORCHESTRATOR = "merchant_orchestrator"
    BUSINESS_INTELLIGENCE = "business_intelligence_agent"
    PRODUCT_DISCOVERY = "product_discovery_agent"
    SUPPLY_INTELLIGENCE = "supply_intelligence_agent"
    PRICING_INTELLIGENCE = "pricing_intelligence_agent"
    GROWTH_STRATEGY = "growth_strategy_agent"
    PAYPAL_TRANSACTION = "paypal_transaction_agent"

    LABELS = {
        MERCHANT_ORCHESTRATOR: "Orchestrator Agent",
        BUSINESS_INTELLIGENCE: "Business Intelligence Agent",
        PRODUCT_DISCOVERY: "Product Discovery Agent",
        SUPPLY_INTELLIGENCE: "Supply Intelligence Agent",
        PRICING_INTELLIGENCE: "Pricing Intelligence Agent",
        GROWTH_STRATEGY: "Growth Strategy Agent",
        PAYPAL_TRANSACTION: "PayPal Transaction Agent",
        INVENTORY_INTELLIGENCE: "Inventory Intelligence",
        BUYER: "Buyer Agent",
        NEGOTIATION: "Negotiation Agent",
        PROCUREMENT_EVALUATION: "Procurement Evaluation",
        SUPPLIER_NETWORK: "Supplier Agents",
        PROCUREMENT_ORCHESTRATOR: "Procurement Orchestrator",
        RECONCILIATION: "Reconciliation Agent",
        MERCHANT: "Merchant Agent",
        GROWTH_SCIENTIST: "Growth Scientist",
        REVIEW_INTELLIGENCE: "Review Intelligence",
        MARKET_INTELLIGENCE: "Market Intelligence",
        EXPERIMENT: "Experiment Agent",
        ACTION: "Action Agent",
        MEASUREMENT: "Measurement Agent",
        ORCHESTRATOR: "Growth Orchestrator",
    }


class AgentRunStatus:
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    CANCELLED = "CANCELLED"


class AgentWorkflow:
    INVESTIGATE = "investigate"
    ASK = "ask"
    DETECT = "detect"
    EXECUTE = "execute"
    MEASURE = "measure"
    VOICE = "voice"
    PROCUREMENT = "procurement"
    MERCHANT_OS = "merchant_os"
    AUTOPILOT = "growth_autopilot"


class AgentRun(BaseModel):
    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_merchant_created", "merchant_id", "created_at"),
        Index("ix_agent_runs_merchant_status", "merchant_id", "status"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), index=True)

    agent_name: Mapped[str] = mapped_column(
        String(48), default=AgentName.ORCHESTRATOR, nullable=False
    )
    workflow: Mapped[str] = mapped_column(
        String(32), default=AgentWorkflow.INVESTIGATE, nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), default=AgentRunStatus.PENDING, nullable=False)

    input_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    intent: Mapped[str | None] = mapped_column(String(48))
    channel: Mapped[str] = mapped_column(String(16), default="web", nullable=False)  # web | voice

    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    #: Validated structured output (see schemas/agent.py GrowthRecommendation).
    output: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    #: A sentence, not an enum - the recommended action in plain language.
    decision: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), index=True)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    experiment_id: Mapped[uuid.UUID | None] = mapped_column(GUID())

    trace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    trace_url: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(96))
    #: True when no LLM key was configured and the deterministic path produced the answer.
    used_fallback: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    steps: Mapped[list[AgentStep]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="AgentStep.sequence",
    )
    tool_calls: Mapped[list[AgentToolCall]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="AgentToolCall.sequence",
    )


class AgentStepStatus:
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class AgentStep(BaseModel):
    """One node of the LangGraph execution, rendered as a human-readable trace row."""

    __tablename__ = "agent_steps"
    __table_args__ = (Index("ix_agent_steps_run_sequence", "agent_run_id", "sequence"),)

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_run_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    node: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(48), nullable=False)
    #: Plain-language action, e.g. "Investigated the evening repeat-customer decline".
    action: Mapped[str] = mapped_column(Text, default="", nullable=False)
    result: Mapped[str] = mapped_column(Text, default="", nullable=False)
    decision: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default=AgentStepStatus.RUNNING, nullable=False)
    evidence: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    run: Mapped[AgentRun] = relationship(back_populates="steps")


class AgentToolCall(BaseModel):
    __tablename__ = "agent_tool_calls"
    __table_args__ = (
        Index("ix_agent_tool_calls_run_sequence", "agent_run_id", "sequence"),
        Index("ix_agent_tool_calls_tool", "merchant_id", "tool_name"),
    )

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_run_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_step_id: Mapped[uuid.UUID | None] = mapped_column(GUID())
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(48), default="", nullable=False)
    arguments: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    result: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    result_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="COMPLETED", nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)

    run: Mapped[AgentRun] = relationship(back_populates="tool_calls")
