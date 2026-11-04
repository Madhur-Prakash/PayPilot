"""Evidence search: one ranked search over everything that explains a decision.

Sources (each tied to the permission a user needs to see it - a search result is
never a way around RBAC):

    audit          audit:read          who did what, and when
    agent_message  agents:view         signed agent-to-agent protocol messages
    offer          procurement:read    negotiation offers and their rationale
    procurement    procurement:read    RFQs, recommendations, failure reasons
    invoice        supplier_invoice:read  supplier invoices and PayPal references
    event          events:read         cross-module business events
    review         reviews:read        customer reviews

Two engines, one interface:

  * **Elasticsearch** when ``ELASTIC_URL`` is set - ``reindex`` bulk-upserts the
    documents and ``search`` runs a tenant-filtered ``multi_match``;
  * **keyword fallback** otherwise - the same documents scored in-process, so the
    screen works on a fresh checkout. The response says which engine answered.

Tenant isolation: documents are always built from ``merchant_id``-scoped queries,
and the Elasticsearch client refuses to search without a merchant filter.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.audit import AuditLog
from app.db.models.automation import DomainEvent
from app.db.models.governance import AgentMessage
from app.db.models.review import Review
from app.db.models.supply import NegotiationOffer, ProcurementRequest, SupplierInvoice
from app.integrations.sponsors import SponsorError, get_elastic
from app.services.intelligence.events import BusinessEvent

log = get_logger(__name__)

KIND_PERMISSION: dict[str, str] = {
    "audit": "audit:read",
    "agent_message": "agents:view",
    "offer": "procurement:read",
    "procurement": "procurement:read",
    "invoice": "supplier_invoice:read",
    "event": "events:read",
    "review": "reviews:read",
}
KIND_LABEL = {
    "audit": "Audit log",
    "agent_message": "Agent message",
    "offer": "Negotiation offer",
    "procurement": "Procurement",
    "invoice": "Supplier invoice",
    "event": "Business event",
    "review": "Customer review",
}
PER_KIND_LIMIT = 400


def allowed_kinds(permissions: Iterable[str]) -> list[str]:
    granted = set(permissions)
    return [kind for kind, permission in KIND_PERMISSION.items() if permission in granted]


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()


def _doc(merchant_id: uuid.UUID, kind: str, ref: Any, title: str, body: str, *, actor: str = "",
         correlation_id: str = "", occurred_at: datetime | None = None, link: str = "") -> dict[str, Any]:
    return {
        "merchant_id": str(merchant_id),
        "kind": kind,
        "ref": str(ref),
        "title": title.strip()[:240],
        "body": " ".join(body.split())[:4000],
        "actor": actor[:120],
        "correlation_id": correlation_id[:64],
        "occurred_at": _iso(occurred_at),
        "link": link,
    }


async def collect_documents(session: AsyncSession, merchant_id: uuid.UUID, kinds: list[str]) -> list[dict[str, Any]]:
    """Build search documents for one merchant. Every query is merchant-scoped."""
    docs: list[dict[str, Any]] = []
    mid = merchant_id

    if "audit" in kinds:
        audit_rows = (await session.execute(
            select(AuditLog).where(AuditLog.merchant_id == mid).order_by(AuditLog.created_at.desc()).limit(PER_KIND_LIMIT)
        )).scalars().all()
        docs += [_doc(mid, "audit", r.id, f"{r.action} {r.resource}".strip(), f"{r.description} {r.actor_label} {r.status}",
                      actor=r.actor_label, occurred_at=r.created_at, link="/activity") for r in audit_rows]

    if "agent_message" in kinds:
        message_rows = (await session.execute(
            select(AgentMessage).where(AgentMessage.merchant_id == mid).order_by(AgentMessage.sent_at.desc()).limit(PER_KIND_LIMIT)
        )).scalars().all()
        docs += [_doc(mid, "agent_message", r.id, r.message_type, f"{r.sender} to {r.recipient}. {r.summary}",
                      actor=r.sender, correlation_id=r.correlation_id, occurred_at=r.sent_at,
                      link="/agents/communication") for r in message_rows]

    if "offer" in kinds:
        offer_rows = (await session.execute(
            select(NegotiationOffer).where(NegotiationOffer.merchant_id == mid)
            .order_by(NegotiationOffer.created_at.desc()).limit(PER_KIND_LIMIT)
        )).scalars().all()
        docs += [_doc(mid, "offer", r.id, f"Round {r.round} {r.direction} {r.kind}",
                      f"{r.rationale} unit price {r.unit_price} landed total {r.landed_total} "
                      f"lead time {r.lead_time_days} days validation {r.validation_status}",
                      actor=r.proposed_by, occurred_at=r.created_at, link="/supply/negotiations") for r in offer_rows]

    if "procurement" in kinds:
        request_rows = (await session.execute(
            select(ProcurementRequest).where(ProcurementRequest.merchant_id == mid)
            .order_by(ProcurementRequest.created_at.desc()).limit(PER_KIND_LIMIT)
        )).scalars().all()
        docs += [_doc(mid, "procurement", r.id, f"{r.reference} {r.product_name}",
                      f"status {r.status} quantity {r.quantity} {r.unit} {r.failure_reason} "
                      f"{(r.recommendation or {}).get('summary', '')}",
                      correlation_id=r.correlation_id, occurred_at=r.created_at, link="/supply/rfqs") for r in request_rows]

    if "invoice" in kinds:
        invoice_rows = (await session.execute(
            select(SupplierInvoice).where(SupplierInvoice.merchant_id == mid)
            .order_by(SupplierInvoice.created_at.desc()).limit(PER_KIND_LIMIT)
        )).scalars().all()
        docs += [_doc(mid, "invoice", r.id, f"Invoice {r.invoice_number}",
                      f"status {r.status} total {r.total} {r.currency} terms {r.payment_terms} paypal {r.paypal_invoice_id}",
                      occurred_at=r.issued_at, link="/supply/invoices") for r in invoice_rows]

    if "event" in kinds:
        event_rows = (await session.execute(
            select(DomainEvent).where(DomainEvent.merchant_id == mid, DomainEvent.event_type.like("business.%"))
            .order_by(DomainEvent.created_at.desc()).limit(PER_KIND_LIMIT)
        )).scalars().all()
        docs += [_doc(mid, "event", r.id, BusinessEvent.LABELS.get(r.event_type, r.event_type),
                      " ".join(f"{k} {v}" for k, v in (r.payload or {}).items() if isinstance(v, (str, int, float))),
                      actor=r.source, correlation_id=r.correlation_id, occurred_at=r.created_at, link="/command")
                 for r in event_rows]

    if "review" in kinds:
        rows = (await session.execute(
            select(Review).where(Review.merchant_id == mid).order_by(Review.reviewed_at.desc()).limit(PER_KIND_LIMIT)
        )).scalars().all()
        docs += [_doc(mid, "review", r.id, r.title or f"{r.rating}-star review", f"{r.body} topic {r.primary_topic}",
                      actor=r.author_name, occurred_at=r.reviewed_at, link="/reviews") for r in rows]

    return docs


# --------------------------------------------------------------------------- #
# Keyword fallback
# --------------------------------------------------------------------------- #
_TOKEN = re.compile(r"[a-z0-9$.#-]{2,}")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def _snippet(body: str, terms: list[str], width: int = 140) -> str:
    lowered = body.lower()
    positions = [lowered.find(t) for t in terms if lowered.find(t) >= 0]
    start = max(0, (min(positions) if positions else 0) - 40)
    piece = body[start:start + width]
    for term in sorted(set(terms), key=len, reverse=True):
        piece = re.sub(f"({re.escape(term)})", r"<mark>\1</mark>", piece, flags=re.IGNORECASE)
    return ("..." if start else "") + piece


def keyword_search(docs: list[dict[str, Any]], text: str, size: int) -> list[dict[str, Any]]:
    terms = _tokens(text)
    if not terms:
        return []
    scored: list[tuple[float, dict[str, Any]]] = []
    for doc in docs:
        title, body = doc["title"].lower(), doc["body"].lower()
        score = sum(3.0 * title.count(t) + body.count(t) for t in terms)
        # Matching *every* term beats matching one term many times.
        score += 2.0 * sum(1 for t in terms if t in title or t in body)
        if score > 0:
            scored.append((score, doc))
    scored.sort(key=lambda pair: (pair[0], pair[1].get("occurred_at") or ""), reverse=True)
    return [
        {**{k: d[k] for k in ("kind", "ref", "title", "actor", "occurred_at", "correlation_id", "link")},
         "snippet": _snippet(d["body"] or d["title"], terms), "score": round(score, 2)}
        for score, d in scored[:size]
    ]


# --------------------------------------------------------------------------- #
# Public operations
# --------------------------------------------------------------------------- #
async def reindex(session: AsyncSession, merchant_id: uuid.UUID) -> dict[str, Any]:
    """Push this merchant's evidence into Elasticsearch (idempotent upserts)."""
    elastic = get_elastic()
    if not elastic.configured:
        return {"engine": "keyword-fallback", "mode": elastic.mode, "indexed": 0, "errors": 0,
                "note": "ELASTIC_URL is not set - nothing to index; search uses the in-process fallback."}
    docs = await collect_documents(session, merchant_id, list(KIND_PERMISSION))
    created = await elastic.ensure_index()
    result = await elastic.bulk_index(docs)
    log.info("evidence_reindexed", documents=len(docs), **result)
    return {"engine": "elasticsearch", "mode": elastic.mode, "index": elastic.index,
            "index_created": created, "documents": len(docs), **result}


async def search(session: AsyncSession, merchant_id: uuid.UUID, text: str, permissions: Iterable[str],
                 *, kinds: list[str] | None = None, size: int = 20) -> dict[str, Any]:
    text = text.strip()
    permitted = allowed_kinds(permissions)
    selected = [k for k in (kinds or permitted) if k in permitted]
    base = {"query": text, "kinds": selected, "kind_labels": KIND_LABEL}
    if not text or not selected:
        return {**base, "engine": "none", "mode": get_elastic().mode, "results": [], "note": ""}

    elastic = get_elastic()
    if elastic.configured:
        try:
            results = await elastic.search(merchant_id, text, kinds=selected, size=size)
            return {**base, "engine": "elasticsearch", "mode": elastic.mode, "results": results, "note": ""}
        except SponsorError as exc:
            log.warning("elastic_search_failed_falling_back", error=str(exc))
            note = f"Elasticsearch unavailable ({exc}); showing in-process keyword results."
    else:
        note = "ELASTIC_URL is not set: in-process keyword search over the same documents."

    docs = await collect_documents(session, merchant_id, selected)
    return {**base, "engine": "keyword-fallback", "mode": "SIMULATED",
            "results": keyword_search(docs, text, size), "note": note}
