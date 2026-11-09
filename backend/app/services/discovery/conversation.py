"""Conversational shopping agent.

Each merchant message is one turn of Channel3's Conversations API
(``POST /v1/conversations``, buffered): Channel3's agent plans and runs real catalog
searches server-side and replies with text, product results and follow-up
suggestions. Its thread state lives at Channel3 under ``conversation_id``.

PayPilot adds two things on top:

* **Remembered constraints.** Every message is also parsed by the deterministic intent
  parser and merged into ``constraints`` (budget, product, use case, brands,
  features). They are shown to the merchant ("what I'm keeping in mind") and pinned
  as catalog filters (price) on later turns, so a budget stated in turn one still
  applies in turn four.
* **Persistence.** The thread, the products each turn returned and the credits used
  are stored per merchant, so the conversation survives a refresh.

Products shown come only from Channel3's tool results - the assistant's text is
Channel3's own, and nothing here generates product data.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models.discovery import SearchSource, ShoppingConversation
from app.integrations.sponsors import get_channel3_catalog
from app.integrations.sponsors.channel3 import attribution_id
from app.integrations.sponsors.channel3_catalog import build_filters
from app.services.discovery.intent import budget_in_catalog_currency, parse_intent
from app.services.discovery.service import ProductDiscoveryService, _throttle

MAX_STORED_MESSAGES = 60


def merge_constraints(previous: dict[str, Any], message: str, catalog_currency: str) -> dict[str, Any]:
    """Fold one message into the running constraints. Newer statements replace older ones."""
    intent = parse_intent(message)
    merged = dict(previous or {})
    if intent.max_price is not None or intent.min_price is not None:
        budget = budget_in_catalog_currency(intent, catalog_currency)
        merged["budget"] = {
            "stated": {"min": intent.min_price, "max": intent.max_price, "currency": intent.budget_currency},
            "catalog": {"min": budget["min_price"], "max": budget["max_price"], "currency": catalog_currency},
            "note": budget["note"],
        }
    if intent.use_case:
        merged["use_case"] = intent.use_case
    elif (merged.get("product") and intent.max_price is None and intent.min_price is None and not intent.brands
          and intent.category and len(intent.category.split()) <= 6):
        # A short follow-up to an open request answers the agent's question ("What will you use it
        # for?" -> "machine learning and development"): it refines the use, not the product.
        merged["use_case"] = intent.category
    if intent.brands:
        merged["brands"] = list(dict.fromkeys([*(merged.get("brands") or []), *intent.brands]))[:6]
    if intent.exclude_brands:
        merged["avoid_brands"] = list(dict.fromkeys([*(merged.get("avoid_brands") or []), *intent.exclude_brands]))[:6]
    if intent.attributes:
        merged["features"] = list(dict.fromkeys([*(merged.get("features") or []), *intent.attributes]))[:8]
    # The first concrete product phrase becomes the subject; a follow-up like
    # "machine learning and development" refines the use, not the product.
    if not merged.get("product") and intent.category and len(intent.category.split()) <= 6 and not intent.use_case:
        merged["product"] = intent.category
    if intent.on_sale:
        merged["on_sale"] = True
    return merged


def describe_constraints(constraints: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if constraints.get("product"):
        lines.append(f"Looking for: {constraints['product']}")
    budget = constraints.get("budget") or {}
    stated = budget.get("stated") or {}
    if stated.get("max") is not None or stated.get("min") is not None:
        span = (f"{stated['min']:,.0f}-{stated['max']:,.0f}" if stated.get("min") and stated.get("max")
                else f"up to {stated['max']:,.0f}" if stated.get("max") else f"from {stated['min']:,.0f}")
        lines.append(f"Budget: {stated.get('currency', '')} {span}")
    if constraints.get("use_case"):
        lines.append(f"Used for: {constraints['use_case']}")
    if constraints.get("features"):
        lines.append("Must have: " + ", ".join(constraints["features"]))
    if constraints.get("brands"):
        lines.append("Preferred brands: " + ", ".join(constraints["brands"]))
    if constraints.get("avoid_brands"):
        lines.append("Avoid: " + ", ".join(constraints["avoid_brands"]))
    if constraints.get("on_sale"):
        lines.append("Only deals")
    return lines


def conversation_out(row: ShoppingConversation, *, include_messages: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(row.id),
        "title": row.title,
        "channel3_conversation_id": row.channel3_conversation_id,
        "constraints": row.constraints or {},
        "remembered": describe_constraints(row.constraints or {}),
        "turn_count": row.turn_count,
        "credits_used": row.credits_used,
        "last_turn_at": row.last_turn_at.isoformat() if row.last_turn_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
    if include_messages:
        out["messages"] = row.messages or []
    return out


class ShoppingAssistant:
    def __init__(self, session: AsyncSession, merchant_id: uuid.UUID, *, user_id: uuid.UUID | None = None) -> None:
        self.session = session
        self.merchant_id = merchant_id
        self.user_id = user_id
        self.catalog = get_channel3_catalog()

    async def get(self, conversation_id: uuid.UUID) -> ShoppingConversation:
        row = (await self.session.execute(
            select(ShoppingConversation).where(ShoppingConversation.id == conversation_id,
                                               ShoppingConversation.merchant_id == self.merchant_id)
        )).scalars().first()
        if row is None:
            raise NotFoundError("Conversation not found.")
        return row

    async def list(self, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = (await self.session.execute(
            select(ShoppingConversation).where(ShoppingConversation.merchant_id == self.merchant_id)
            .order_by(ShoppingConversation.updated_at.desc()).limit(limit)
        )).scalars().all()
        return [conversation_out(r, include_messages=False) for r in rows]

    async def turn(self, message: str, *, conversation_id: uuid.UUID | None = None) -> dict[str, Any]:
        row = await self.get(conversation_id) if conversation_id else ShoppingConversation(
            merchant_id=self.merchant_id, user_id=self.user_id, title=message.strip()[:200], constraints={},
            messages=[], turn_count=0, credits_used=0,
        )
        constraints = merge_constraints(row.constraints or {}, message, self.catalog.currency)
        catalog_budget = (constraints.get("budget") or {}).get("catalog") or {}
        pinned = build_filters(min_price=catalog_budget.get("min"), max_price=catalog_budget.get("max"))
        await _throttle(self.merchant_id, 2)
        turn = await self.catalog.conversation_turn(
            message, conversation_id=row.channel3_conversation_id or None, filters=pinned or None,
            user_id=attribution_id(self.merchant_id),
        )
        now = datetime.now(tz=UTC).isoformat()
        products = [p.as_dict() for p in turn.products[:12]]
        messages = list(row.messages or [])
        messages.append({"role": "user", "text": message.strip()[:2000], "at": now})
        messages.append({
            "role": "assistant", "text": turn.text, "products": products, "suggestions": turn.suggestions,
            "searches": turn.searches, "at": now, "source": "Channel3 shopping agent",
        })
        row.messages = messages[-MAX_STORED_MESSAGES:]
        row.constraints = constraints
        row.channel3_conversation_id = turn.conversation_id or row.channel3_conversation_id
        row.turn_count = (row.turn_count or 0) + 1
        row.credits_used = (row.credits_used or 0) + int(turn.usage.get("credits_charged") or 0)
        row.last_turn_at = datetime.now(tz=UTC)
        if row.id is None or conversation_id is None:
            self.session.add(row)
        await ProductDiscoveryService(self.session, self.merchant_id, user_id=self.user_id)._remember(
            turn.products, SearchSource.CONVERSATION)
        await self.session.flush()
        return {
            "conversation": conversation_out(row),
            "reply": {"text": turn.text, "products": products, "suggestions": turn.suggestions,
                      "searches": turn.searches, "usage": turn.usage},
            "pinned_filters": pinned,
        }


__all__ = ["ShoppingAssistant", "conversation_out", "describe_constraints", "merge_constraints"]
