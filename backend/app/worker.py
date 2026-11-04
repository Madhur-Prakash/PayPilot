"""Background worker: delivers the transactional outbox outside the API process.

    python -m app.worker

Runs the same ``OutboxRelay`` the API runs in-process (set
``OUTBOX_RELAY_IN_PROCESS=false`` on the API when this worker is deployed, so
events are not delivered from two places - though the relay's row lease makes a
double run safe, just wasteful). Stops cleanly on SIGINT/SIGTERM.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import dispose_engine, ping_database
from app.services.inventory.relay import relay

log = get_logger("app.worker")


async def main() -> None:
    log.info("worker_starting", environment=settings.app_env, interval=settings.inventory_dispatch_interval_seconds)
    for attempt in range(30):
        if await ping_database():
            break
        log.warning("worker_waiting_for_database", attempt=attempt + 1)
        await asyncio.sleep(2)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        # Windows has no loop signal handlers; Ctrl-C raises KeyboardInterrupt instead.
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(sig, stop.set)

    relay.start()
    try:
        await stop.wait()
    finally:
        log.info("worker_stopping")
        await relay.stop()
        await dispose_engine()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
