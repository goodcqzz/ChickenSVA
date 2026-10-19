"""
OpenAI兼容LLM提供商

支持所有OpenAI API兼容的模型服务，包括：
- OpenAI (GPT-4o, GPT-4-turbo, GPT-3.5-turbo)
- 通义千问 (通过兼容接口)
- Kimi/Moonshot (通过兼容接口)
"""

import logging
from typing import AsyncIterator, Dict, List, Optional, Any

import httpx

from app.llm.base import (
    BaseLLMProvider,
    LLMConfig,
    LLMMessage,
    LLMResponse,
    StreamToken,
    ToolDefinition,
)
from app.llm_config import build_request_payload
from app.llm_config.providers import ProviderRegistry

logger = logging.getLogger(__name__)

PROVIDER_BASE_URLS: Dict[str, str] = {
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}


class OpenAICompatibleProvider(BaseLLMProvider):
    """
    OpenAI兼容API提供商

    使用OpenAI兼容接口调用各种LLM服务
    """

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        base_url = config.base_url or PROVIDER_BASE_URLS.get(config.provider, "")
        self._base_url = base_url.rstrip("/")
        self._api_key = config.api_key or ""
        
        if not self._api_key:
            logger.warning(f"API Key 未配置 [{config.provider}]，LLM调用将失败")

        headers: Dict[str, str] = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        prov_cfg = ProviderRegistry.get(config.provider)
        if prov_cfg and prov_cfg.default_headers:
            headers.update(prov_cfg.default_headers)

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=httpx.Timeout(120.0, connect=10.0),
        )

    async def chat(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        payload = self._build_payload(messages, tools, stream=False, **kwargs)

        try:
            response = await self._client.post("/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()

            choice = data["choices"][0]
            message = choice["message"]

            tool_calls = None
            if message.get("tool_calls"):
                tool_calls = message["tool_calls"]

            return LLMResponse(
                content=message.get("content", "") or "",
                finish_reason=choice.get("finish_reason", "stop"),
                tool_calls=tool_calls,
                usage=data.get("usage", {}),
                model=data.get("model", self.config.model),
            )
        except httpx.HTTPStatusError as e:
            logger.error(f"LLM API错误 [{self.config.provider}]: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"LLM调用失败 [{self.config.provider}]: {e}")
            raise

    async def chat_stream(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamToken]:
        payload = self._build_payload(messages, tools, stream=True, **kwargs)

        try:
            async with self._client.stream(
                "POST", "/chat/completions", json=payload
            ) as response:
                if response.status_code >= 400:
                    err_body = (await response.aread()).decode(
                        "utf-8", errors="replace"
                    )
                    logger.error(
                        "LLM流式API错误 [%s]: %s - %s",
                        self.config.provider,
                        response.status_code,
                        err_body,
                    )
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue

                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        yield StreamToken(content="", finish_reason="stop")
                        break

                    import json

                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    choices = data.get("choices", [])
                    if not choices:
                        continue

                    delta = choices[0].get("delta", {})
                    finish_reason = choices[0].get("finish_reason")

                    content = delta.get("content", "") or ""
                    tool_calls = delta.get("tool_calls")

                    if content or tool_calls or finish_reason:
                        yield StreamToken(
                            content=content,
                            finish_reason=finish_reason,
                            tool_calls=tool_calls if tool_calls else None,
                        )

        except httpx.HTTPStatusError as e:
            detail = ""
            if e.response is not None:
                try:
                    detail = e.response.text
                except Exception:
                    detail = ""
            if detail:
                logger.error(
                    "LLM流式HTTP错误 [%s]: %s - %s",
                    self.config.provider,
                    e.response.status_code,
                    detail,
                )
            raise
        except Exception as e:
            logger.error(f"LLM流式调用失败 [{self.config.provider}]: {e}")
            raise

    def _build_payload(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]],
        stream: bool = False,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        formatted_messages = self.build_messages(messages)

        # 组装用户参数
        params = {
            "temperature": kwargs.get("temperature", self.config.temperature),
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "top_p": kwargs.get("top_p", self.config.top_p),
            "frequency_penalty": kwargs.get(
                "frequency_penalty", self.config.frequency_penalty
            ),
            "presence_penalty": kwargs.get(
                "presence_penalty", self.config.presence_penalty
            ),
            "enable_online_search": kwargs.get(
                "enable_online_search", self.config.enable_online_search
            ),
        }
        if self.config.top_k is not None:
            params["top_k"] = self.config.top_k
        if self.config.reasoning_effort:
            params["reasoning_effort"] = self.config.reasoning_effort

        tools_dict = self.get_tools_dict(tools)

        # 使用能力表过滤构建请求
        return build_request_payload(
            provider_id=self.config.provider,
            model_name=self.config.model,
            messages=formatted_messages,
            params=params,
            tools=tools_dict,
            stream=stream,
            enable_reasoning=self.config.enable_reasoning,
        )

    async def close(self):
        if self._client:
            await self._client.aclose()
