"""The Growth Graph.

Decomposes the headline movement into the metrics and segments that make it up,
then attaches independent evidence to the branch that moved most.

Language discipline (spec section 18): edges are ``decomposes_into``,
``correlates_with`` or ``evidenced_by``. Nothing here claims causation, because
no causal inference has been performed - only a controlled experiment can
establish that, which is exactly what the product goes on to run.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.growth import MetricKey
from app.db.models.review import ReviewTopic
from app.repositories.review import ReviewRepository
from app.repositories.transaction import _pct_change
from app.schemas.analytics import GraphEdge, GraphNode, GrowthGraph, PeriodInfo
from app.schemas.common import EvidenceItem
from app.services.analytics.service import AnalyticsService

log = get_logger(__name__)


def _fmt_money(value: float) -> str:
    if abs(value) >= 100_000:
        return f"Rs {value / 100_000:.2f}L"
    return f"Rs {value:,.0f}"


def _unique_nodes(nodes: list[GraphNode]) -> list[GraphNode]:
    """Keep the first node per id, in order.

    Node ids are assembled from a daypart and a metric or topic name, and those
    namespaces have collided before - `service` is both an operational metric and a
    review topic. A duplicate id makes React drop a node from the graph, which is a
    silent wrong answer rather than a crash, so it is worth a loud log and a
    deterministic result.
    """
    seen: set[str] = set()
    unique: list[GraphNode] = []
    for node in nodes:
        if node.id in seen:
            log.warning("growth_graph_duplicate_node", node_id=node.id, label=node.label)
            continue
        seen.add(node.id)
        unique.append(node)
    return unique


def _direction(change: float | None) -> str:
    if change is None:
        return "FLAT"
    if change > 1.5:
        return "UP"
    if change < -1.5:
        return "DOWN"
    return "FLAT"


def _severity(change: float | None, *, down_is_bad: bool = True) -> str:
    if change is None:
        return "INFO"
    magnitude = abs(change)
    bad = change < 0 if down_is_bad else change > 0
    if not bad:
        return "INFO"
    if magnitude >= 25:
        return "CRITICAL"
    if magnitude >= 15:
        return "HIGH"
    if magnitude >= 8:
        return "MEDIUM"
    return "LOW"


class GrowthGraphService:
    def __init__(self, session: AsyncSession, merchant_id: uuid.UUID) -> None:
        self.session = session
        self.merchant_id = merchant_id
        self.analytics = AnalyticsService(session, merchant_id)
        self.reviews = ReviewRepository(session, merchant_id)

    async def build(self, *, days: int = 30) -> GrowthGraph:
        period = await self.analytics.resolve_period(days=days)
        kpis, current, previous = await self.analytics.kpis(period)
        dayparts = await self.analytics.daypart_breakdown(period)

        by_key = {kpi.key: kpi for kpi in kpis}
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        # -------------------------------------------------- root: revenue
        revenue = by_key[MetricKey.REVENUE]
        nodes.append(
            GraphNode(
                id="revenue",
                label="Revenue",
                metric_key=MetricKey.REVENUE,
                value=revenue.value,
                formatted_value=_fmt_money(revenue.value),
                change_pct=revenue.change_pct,
                direction=_direction(revenue.change_pct),
                severity=_severity(revenue.change_pct),
                depth=0,
                node_kind="metric",
                interpretation=(
                    f"Revenue is {revenue.change_pct:+.1f}% versus the previous {days} days "
                    f"({_fmt_money(revenue.previous_value or 0)} to {_fmt_money(revenue.value)})."
                    if revenue.change_pct is not None
                    else "Revenue for the period."
                ),
                related_metrics=[MetricKey.ORDERS, MetricKey.AOV],
                reference="dashboard",
            )
        )

        # -------------------------------------------------- level 1: the identity
        # Revenue is exactly orders x AOV, so this decomposition is arithmetic, not
        # inference - which is why these edges are `decomposes_into`.
        for key, label, reference in (
            (MetricKey.ORDERS, "Orders", "dashboard"),
            (MetricKey.AOV, "Average Order Value", "dashboard"),
        ):
            kpi = by_key[key]
            nodes.append(
                GraphNode(
                    id=key,
                    label=label,
                    metric_key=key,
                    value=kpi.value,
                    formatted_value=(
                        _fmt_money(kpi.value) if kpi.unit == "currency" else f"{kpi.value:,.0f}"
                    ),
                    change_pct=kpi.change_pct,
                    direction=_direction(kpi.change_pct),
                    severity=_severity(kpi.change_pct),
                    depth=1,
                    node_kind="metric",
                    interpretation=(
                        f"{label} moved {kpi.change_pct:+.1f}%. Revenue is exactly orders "
                        "multiplied by average order value, so this is an arithmetic split of "
                        "the movement above."
                        if kpi.change_pct is not None
                        else f"{label} for the period."
                    ),
                    reference=reference,
                )
            )
            edges.append(
                GraphEdge(
                    source="revenue",
                    target=key,
                    relationship="decomposes_into",
                    strength=1.0,
                    label="arithmetic component",
                )
            )

        # Repeat rate sits under orders: fewer returning customers means fewer orders.
        repeat = by_key[MetricKey.REPEAT_RATE]
        nodes.append(
            GraphNode(
                id="repeat_customers",
                label="Repeat Customers",
                metric_key=MetricKey.REPEAT_RATE,
                value=float(current.repeat_customers),
                formatted_value=f"{current.repeat_customers:,} ({repeat.value:.1f}%)",
                change_pct=_pct_change(
                    float(current.repeat_customers), float(previous.repeat_customers)
                ),
                direction=_direction(
                    _pct_change(float(current.repeat_customers), float(previous.repeat_customers))
                ),
                severity=_severity(
                    _pct_change(float(current.repeat_customers), float(previous.repeat_customers))
                ),
                depth=2,
                node_kind="metric",
                interpretation=(
                    f"{current.repeat_customers} customers ordered two or more times this period, "
                    f"down from {previous.repeat_customers}. Repeat rate is {repeat.value:.1f}%."
                ),
                related_metrics=[MetricKey.ORDERS, MetricKey.RETENTION_RATE],
                reference="customers",
            )
        )
        edges.append(
            GraphEdge(
                source=MetricKey.ORDERS,
                target="repeat_customers",
                relationship="correlates_with",
                strength=0.8,
                label="order volume driver",
            )
        )

        # -------------------------------------------------- level 2: segments
        worst = min(
            (d for d in dayparts if d.change_pct is not None),
            key=lambda d: d.change_pct or 0,
            default=None,
        )
        for part in dayparts:
            node_id = f"daypart:{part.daypart}"
            slot = part.label.split(" (")[0]
            is_worst = worst is not None and part.daypart == worst.daypart
            nodes.append(
                GraphNode(
                    id=node_id,
                    label=f"{slot} segment",
                    metric_key="revenue",
                    value=part.revenue,
                    formatted_value=_fmt_money(part.revenue),
                    change_pct=part.change_pct,
                    direction=_direction(part.change_pct),
                    severity=_severity(part.change_pct),
                    depth=3,
                    node_kind="segment",
                    interpretation=(
                        f"{slot} is {part.change_pct:+.1f}% and carries "
                        f"{part.revenue_share_pct:.0f}% of revenue. Repeat customers in this slot "
                        f"are {part.repeat_customers_change_pct:+.1f}%."
                        if part.change_pct is not None
                        and part.repeat_customers_change_pct is not None
                        else f"{slot} revenue for the period."
                    )
                    + (
                        "  This is the segment moving furthest from the rest of the business."
                        if is_worst
                        else ""
                    ),
                    evidence=[
                        EvidenceItem(
                            metric=f"{slot} orders",
                            value=f"{part.orders:,}",
                            source="analytics",
                            reference="dashboard",
                        ),
                        EvidenceItem(
                            metric=f"{slot} repeat customers",
                            value=str(part.repeat_customers),
                            change=(
                                f"{part.repeat_customers_change_pct:+.1f}%"
                                if part.repeat_customers_change_pct is not None
                                else None
                            ),
                            source="analytics",
                            reference="customers",
                        ),
                    ],
                    related_metrics=["repeat_customers"],
                    reference=f"customers?daypart={part.daypart}",
                )
            )
            edges.append(
                GraphEdge(
                    source="repeat_customers",
                    target=node_id,
                    relationship="decomposes_into",
                    strength=round(part.revenue_share_pct / 100, 3),
                    label=f"{part.revenue_share_pct:.0f}% of revenue",
                )
            )

        # -------------------------------------------------- level 3: evidence
        if worst is not None:
            await self._attach_evidence(nodes, edges, period, worst)

        return GrowthGraph(
            root_id="revenue",
            nodes=_unique_nodes(nodes),
            edges=edges,
            period=period,
            generated_at=datetime.now(tz=UTC),
        )

    async def _attach_evidence(
        self, nodes: list[GraphNode], edges: list[GraphEdge], period: PeriodInfo, worst
    ) -> None:
        """Hang independent evidence off the worst-moving segment."""
        slot = worst.label.split(" (")[0]
        parent = f"daypart:{worst.daypart}"

        # 1. Operational metric: service time.
        if worst.avg_service_minutes is not None and worst.service_minutes_change_pct is not None:
            node_id = f"evidence:{worst.daypart}:service"
            nodes.append(
                GraphNode(
                    id=node_id,
                    label=f"{slot} service time",
                    metric_key="avg_service_minutes",
                    value=worst.avg_service_minutes,
                    formatted_value=f"{worst.avg_service_minutes:.1f} min",
                    change_pct=worst.service_minutes_change_pct,
                    direction=_direction(worst.service_minutes_change_pct),
                    severity=_severity(worst.service_minutes_change_pct, down_is_bad=False),
                    depth=4,
                    node_kind="signal",
                    source="analytics",
                    interpretation=(
                        f"Average order-to-handover time in the {slot.lower()} slot is "
                        f"{worst.avg_service_minutes:.1f} minutes, "
                        f"{worst.service_minutes_change_pct:+.1f}% versus the previous period. "
                        "This moved over the same window as the revenue decline - a correlation, "
                        "not a demonstrated cause."
                    ),
                    reference="dashboard",
                )
            )
            edges.append(
                GraphEdge(
                    source=parent,
                    target=node_id,
                    relationship="correlates_with",
                    strength=0.7,
                    label="moved over the same window",
                )
            )

        # 2. Independent source: the review corpus.
        current = await self.reviews.topic_stats(
            period.current.start, period.current.end, daypart=worst.daypart
        )
        previous = await self.reviews.topic_stats(
            period.previous.start, period.previous.end, daypart=worst.daypart
        )
        prev_by_topic = {row["topic"]: row for row in previous}

        rising = []
        for row in current:
            prior = prev_by_topic.get(row["topic"], {})
            prior_negative = int(prior.get("negative_count", 0) or 0)
            change = _pct_change(float(row["negative_count"]), float(prior_negative))
            if row["negative_count"] >= 4 and change is not None and change >= 20:
                rising.append((row, prior_negative, change))
        rising.sort(key=lambda item: item[0]["negative_count"], reverse=True)

        for row, prior_negative, change in rising[:2]:
            topic = row["topic"]
            label = ReviewTopic.LABELS.get(topic, topic.replace("_", " ").title())
            # Namespaced by source: `service` is both an operational metric and a
            # review topic, and without this both nodes claim
            # `evidence:<daypart>:service`.
            node_id = f"evidence:{worst.daypart}:review:{topic}"
            nodes.append(
                GraphNode(
                    id=node_id,
                    label=f"{label} complaints",
                    metric_key=f"reviews.{topic}",
                    value=float(row["negative_count"]),
                    formatted_value=f"{row['negative_count']} reviews",
                    change_pct=change,
                    direction=_direction(change),
                    severity=_severity(change, down_is_bad=False),
                    depth=5,
                    node_kind="evidence",
                    source="reviews",
                    interpretation=(
                        f"Negative {label.lower()} reviews for the {slot.lower()} slot rose from "
                        f"{prior_negative} to {row['negative_count']} ({change:+.1f}%). Reviews are "
                        "an independent source from the transaction ledger, which is what makes "
                        "this corroboration rather than the same number twice."
                    ),
                    evidence=[
                        EvidenceItem(
                            metric="Average rating for this topic",
                            value=f"{row['avg_rating']:.1f}",
                            source="reviews",
                            reference=f"reviews?topic={topic}",
                        ),
                        EvidenceItem(
                            metric="Share of this slot's reviews",
                            value=f"{row['share_pct']:.0f}%",
                            source="reviews",
                            reference=f"reviews?topic={topic}",
                        ),
                    ],
                    reference=f"reviews?topic={topic}&daypart={worst.daypart}",
                )
            )
            source_node = (
                f"evidence:{worst.daypart}:service"
                if any(n.id == f"evidence:{worst.daypart}:service" for n in nodes)
                else parent
            )
            edges.append(
                GraphEdge(
                    source=source_node,
                    target=node_id,
                    relationship="evidenced_by",
                    strength=0.65,
                    label="independent source",
                )
            )
