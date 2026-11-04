"""Vapi voice endpoints.

Voice is a *surface*, not a second brain. The assistant's tools map onto the same
backend agents and the same tool registry the web UI uses, so there is exactly one
implementation of the business logic.

The wire contract follows Vapi's server-message spec
(https://docs.vapi.ai/server-url/events): Vapi POSTs ``{"message": {"type": ...}}``
to a single Server URL, and expects a type-specific reply.
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response, status
from fastapi.responses import JSONResponse

from app.agents.orchestrator import GrowthOrchestrator
from app.api.deps import DbSession, Principal, require_permission
from app.core.config import settings
from app.core.exceptions import AuthenticationError, BadRequestError
from app.core.logging import get_logger
from app.core.permissions import Permission
from app.core.security import create_access_token, decode_token
from app.db.models.agent import AgentWorkflow
from app.integrations.vapi import (
    VOICE_TOOLS,
    call_variable_values,
    parse_tool_calls,
    resolve_page,
    tool_result,
    tool_results,
    vapi_client,
)
from app.repositories.merchant import MembershipRepository
from app.repositories.user import UserRepository
from app.schemas.agent import VoiceSessionConfig, VoiceToolRequest, VoiceToolResponse
from app.schemas.common import APIResponse
from app.services.analytics.service import AnalyticsService
from app.tools import registry
from app.tools.base import ToolContext

log = get_logger(__name__)
router = APIRouter(prefix="/voice", tags=["voice"])

#: Short-lived token the browser hands to Vapi, and Vapi hands back on each tool call.
VOICE_TOKEN_MINUTES = 30

#: Voice tool names that map onto a differently-named registry tool.
VOICE_TOOL_ALIASES = {"get_business_snapshot": "get_sales_summary"}

#: Server messages this endpoint acts on. Everything else is acknowledged and logged.
HANDLED_MESSAGES = {
    "tool-calls",
    "assistant-request",
    "status-update",
    "end-of-call-report",
    "transcript",
    "hang",
    "speech-update",
    "conversation-update",
    "user-interrupted",
}


@router.get(
    "/session",
    summary="Start a voice session",
    description=(
        "Returns the public key, assistant id and per-session overrides the browser "
        "SDK needs. Includes a short-lived session token that the assistant presents "
        "when calling back into the API, so voice tool calls are authenticated and "
        "merchant-scoped like any other request."
    ),
)
async def voice_session(
    session: DbSession,
    principal: Principal = Depends(require_permission(Permission.AGENTS_RUN)),
) -> APIResponse[VoiceSessionConfig]:
    if not settings.vapi_public_key or not settings.vapi_assistant_id:
        return APIResponse(
            data=VoiceSessionConfig(
                enabled=False,
                disabled_reason=(
                    "Voice is not configured. Set VAPI_PUBLIC_KEY and VAPI_ASSISTANT_ID "
                    "to enable it. Everything else in the product works without it."
                ),
            )
        )

    analytics = AnalyticsService(session, principal.merchant_id)
    period = await analytics.resolve_period(days=30)
    kpis, current, _ = await analytics.kpis(period)
    revenue = next((k for k in kpis if k.key == "revenue"), None)
    snapshot = (
        f"Revenue ${current.revenue:,.0f} ({revenue.change_pct:+.1f}%), "
        f"{current.orders:,} orders, repeat rate {current.repeat_rate:.1f}%."
        if revenue and revenue.change_pct is not None
        else ""
    )

    token, _ = create_access_token(
        principal.user_id,
        merchant_id=principal.merchant_id,
        roles=[principal.membership.role],
        expires_minutes=VOICE_TOKEN_MINUTES,
        extra_claims={"scope": "voice"},
    )
    return APIResponse(
        data=VoiceSessionConfig(
            enabled=True,
            public_key=settings.vapi_public_key,
            assistant_id=settings.vapi_assistant_id,
            assistant_overrides=vapi_client.assistant_overrides(
                merchant_name=principal.merchant.name,
                merchant_id=str(principal.merchant_id),
                snapshot_line=snapshot,
                session_token=token,
            ),
            session_token=token,
            greeting=(
                f"Hi! I am your Growth Scientist for {principal.merchant.name}. "
                "Ask me why your numbers moved, or what to do about it."
            ),
        ),
        meta={"tools": [t["function"]["name"] for t in VOICE_TOOLS]},
    )


@router.get(
    "/assistant-config",
    summary="Vapi assistant configuration",
    description=(
        "The tool definitions and system prompt to paste into your Vapi assistant, "
        "plus the Server URL it should call back on."
    ),
)
async def assistant_config(
    principal: Principal = Depends(require_permission(Permission.SETTINGS_MANAGE)),
) -> APIResponse[dict]:
    from app.integrations.vapi import SYSTEM_PROMPT

    return APIResponse(
        data={
            "system_prompt": SYSTEM_PROMPT,
            "tools": VOICE_TOOLS,
            "server_url": f"{settings.backend_url}/api/v1/voice/server",
            "server_messages": sorted(HANDLED_MESSAGES),
            "notes": (
                "Set this as the assistant's Server URL. Authenticate it with a Bearer "
                "Token credential whose value is VAPI_WEBHOOK_SECRET, or with the legacy "
                "X-Vapi-Secret header. The browser passes a short-lived session token in "
                "assistantOverrides.variableValues, which scopes every tool call to the "
                "signed-in merchant. Prefer POST /voice/sync over pasting this by hand - "
                "it pushes the same tools and prompt straight onto the assistant."
            ),
        }
    )


@router.post(
    "/sync",
    summary="Push this backend's tools and prompt onto the live Vapi assistant",
    description=(
        "The assistant's tools and system prompt live on Vapi's platform, not in this "
        "backend - adding a tool here (e.g. navigate_page) does nothing to the assistant "
        "Vapi actually runs until it is pushed there. This does that: it fetches the "
        "configured assistant, replaces its system message and tool list with this "
        "backend's VOICE_TOOLS and SYSTEM_PROMPT, and leaves its provider, model and "
        "voice untouched. Runs automatically at startup; call it again after editing a "
        "voice tool without restarting the server."
    ),
)
async def sync_assistant(
    principal: Principal = Depends(require_permission(Permission.SETTINGS_MANAGE)),
) -> APIResponse[dict]:
    if not vapi_client.enabled:
        raise BadRequestError(
            "Voice is not configured. Set VAPI_PRIVATE_KEY and VAPI_ASSISTANT_ID first."
        )
    synced = await vapi_client.sync_assistant()
    if not synced:
        raise BadRequestError(
            "Could not sync the assistant. Check the server log for the Vapi API error, "
            "and that VAPI_PRIVATE_KEY has permission to update this assistant."
        )
    return APIResponse(
        data={
            "synced": True,
            "tools": [t["function"]["name"] for t in VOICE_TOOLS],
        }
    )


def _navigate_result(page_key: str, permissions: frozenset[str]) -> str:
    """Resolve a ``navigate_page`` call to the sentence the assistant should say.

    Navigation itself happens client-side (the browser is watching for this same
    tool call in the Vapi message stream and pushes the route the instant it sees
    it); this only supplies the confirmation - and the permission check, since a
    page the merchant's role cannot see must never be offered as reachable.
    """
    page = resolve_page(page_key)
    if page is None:
        return f"I don't have a page called '{page_key}'."
    if page["permission"] and page["permission"] not in permissions:
        return f"Your role doesn't have access to {page['label']}."
    return f"Opening {page['label']} — {page['description']}."


async def _principal_from_voice_token(session: DbSession, token: str) -> tuple:
    payload = decode_token(token)
    if (payload.raw or {}).get("scope") != "voice":
        raise AuthenticationError("This token cannot be used for voice tool calls.")
    user = await UserRepository(session).get_with_memberships(uuid.UUID(payload.subject))
    if user is None or not user.is_active:
        raise AuthenticationError("Account not available.")
    merchant_id = uuid.UUID(payload.merchant_id) if payload.merchant_id else None
    membership = (
        await MembershipRepository(session).get_for_user_and_merchant(user.id, merchant_id)
        if merchant_id
        else await MembershipRepository(session).default_for_user(user.id)
    )
    if membership is None:
        raise AuthenticationError("No merchant access for this session.")
    return user, membership


async def _principal_from_message(session: DbSession, message: dict) -> tuple:
    """Resolve the merchant for a call from its per-session variable values."""
    token = str(call_variable_values(message).get("sessionToken") or "")
    if not token:
        raise AuthenticationError(
            "This call carries no session token. Start voice from the dashboard."
        )
    return await _principal_from_voice_token(session, token)


# --------------------------------------------------------------------------- #
# Vapi Server URL
# --------------------------------------------------------------------------- #
@router.post(
    "/server",
    summary="Vapi server URL",
    description=(
        "The assistant's single Server URL. Implements Vapi's server-message contract: "
        "`tool-calls` returns `{results:[{toolCallId, name, result}]}`, `assistant-request` "
        "returns an assistant, and lifecycle events are acknowledged. Authenticated with "
        "VAPI_WEBHOOK_SECRET via a Bearer token, the legacy X-Vapi-Secret header, or an "
        "HMAC signature."
    ),
    include_in_schema=False,
)
async def vapi_server(request: Request, session: DbSession) -> Response:
    body = await request.body()
    if not vapi_client.verify_request(headers=dict(request.headers), body=body):
        raise AuthenticationError("Invalid Vapi server-URL credentials.")

    try:
        envelope = json.loads(body or b"{}")
    except json.JSONDecodeError as exc:
        raise BadRequestError("Malformed Vapi payload.") from exc

    message = envelope.get("message")
    if not isinstance(message, dict):
        raise BadRequestError("Vapi payload is missing 'message'.")

    kind = str(message.get("type") or "")
    log.info("vapi_server_message", type=kind, bytes=len(body))

    if kind == "tool-calls":
        return JSONResponse(await _handle_tool_calls(session, message))

    if kind == "assistant-request":
        # The browser already opens the session with an assistant id; returning the
        # configured one keeps phone-originated calls working too.
        if settings.vapi_assistant_id:
            return JSONResponse({"assistantId": settings.vapi_assistant_id})
        return JSONResponse({"error": "No assistant is configured for this deployment."})

    if kind == "end-of-call-report":
        log.info(
            "vapi_end_of_call",
            ended_reason=message.get("endedReason"),
            seconds=message.get("durationSeconds"),
        )

    # status-update, transcript, hang, speech-update, ... - acknowledge only.
    return JSONResponse({"received": True})


async def _handle_tool_calls(session: DbSession, message: dict) -> dict:
    """Execute each requested tool and answer in Vapi's documented shape."""
    calls = parse_tool_calls(message)
    if not calls:
        return tool_results([])

    user, membership = await _principal_from_message(session, message)

    from app.core.permissions import permissions_for_role

    permissions = frozenset(str(p) for p in permissions_for_role(membership.role))
    allowed = {t["function"]["name"] for t in VOICE_TOOLS}

    orchestrator = GrowthOrchestrator(
        session,
        merchant_id=membership.merchant_id,
        merchant_name=membership.merchant.name,
        user_id=user.id,
        permissions=permissions,
        actor_label=f"{user.full_name} (voice)",
    )
    ctx = ToolContext(
        session=session,
        merchant_id=membership.merchant_id,
        merchant_name=membership.merchant.name,
        user_id=user.id,
        permissions=permissions,
        agent_name="voice_agent",
    )

    results: list[dict] = []
    for call in calls:
        name = call["name"]
        if name not in allowed:
            results.append(
                tool_result(call["id"], name, f"The tool '{name}' is not available over voice.")
            )
            continue

        try:
            # The heavyweight question routes into the same LangGraph workflow as the web UI.
            if name == "investigate_growth":
                question = str(call["arguments"].get("question") or "Why did my sales change?")
                _, state = await orchestrator.run(
                    question=question, workflow=AgentWorkflow.VOICE, channel="voice"
                )
                results.append(tool_result(call["id"], name, state.get("answer", "")[:1200]))
                continue

            if name == "navigate_page":
                page_key = str(call["arguments"].get("page") or "")
                results.append(tool_result(call["id"], name, _navigate_result(page_key, permissions)))
                continue

            registry_name = VOICE_TOOL_ALIASES.get(name, name)
            outcome = await registry.execute(registry_name, ctx, call["arguments"])
            results.append(
                tool_result(
                    call["id"],
                    name,
                    outcome.summary
                    if outcome.ok
                    else "I could not fetch that just now. Please try again.",
                )
            )
            log.info("voice_tool_call", tool=registry_name, ok=outcome.ok, call_id=call["id"])
        except Exception as exc:  # one bad tool must not fail the whole turn
            log.warning("voice_tool_failed", tool=name, detail=str(exc)[:200])
            results.append(
                tool_result(call["id"], name, "That lookup failed. Please try again in a moment.")
            )

    return tool_results(results)


@router.post(
    "/webhook",
    status_code=status.HTTP_200_OK,
    summary="Vapi server URL (alias)",
    description="Kept so an assistant already pointed at /voice/webhook keeps working.",
    include_in_schema=False,
)
async def voice_webhook(request: Request, session: DbSession) -> Response:
    return await vapi_server(request, session)


# --------------------------------------------------------------------------- #
# Direct tool endpoint
#
# Not part of the Vapi contract - a plain JSON entry point kept for manual
# testing and for any caller that wants one tool without the server envelope.
# --------------------------------------------------------------------------- #
@router.post(
    "/tool",
    summary="Run one voice tool directly",
    description=(
        "Executes a single tool against the same registry the web agents use. "
        "Authenticated with the short-lived voice session token; never anonymous."
    ),
)
async def voice_tool(
    payload: VoiceToolRequest,
    request: Request,
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> APIResponse[VoiceToolResponse]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthenticationError("Voice tool calls require the session token.")
    user, membership = await _principal_from_voice_token(session, authorization.split(" ", 1)[1])

    from app.core.permissions import permissions_for_role

    permissions = frozenset(str(p) for p in permissions_for_role(membership.role))

    allowed = {t["function"]["name"] for t in VOICE_TOOLS}
    if payload.tool not in allowed:
        raise BadRequestError(f"Tool '{payload.tool}' is not available over voice.")

    orchestrator = GrowthOrchestrator(
        session,
        merchant_id=membership.merchant_id,
        merchant_name=membership.merchant.name,
        user_id=user.id,
        permissions=permissions,
        actor_label=f"{user.full_name} (voice)",
    )

    if payload.tool == "investigate_growth":
        question = str(payload.arguments.get("question") or "Why did my sales change?")
        run, state = await orchestrator.run(
            question=question, workflow=AgentWorkflow.VOICE, channel="voice"
        )
        return APIResponse(
            data=VoiceToolResponse(
                result=state.get("answer", "")[:1200],
                data={
                    "recommendation": (
                        state.get("recommendation").model_dump(mode="json")
                        if state.get("recommendation")
                        else {}
                    )
                },
                agent_run_id=run.id,
            )
        )

    if payload.tool == "navigate_page":
        page_key = str(payload.arguments.get("page") or "")
        return APIResponse(data=VoiceToolResponse(result=_navigate_result(page_key, permissions)))

    tool_name = VOICE_TOOL_ALIASES.get(payload.tool, payload.tool)
    ctx = ToolContext(
        session=session,
        merchant_id=membership.merchant_id,
        merchant_name=membership.merchant.name,
        user_id=user.id,
        permissions=permissions,
        agent_name="voice_agent",
    )
    result = await registry.execute(tool_name, ctx, payload.arguments)
    log.info("voice_tool_call", tool=tool_name, ok=result.ok, call_id=payload.call_id)
    if not result.ok:
        return APIResponse(
            data=VoiceToolResponse(
                result="I could not fetch that just now. Please try again.",
                data={"error": result.error or "tool_failed"},
            )
        )
    return APIResponse(data=VoiceToolResponse(result=result.summary, data=result.data))
