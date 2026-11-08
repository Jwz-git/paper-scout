import asyncio
import json

import httpx
import pytest

from backend.app.adapters.llm import (
    AnthropicMessagesAdapter,
    LLMError,
    LLMMessage,
    OpenAIChatAdapter,
    OpenAIResponsesAdapter,
    create_llm_adapter,
)


ADAPTERS = [OpenAIChatAdapter, OpenAIResponsesAdapter, AnthropicMessagesAdapter]
MESSAGES = [LLMMessage(role="system", content="Return a JSON object"), LLMMessage(role="user", content="Analyze")]


def payload_for(adapter_type, content, usage=None):
    if adapter_type is OpenAIChatAdapter:
        return {"choices": [{"message": {"content": content}, "finish_reason": "stop"}], "usage": usage}
    if adapter_type is OpenAIResponsesAdapter:
        return {"status": "completed", "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "content": [{"type": "output_text", "text": content}]},
        ], "usage": usage}
    return {"content": [{"type": "text", "text": content}], "stop_reason": "end_turn", "usage": usage}


def call_mock(adapter_type, payload, *, handler_check=None, **options):
    def handler(request):
        if handler_check:
            handler_check(request, json.loads(request.content))
        return httpx.Response(200, json=payload)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = adapter_type("https://model.test/v1", "user-model", "test-key", client=client)
            return await adapter.generate(MESSAGES, **options)

    return asyncio.run(run())


def test_factory_only_accepts_configured_protocol_names():
    for protocol, adapter_type in zip(["openai_chat", "openai_responses", "anthropic_messages"], ADAPTERS):
        assert isinstance(create_llm_adapter(protocol, "https://model.test/v1", "user-model"), adapter_type)
    with pytest.raises(ValueError):
        create_llm_adapter("openai", "https://model.test/v1", "user-model")


@pytest.mark.parametrize("adapter_type", ADAPTERS)
def test_official_request_and_json_response(adapter_type):
    usage = ({"prompt_tokens": 12, "completion_tokens": 18, "total_tokens": 30}
             if adapter_type is OpenAIChatAdapter else {"input_tokens": 12, "output_tokens": 18})

    def check(request, body):
        assert body["model"] == "user-model"
        assert body["temperature"] == 0.0
        if adapter_type is AnthropicMessagesAdapter:
            assert request.url.path == "/v1/messages"
            assert request.headers["x-api-key"] == "test-key"
            assert request.headers["anthropic-version"] == "2023-06-01"
            assert body["max_tokens"] == 64
            assert body["system"] == MESSAGES[0].content
            assert body["messages"] == [{"role": "user", "content": "Analyze"}]
            assert "response_format" not in body and "output_config" not in body
        else:
            assert request.headers["authorization"] == "Bearer test-key"
            if adapter_type is OpenAIChatAdapter:
                assert request.url.path == "/v1/chat/completions"
                assert body["max_completion_tokens"] == 64
                assert body["response_format"] == {"type": "json_object"}
            else:
                assert request.url.path == "/v1/responses"
                assert body["max_output_tokens"] == 64
                assert body["text"] == {"format": {"type": "json_object"}}
        assert "max_tokens" not in body or adapter_type is AnthropicMessagesAdapter

    response = call_mock(adapter_type, payload_for(adapter_type, '{"summary":"sample"}', usage),
                         handler_check=check, response_format="json_object", temperature=0.0, max_tokens=64)
    assert response.parsed_json == {"summary": "sample"}
    assert response.usage.model_dump() == {"prompt_tokens": 12, "completion_tokens": 18, "total_tokens": 30}


@pytest.mark.parametrize("adapter_type", ADAPTERS)
def test_optional_parameters_omitted_and_unknown_usage_stays_unknown(adapter_type):
    def check(request, body):
        assert "temperature" not in body
        assert "max_completion_tokens" not in body and "max_output_tokens" not in body
        if adapter_type is AnthropicMessagesAdapter:
            assert body["max_tokens"] == 4096  # 官方 Messages 必需字段。
    response = call_mock(adapter_type, payload_for(adapter_type, "sample"), handler_check=check)
    assert response.usage.model_dump() == {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}


@pytest.mark.parametrize("text", ["invalid JSON", "[]"])
@pytest.mark.parametrize("adapter_type", ADAPTERS)
def test_invalid_structured_output_is_failure_not_empty_success(adapter_type, text):
    with pytest.raises(LLMError) as error:
        call_mock(adapter_type, payload_for(adapter_type, text), response_format="json_object")
    assert error.value.code == "invalid_json"


@pytest.mark.parametrize("adapter_type", ADAPTERS)
@pytest.mark.parametrize("language, newline", [("json", "\n"), ("", "\n"), ("JSON", "\r\n")])
def test_single_complete_json_fence_is_unwrapped(adapter_type, language, newline):
    expected = {"summary": "中文中的 ``` 保留", "value": 1}
    text = " \n```" + language + newline + json.dumps(expected, ensure_ascii=False) + newline + "```\n"
    response = call_mock(adapter_type, payload_for(adapter_type, text), response_format="json_object")
    assert response.parsed_json == expected
    assert response.content == text


@pytest.mark.parametrize("text", [
    '```json\n{"x":1}\n',
    'Before\n```json\n{"x":1}\n```',
    '```json\n{"x":1}\n```\nAfter',
    '```json\n{"x":1}\n```\n```json\n{"y":2}\n```',
    '```python\n{"x":1}\n```',
    '```json\n{"x":1,}\n```',
    '```json\n[]\n```',
])
def test_fence_unwrapping_does_not_extract_or_repair_json(text):
    with pytest.raises(LLMError) as error:
        call_mock(OpenAIResponsesAdapter, payload_for(OpenAIResponsesAdapter, text), response_format="json_object")
    assert error.value.code == "invalid_json"


def test_plain_text_keeps_json_code_fence():
    text = '```json\n{"x":1}\n```'
    response = call_mock(OpenAIResponsesAdapter, payload_for(OpenAIResponsesAdapter, text))
    assert response.content == text and response.parsed_json is None


@pytest.mark.parametrize("commentary", ["Preparing the answer.", '{"action":"cancel"}'])
@pytest.mark.parametrize("phase", [None, "final_answer"])
def test_responses_json_uses_final_answer_not_commentary(commentary, phase):
    payload = payload_for(OpenAIResponsesAdapter, '{"action":"clarify"}', {"input_tokens": 5, "output_tokens": 7})
    payload["output"][-1]["phase"] = phase
    payload["output"].insert(1, {"type": "message", "phase": "commentary", "content": [
        {"type": "output_text", "text": commentary}]})
    response = call_mock(OpenAIResponsesAdapter, payload, response_format="json_object")
    assert response.parsed_json == {"action": "clarify"}
    assert response.content == '{"action":"clarify"}'
    assert response.usage.total_tokens == 12


def test_responses_commentary_alone_is_not_a_structured_answer():
    payload = payload_for(OpenAIResponsesAdapter, '{"action":"cancel"}')
    payload["output"][-1]["phase"] = "commentary"
    with pytest.raises(LLMError) as error:
        call_mock(OpenAIResponsesAdapter, payload, response_format="json_object")
    assert error.value.code == "no_text"


@pytest.mark.parametrize("final_part, code", [
    ({"type": "refusal", "refusal": "declined"}, "refusal"),
    ({"type": "output_text", "text": "invalid JSON"}, "invalid_json"),
])
def test_responses_invalid_final_does_not_fall_back_to_commentary(final_part, code):
    payload = {"status": "completed", "output": [
        {"type": "message", "phase": "commentary", "content": [{"type": "output_text", "text": '{"action":"cancel"}'}]},
        {"type": "message", "phase": "final_answer", "content": [final_part]},
    ]}
    with pytest.raises(LLMError) as error:
        call_mock(OpenAIResponsesAdapter, payload, response_format="json_object")
    assert error.value.code == code


@pytest.mark.parametrize("second_text", ['{"answer":2}', "invalid JSON"])
def test_responses_structured_blocks_are_validated_separately(second_text):
    payload = payload_for(OpenAIResponsesAdapter, '{"answer":1}')
    payload["output"][-1]["content"].append({"type": "output_text", "text": second_text})
    if second_text == "invalid JSON":
        with pytest.raises(LLMError) as error:
            call_mock(OpenAIResponsesAdapter, payload, response_format="json_object")
        assert error.value.code == "invalid_json"
    else:
        response = call_mock(OpenAIResponsesAdapter, payload, response_format="json_object")
        assert response.parsed_json == {"answer": 1}
        assert response.content == '{"answer":1}'


def test_responses_plain_text_still_includes_commentary():
    payload = payload_for(OpenAIResponsesAdapter, "Final answer.")
    payload["output"].insert(1, {"type": "message", "phase": "commentary", "content": [
        {"type": "output_text", "text": "Preparing. "}]})
    response = call_mock(OpenAIResponsesAdapter, payload)
    assert response.content == "Preparing. Final answer."
    assert response.parsed_json is None


@pytest.mark.parametrize("text, diagnostic", [
    ('```json\n{"private_marker":true}', "JSON代码块"),
    ('```json\n{"private_marker": }\n```', "JSON正文语法错误"),
    ('{\n"private_marker":\n}', "第3行"),
    ('["private_marker"]', "顶层"),
])
def test_json_failure_diagnostic_does_not_include_response_text(text, diagnostic):
    with pytest.raises(LLMError) as error:
        call_mock(OpenAIResponsesAdapter, payload_for(OpenAIResponsesAdapter, text,
                  {"input_tokens": 5, "output_tokens": 7}), response_format="json_object")
    assert error.value.code == "invalid_json"
    assert diagnostic in error.value.diagnostic
    assert "private_marker" not in error.value.diagnostic + str(error.value)
    assert error.value.usage.total_tokens == 12


def test_responses_sdk_shortcut_and_wrong_content_type_are_not_wire_protocol():
    for payload in [{"output_text": "SDK only", "output": []},
                    {"output": [{"type": "message", "content": [{"type": "text", "text": "wrong"}]}]}]:
        with pytest.raises(LLMError) as error:
            call_mock(OpenAIResponsesAdapter, payload)
        assert error.value.code == "no_text"


def test_incomplete_response_cannot_be_accepted_even_if_text_is_valid_json():
    payload = payload_for(OpenAIResponsesAdapter, '{"ok":true}', {"input_tokens": 5, "output_tokens": 7})
    payload["status"] = "incomplete"
    with pytest.raises(LLMError) as error:
        call_mock(OpenAIResponsesAdapter, payload, response_format="json_object")
    assert error.value.code == "incomplete"
    assert error.value.usage.total_tokens == 12


@pytest.mark.parametrize("reason,code,hint", [
    ("content_filter", "refusal", "内容过滤"),
    ("max_output_tokens", "incomplete", "长度上限"),
    (None, "incomplete", "reason=unknown"),
    ("private_marker", "incomplete", "reason=unknown"),
    ({"private_marker": True}, "incomplete", "reason=unknown"),
])
def test_responses_incomplete_reasons_are_distinguished_without_echoing_unknown_details(reason, code, hint):
    payload = payload_for(OpenAIResponsesAdapter, '{"ok":true}', {"input_tokens": 5, "output_tokens": 7})
    payload.update(status="incomplete", incomplete_details={"reason": reason})
    with pytest.raises(LLMError) as error:
        call_mock(OpenAIResponsesAdapter, payload, response_format="json_object")
    assert error.value.code == code and hint in error.value.diagnostic
    assert "private_marker" not in str(error.value) + error.value.diagnostic
    assert error.value.usage.total_tokens == 12


@pytest.mark.parametrize("status", ["failed", "cancelled", "queued", "in_progress"])
def test_responses_nonterminal_or_failed_status_is_not_a_json_correction_error(status):
    payload = payload_for(OpenAIResponsesAdapter, '{"ok":true}')
    payload["status"] = status
    with pytest.raises(LLMError) as error:
        call_mock(OpenAIResponsesAdapter, payload, response_format="json_object")
    assert error.value.code == "response_not_completed"


def test_invalid_latex_escape_returns_correction_hint_without_accepting_or_echoing_text():
    text = r'{"private_marker":"坐标为 \(x,y\)"}'
    with pytest.raises(LLMError) as error:
        call_mock(OpenAIResponsesAdapter, payload_for(OpenAIResponsesAdapter, text), response_format="json_object")
    assert error.value.code == "invalid_json"
    assert "双反斜杠" in error.value.diagnostic and "private_marker" not in error.value.diagnostic


def test_null_chat_content_and_refusal_are_explicit_failures():
    for message, expected in [({"content": None}, "no_text"), ({"content": None, "refusal": "declined"}, "refusal")]:
        with pytest.raises(LLMError) as error:
            call_mock(OpenAIChatAdapter, {"choices": [{"message": message}]}, response_format="json_object")
        assert error.value.code == expected


def test_partial_usage_does_not_invent_total_and_reported_zero_is_preserved():
    response = call_mock(OpenAIChatAdapter, payload_for(OpenAIChatAdapter, "sample", {"prompt_tokens": 0}))
    assert response.usage.prompt_tokens == 0
    assert response.usage.completion_tokens is None and response.usage.total_tokens is None


def test_anthropic_input_usage_includes_reported_cache_tokens():
    response = call_mock(AnthropicMessagesAdapter, payload_for(AnthropicMessagesAdapter, "sample", {
        "input_tokens": 10, "cache_creation_input_tokens": 20, "cache_read_input_tokens": 30, "output_tokens": 5,
    }))
    assert response.usage.prompt_tokens == 60
    assert response.usage.total_tokens == 65


@pytest.mark.parametrize("status,code", [(401, "authentication_failed"), (429, "rate_limited"), (503, "server_error"), (404, "http_error")])
def test_service_failures_have_safe_explicit_codes(status, code):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(status))) as client:
            adapter = OpenAIChatAdapter("https://model.test/v1", "m", "secret-test-key", client=client)
            with pytest.raises(LLMError) as error:
                await adapter.generate(MESSAGES)
            assert error.value.code == code
            assert "secret-test-key" not in str(error.value)
    asyncio.run(run())


def test_slow_response_is_a_timeout_after_the_whole_request_limit():
    async def slow(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json=payload_for(OpenAIChatAdapter, '{"a": 1}'))

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as client:
            adapter = OpenAIChatAdapter("https://model.test/v1", "m", client=client, timeout_seconds=0.05)
            with pytest.raises(LLMError) as error:
                await adapter.generate(MESSAGES)
            assert error.value.code == "timeout"
    asyncio.run(run())


def test_unsupported_json_mode_is_rejected_before_network_request():
    def handler(request):
        pytest.fail("无效模式不得发起请求")
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = OpenAIChatAdapter("https://model.test/v1", "m", client=client)
            with pytest.raises(LLMError) as error:
                await adapter.generate(MESSAGES, response_format="json_schema")
            assert error.value.code == "unsupported_response_format"
    asyncio.run(run())


@pytest.mark.parametrize("adapter_type,payload", [
    (OpenAIChatAdapter, {"choices": [{}]}),
    (OpenAIResponsesAdapter, {"output": [{"type": "message"}]}),
    (AnthropicMessagesAdapter, {"content": [{"type": "text"}]}),
])
def test_malformed_wire_fields_are_external_response_errors(adapter_type, payload):
    with pytest.raises(LLMError) as error:
        call_mock(adapter_type, payload)
    assert error.value.code == "invalid_response"


@pytest.mark.parametrize("usage", [[], {"prompt_tokens": -1}, {"prompt_tokens": True}, {"prompt_tokens": "3"}])
def test_malformed_or_negative_usage_is_not_accepted(usage):
    with pytest.raises(LLMError) as error:
        call_mock(OpenAIChatAdapter, payload_for(OpenAIChatAdapter, "sample", usage))
    assert error.value.code == "invalid_response"


@pytest.mark.parametrize("max_tokens", [-1, True, "3"])
def test_invalid_token_limit_is_rejected_before_http(max_tokens):
    def handler(request, body):
        pytest.fail("无效 token 上限不得发起 HTTP 请求")
    with pytest.raises(LLMError) as error:
        call_mock(OpenAIChatAdapter, payload_for(OpenAIChatAdapter, "sample"), handler_check=handler, max_tokens=max_tokens)
    assert error.value.code == "invalid_request"


def test_message_role_is_validated_at_entry():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        LLMMessage(role="tool", content="outside current interface")
