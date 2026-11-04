"""Elasticsearch - evidence search across the merchant's operating history.

Every approval needs evidence: why this supplier, what was negotiated, what the
PayPal capture said, which review or event triggered the demand. That evidence is
spread over audit logs, signed agent messages, negotiation offers, supplier
invoices, business events and customer reviews. Elasticsearch gives one ranked
full-text search over all of it.

It talks to the standard Elasticsearch REST API over HTTP (no client package):

  * ``PUT  /{index}``                   create the index with an explicit mapping
  * ``POST /_bulk``                     idempotent upserts (``index`` with a fixed ``_id``)
  * ``POST /{index}/_search``           ranked ``multi_match`` + highlight
  * ``GET  /``                          reachability check

Auth is ``Authorization: ApiKey <key>`` when ``ELASTIC_API_KEY`` is set (a local
dev node runs without security).

**Tenant isolation is not the caller's job.** ``search`` takes ``merchant_id`` as a
required argument and always wraps the query in a ``merchant_id`` term filter, so
there is no code path that searches across merchants.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.sponsors.base import (
    LIVE,
    SIMULATED,
    SponsorError,
    as_dict,
    build_client,
    raise_for_status,
)

log = get_logger(__name__)

MAPPING: dict[str, Any] = {
    "mappings": {
        "dynamic": "false",
        "properties": {
            "merchant_id": {"type": "keyword"},
            "kind": {"type": "keyword"},
            "ref": {"type": "keyword"},
            "title": {"type": "text"},
            "body": {"type": "text"},
            "actor": {"type": "keyword"},
            "correlation_id": {"type": "keyword"},
            "occurred_at": {"type": "date"},
            "link": {"type": "keyword"},
        },
    }
}


class ElasticClient:
    def __init__(self, *, url: str | None = None, api_key: str | None = None,
                 index: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._url = settings.elastic_url if url is None else url
        self._key = settings.elastic_api_key if api_key is None else api_key
        self.index = index or f"{settings.elastic_index_prefix}-evidence"
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(self._url)

    @property
    def mode(self) -> str:
        return LIVE if self.configured else SIMULATED

    def __repr__(self) -> str:
        return f"ElasticClient(configured={self.configured}, index={self.index})"

    def _client(self) -> httpx.AsyncClient:
        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["Authorization"] = f"ApiKey {self._key}"
        return build_client(self._url, headers, transport=self._transport)

    async def _call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if not self.configured:
            raise SponsorError("Elasticsearch is not configured (set ELASTIC_URL).")
        try:
            async with self._client() as client:
                return await client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise SponsorError(f"Elasticsearch is unreachable ({type(exc).__name__}).") from exc

    async def ping(self) -> dict[str, Any]:
        response = await self._call("GET", "/")
        raise_for_status(response, "Elasticsearch")
        body = as_dict(response.json())
        return {"cluster": body.get("cluster_name", ""), "version": as_dict(body.get("version")).get("number", "")}

    async def ensure_index(self) -> bool:
        """Create the index if missing. Returns True when it was created."""
        head = await self._call("HEAD", f"/{self.index}")
        if head.status_code == 200:
            return False
        created = await self._call("PUT", f"/{self.index}", content=json.dumps(MAPPING))
        raise_for_status(created, "Elasticsearch")
        return True

    async def bulk_index(self, documents: list[dict[str, Any]]) -> dict[str, int]:
        """Upsert documents keyed by ``merchant_id:kind:ref`` - re-indexing never duplicates."""
        if not documents:
            return {"indexed": 0, "errors": 0}
        lines: list[str] = []
        for doc in documents:
            doc_id = f"{doc['merchant_id']}:{doc['kind']}:{doc['ref']}"
            lines.append(json.dumps({"index": {"_index": self.index, "_id": doc_id}}))
            lines.append(json.dumps(doc, default=str))
        response = await self._call(
            "POST", "/_bulk", content="\n".join(lines) + "\n",
            headers={"Content-Type": "application/x-ndjson"}, params={"refresh": "true"},
        )
        raise_for_status(response, "Elasticsearch")
        body = as_dict(response.json())
        items = body.get("items") or []
        errors = sum(1 for item in items if as_dict(as_dict(item).get("index")).get("error"))
        return {"indexed": len(items) - errors, "errors": errors}

    async def search(self, merchant_id: uuid.UUID, text: str, *, kinds: list[str] | None = None,
                     size: int = 20) -> list[dict[str, Any]]:
        filters: list[dict[str, Any]] = [{"term": {"merchant_id": str(merchant_id)}}]
        if kinds:
            filters.append({"terms": {"kind": kinds}})
        query = {
            "size": max(1, min(size, 50)),
            "query": {
                "bool": {
                    "must": [{"multi_match": {"query": text, "fields": ["title^3", "body"], "fuzziness": "AUTO"}}],
                    "filter": filters,
                }
            },
            "highlight": {"fields": {"body": {"fragment_size": 140, "number_of_fragments": 1}, "title": {}},
                          "pre_tags": ["<mark>"], "post_tags": ["</mark>"]},
        }
        response = await self._call("POST", f"/{self.index}/_search", content=json.dumps(query))
        raise_for_status(response, "Elasticsearch")
        hits = as_dict(as_dict(response.json()).get("hits")).get("hits") or []
        results: list[dict[str, Any]] = []
        for hit in hits:
            hit = as_dict(hit)
            source = as_dict(hit.get("_source"))
            highlight = as_dict(hit.get("highlight"))
            snippet = (highlight.get("body") or highlight.get("title") or [source.get("body", "")[:140]])[0]
            results.append({
                "kind": source.get("kind", ""),
                "ref": source.get("ref", ""),
                "title": source.get("title", ""),
                "snippet": snippet,
                "actor": source.get("actor", ""),
                "occurred_at": source.get("occurred_at"),
                "correlation_id": source.get("correlation_id", ""),
                "link": source.get("link", ""),
                "score": hit.get("_score"),
            })
        return results
