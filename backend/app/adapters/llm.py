import json
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Literal, Optional

import httpx
from pydantic import BaseModel, Field, ValidationError


class LLMMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class LLMUsage(BaseModel):
    prompt_tokens: Optional[int] = Field(default=None, ge=0, strict=True)
    completion_tokens: Optional[int] = Field(default=None, ge=0, strict=True)
    total_tokens: Optional[int] = Field(default=None, ge=0, strict=True)


class LLMResponse(BaseModel):
    content: str
    usage: LLMUsage = Field(default_factory=LLMUsage)
    parsed_json: Optional[Dict[str, Any]] = None


class LLMError(RuntimeError):
    """外部服务或结构化输出失败；不附带密钥和原始响应。"""

    def __init__(self, code: str, message: str, *, usage: Optional[LLMUsage] = None,
                 diagnostic: Optional[str] = None):
        super().__init__(message)
        self.code = code
        self.usage = usage
        # 仅供代码生成的格式/位置说明；不得放入模型原文或服务错误正文。
        self.diagnostic = diagnostic


def _usage(data: Optional[dict], input_key: str, output_key: str, *, include_cache: bool = False) -> LLMUsage:
    if data is not None and not isinstance(data, dict):
        raise LLMError("invalid_response", "模型 usage 必须是 JSON 对象或 null。")
    values = data or {}
    try:
        usage = LLMUsage(prompt_tokens=values.get(input_key), completion_tokens=values.get(output_key),
                         total_tokens=values.get("total_tokens"))
        if include_cache:
            cache = LLMUsage(prompt_tokens=values.get("cache_creation_input_tokens"),
                             completion_tokens=values.get("cache_read_input_tokens"))
            if usage.prompt_tokens is not None:
                usage.prompt_tokens += (cache.prompt_tokens or 0) + (cache.completion_tokens or 0)
    except ValidationError as exc:
        raise LLMError("invalid_response", "模型 usage token 必须是非负整数或 null。") from exc
    if usage.total_tokens is None and usage.prompt_tokens is not None and usage.completion_tokens is not None:
        usage.total_tokens = usage.prompt_tokens + usage.completion_tokens
    return usage


class BaseLLMAdapter(ABC):
    def __init__(self, base_url: str, model: str, api_key: str = "", timeout_seconds: float = 60.0,
                 client: Optional[httpx.AsyncClient] = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self.timeout_seconds = timeout_seconds
        self._client = client

    async def _post_json(self, url: str, headers: Dict[str, str], payload: Dict[str, Any]) -> dict:
        try:
            if self._client is not None:
                response = await self._client.post(url, json=payload, headers=headers, timeout=self.timeout_seconds)
            else:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.post(url, json=payload, headers=headers)
            if response.status_code == 401:
                raise LLMError("authentication_failed", "模型服务鉴权失败，请检查凭据。")
            if response.status_code == 429:
                raise LLMError("rate_limited", "模型服务限流或配额不足。")
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LLMError("http_error", f"模型服务失败，HTTP {exc.response.status_code}。") from exc
        except httpx.TimeoutException as exc:
            raise LLMError("timeout", "模型请求超时。") from exc
        except httpx.RequestError as exc:
            raise LLMError("network_error", "模型服务网络请求失败。") from exc
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise LLMError("invalid_response", "模型服务响应不是有效 JSON。") from exc
        if not isinstance(data, dict):
            raise LLMError("invalid_response", "模型服务响应必须是 JSON 对象。")
        return data

    @abstractmethod
    async def generate(self, messages: List[LLMMessage], temperature: Optional[float] = None,
                       response_format: Optional[str] = None, *, max_tokens: Optional[int] = None) -> LLMResponse:
        """可选参数仅在调用者指定时发送；不推断模型能力。"""
        raise NotImplementedError

    @staticmethod
    def _check_options(response_format: Optional[str], max_tokens: Optional[int]) -> None:
        if response_format not in (None, "json_object"):
            raise LLMError("unsupported_response_format", "仅支持普通文本或 json_object 输出。")
        if max_tokens is not None and (type(max_tokens) is not int or max_tokens < 0):
            raise LLMError("invalid_request", "max_tokens 必须是非负整数或 None。")

    @staticmethod
    def _response(content: str, usage: LLMUsage, response_format: Optional[str]) -> LLMResponse:
        if not isinstance(content, str) or not content.strip():
            raise LLMError("no_text", "模型未返回可用文本。", usage=usage)
        parsed_json = None
        if response_format == "json_object":
            # 只接受完整独立的JSON代码块外壳，不从正文中搜索或修补JSON。
            fence = re.fullmatch(r"```(?:json)?[ \t]*\r?\n(.*?)\r?\n```", content.strip(), re.DOTALL | re.IGNORECASE)
            json_text = fence.group(1) if fence else content
            try:
                parsed_json = json.loads(json_text)
            except json.JSONDecodeError as exc:
                diagnostic = ("响应不是单个完整的JSON代码块；不接受其他语言标记、缺失的围栏或块外文字。"
                              if content.lstrip().startswith("```") and fence is None
                              else f"JSON正文语法错误：第{exc.lineno}行，第{exc.colno}列（共{len(json_text)}字符）。")
                raise LLMError("invalid_json", "模型结构化输出不是有效 JSON 对象。",
                               usage=usage, diagnostic=diagnostic) from exc
            if not isinstance(parsed_json, dict):
                raise LLMError("invalid_json", "模型结构化输出必须是 JSON 对象。", usage=usage,
                               diagnostic=f"JSON顶层不是对象（类型：{type(parsed_json).__name__}）。")
        return LLMResponse(content=content, usage=usage, parsed_json=parsed_json)


class OpenAIChatAdapter(BaseLLMAdapter):
    """OpenAI Chat Completions：base_url 为协议 API 前缀。"""

    async def generate(self, messages: List[LLMMessage], temperature: Optional[float] = None,
                       response_format: Optional[str] = None, *, max_tokens: Optional[int] = None) -> LLMResponse:
        self._check_options(response_format, max_tokens)
        payload: Dict[str, Any] = {"model": self.model, "messages": [{"role": m.role, "content": m.content} for m in messages]}
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_completion_tokens"] = max_tokens
        if response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}
        data = await self._post_json(f"{self.base_url}/chat/completions",
                                    {"Content-Type": "application/json", "Authorization": f"Bearer {self._api_key}"}, payload)
        try:
            return self._parse_response(data, response_format)
        except (KeyError, TypeError) as exc:
            raise LLMError("invalid_response", "Chat Completions 响应字段结构无效。") from exc

    def _parse_response(self, data: dict, response_format: Optional[str]) -> LLMResponse:
        usage = _usage(data.get("usage"), "prompt_tokens", "completion_tokens")
        choices = data.get("choices", [])
        if not choices:
            raise LLMError("no_text", "模型未返回可用文本。", usage=usage)
        choice = choices[0]
        message = choice["message"]
        if not isinstance(message, dict):
            raise LLMError("invalid_response", "Chat Completions message 必须是 JSON 对象。", usage=usage)
        if message.get("refusal") or choice.get("finish_reason") == "content_filter":
            raise LLMError("refusal", "模型拒绝生成本次内容。", usage=usage)
        if choice.get("finish_reason") == "length":
            raise LLMError("incomplete", "模型输出达到 token 上限，内容不完整。", usage=usage)
        return self._response(message.get("content"), usage, response_format)


class OpenAIResponsesAdapter(BaseLLMAdapter):
    """OpenAI Responses：只解析官方 output/message/output_text 结构。"""

    async def generate(self, messages: List[LLMMessage], temperature: Optional[float] = None,
                       response_format: Optional[str] = None, *, max_tokens: Optional[int] = None) -> LLMResponse:
        self._check_options(response_format, max_tokens)
        payload: Dict[str, Any] = {"model": self.model, "input": [{"role": m.role, "content": m.content} for m in messages]}
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_output_tokens"] = max_tokens
        if response_format == "json_object":
            payload["text"] = {"format": {"type": "json_object"}}
        data = await self._post_json(f"{self.base_url}/responses",
                                    {"Content-Type": "application/json", "Authorization": f"Bearer {self._api_key}"}, payload)
        try:
            return self._parse_response(data, response_format)
        except (KeyError, TypeError) as exc:
            raise LLMError("invalid_response", "Responses 响应字段结构无效。") from exc

    def _parse_response(self, data: dict, response_format: Optional[str]) -> LLMResponse:
        usage = _usage(data.get("usage"), "input_tokens", "output_tokens")
        if data.get("status") in ("incomplete", "failed", "cancelled", "queued", "in_progress"):
            raise LLMError("incomplete", "模型响应未完成，不能用作完整结果。", usage=usage)
        parts, structured = [], None
        for item in data.get("output", []):
            if item["type"] == "message":
                # JSON只解析最终回答；无phase/null保留协议原有行为，不从文本推断阶段。
                if response_format == "json_object" and item.get("phase") not in (None, "final_answer"):
                    continue
                for part in item["content"]:
                    if part["type"] == "refusal":
                        raise LLMError("refusal", "模型拒绝生成本次内容。", usage=usage)
                    if part["type"] == "output_text":
                        if response_format == "json_object":
                            result = self._response(part["text"], usage, response_format)
                            if structured is None:
                                structured = result
                        else:
                            parts.append(part["text"])
        if structured is not None:
            return structured
        return self._response("".join(parts), usage, response_format)


class AnthropicMessagesAdapter(BaseLLMAdapter):
    """Anthropic Messages；JSON 模式只校验输出，不假定支持原生 schema。"""

    async def generate(self, messages: List[LLMMessage], temperature: Optional[float] = None,
                       response_format: Optional[str] = None, *, max_tokens: Optional[int] = None) -> LLMResponse:
        self._check_options(response_format, max_tokens)
        system = "\n".join(m.content for m in messages if m.role == "system")
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages if m.role != "system"],
            # Messages 协议要求 max_tokens；保留原先调用上限，调用者可覆盖。
            "max_tokens": 4096 if max_tokens is None else max_tokens,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if system:
            payload["system"] = system
        data = await self._post_json(f"{self.base_url}/messages",
                                    {"Content-Type": "application/json", "x-api-key": self._api_key, "anthropic-version": "2023-06-01"}, payload)
        try:
            return self._parse_response(data, response_format)
        except (KeyError, TypeError) as exc:
            raise LLMError("invalid_response", "Messages 响应字段结构无效。") from exc

    def _parse_response(self, data: dict, response_format: Optional[str]) -> LLMResponse:
        # 官方 Messages 计量口径：输入包括普通输入、cache 创建和读取。
        usage = _usage(data.get("usage"), "input_tokens", "output_tokens", include_cache=True)
        if data.get("stop_reason") == "refusal":
            raise LLMError("refusal", "模型拒绝生成本次内容。", usage=usage)
        if data.get("stop_reason") in ("max_tokens", "model_context_window_exceeded", "pause_turn"):
            raise LLMError("incomplete", "模型输出未完成，不能用作完整结果。", usage=usage)
        content = "".join(block["text"] for block in data.get("content", []) if block["type"] == "text")
        return self._response(content, usage, response_format)


def create_llm_adapter(protocol: str, base_url: str, model: str, api_key: str = "", timeout_seconds: float = 60.0,
                       client: Optional[httpx.AsyncClient] = None) -> BaseLLMAdapter:
    adapters = {"openai_chat": OpenAIChatAdapter, "openai_responses": OpenAIResponsesAdapter,
                "anthropic_messages": AnthropicMessagesAdapter}
    if protocol not in adapters:
        raise ValueError("不支持的模型协议；仅支持 openai_chat, openai_responses, anthropic_messages。")
    return adapters[protocol](base_url, model, api_key, timeout_seconds, client)
