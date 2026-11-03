"""Centralised LLM service (Groq).

Every model call in the application goes through ``llm_service``. Nothing else
imports the Groq SDK, the model name only ever comes from configuration, and the
public entrypoint returns *validated Pydantic models* - never raw prose.

Failure policy (spec section 35):
  timeout -> retry (bounded) -> fallback model -> deterministic fallback value.
A malformed or missing LLM response can never raise into an API handler.
"""

from __future__ import annotations

import contextlib
import json
import re
import time
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.langfuse import AgentTrace

log = get_logger(__name__)

TModel = TypeVar("TModel", bound=BaseModel)

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)


class LLMResult(BaseModel):
    """Outcome of one structured LLM call."""

    model_config = {"arbitrary_types_allowed": True}

    content: str = ""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    duration_ms: float = 0.0
    used_fallback: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.content)


def extract_json(text: str) -> Any:
    """Pull a JSON value out of a model response.

    Handles bare JSON, fenced code blocks and prose-wrapped JSON. Returns None
    when nothing parseable is present - callers then use their fallback.
    """
    if not text:
        return None
    candidate = text.strip()
    try:
        return json.loads(candidate)
    except (ValueError, TypeError):
        pass

    match = _JSON_BLOCK.search(candidate)
    if match:
        try:
            return json.loads(match.group(1))
        except (ValueError, TypeError):
            pass

    # Last resort: the outermost {...} or [...] span.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = candidate.find(opener)
        end = candidate.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(candidate[start : end + 1])
            except (ValueError, TypeError):
                continue
    return None


class LLMService:
    """Async Groq client with retries, timeouts and schema-validated outputs."""

    def __init__(self) -> None:
        self._client: Any = None
        self._initialised = False

    # ------------------------------------------------------------------ setup
    @property
    def enabled(self) -> bool:
        return settings.llm_enabled

    @property
    def model(self) -> str:
        return settings.groq_model

    def _ensure_client(self) -> Any:
        if self._initialised:
            return self._client
        self._initialised = True
        if not settings.groq_api_key:
            log.info("llm_disabled", reason="missing_groq_api_key", model=settings.groq_model)
            return None
        try:
            from groq import AsyncGroq

            self._client = AsyncGroq(
                api_key=settings.groq_api_key,
                timeout=settings.groq_timeout_seconds,
                max_retries=0,  # retries are handled here so they can be traced
            )
            log.info("llm_enabled", model=settings.groq_model)
        except Exception as exc:
            self._client = None
            log.warning("llm_init_failed", detail=str(exc)[:200])
        return self._client

    # ------------------------------------------------------------------ raw call
    async def complete(
        self,
        *,
        system: str,
        user: str,
        json_mode: bool = True,
        temperature: float | None = None,
        max_tokens: int | None = None,
        trace: AgentTrace | None = None,
        trace_name: str = "llm_generation",
    ) -> LLMResult:
        """One chat completion with bounded retries and a fallback model."""
        client = self._ensure_client()
        if client is None:
            return LLMResult(error="llm_disabled", used_fallback=True)

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        models = [settings.groq_model]
        if settings.groq_fallback_model and settings.groq_fallback_model != settings.groq_model:
            models.append(settings.groq_fallback_model)

        last_error: str | None = None
        started = time.perf_counter()

        for model_index, model_name in enumerate(models):
            for attempt in range(settings.groq_max_retries + 1):
                try:
                    kwargs: dict[str, Any] = {
                        "model": model_name,
                        "messages": messages,
                        "temperature": (
                            settings.groq_temperature if temperature is None else temperature
                        ),
                        "max_tokens": max_tokens or settings.groq_max_tokens,
                    }
                    if json_mode:
                        kwargs["response_format"] = {"type": "json_object"}

                    response = await client.chat.completions.create(**kwargs)
                    content = (response.choices[0].message.content or "").strip()
                    usage = getattr(response, "usage", None)
                    duration_ms = round((time.perf_counter() - started) * 1000, 2)

                    result = LLMResult(
                        content=content,
                        model=model_name,
                        prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                        completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                        total_tokens=getattr(usage, "total_tokens", 0) or 0,
                        duration_ms=duration_ms,
                        used_fallback=model_index > 0,
                    )
                    log.info(
                        "llm_generation",
                        model=model_name,
                        duration_ms=duration_ms,
                        total_tokens=result.total_tokens,
                        attempt=attempt + 1,
                        fallback_model=model_index > 0,
                    )
                    if trace is not None:
                        trace.generation(
                            name=trace_name,
                            model=model_name,
                            input={"system": system[:2000], "user": user[:4000]},
                            output=content[:4000],
                            usage={
                                "input": result.prompt_tokens,
                                "output": result.completion_tokens,
                                "total": result.total_tokens,
                            },
                            metadata={"attempt": attempt + 1, "json_mode": json_mode},
                        )
                    return result

                except Exception as exc:
                    last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
                    log.warning(
                        "llm_call_failed",
                        model=model_name,
                        attempt=attempt + 1,
                        detail=last_error,
                    )
                    # Auth/permission errors will not improve with a retry.
                    if any(
                        tok in last_error.lower() for tok in ("authentication", "api key", "401")
                    ):
                        break

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        if trace is not None:
            trace.generation(
                name=trace_name,
                model=settings.groq_model,
                input={"system": system[:500], "user": user[:1000]},
                output=None,
                level="ERROR",
                status_message=last_error or "llm_failed",
            )
        log.error("llm_exhausted", detail=last_error, duration_ms=duration_ms)
        return LLMResult(
            error=last_error or "llm_failed", duration_ms=duration_ms, used_fallback=True
        )

    # ------------------------------------------------------------------ structured
    async def structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[TModel],
        fallback: TModel,
        temperature: float | None = None,
        max_tokens: int | None = None,
        trace: AgentTrace | None = None,
        trace_name: str = "llm_generation",
    ) -> tuple[TModel, LLMResult]:
        """Return a *validated* instance of ``schema``.

        On any failure - disabled LLM, timeout, malformed JSON, schema mismatch -
        ``fallback`` is returned unchanged. The caller can inspect
        ``LLMResult.used_fallback`` to label the answer honestly in the UI.
        """
        instruction = (
            f"{system}\n\n"
            "Respond with a single valid JSON object and nothing else. "
            f"It must conform to this JSON schema:\n{json.dumps(schema.model_json_schema())}"
        )
        result = await self.complete(
            system=instruction,
            user=user,
            json_mode=True,
            temperature=temperature,
            max_tokens=max_tokens,
            trace=trace,
            trace_name=trace_name,
        )
        if not result.ok:
            return fallback, result

        payload = extract_json(result.content)
        if payload is None:
            log.warning("llm_unparseable_response", model=result.model)
            result.error = "llm_unparseable_response"
            result.used_fallback = True
            return fallback, result

        try:
            return schema.model_validate(payload), result
        except ValidationError as exc:
            log.warning(
                "llm_schema_mismatch",
                model=result.model,
                schema=schema.__name__,
                errors=len(exc.errors()),
                first_error=str(exc.errors()[0].get("msg", ""))[:120] if exc.errors() else None,
            )
            result.error = "llm_schema_mismatch"
            result.used_fallback = True
            return fallback, result

    async def close(self) -> None:
        client = self._client
        if client is not None and hasattr(client, "close"):
            with contextlib.suppress(Exception):
                await client.close()


llm_service = LLMService()
