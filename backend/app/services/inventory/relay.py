"""The outbox relay.

Events are written to the outbox inside the transaction that caused them, which
is what makes a stock change and its event atomic. Something then has to carry
them to n8n — and until this existed, nothing did: events sat at PENDING until a
human pressed "Flush event outbox" in the Automation Center. The retry schedule
was equally inert, because retries are also only attempted by a dispatch.

So this is the missing half of the outbox pattern. It belongs in the backend
rather than in an n8n schedule, because draining the outbox is not a business
decision about *when* to act — it is the transport for decisions already made,
and it has to keep working when n8n is the thing that is down.
"""

from __future__ import annotations

import asyncio
import contextlib

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.services.inventory import events as event_bus

log = get_logger(__name__)

#: Backoff applied to the *loop*, not to individual events, when a tick raises.
#: Without it a database outage would spin this loop as fast as the event loop
#: allows and bury the real error in log noise.
_ERROR_BACKOFF = 30.0


class OutboxRelay:
    """Delivers due events on a timer, for the lifetime of the process."""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.running:
            return

        if not settings.inventory_automation_enabled:
            log.info("outbox_relay_disabled", reason="inventory automation is off")
            return

        if not settings.n8n_inventory_webhook_url:
            # dispatch_pending would mark everything SKIPPED, which is the right
            # behaviour on demand but pointless to do on a timer.
            log.info("outbox_relay_disabled", reason="no N8N_INVENTORY_WEBHOOK_URL")
            return

        self._task = asyncio.create_task(self._run(), name="inventory-outbox-relay")
        log.info(
            "outbox_relay_started",
            interval_seconds=settings.inventory_dispatch_interval_seconds,
            target=settings.n8n_inventory_webhook_url,
        )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        log.info("outbox_relay_stopped")

    async def _run(self) -> None:
        interval = max(1.0, float(settings.inventory_dispatch_interval_seconds))
        while True:
            try:
                await asyncio.sleep(interval)
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # The relay must outlive any single failure; a dead relay means
                # reorders stop happening silently, which is the worst outcome.
                log.error(
                    "outbox_relay_tick_failed",
                    error=f"{type(exc).__name__}: {exc}"[:300],
                )
                await asyncio.sleep(_ERROR_BACKOFF)

    async def _tick(self) -> None:
        async with SessionLocal() as session:
            result = await event_bus.dispatch_pending(session, limit=25)
        # Silence is the normal case - only say something when work happened.
        if result["delivered"] or result["failed"]:
            log.info("outbox_relay_tick", **result)


#: Started and stopped by the application lifespan.
relay = OutboxRelay()
