"""Agent request/response schemas.

``GrowthRecommendation`` is the contract the LLM must satisfy. Nothing downstream
parses prose: if the model's JSON does not validate against this schema the run
falls back to the deterministic recommendation instead of guessing.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from app.schemas.common import EvidenceItem, SchemaBase

IntentLiteral = Literal[
    "diagnose_decline",
    "find_opportunity",
    "explain_metric",
    "product_performance",
    "customer_insight",
    "review_insight",
    "competitor_insight",
    "launch_action",
    "experiment_status",
    "daily_briefing",
    "general_question",
]

AgentWorkflowLiteral = Literal["investigate", "ask", "detect", "execute", "measure", "voice"]


# --------------------------------------------------------------------------- #
# LLM structured output contract
# --------------------------------------------------------------------------- #
class GrowthRecommendation(SchemaBase):
    """The Growth Scientist's structured verdict. Section 36 of the spec."""

    opportunity: str = Field(max_length=200)
    summary: str = Field(max_length=2000)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    hypothesis: str = Field(default="", max_length=1500)
    recommended_action: str = Field(default="", max_length=1000)
    reasoning: str = Field(default="", max_length=2000)
    estimated_impact: float = Field(default=0, ge=0)
    confidence: float = Field(default=0.5, ge=0, le=1)
    risk: Literal["low", "medium", "high"] = "medium"
    requires_approval: bool = True
    #: Machine-readable action the Action Agent can execute, e.g. "create_evening_combo_experiment".
    action_key: str | None = Field(default=None, max_length=80)
    alternatives_considered: list[str] = Field(default_factory=list)

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalise_confidence(cls, value: object) -> object:
        """Models sometimes emit 82 instead of 0.82."""
        if isinstance(value, int | float) and value > 1:
            return min(float(value) / 100.0, 1.0)
        return value

    @field_validator("estimated_impact", mode="before")
    @classmethod
    def _strip_currency(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.replace(",", "").replace("Rs", "").replace("INR", "")
            cleaned = "".join(ch for ch in cleaned if ch.isdigit() or ch == ".")
            return float(cleaned) if cleaned else 0.0
        return value


class IntentClassification(SchemaBase):
    intent: IntentLiteral = "general_question"
    confidence: float = Field(default=0.5, ge=0, le=1)
    #: Which specialists the orchestrator should fan out to.
    needs_reviews: bool = False
    needs_market: bool = False
    needs_products: bool = False
    focus_metric: str | None = None
    rationale: str = Field(default="", max_length=500)


class MerchantAnswer(SchemaBase):
    """Conversational reply from the Merchant Agent."""

    answer: str = Field(max_length=3000)
    key_points: list[str] = Field(default_factory=list)
    suggested_followups: list[str] = Field(default_factory=list)
    references: list[EvidenceItem] = Field(default_factory=list)


class ReviewInsight(SchemaBase):
    headline: str = Field(default="", max_length=300)
    emerging_complaints: list[str] = Field(default_factory=list)
    positive_themes: list[str] = Field(default_factory=list)
    interpretation: str = Field(default="", max_length=1500)
    evidence: list[EvidenceItem] = Field(default_factory=list)


class MarketInsight(SchemaBase):
    headline: str = Field(default="", max_length=300)
    competitor_edge: list[str] = Field(default_factory=list)
    merchant_edge: list[str] = Field(default_factory=list)
    external_context: list[str] = Field(default_factory=list)
    interpretation: str = Field(default="", max_length=1500)
    evidence: list[EvidenceItem] = Field(default_factory=list)


class MeasurementVerdict(SchemaBase):
    decision: Literal["SCALE", "STOP", "CONTINUE", "WATCH"] = "WATCH"
    rationale: str = Field(default="", max_length=1500)
    learning: str = Field(default="", max_length=1500)
    confidence: float = Field(default=0.5, ge=0, le=1)


# --------------------------------------------------------------------------- #
# API surface
# --------------------------------------------------------------------------- #
class AgentAskRequest(SchemaBase):
    message: str = Field(min_length=2, max_length=2000)
    workflow: AgentWorkflowLiteral | None = None
    #: Focus the investigation on a specific opportunity.
    opportunity_id: uuid.UUID | None = None
    channel: Literal["web", "voice"] = "web"
    conversation_id: str | None = Field(default=None, max_length=64)


class InvestigateRequest(SchemaBase):
    opportunity_id: uuid.UUID | None = None
    question: str | None = Field(default=None, max_length=2000)
    days: int = Field(default=30, ge=7, le=180)


class ToolCallOut(SchemaBase):
    id: uuid.UUID
    sequence: int
    tool_name: str
    agent_name: str
    arguments: dict = Field(default_factory=dict)
    result_summary: str = ""
    status: str
    duration_ms: int | None = None
    error: str | None = None


class AgentStepOut(SchemaBase):
    id: uuid.UUID
    sequence: int
    node: str
    agent_name: str
    agent_label: str = ""
    action: str
    result: str
    decision: str | None = None
    status: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    duration_ms: int | None = None
    error: str | None = None


class AgentRunOut(SchemaBase):
    id: uuid.UUID
    agent_name: str
    agent_label: str = ""
    workflow: str
    status: str
    intent: str | None = None
    channel: str
    input_text: str
    summary: str
    output: dict = Field(default_factory=dict)
    decision: str | None = None
    confidence: float | None = None
    requires_approval: bool = False
    opportunity_id: uuid.UUID | None = None
    campaign_id: uuid.UUID | None = None
    experiment_id: uuid.UUID | None = None
    trace_id: str | None = None
    trace_url: str | None = None
    model: str | None = None
    used_fallback: bool = False
    duration_ms: int | None = None
    total_tokens: int | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class AgentRunDetail(AgentRunOut):
    """Human-readable trace. Deliberately excludes raw model reasoning."""

    steps: list[AgentStepOut] = Field(default_factory=list)
    tool_calls: list[ToolCallOut] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    recommendation: GrowthRecommendation | None = None
    trace_disclaimer: str = (
        "This trace shows actions, tools, evidence and decisions. Internal model "
        "reasoning is never recorded or displayed."
    )


class AgentRunResponse(SchemaBase):
    run: AgentRunDetail
    answer: str = ""
    recommendation: GrowthRecommendation | None = None
    opportunity_id: uuid.UUID | None = None
    suggested_followups: list[str] = Field(default_factory=list)
    requires_approval: bool = False


class ApproveActionRequest(SchemaBase):
    """The human approval gate for a financially consequential agent action."""

    approve: bool = True
    note: str = Field(default="", max_length=500)
    #: Launch the campaign/experiment immediately after approval.
    execute_now: bool = True


class ApprovalOutcome(SchemaBase):
    approved: bool
    opportunity_id: uuid.UUID | None = None
    campaign_id: uuid.UUID | None = None
    experiment_id: uuid.UUID | None = None
    agent_run_id: uuid.UUID | None = None
    status: str
    message: str
    steps: list[str] = Field(default_factory=list)


class AgentActivityItem(SchemaBase):
    run_id: uuid.UUID
    agent_name: str
    agent_label: str
    workflow: str
    status: str
    title: str
    #: "web" or "voice" - which surface the run came in on.
    channel: str = "web"
    decision: str | None = None
    confidence: float | None = None
    tools_used: list[str] = Field(default_factory=list)
    duration_ms: int | None = None
    used_fallback: bool = False
    created_at: datetime


class AgentActivityFeed(SchemaBase):
    items: list[AgentActivityItem]
    total_runs: int
    completed_runs: int
    failed_runs: int
    avg_duration_ms: float | None = None
    top_tools: list[dict] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Voice (Vapi)
# --------------------------------------------------------------------------- #
class VoiceSessionRequest(SchemaBase):
    merchant_id: uuid.UUID | None = None


class VoiceSessionConfig(SchemaBase):
    """Everything the browser SDK needs to open a Vapi session."""

    enabled: bool
    public_key: str | None = None
    assistant_id: str | None = None
    assistant_overrides: dict = Field(default_factory=dict)
    session_token: str | None = None
    greeting: str = ""
    disabled_reason: str | None = None


class VoiceToolRequest(SchemaBase):
    """Vapi server-tool webhook payload (normalised)."""

    tool: str = Field(max_length=64)
    arguments: dict = Field(default_factory=dict)
    merchant_id: uuid.UUID | None = None
    call_id: str | None = None


class VoiceToolResponse(SchemaBase):
    result: str
    data: dict = Field(default_factory=dict)
    agent_run_id: uuid.UUID | None = None
