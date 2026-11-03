"""External market context.

Default provider is ``seed``: signals come from the merchant's own seeded
``external_signals`` table, already scored for relevance against that merchant's
revenue mix. Configuring ``EXTERNAL_SEARCH_PROVIDER=tavily`` swaps in a live web
search without changing any caller.

Whatever the provider, a signal is only surfaced when it can be tied to the
merchant's actual exposure - this is deliberately not a news feed.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass(slots=True)
class ExternalResult:
    title: str
    summary: str
    url: str | None = None
    source_name: str = "Web"
    score: float = 0.5
    published_at: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class ExternalSearchService:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    @property
    def provider(self) -> str:
        return settings.external_search_provider

    @property
    def live_enabled(self) -> bool:
        return settings.external_search_provider == "tavily" and bool(settings.tavily_api_key)

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(15.0))
        return self._client

    async def search(self, query: str, *, limit: int = 5) -> list[ExternalResult]:
        """Fetch external context. Returns [] when no live provider is configured.

        Callers fall back to seeded signals, so the core demo never depends on an
        external API being reachable.
        """
        if not self.live_enabled:
            log.debug("external_search_skipped", provider=self.provider, reason="not_configured")
            return []
        try:
            response = await self._http().post(
                "https://api.tavily.com/search",
                json={
                    "api_key": settings.tavily_api_key,
                    "query": query,
                    "max_results": limit,
                    "search_depth": "basic",
                    "include_answer": False,
                },
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            log.warning("external_search_failed", detail=str(exc)[:200])
            return []

        results: list[ExternalResult] = []
        for item in payload.get("results", [])[:limit]:
            results.append(
                ExternalResult(
                    title=str(item.get("title", ""))[:240],
                    summary=str(item.get("content", ""))[:1000],
                    url=item.get("url"),
                    source_name=str(item.get("url", "")).split("/")[2]
                    if item.get("url")
                    else "Web",
                    score=float(item.get("score", 0.5) or 0.5),
                    raw=item,
                )
            )
        log.info("external_search", provider="tavily", query=query[:80], results=len(results))
        return results

    async def close(self) -> None:
        if self._client is not None:
            with contextlib.suppress(Exception):
                await self._client.aclose()
            self._client = None


external_search = ExternalSearchService()
