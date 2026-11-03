"""Turning agent runs into memories worth recalling.

The hard part of agent memory is not storage, it is deciding what is worth
writing down and in what words. cognee builds a knowledge graph out of prose, so
what gets written here is what a later run can find.

Two properties make a memory useful:

* **It stands alone.** "It worked" is unrecallable. Every memory names the
  merchant, the action, the numbers and the date, because it will be read months
  later with no surrounding context.
* **It records the outcome, not just the intent.** A recommendation that was
  rejected, or an experiment that lost, is worth more than one that was merely
  proposed - it stops the agent proposing the same thing again.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.integrations.cognee_memory import MemoryKind, memory
from app.schemas.agent import GrowthRecommendation, MeasurementVerdict


def _today() -> str:
    return datetime.now(tz=UTC).strftime("%d %B %Y")


def _money(value: float) -> str:
    return f"₹{value:,.0f}"


def record_recommendation(
    *,
    merchant_id: Any,
    merchant_name: str,
    question: str,
    recommendation: GrowthRecommendation,
) -> None:
    """What the agent concluded, and on what evidence."""
    evidence = "; ".join(
        f"{item.metric}: {item.value}" for item in (recommendation.evidence or [])[:5]
    )
    text = (
        f"On {_today()}, the growth agent analysed {merchant_name} "
        f'in response to the question "{question.strip()[:200]}".\n\n'
        f"Opportunity identified: {recommendation.opportunity}.\n"
        f"Recommended action: {recommendation.recommended_action}\n"
        f"Hypothesis: {recommendation.hypothesis}\n"
        f"Reasoning: {recommendation.reasoning}\n"
        f"Estimated impact: {_money(recommendation.estimated_impact)} per month "
        f"at {recommendation.confidence:.0%} confidence, {recommendation.risk} risk.\n"
    )
    if evidence:
        text += f"Evidence: {evidence}.\n"
    if recommendation.alternatives_considered:
        text += (
            "Alternatives considered and set aside: "
            + "; ".join(str(a) for a in recommendation.alternatives_considered[:3])
            + ".\n"
        )

    memory.remember_later(
        merchant_id,
        text,
        kind=MemoryKind.RECOMMENDATION,
        tags=(_slug(recommendation.opportunity),),
    )


def record_approval(
    *,
    merchant_id: Any,
    merchant_name: str,
    opportunity: str,
    approved: bool,
    decided_by: str,
    note: str = "",
) -> None:
    """Whether a human agreed.

    A rejection is the more valuable memory of the two: it is the only record of
    a judgement the numbers alone do not explain.
    """
    verdict = "approved" if approved else "rejected"
    text = (
        f"On {_today()}, {decided_by or 'a user'} {verdict} the agent's "
        f'recommendation "{opportunity}" for {merchant_name}.\n'
    )
    if note:
        text += f"Reason given: {note}\n"
    if not approved:
        text += (
            "Treat this as a standing signal: do not re-propose the same action "
            "for this merchant without new evidence that addresses the rejection.\n"
        )

    memory.remember_later(
        merchant_id, text, kind=MemoryKind.OUTCOME, tags=(_slug(opportunity), verdict)
    )


def record_measurement(
    *,
    merchant_id: Any,
    merchant_name: str,
    experiment_name: str,
    verdict: MeasurementVerdict,
    metrics: dict[str, Any] | None = None,
) -> None:
    """What the experiment actually proved.

    This is the memory the whole layer exists for - the only one grounded in a
    measured result rather than a projection.
    """
    text = (
        f"On {_today()}, the experiment \"{experiment_name}\" for {merchant_name} "
        f"concluded with the decision: {verdict.decision}.\n"
        f"Rationale: {verdict.rationale}\n"
        f"What was learned: {verdict.learning}\n"
        f"Confidence in this conclusion: {verdict.confidence:.0%}.\n"
    )
    if metrics:
        readable = ", ".join(f"{k}={v}" for k, v in list(metrics.items())[:8])
        text += f"Measured figures: {readable}.\n"

    memory.remember_later(
        merchant_id,
        text,
        kind=MemoryKind.EXPERIMENT,
        tags=(_slug(experiment_name), str(verdict.decision).lower()),
    )


def format_for_prompt(hits: list[dict[str, Any]], limit: int = 5) -> str:
    """Render recalled memory for an LLM prompt.

    Labelled as prior conclusions rather than facts: these are things this system
    concluded before, which may since have been overtaken by the computed
    metrics in the same prompt. The model is told which one wins.
    """
    if not hits:
        return ""
    lines = []
    for index, hit in enumerate(hits[:limit], start=1):
        text = " ".join(str(hit.get("text", "")).split())
        if text:
            lines.append(f"{index}. {text[:600]}")
    if not lines:
        return ""
    return (
        "What this system previously concluded for this merchant (prior "
        "conclusions, not fresh measurements - where they disagree with the "
        "computed figures above, the computed figures win):\n" + "\n".join(lines)
    )


def _slug(value: str) -> str:
    """A short, stable tag - cognee node sets are matched literally."""
    cleaned = "".join(c.lower() if c.isalnum() else "-" for c in str(value))
    return "-".join(part for part in cleaned.split("-") if part)[:48] or "general"
