"""Kernel cloud browsers - supplier-portal verification sessions.

Some suppliers have no API, only a website. Before a human approves a purchase
the Buyer Agent can open the supplier's public catalogue page in a **Kernel cloud
browser** so the merchant can watch it live and confirm that the quoted product
and price really exist on the supplier's own site.

PayPilot's part is deliberately small and safe:

  * the session is created on demand, by a user holding ``procurement:negotiate``;
  * only public ``https`` pages on a real hostname are allowed (no localhost,
    private ranges or raw IPs), because the URL is user-supplied;
  * the session is short-lived (``timeout_seconds``) and closed after use;
  * the browser **observes** - nothing here fills a form, logs in or pays. Money
    still moves only through the approval-gated PayPal flow.

API (https://www.kernel.sh/docs): ``POST {base}/browsers`` with
``Authorization: Bearer $KERNEL_API_KEY`` and an optional JSON body
(``timeout_seconds``, ``headless``, ``start_url``, ``name`` ...). The response
carries ``session_id``, ``browser_live_view_url`` and ``cdp_ws_url``. Closing a
session is best-effort; Kernel also expires it at ``timeout_seconds``.
"""

from __future__ import annotations

import ipaddress
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.sponsors.base import (
    LIVE,
    SIMULATED,
    SponsorError,
    SponsorRequestError,
    build_client,
    raise_for_status,
)

log = get_logger(__name__)

MIN_TIMEOUT = 10
MAX_TIMEOUT = 600


@dataclass(slots=True)
class BrowserSession:
    mode: str
    session_id: str
    url: str
    live_view_url: str = ""
    cdp_ws_url: str = ""
    timeout_seconds: int = 120
    closed: bool = False
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "session_id": self.session_id,
            "url": self.url,
            "live_view_url": self.live_view_url,
            "cdp_ws_url_available": bool(self.cdp_ws_url),
            "timeout_seconds": self.timeout_seconds,
            "closed": self.closed,
            "note": self.note,
        }


def validate_public_https_url(raw: str) -> str:
    """Return a normalised URL, or raise SponsorError. The input is untrusted."""
    parsed = urlparse(raw.strip())
    if parsed.scheme != "https":
        raise SponsorRequestError("Only https:// supplier pages can be opened.")
    host = (parsed.hostname or "").lower()
    if not host or "." not in host or host.endswith((".local", ".internal", ".localhost")):
        raise SponsorRequestError("The URL must have a public hostname.")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        pass  # a DNS name - fine
    else:
        raise SponsorRequestError(f"Raw IP addresses are not allowed ({ip.version}).")
    if parsed.username or parsed.password:
        raise SponsorRequestError("URLs with embedded credentials are not allowed.")
    return parsed.geturl()


class KernelClient:
    def __init__(self, *, api_key: str | None = None, base_url: str | None = None,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._key = settings.kernel_api_key if api_key is None else api_key
        self._base = base_url or settings.kernel_base_url
        self._transport = transport

    @property
    def mode(self) -> str:
        return LIVE if self._key else SIMULATED

    def __repr__(self) -> str:
        return f"KernelClient(mode={self.mode})"

    async def open_session(self, url: str, *, timeout_seconds: int = 120, name: str = "") -> BrowserSession:
        url = validate_public_https_url(url)
        timeout_seconds = max(MIN_TIMEOUT, min(timeout_seconds, MAX_TIMEOUT))
        if not self._key:
            return BrowserSession(
                mode=SIMULATED,
                session_id=f"SIM-KERNEL-{uuid.uuid4().hex[:12]}",
                url=url,
                timeout_seconds=timeout_seconds,
                note="No KERNEL_API_KEY configured: no browser was started. A live session would open this page in a Kernel cloud browser.",
            )

        body: dict[str, Any] = {"timeout_seconds": timeout_seconds, "start_url": url, "headless": False}
        if name:
            body["name"] = name[:80]
        try:
            async with build_client(self._base, {"Authorization": f"Bearer {self._key}"},
                                    transport=self._transport) as client:
                response = await client.post("/browsers", json=body)
        except httpx.HTTPError as exc:
            raise SponsorError(f"Kernel is unreachable ({type(exc).__name__}).") from exc
        raise_for_status(response, "Kernel")
        data = response.json()
        session = BrowserSession(
            mode=LIVE,
            session_id=str(data.get("session_id") or ""),
            url=url,
            live_view_url=str(data.get("browser_live_view_url") or ""),
            cdp_ws_url=str(data.get("cdp_ws_url") or ""),
            timeout_seconds=timeout_seconds,
            note="Live Kernel cloud browser. It observes only and expires automatically.",
        )
        if not session.session_id:
            raise SponsorError("Kernel did not return a session id.")
        log.info("kernel_session_opened", session=session.session_id)
        return session

    async def close_session(self, session: BrowserSession) -> bool:
        """Best-effort close. The session also expires on its own timeout."""
        if session.mode != LIVE or not self._key:
            session.closed = True
            return True
        try:
            async with build_client(self._base, {"Authorization": f"Bearer {self._key}"},
                                    transport=self._transport) as client:
                response = await client.delete(f"/browsers/{session.session_id}")
            session.closed = response.is_success
        except httpx.HTTPError:
            session.closed = False
        if not session.closed:
            log.info("kernel_session_close_skipped", session=session.session_id,
                     reason="will expire at its timeout")
        return session.closed
