"""The operational tables the main seed leaves empty.

Three tables sit outside the demo narrative the rest of the seed builds -- they
are written by the platform at runtime rather than by the business story -- so
nothing had ever put a row in them. An empty table makes a feature look unbuilt
in a demo, and makes a schema review ask whether it is dead.

* ``growth_metrics`` -- metric snapshots. **Computed, never invented**: the
  values come from :class:`AnalyticsService` over the seeded ledger, which is the
  same code path the dashboard uses. Seeding literals here would put fabricated
  numbers one join away from real ones.
* ``custom_roles`` -- merchant-defined roles. Permission codes are validated
  against the ``Permission`` enum before they are stored, so a typo fails the
  seed rather than creating a role that silently grants nothing.
* ``processed_events`` -- the idempotency ledger. See ``seed_processed_events``
  for why its keys are the seeded events' own ids and nothing else.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.permissions import ALL_PERMISSIONS, Permission
from app.db.models.agent import (
    AgentName,
    AgentRun,
    AgentRunStatus,
    AgentStep,
    AgentStepStatus,
    AgentToolCall,
    AgentWorkflow,
)
from app.db.models.auth import CustomRole
from app.db.models.automation import DomainEvent, ProcessedEvent
from app.db.models.growth import GrowthOpportunity, MetricKey
from app.db.models.inventory import InventoryItem, MovementType
from app.db.models.merchant import Merchant
from app.db.models.procurement import PurchaseOrder, PurchaseOrderStatus
from app.repositories.opportunity import GrowthMetricRepository
from app.services.analytics.service import AnalyticsService
from app.services.inventory.stock import InsufficientStock, StockEngine

log = get_logger(__name__)

#: Roles a café of this size would actually create, rather than a demonstration
#: of the permission list. Each is a real subset: the supervisor runs the floor
#: and the counter but cannot spend money, and the accountant sees the value of
#: stock without being able to move any of it.
CUSTOM_ROLES: tuple[tuple[str, str, tuple[Permission, ...]], ...] = (
    (
        "Shift Supervisor",
        "Runs the floor: stock counts, reorder requests and the day's numbers. "
        "Cannot approve or execute anything that spends money.",
        (
            Permission.DASHBOARD_READ,
            Permission.INVENTORY_READ,
            Permission.INVENTORY_WRITE,
            Permission.PURCHASE_ORDER_READ,
            Permission.PURCHASE_ORDER_CREATE,
            Permission.REVIEWS_READ,
        ),
    ),
    (
        "Accountant",
        "Reads the books: stock valuation, campaign spend and experiment "
        "outcomes. Read-only everywhere by design.",
        (
            Permission.DASHBOARD_READ,
            Permission.INVENTORY_READ,
            Permission.INVENTORY_VALUE_READ,
            Permission.PURCHASE_ORDER_READ,
            Permission.CAMPAIGN_READ,
            Permission.EXPERIMENT_READ,
        ),
    ),
)

#: Which of the seeded events a consumer would plausibly have claimed. Scoped by
#: consumer, because two consumers may each process the same event once.
_CLAIMED_BY = {
    "inventory.low_stock": "replenishment",
    "inventory.purchase_order_created": "vendor_notifier",
    "inventory.purchase_received": "stock_ledger",
}


async def seed_custom_roles(
    session: AsyncSession, merchant: Merchant, *, created_by_id: uuid.UUID | None
) -> int:
    """Create the merchant's custom roles. Idempotent on (merchant, name)."""
    existing = set(
        (
            await session.execute(
                select(CustomRole.name).where(CustomRole.merchant_id == merchant.id)
            )
        ).scalars()
    )

    valid = {str(p) for p in ALL_PERMISSIONS}
    created = 0
    for name, description, permissions in CUSTOM_ROLES:
        if name in existing:
            continue
        codes = [str(p) for p in permissions]
        unknown = sorted(set(codes) - valid)
        if unknown:
            # Fail loudly. A role holding a permission the enum dropped grants
            # nothing at request time, and does it silently.
            raise ValueError(f"Custom role {name!r} references unknown permissions: {unknown}")
        session.add(
            CustomRole(
                merchant_id=merchant.id,
                name=name,
                description=description,
                permission_codes=codes,
                created_by_id=created_by_id,
            )
        )
        created += 1

    await session.flush()
    log.info("custom_roles_seeded", created=created, total=len(CUSTOM_ROLES))
    return created


async def seed_growth_metric_snapshots(
    session: AsyncSession, merchant: Merchant, *, periods: tuple[int, ...] = (7, 30, 90)
) -> int:
    """Snapshot the headline KPIs, overall and per daypart, for several windows.

    Every value is computed by ``AnalyticsService`` over the seeded ledger, so a
    snapshot and a live dashboard read agree by construction. ``upsert_snapshot``
    keys on (metric, period, dimension), which is what makes a re-run update
    rather than duplicate.
    """
    analytics = AnalyticsService(session, merchant.id)
    metrics = GrowthMetricRepository(session, merchant.id)
    written = 0

    for days in periods:
        period = await analytics.resolve_period(days=days)
        kpis, _current, _previous = await analytics.kpis(period)

        for kpi in kpis:
            await metrics.upsert_snapshot(
                metric_key=kpi.key,
                label=kpi.label,
                period_start=period.current.start,
                period_end=period.current.end,
                value=float(kpi.value),
                previous_value=kpi.previous_value,
                change_abs=kpi.change_abs,
                change_pct=kpi.change_pct,
                unit=kpi.unit,
                direction=kpi.direction,
                is_anomaly=kpi.is_anomaly,
                sample_size=kpi.sample_size,
                granularity=f"{days}d",
                metadata_json={"source": "seed", "window_days": days},
            )
            written += 1

        # The segment cut is the one the growth story turns on: revenue overall
        # moved less than the evening slot did, and that gap is only visible
        # once the same metric is stored per daypart.
        for slot in await analytics.daypart_breakdown(period):
            await metrics.upsert_snapshot(
                metric_key=MetricKey.REVENUE,
                label=f"Revenue - {slot.label}",
                period_start=period.current.start,
                period_end=period.current.end,
                value=float(slot.revenue),
                change_pct=slot.change_pct,
                unit="currency",
                dimension="daypart",
                dimension_value=slot.daypart,
                sample_size=int(slot.orders),
                granularity=f"{days}d",
                # The breakdown reports a period-over-period percentage, not the
                # prior absolute, so previous_value stays null rather than being
                # back-computed from a rounded percentage.
                metadata_json={
                    "source": "seed",
                    "window_days": days,
                    "revenue_share_pct": slot.revenue_share_pct,
                    "repeat_customers_change_pct": slot.repeat_customers_change_pct,
                    "service_minutes_change_pct": slot.service_minutes_change_pct,
                },
            )
            written += 1

    await session.flush()
    log.info("growth_metrics_seeded", snapshots=written, periods=list(periods))
    return written


async def seed_processed_events(session: AsyncSession, merchant: Merchant) -> int:
    """Mark the seeded history's events as already handled.

    Deliberately narrow. ``processed_events`` is an idempotency ledger: a
    consumer inserts a key here in the same transaction as its side effect, and
    the unique constraint turns a duplicate delivery into a no-op. Inventing
    plausible-looking keys would be worse than leaving the table empty -- the
    day a real consumer claims a key that collides with a seeded one, its work
    is skipped and nothing raises.

    So the key is each seeded event's **own id**. Those are UUIDs minted at seed
    time and can never be produced again, so no future delivery can collide with
    one; and "these historical demo events were processed" is true of the
    narrative the rest of the seed builds.

    Note: ``claim_event`` currently has no callers, so nothing writes this table
    at runtime yet.
    """
    rows = (
        (
            await session.execute(
                select(DomainEvent.id, DomainEvent.event_type)
                .where(
                    DomainEvent.merchant_id == merchant.id,
                    DomainEvent.event_type.in_(tuple(_CLAIMED_BY)),
                )
                .order_by(DomainEvent.created_at)
            )
        )
        .all()
    )
    if not rows:
        return 0

    existing = {
        (scope, key)
        for scope, key in (
            await session.execute(
                select(ProcessedEvent.scope, ProcessedEvent.event_key).where(
                    ProcessedEvent.merchant_id == merchant.id
                )
            )
        ).all()
    }

    created = 0
    for event_id, event_type in rows:
        scope = _CLAIMED_BY[event_type]
        key = str(event_id)
        if (scope, key) in existing:
            continue
        session.add(
            ProcessedEvent(
                merchant_id=merchant.id,
                scope=scope,
                event_key=key,
                result_ref=event_type,
            )
        )
        created += 1

    await session.flush()
    log.info("processed_events_seeded", created=created)
    return created


async def seed_automation_history(
    session: AsyncSession, merchant: Merchant, *, actor_id: uuid.UUID | None
) -> dict[str, int]:
    """Drive the procurement loop with the vendor mail transport muted.

    Raising a purchase order really does contact the supplier when Gmail is
    configured, and seeding a demo database is not a reason to email anyone. The
    credential is blanked for the duration -- ``emails_enabled`` is derived from
    it, and the email layer renders to the log when it is false -- and restored
    afterwards, so a seed run cannot send mail even on a machine set up to.
    """
    saved = settings.gmail_credentials_b64
    settings.gmail_credentials_b64 = ""
    try:
        return await _drive_procurement(session, merchant, actor_id=actor_id)
    finally:
        settings.gmail_credentials_b64 = saved


async def _drive_procurement(
    session: AsyncSession, merchant: Merchant, *, actor_id: uuid.UUID | None
) -> dict[str, int]:
    """Drive the real procurement loop once so its tables are not empty.

    Deliberately *runs* the services rather than inserting rows into their
    tables. A hand-written purchase order can contradict the ledger it is
    supposed to have come from; one produced by ``replenish`` and ``receive``
    cannot, because it took the same path a live reorder takes -- including the
    stock movements, the batch, the automation run and the domain events.

    Fills: inventory_movements, automation_runs, purchase_orders,
    purchase_order_lines, domain_events (and more inventory_batches).
    """
    from app.services.inventory.automation import InventoryAutomation
    from app.services.inventory.procurement import ProcurementService

    counts = {"consumed": 0, "runs": 0, "orders": 0, "received": 0}
    automation = InventoryAutomation(session, merchant.id)
    procurement = ProcurementService(session, merchant.id)
    engine = StockEngine(session, merchant.id)

    items = list(
        (
            await session.execute(
                select(InventoryItem)
                .where(InventoryItem.merchant_id == merchant.id)
                .order_by(InventoryItem.sku)
            )
        ).scalars()
    )
    if not items:
        log.warning("automation_history_skipped", reason="no inventory items")
        return counts

    # A week of counter sales, drawn down far enough that the top items cross
    # their reorder point. This is what a low-stock event is actually made of.
    for offset, item in enumerate(items[:5]):
        on_hand = float(item.quantity_on_hand)
        target = float(item.reorder_point or 0)
        quantity = max(round(on_hand - target * 0.6, 2), 1.0)
        if quantity >= on_hand:
            quantity = max(round(on_hand * 0.7, 2), 1.0)
        try:
            await engine.apply(
                item_id=item.id,
                movement_type=MovementType.SALE,
                quantity=quantity,
                note="Counter sales for the week",
                reference_type="SEED",
                reference_id=f"week-{offset + 1}",
                source="seed",
            )
            counts["consumed"] += 1
        except InsufficientStock:
            continue

    await session.flush()

    # Let the automation decide. force=True because the seeded policy may not
    # have an automatic-ordering flag set, and the point is to exercise the path.
    for item in items[:5]:
        try:
            result = await automation.replenish(inventory_item_id=item.id, force=True)
        except Exception as exc:  # a vendor-less item is a real outcome, not a failure
            log.info("replenish_skipped", sku=item.sku, detail=str(exc)[:120])
            continue
        counts["runs"] += 1
        if getattr(result, "purchase_order_id", None):
            counts["orders"] += 1

    await session.flush()

    # Walk one order all the way to goods-in, so the receipt path and its batch,
    # ledger movement and status transition are all represented.
    orders = list(
        (
            await session.execute(
                select(PurchaseOrder)
                .where(PurchaseOrder.merchant_id == merchant.id)
                .order_by(PurchaseOrder.created_at.desc())
            )
        ).scalars()
    )
    for order in orders[:2]:
        try:
            hydrated = await procurement.hydrate(order)
            if hydrated.status == PurchaseOrderStatus.PENDING_APPROVAL and actor_id:
                hydrated = await procurement.approve(
                    order_id=order.id, approve=True, actor_id=actor_id, note="Seeded approval"
                )
            if hydrated.status == PurchaseOrderStatus.APPROVED:
                hydrated = await procurement.mark_sent(
                    order_id=order.id, channel="EMAIL", detail="Seeded vendor notification"
                )
            lines = [
                {"line_id": line.id, "quantity": float(line.quantity_outstanding)}
                for line in hydrated.lines
                if float(line.quantity_outstanding) > 0
            ]
            if lines and counts["received"] == 0:
                # One full receipt; the second order is left in flight on purpose
                # so the board shows both states.
                await procurement.receive(
                    order_id=order.id, lines=lines, actor_id=actor_id
                )
                counts["received"] += 1
        except Exception as exc:
            log.info("order_walk_skipped", reference=order.reference, detail=str(exc)[:120])
            continue

    try:
        await automation.sweep_aging()
        counts["runs"] += 1
    except Exception as exc:
        log.info("sweep_skipped", detail=str(exc)[:120])

    await session.flush()
    log.info("automation_history_seeded", **counts)
    return counts


#: One completed investigation, told as the trace the Agent Activity page renders.
#: Mirrors the demo narrative rather than inventing a second story: the evening
#: repeat-customer opportunity, the tools that produced it, and the approval gate.
_AGENT_STEPS: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "intake",
        AgentName.ORCHESTRATOR,
        "Classified the merchant's question as a revenue investigation.",
        "Intent: investigate. Routed to the Growth Scientist.",
        "",
    ),
    (
        "growth_scientist",
        AgentName.GROWTH_SCIENTIST,
        "Computed the period metrics and decomposed the revenue movement.",
        "Revenue down 12.9%. Orders down 7.9%, AOV down 5.5%, repeat rate down 11.8%.",
        "The decline concentrates in repeat customers, not in footfall.",
    ),
    (
        "review_intelligence",
        AgentName.REVIEW_INTELLIGENCE,
        "Classified the period's reviews by topic and sentiment.",
        "Waiting-time complaints up 117% over the same window, concentrated in the evening.",
        "",
    ),
    (
        "market_intelligence",
        AgentName.MARKET_INTELLIGENCE,
        "Compared competitor perception on speed and service.",
        "Competitors are perceived as faster on service; price perception is unchanged.",
        "",
    ),
    (
        "synthesize",
        AgentName.ORCHESTRATOR,
        "Assembled the evidence into a single schema-validated recommendation.",
        "Opportunity: recover lost evening repeat customers. Rs 14,470/month at 92% confidence.",
        "Recommend a targeted evening win-back against a held-out control group.",
    ),
    (
        "approval_gate",
        AgentName.ORCHESTRATOR,
        "Stopped for human approval: the action commits budget.",
        "Awaiting merchant approval. No campaign was created or launched by the agent.",
        "APPROVAL_REQUIRED",
    ),
)

#: (tool, arguments, one-line result) - the deterministic calls behind the run.
_AGENT_TOOLS: tuple[tuple[str, str, dict, str], ...] = (
    ("get_sales_summary", AgentName.GROWTH_SCIENTIST, {"days": 30}, "Revenue Rs 4.94L, down 12.9%."),
    ("get_customer_metrics", AgentName.GROWTH_SCIENTIST, {"days": 30}, "Repeat rate 38.3%, down 11.8%."),
    (
        "get_customer_segments",
        AgentName.GROWTH_SCIENTIST,
        {"dimension": "daypart"},
        "Evening segment down 32.3%, the steepest of the four slots.",
    ),
    (
        "get_review_summary",
        AgentName.REVIEW_INTELLIGENCE,
        {"days": 30, "topic": "waiting_time"},
        "Waiting-time complaints up 117%; 2,475 reviews scanned.",
    ),
    (
        "get_competitor_summary",
        AgentName.MARKET_INTELLIGENCE,
        {"limit": 3},
        "Three competitors; service speed is their strongest perceived advantage.",
    ),
    (
        "calculate_opportunity_value",
        AgentName.GROWTH_SCIENTIST,
        {"segment": "EVENING", "horizon_days": 30},
        "Rs 14,470/month recoverable at 92% confidence.",
    ),
)


async def seed_agent_history(
    session: AsyncSession, merchant: Merchant, *, user_id: uuid.UUID | None
) -> int:
    """One completed agent run, with its steps and tool calls.

    The Agent Activity and trace pages are the ones that make the system's
    autonomy visible, and on a fresh database they had nothing to render. The run
    is recorded as ``used_fallback`` and ``model=None`` because no model was
    called to produce it -- labelling it as deterministic is the same rule the
    rest of the app follows, rather than dressing seeded rows up as inference.

    Fills: agent_runs, agent_steps, agent_tool_calls.
    """
    existing = (
        await session.execute(select(AgentRun).where(AgentRun.merchant_id == merchant.id).limit(1))
    ).scalars().first()
    if existing is not None:
        return 0

    opportunity = (
        await session.execute(
            select(GrowthOpportunity)
            .where(GrowthOpportunity.merchant_id == merchant.id)
            .order_by(GrowthOpportunity.estimated_value_monthly.desc())
            .limit(1)
        )
    ).scalars().first()

    started = datetime.now(tz=UTC) - timedelta(hours=6)
    run = AgentRun(
        merchant_id=merchant.id,
        user_id=user_id,
        agent_name=AgentName.GROWTH_SCIENTIST,
        workflow=AgentWorkflow.INVESTIGATE,
        status=AgentRunStatus.AWAITING_APPROVAL,
        input_text="Why are sales down?",
        intent="investigate",
        channel="web",
        summary=(
            "Revenue fell 12.9%, and the fall concentrates in evening repeat customers "
            "rather than in footfall. Waiting-time complaints moved in step over the same "
            "window. Recommended a targeted evening win-back with a held-out control group; "
            "a blanket discount was considered and rejected."
        ),
        decision="Run a targeted evening win-back experiment.",
        confidence=0.92,
        requires_approval=True,
        opportunity_id=opportunity.id if opportunity else None,
        used_fallback=True,
        started_at=started,
        finished_at=started + timedelta(seconds=9),
        duration_ms=9_240,
        metadata_json={"source": "seed", "deterministic": True},
    )
    session.add(run)
    await session.flush()

    for index, (node, agent, action, result, decision) in enumerate(_AGENT_STEPS, start=1):
        session.add(
            AgentStep(
                merchant_id=merchant.id,
                agent_run_id=run.id,
                sequence=index,
                node=node,
                agent_name=agent,
                action=action,
                result=result,
                decision=decision or None,
                status=AgentStepStatus.COMPLETED,
                evidence=[],
            )
        )

    for index, (tool, agent, arguments, summary) in enumerate(_AGENT_TOOLS, start=1):
        session.add(
            AgentToolCall(
                merchant_id=merchant.id,
                agent_run_id=run.id,
                sequence=index,
                tool_name=tool,
                agent_name=agent,
                arguments=arguments,
                result={},
                result_summary=summary,
            )
        )

    await session.flush()
    log.info(
        "agent_history_seeded", steps=len(_AGENT_STEPS), tool_calls=len(_AGENT_TOOLS)
    )
    return 1
