"""Verify the live integrations from the command line: ``python -m app.integrations.verify``.

One lightweight call per service, nothing created, no secret printed:

* **Channel3** - ``GET /v1/categories/search?query=coffee&limit=1`` with ``CHANNEL3_API_KEY``.
* **PayPal**   - an OAuth 2.0 client-credentials token from the configured environment.

Exit code 0 when every configured service answered; 1 when one failed. A service that
is not configured is reported (with how to enable it) but is not a failure.
"""

from __future__ import annotations

import asyncio
import sys

from app.core.config import settings


async def _channel3() -> tuple[str, bool]:
    from app.integrations.sponsors.base import SponsorError
    from app.integrations.sponsors.channel3_catalog import Channel3Catalog

    catalog = Channel3Catalog()
    if not catalog.configured:
        return "NOT CONFIGURED - set CHANNEL3_API_KEY (https://trychannel3.com/developers). Product Discovery stays off.", True
    try:
        categories = await catalog.categories("coffee", limit=1)
    except SponsorError as exc:
        return f"FAILED - {exc}", False
    return f"OK - live catalog reachable ({len(categories)} category match, prices in {catalog.currency})", True


async def _paypal() -> tuple[str, bool]:
    if not settings.paypal_configured:
        return ("NOT CONFIGURED - payments run on the labelled simulator. Set PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET "
                "from a sandbox REST app (developer.paypal.com -> Apps & Credentials)."), True
    from app.integrations.paypal.client import PayPalClient
    from app.integrations.paypal.errors import PayPalError

    client = PayPalClient()
    try:
        await client.access_token()
    except PayPalError as exc:
        return f"FAILED - {exc.message}", False
    finally:
        await client.aclose()
    webhook = "webhook id set" if settings.paypal_webhook_id else "PAYPAL_WEBHOOK_ID not set (real webhooks will be rejected)"
    return f"OK - {settings.paypal_mode} credentials accepted by {settings.paypal_base_url}; {webhook}", True


async def main() -> int:
    results = {"Channel3": await _channel3(), "PayPal": await _paypal()}
    width = max(len(k) for k in results)
    for name, (message, _) in results.items():
        print(f"  {name:<{width}}  {message}")
    return 0 if all(ok for _, ok in results.values()) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
