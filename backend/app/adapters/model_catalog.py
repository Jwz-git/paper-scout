"""读取用户所选服务的模型列表；不发送对话或执行生成请求。"""
import json
from typing import List, Optional

import httpx
from pydantic import BaseModel, Field, ValidationError

from backend.app.adapters.llm import LLMError


class AvailableModel(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=300)


class ModelCatalogPage(BaseModel):
    models: List[AvailableModel]
    next_cursor: Optional[str] = None


async def list_models(base_url, protocol, api_key, cursor=None, client=None):
    headers = {"Accept": "application/json"}
    params = {}
    if protocol == "anthropic_messages":
        headers.update({"x-api-key": api_key, "anthropic-version": "2023-06-01"})
        params["limit"] = 100
        if cursor:
            params["after_id"] = cursor
    elif api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        if client is not None:
            response = await client.get(f"{base_url}/models", headers=headers, params=params, timeout=15, follow_redirects=False)
        else:
            async with httpx.AsyncClient(timeout=15, follow_redirects=False) as session:
                response = await session.get(f"{base_url}/models", headers=headers, params=params)
        if response.status_code in (401, 403):
            raise LLMError("authentication_failed", "获取模型鉴权失败，请检查密钥及其访问权限。")
        if response.status_code == 429:
            raise LLMError("rate_limited", "模型列表请求被限流，请稍后重试。")
        if response.status_code == 404:
            raise LLMError("not_supported", "该地址未提供模型列表，请检查 API 根地址，或手动添加模型 ID。")
        if not 200 <= response.status_code < 300:
            raise LLMError("http_error", f"获取模型失败，HTTP {response.status_code}。")
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise LLMError("invalid_response", "模型列表响应缺少 data 数组。")
        models = [AvailableModel(id=item["id"], name=item.get("display_name") or item["id"]) for item in data["data"]]
        cursor = None
        if protocol == "anthropic_messages" and data.get("has_more"):
            cursor = data.get("last_id")
            if not isinstance(cursor, str) or not cursor or len(cursor) > 200:
                raise LLMError("invalid_response", "模型列表缺少有效的下一页标识。")
        return ModelCatalogPage(models=list({item.id: item for item in models}.values()), next_cursor=cursor)
    except httpx.TimeoutException as exc:
        raise LLMError("timeout", "获取模型超时，请稍后重试。") from exc
    except httpx.RequestError as exc:
        raise LLMError("network_error", "无法连接模型服务，请检查地址与网络。") from exc
    except (json.JSONDecodeError, ValidationError, KeyError, TypeError) as exc:
        raise LLMError("invalid_response", "模型列表响应格式无效，未取得可用列表。") from exc
