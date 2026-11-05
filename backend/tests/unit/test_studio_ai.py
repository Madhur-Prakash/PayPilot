"""AG Studio's AI assistant relay: item translation, provider calls, rate limits and the API."""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import settings
from app.core.exceptions import IntegrationError, RateLimitError, ServiceUnavailableError
from app.services.integrations import studio_ai
from app.services.integrations.studio_ai import (
    StudioTurnRequest,
    build_payload,
    run_turn,
    to_chat_messages,
    to_chat_tools,
    to_output_items,
    to_tool_choice,
)


def user(text: str) -> dict:
    return {"id": "u", "kind": "input", "type": "message", "role": "user", "status": "completed",
            "content": [{"type": "text", "text": text}]}


def call(call_id: str, name: str = "add_widget", args: str = "{}") -> dict:
    return {"id": f"fc-{call_id}", "kind": "output", "type": "function_call", "callId": call_id,
            "name": name, "arguments": args, "status": "completed"}


def output(call_id: str, text: str = '{"ok":true}') -> dict:
    return {"type": "function_call_output", "callId": call_id, "output": text, "status": "completed"}


@pytest.fixture
def groq_on(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "gsk-test-secret")
    monkeypatch.setattr(settings, "studio_ai_enabled", True)
    monkeypatch.setattr(settings, "studio_ai_base_url", "")
    monkeypatch.setattr(settings, "studio_ai_api_key", "")
    monkeypatch.setattr(settings, "studio_ai_model", "")


class TestTranslation:
    def test_instructions_become_the_system_message(self):
        messages = to_chat_messages("Build dashboards.", [user("hi")])
        assert messages == [{"role": "system", "content": "Build dashboards."}, {"role": "user", "content": "hi"}]

    def test_tool_calls_are_grouped_and_each_gets_its_reply(self):
        items = [user("add two charts"), call("a"), call("b"), output("a", "A"), output("b", "B")]
        messages = to_chat_messages(None, items)
        assistant = messages[1]
        assert assistant["role"] == "assistant" and [c["id"] for c in assistant["tool_calls"]] == ["a", "b"]
        assert messages[2:] == [
            {"role": "tool", "tool_call_id": "a", "content": "A"},
            {"role": "tool", "tool_call_id": "b", "content": "B"},
        ]

    def test_a_call_without_a_result_is_closed_before_the_next_message(self):
        messages = to_chat_messages(None, [user("go"), call("x"), user("and now?")])
        assert messages[2] == {"role": "tool", "tool_call_id": "x", "content": studio_ai.TOOL_RESULT_MISSING}
        assert messages[3] == {"role": "user", "content": "and now?"}

    def test_a_reply_to_an_unknown_call_is_dropped(self):
        messages = to_chat_messages(None, [user("go"), output("ghost")])
        assert all(m["role"] != "tool" for m in messages)

    def test_reasoning_items_are_not_forwarded(self):
        items = [user("go"), {"id": "r", "kind": "output", "type": "reasoning", "summary": [], "content": [{"type": "text", "text": "secret thoughts"}]}]
        assert "secret thoughts" not in json.dumps(to_chat_messages(None, items))

    def test_assistant_text_then_tool_call_is_one_message(self):
        text = {"id": "m", "kind": "output", "type": "message", "role": "assistant", "status": "completed",
                "content": [{"type": "text", "text": "Adding it", "annotations": []}]}
        messages = to_chat_messages(None, [user("go"), text, call("c"), output("c")])
        assert messages[1]["content"] == "Adding it" and messages[1]["tool_calls"][0]["id"] == "c"

    def test_tools_and_tool_choice(self):
        tools = to_chat_tools([
            {"name": "add_widget", "description": "Add", "parameters": {"type": "object"}},
            {"name": "web_search", "kind": "provided", "provider": {"type": "web_search"}},
        ])
        assert [t["function"]["name"] for t in tools] == ["add_widget"]
        assert to_tool_choice("auto") == "auto"
        assert to_tool_choice({"name": "add_widget"}) == {"type": "function", "function": {"name": "add_widget"}}

    def test_output_items_from_a_chat_message(self):
        items = to_output_items({
            "reasoning": "think", "content": "Done.",
            "tool_calls": [{"id": "call_1", "function": {"name": "add_widget", "arguments": '{"a":1}'}}],
        })
        assert [i["type"] for i in items] == ["reasoning", "message", "function_call"]
        assert items[2]["callId"] == "call_1" and items[2]["arguments"] == '{"a":1}'

    def test_json_format_adds_an_instruction_and_json_mode(self, groq_on):
        payload = build_payload(StudioTurnRequest(
            input=[user("title?")],
            response_format={"type": "json", "name": "title", "schema": {"type": "object"}},
        ), "openai/gpt-oss-120b")
        assert payload["response_format"] == {"type": "json_object"}
        assert "JSON schema" in payload["messages"][0]["content"]
        assert payload["reasoning_effort"] == settings.studio_ai_reasoning_effort

    def test_reasoning_effort_only_for_gpt_oss(self, groq_on):
        payload = build_payload(StudioTurnRequest(input=[user("hi")]), "gpt-4.1-mini")
        assert "reasoning_effort" not in payload


class TestRunTurn:
    async def test_returns_a_studio_response_and_sends_the_key_only_to_the_provider(self, groq_on):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["auth"] = request.headers["authorization"]
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={
                "id": "chatcmpl-1",
                "choices": [{"finish_reason": "tool_calls", "message": {
                    "content": None, "tool_calls": [{"id": "call_9", "function": {"name": "add_widget", "arguments": "{}"}}],
                }}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
            })

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await run_turn(StudioTurnRequest(input=[user("add")], tools=[{"name": "add_widget", "description": "", "parameters": {}}]), client=client)

        assert seen["url"] == "https://api.groq.com/openai/v1/chat/completions"
        assert seen["auth"] == "Bearer gsk-test-secret"
        assert seen["body"]["model"] == settings.groq_model
        assert result["status"] == "completed"
        assert result["output"][0]["type"] == "function_call" and result["output"][0]["callId"] == "call_9"
        assert result["usage"] == {"inputTokens": 100, "outputTokens": 20, "totalTokens": 120}
        assert "gsk-test-secret" not in json.dumps(result)

    async def test_a_custom_provider_is_used_when_configured(self, groq_on, monkeypatch):
        monkeypatch.setattr(settings, "studio_ai_base_url", "https://llm.example.com/v1")
        monkeypatch.setattr(settings, "studio_ai_api_key", "custom-key")
        monkeypatch.setattr(settings, "studio_ai_model", "my-model")
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"], seen["auth"] = str(request.url), request.headers["authorization"]
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await run_turn(StudioTurnRequest(input=[user("hi")]), client=client)
        assert seen == {"url": "https://llm.example.com/v1/chat/completions", "auth": "Bearer custom-key"}
        assert result["model"] == "my-model"
        assert studio_ai.availability()["provider"] == "llm.example.com"

    async def test_a_rate_limit_is_waited_out(self, groq_on, monkeypatch):
        waits: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            waits.append(seconds)

        monkeypatch.setattr(studio_ai.asyncio, "sleep", fake_sleep)
        responses = iter([
            httpx.Response(429, headers={"retry-after": "7"}, json={"error": {"message": "TPM"}}),
            httpx.Response(200, json={"choices": [{"message": {"content": "done"}}]}),
        ])
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: next(responses))) as client:
            result = await run_turn(StudioTurnRequest(input=[user("hi")]), client=client)
        assert waits == [7.0]
        assert result["output"][0]["type"] == "message"

    async def test_a_too_large_request_is_refitted_to_the_budget(self, groq_on):
        sent: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(json.loads(request.content)["max_tokens"])
            if len(sent) == 1:
                return httpx.Response(413, json={"error": {"message": (
                    "Request too large for model `openai/gpt-oss-120b` on tokens per minute (TPM): "
                    f"Limit 8000, Requested {5000 + sent[0]}, please reduce your message size and try again."
                )}})
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await run_turn(StudioTurnRequest(input=[user("hi")]), client=client)
        assert sent == [settings.studio_ai_max_tokens, 8000 - 5000 - studio_ai.FIT_MARGIN_TOKENS]
        assert result["status"] == "completed"

    def test_fitting_gives_up_when_the_prompt_alone_is_too_big(self):
        assert studio_ai.fit_max_tokens("Limit 8000, Requested 12000", 4096) is None
        assert studio_ai.fit_max_tokens("no numbers here", 4096) is None

    async def test_a_request_bigger_than_the_tier_is_a_clear_429(self, groq_on):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(413, json={"error": {"message": "Request too large ... TPM: Limit 8000"}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(RateLimitError) as err:
                await run_turn(StudioTurnRequest(input=[user("hi")]), client=client)
        assert "per-minute token limit" in err.value.message

    async def test_other_failures_are_a_502_without_the_key(self, groq_on):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": {"message": "boom"}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(IntegrationError) as err:
                await run_turn(StudioTurnRequest(input=[user("hi")]), client=client)
        assert "gsk-test-secret" not in json.dumps(err.value.details)

    async def test_without_a_key_the_assistant_is_unavailable(self, monkeypatch):
        monkeypatch.setattr(settings, "groq_api_key", "")
        monkeypatch.setattr(settings, "studio_ai_base_url", "")
        monkeypatch.setattr(settings, "studio_ai_api_key", "")
        assert studio_ai.availability()["available"] is False
        with pytest.raises(ServiceUnavailableError):
            await run_turn(StudioTurnRequest(input=[user("hi")]))


class TestApi:
    async def test_status_and_turn_need_a_login(self, client):
        assert (await client.get("/integrations/studio/ai")).status_code == 401
        assert (await client.post("/integrations/studio/ai/turn", json={"input": []})).status_code == 401

    async def test_datasets_report_whether_the_assistant_is_available(self, client, viewer_headers):
        response = await client.get("/integrations/studio/datasets", headers=viewer_headers)
        assert response.status_code == 200
        ai = response.json()["data"]["ai"]
        assert ai["available"] is False and "GROQ_API_KEY" in ai["note"]

    async def test_a_turn_without_a_configured_model_is_503(self, client, owner_headers):
        response = await client.post("/integrations/studio/ai/turn", headers=owner_headers,
                                     json={"input": [user("hi")], "response_format": {"type": "text"}})
        assert response.status_code == 503

    async def test_a_turn_relays_to_the_model(self, client, owner_headers, groq_on, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": [{"message": {"content": "Chart added."}}]})

        real = httpx.AsyncClient
        monkeypatch.setattr(studio_ai.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
        response = await client.post("/integrations/studio/ai/turn", headers=owner_headers,
                                     json={"input": [user("add a chart")], "response_format": {"type": "text"}})
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["output"][0]["content"][0]["text"] == "Chart added."
