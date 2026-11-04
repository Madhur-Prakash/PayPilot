"""Shared plumbing for the sponsor adapters.

Every adapter follows the same contract as the PayPal gateway:

  * ``mode`` is ``LIVE`` when credentials are configured, ``SIMULATED`` when not -
    and it is returned with every result, so a fallback can never be mistaken for
    the real service;
  * a missing key degrades to a deterministic, labelled fallback instead of an error;
  * secrets are never logged and never returned to a client;
  * the HTTP transport is injectable, so tests exercise the real request-building and
    response-parsing code against mocked responses.
"""

from __future__ import annotations

from typing import Any

import httpx

LIVE = "LIVE"
SIMULATED = "SIMULATED"

DEFAULT_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


class SponsorError(Exception):
    """A sponsor service failed. The message is safe to show to a user."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class SponsorRequestError(SponsorError):
    """The caller asked for something invalid (bad URL, empty query) - not an upstream failure."""


def build_client(
    base_url: str,
    headers: dict[str, str] | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    timeout: httpx.Timeout | float = DEFAULT_TIMEOUT,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=base_url.rstrip("/"), headers=headers or {}, timeout=timeout, transport=transport
    )


def raise_for_status(response: httpx.Response, service: str) -> None:
    """Turn an HTTP error into a SponsorError that never echoes credentials."""
    if response.is_success:
        return
    detail = ""
    try:
        body = response.json()
        if isinstance(body, dict):
            detail = str(body.get("message") or body.get("error") or body.get("detail") or "")[:200]
    except ValueError:
        detail = response.text[:120]
    raise SponsorError(
        f"{service} returned HTTP {response.status_code}" + (f": {detail}" if detail else ""),
        status_code=response.status_code,
    )


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
