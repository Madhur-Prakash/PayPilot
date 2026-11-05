"""AG Studio's AI assistant, run on PayPilot's own LLM.

AG Studio ships an agent harness - five agents (lead, data, page, planning, widget)
that build and edit a dashboard through Studio's own tools. Studio never talks to a
model provider itself: the host supplies an ``AgLlmAdapter``. PayPilot's adapter
posts each turn here, and this module runs it on an OpenAI-compatible
chat-completions API - Groq with ``GROQ_API_KEY`` by default, or whatever
``STUDIO_AI_BASE_URL`` / ``STUDIO_AI_API_KEY`` / ``STUDIO_AI_MODEL`` name - so the
key never reaches the browser.

What the assistant can do is bounded by Studio's tools, which execute **in the
browser, against the dashboard only**: add, configure and arrange charts over the
datasets the backend already computed and permission-filtered. Nothing in this
module reads the database, calls PayPal or changes a record - it relays one model
turn and returns the model's output.

Translation: Studio speaks an OpenAI *Responses*-style item list (input messages,
output messages, ``function_call`` / ``function_call_output`` items); the provider
speaks *chat completions*. ``to_chat_messages`` / ``to_output_items`` convert.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from pydantic import Field

from app.core.config import settings
from app.core.exceptions import IntegrationError, RateLimitError, ServiceUnavailableError
from app.core.logging import get_logger
from app.schemas.common import SchemaBase

log = get_logger(__name__)

GROQ_OPENAI_BASE = "https://api.groq.com/openai/v1"

#: Bounds on one turn, so the proxy cannot be used as an open-ended LLM relay.
MAX_ITEMS = 200
MAX_TOOLS = 80
MAX_CHARS = 400_000

#: Rate limits (HTTP 429): wait for the provider's window, within this total budget per turn.
RATE_LIMIT_BUDGET_SECONDS = 80.0
DEFAULT_RATE_LIMIT_WAIT = 10.0
MAX_RATE_LIMIT_WAIT = 30.0

#: When a request is too large for the tier, keep at least this much room for the answer.
MIN_ANSWER_TOKENS = 600
FIT_MARGIN_TOKENS = 64

TOOL_RESULT_MISSING = "No result was recorded for this tool call (it was cancelled or skipped)."


class StudioTurnRequest(SchemaBase):
    """One ``AgLlmRequest`` from Studio's adapter. Item shapes are Studio's; validated loosely here
    and strictly where they are read."""

    input: list[dict[str, Any]] = Field(default_factory=list, max_length=MAX_ITEMS)
    instructions: str | None = Field(default=None, max_length=120_000)
    tools: list[dict[str, Any]] = Field(default_factory=list, max_length=MAX_TOOLS)
    tool_choice: str | dict[str, Any] | None = None
    response_format: dict[str, Any] = Field(default_factory=lambda: {"type": "text"})
    model: dict[str, Any] | None = None


# --------------------------------------------------------------------------- #
# Provider configuration
# --------------------------------------------------------------------------- #
def _provider() -> dict[str, Any]:
    """Where turns go. Blank STUDIO_AI_* settings mean Groq with the app's Groq key and models."""
    custom = bool(settings.studio_ai_base_url)
    base = (settings.studio_ai_base_url or GROQ_OPENAI_BASE).rstrip("/")
    key = settings.studio_ai_api_key or ("" if custom else settings.groq_api_key)
    model = settings.studio_ai_model or ("" if custom else settings.groq_model)
    fallback = settings.studio_ai_fallback_model or ("" if custom else settings.groq_fallback_model)
    host = urlparse(base).hostname or "provider"
    name = "groq" if host.endswith("groq.com") else host
    return {"base": base, "key": key, "model": model, "fallback": fallback, "name": name}


def availability() -> dict[str, Any]:
    p = _provider()
    available = settings.studio_ai_enabled and bool(p["key"]) and bool(p["model"])
    return {
        "available": available,
        "provider": p["name"] if available else None,
        "model": p["model"] if available else None,
        "note": (
            "Studio's AI agents build and edit charts in your browser, over datasets PayPilot already "
            "computed. They cannot read the database, call PayPal or change any record."
            if available else
            "Set GROQ_API_KEY (or STUDIO_AI_*) to enable Studio's AI assistant. The drag-and-drop editor "
            "works without it."
        ),
    }


# --------------------------------------------------------------------------- #
# Studio items -> chat completions
# --------------------------------------------------------------------------- #
def _text_of(content: Any) -> str:
    """Text parts of an input/output message, joined. Images and files are not forwarded."""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for part in content or []:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text" and isinstance(part.get("text"), str):
            parts.append(part["text"])
        elif part.get("type") == "refusal" and isinstance(part.get("refusal"), str):
            parts.append(part["refusal"])
    return "\n".join(parts)


def to_chat_messages(instructions: str | None, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rebuild a chat-completions conversation from Studio's item list.

    Consecutive ``function_call`` items become one assistant message with ``tool_calls`` (attached
    to the assistant text that preceded them, if any), each followed by its ``tool`` reply. Every
    tool call is guaranteed a reply - providers reject a conversation that leaves one open.
    Reasoning items are dropped: the model re-reasons each turn.
    """
    messages: list[dict[str, Any]] = []
    if instructions:
        messages.append({"role": "system", "content": instructions})

    outputs: dict[str, str] = {}
    for item in items:
        if item.get("type") == "function_call_output" and item.get("callId"):
            outputs[str(item["callId"])] = str(item.get("output") or "")

    answered: set[str] = set()
    for item in items:
        kind = item.get("type")
        if kind == "message":
            role = item.get("role")
            text = _text_of(item.get("content"))
            if role in ("user", "system"):
                messages.append({"role": role, "content": text})
            elif role == "assistant":
                messages.append({"role": "assistant", "content": text})
        elif kind == "function_call":
            call_id = str(item.get("callId") or item.get("id") or uuid.uuid4().hex)
            call = {
                "id": call_id,
                "type": "function",
                "function": {"name": str(item.get("name") or ""), "arguments": str(item.get("arguments") or "{}")},
            }
            last = messages[-1] if messages else None
            if last is not None and last["role"] == "assistant" and "tool_calls" in last:
                last["tool_calls"].append(call)
            elif last is not None and last["role"] == "assistant":
                last["tool_calls"] = [call]
                last["content"] = last.get("content") or None
            else:
                messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
            if call_id not in outputs and item.get("result") is not None:
                outputs[call_id] = str(item["result"])
        elif kind == "function_call_output":
            call_id = str(item.get("callId") or "")
            if call_id and call_id not in answered:
                messages.append({"role": "tool", "tool_call_id": call_id, "content": outputs.get(call_id, "")})
                answered.add(call_id)
        # reasoning items and unknown kinds are not forwarded

    return _close_open_calls(messages, outputs)


def _close_open_calls(messages: list[dict[str, Any]], outputs: dict[str, str]) -> list[dict[str, Any]]:
    """Make sure every assistant tool call is followed by a tool reply before the next turn."""
    fixed: list[dict[str, Any]] = []
    pending: list[str] = []

    def flush() -> None:
        for call_id in pending:
            fixed.append({"role": "tool", "tool_call_id": call_id, "content": outputs.get(call_id) or TOOL_RESULT_MISSING})
        pending.clear()

    for message in messages:
        if message["role"] == "tool":
            if message["tool_call_id"] in pending:
                pending.remove(message["tool_call_id"])
                fixed.append(message)
            # a reply to a call we never saw would be rejected by the provider - drop it
            continue
        flush()
        fixed.append(message)
        if message["role"] == "assistant" and message.get("tool_calls"):
            pending.extend(call["id"] for call in message["tool_calls"])
    flush()
    return fixed


def to_chat_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Function tools in chat-completions form. Provider-hosted tools are not supported here."""
    out = []
    for tool in tools:
        if tool.get("kind") == "provided" or not tool.get("name"):
            continue
        out.append({
            "type": "function",
            "function": {
                "name": str(tool["name"]),
                "description": str(tool.get("description") or "")[:4000],
                "parameters": tool.get("parameters") or {"type": "object", "properties": {}},
            },
        })
    return out


def to_tool_choice(choice: str | dict[str, Any] | None) -> str | dict[str, Any] | None:
    if choice in (None, "auto", "none", "required"):
        return choice
    if isinstance(choice, dict) and choice.get("name"):
        return {"type": "function", "function": {"name": str(choice["name"])}}
    return None


def _json_instruction(fmt: dict[str, Any]) -> str:
    schema = json.dumps(fmt.get("schema") or {}, separators=(",", ":"))[:20_000]
    return (
        f"\n\nRespond with a single JSON object for `{fmt.get('name', 'output')}` and nothing else. "
        f"It must conform to this JSON schema: {schema}"
    )


# --------------------------------------------------------------------------- #
# chat completions -> Studio items
# --------------------------------------------------------------------------- #
def to_output_items(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Studio output items (reasoning, message, function calls) from one chat-completions message."""
    items: list[dict[str, Any]] = []
    reasoning = message.get("reasoning") or message.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning.strip():
        items.append({
            "id": f"rs_{uuid.uuid4().hex[:16]}", "kind": "output", "type": "reasoning",
            "summary": [], "content": [{"type": "text", "text": reasoning}],
        })
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        items.append({
            "id": f"msg_{uuid.uuid4().hex[:16]}", "kind": "output", "type": "message", "role": "assistant",
            "status": "completed", "content": [{"type": "text", "text": content, "annotations": []}],
        })
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        items.append({
            "id": f"fc_{uuid.uuid4().hex[:16]}", "kind": "output", "type": "function_call",
            "callId": str(call.get("id") or uuid.uuid4().hex),
            "name": str(function.get("name") or ""),
            "arguments": str(function.get("arguments") or "{}"),
            "status": "completed",
        })
    return items


def retry_after_seconds(response: httpx.Response) -> float | None:
    """Seconds to wait before retrying a rate-limited (429) call, or None if it was not one."""
    if response.status_code != 429:
        return None
    header = response.headers.get("retry-after")
    try:
        wait = float(header) if header is not None else DEFAULT_RATE_LIMIT_WAIT
    except ValueError:
        wait = DEFAULT_RATE_LIMIT_WAIT
    return min(max(wait, 1.0), MAX_RATE_LIMIT_WAIT)


def _provider_error(response: httpx.Response) -> str:
    try:
        body = response.json()
        message = (body.get("error") or {}).get("message") or str(body)[:400]
    except ValueError:
        message = response.text[:400]
    return f"HTTP {response.status_code}: {message[:400]}"


_TOO_LARGE = re.compile(r"Limit\s+(\d+),\s*Requested\s+(\d+)", re.IGNORECASE)


def fit_max_tokens(error: str, current: int | None) -> int | None:
    """A smaller answer budget that fits a "request too large" (413) limit, or None if it cannot.

    Groq reports ``Limit L, Requested R`` where R = prompt tokens + max_tokens. Keeping the prompt
    and shrinking max_tokens to ``L - prompt`` (minus a margin) often fits: Studio's tool schemas are
    large, but an agent's answer - a tool call or a sentence - is short.
    """
    match = _TOO_LARGE.search(error or "")
    if not match or not current:
        return None
    limit, requested = int(match.group(1)), int(match.group(2))
    prompt = requested - current
    fitted = limit - prompt - FIT_MARGIN_TOKENS
    if fitted < MIN_ANSWER_TOKENS or fitted >= current:
        return None
    return fitted


# --------------------------------------------------------------------------- #
# The turn
# --------------------------------------------------------------------------- #
def build_payload(request: StudioTurnRequest, model: str) -> dict[str, Any]:
    fmt = request.response_format or {"type": "text"}
    instructions = request.instructions or ""
    tools = to_chat_tools(request.tools)
    payload: dict[str, Any] = {
        "model": model,
        "temperature": settings.groq_temperature,
        "max_tokens": settings.studio_ai_max_tokens,
    }
    if fmt.get("type") == "json":
        instructions += _json_instruction(fmt)
        if not tools:
            payload["response_format"] = {"type": "json_object"}
    payload["messages"] = to_chat_messages(instructions, request.input)
    if tools:
        payload["tools"] = tools
        choice = to_tool_choice(request.tool_choice)
        if choice is not None:
            payload["tool_choice"] = choice
    if settings.studio_ai_reasoning_effort and "gpt-oss" in model:
        payload["reasoning_effort"] = settings.studio_ai_reasoning_effort
    return payload


async def run_turn(request: StudioTurnRequest, *, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Run one Studio turn and return an ``AgLlmResponse``."""
    if not availability()["available"]:
        raise ServiceUnavailableError("Studio's AI assistant is not configured (GROQ_API_KEY or STUDIO_AI_*).")
    size = len(json.dumps(request.input, default=str)) + len(request.instructions or "")
    if size > MAX_CHARS:
        raise ServiceUnavailableError("This conversation is too long for the assistant - start a new one.")

    provider = _provider()
    models = [provider["model"]] + ([provider["fallback"]] if provider["fallback"] and provider["fallback"] != provider["model"] else [])
    headers = {"Authorization": f"Bearer {provider['key']}", "Content-Type": "application/json"}
    url = f"{provider['base']}/chat/completions"

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=settings.studio_ai_timeout_seconds)
    started = time.perf_counter()
    last_error = ""
    rate_limited = too_large = False
    data: dict[str, Any] | None = None
    used_model = ""
    try:
        for model in models:
            payload = build_payload(request, model)
            for _attempt in range(6):
                try:
                    response = await http.post(url, headers=headers, json=payload)
                except httpx.HTTPError as exc:
                    last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
                    log.warning("studio_ai_turn_failed", model=model, provider=provider["name"], detail=last_error)
                    break
                if response.status_code < 400:
                    data, used_model = response.json(), model
                    break
                last_error = _provider_error(response)
                if response.status_code == 413:
                    # The tier's per-minute budget counts the prompt *plus* the reserved
                    # answer space. Shrink the reservation to fit and retry once per size.
                    fitted = fit_max_tokens(last_error, payload.get("max_tokens"))
                    if fitted is not None:
                        log.info("studio_ai_fit_to_budget", model=model, max_tokens=fitted)
                        payload["max_tokens"] = fitted
                        continue
                    too_large = True
                    log.warning("studio_ai_turn_failed", model=model, provider=provider["name"], detail=last_error)
                    break
                wait = retry_after_seconds(response)
                rate_limited = rate_limited or wait is not None
                if wait is not None and time.perf_counter() - started + wait < RATE_LIMIT_BUDGET_SECONDS:
                    # Groq's free tier allows ~8k tokens/minute per model and a Studio turn carries
                    # ~4-9k of tool schemas: wait for the window instead of failing the turn.
                    log.info("studio_ai_rate_limited", model=model, provider=provider["name"], wait_s=round(wait, 1))
                    await asyncio.sleep(wait)
                    continue
                log.warning("studio_ai_turn_failed", model=model, provider=provider["name"], detail=last_error)
                break
            if data is not None:
                break
    finally:
        if owns_client:
            await http.aclose()

    if data is None:
        if too_large:
            raise RateLimitError(
                "This step is larger than the AI model's per-minute token limit (Groq's free tier allows "
                "about 8,000). Use a paid Groq tier or set STUDIO_AI_* to another provider.",
            )
        if rate_limited:
            raise RateLimitError(
                "The AI model's rate limit was reached (tokens per minute). Wait a minute and ask again - "
                "a paid Groq tier removes this limit.",
            )
        raise IntegrationError("Studio's AI assistant could not get an answer from the model.", details={"error": last_error})

    choice = (data.get("choices") or [{}])[0]
    usage = data.get("usage") or {}
    output = to_output_items(choice.get("message") or {})
    finish = choice.get("finish_reason")
    log.info(
        "studio_ai_turn", model=used_model, provider=provider["name"], items=len(request.input),
        tools=len(request.tools), tool_calls=sum(1 for i in output if i["type"] == "function_call"),
        duration_ms=round((time.perf_counter() - started) * 1000, 1), total_tokens=usage.get("total_tokens", 0),
    )
    status: Literal["completed", "incomplete"] = "incomplete" if finish == "length" else "completed"
    result: dict[str, Any] = {
        "id": str(data.get("id") or f"resp_{uuid.uuid4().hex}"),
        "createdAt": int(time.time() * 1000),
        "status": status,
        "output": output,
        "model": used_model,
        "usage": {
            "inputTokens": usage.get("prompt_tokens", 0) or 0,
            "outputTokens": usage.get("completion_tokens", 0) or 0,
            "totalTokens": usage.get("total_tokens", 0) or 0,
        },
    }
    if status == "incomplete":
        result["incompleteDetails"] = {"reason": "max_output_tokens"}
    return result
