"""
LLM提供商抽象基类

定义所有LLM提供商必须实现的接口
"""

import logging
from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class LLMMessage:
    role: MessageRole
    content: str
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"role": self.role.value, "content": self.content}
        if self.name:
            d["name"] = self.name
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        return d


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class StreamToken:
    content: str
    finish_reason: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None


@dataclass
class LLMResponse:
    content: str
    finish_reason: str = "stop"
    tool_calls: Optional[List[Dict[str, Any]]] = None
    usage: Dict[str, int] = field(default_factory=dict)
    model: str = ""


@dataclass
class LLMConfig:
    provider: str
    model: str
    api_key: str
    temperature: float = 0.7
    max_tokens: int = 2048
    top_p: float = 0.95
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    enable_online_search: bool = False
    enable_reasoning: bool = False
    top_k: Optional[int] = None
    reasoning_effort: Optional[str] = None
    system_prompt: str = ""
    base_url: Optional[str] = None


class BaseLLMProvider(ABC):
    """
    LLM提供商抽象基类

    所有LLM提供商必须实现此接口
    """

    def __init__(self, config: LLMConfig):
        self.config = config
        self._client: Optional[Any] = None

    @abstractmethod
    async def chat(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """
        同步聊天接口

        Args:
            messages: 消息列表
            tools: 可用工具列表
            **kwargs: 额外参数

        Returns:
            LLM响应
        """
        pass

    @abstractmethod
    async def chat_stream(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamToken]:
        """
        流式聊天接口

        Args:
            messages: 消息列表
            tools: 可用工具列表
            **kwargs: 额外参数

        Yields:
            流式Token
        """
        pass

    def build_messages(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        构建消息列表

        Args:
            messages: 原始消息列表
            system_prompt: 系统提示词

        Returns:
            格式化后的消息列表
        """
        result: List[Dict[str, Any]] = []
        prepend = system_prompt or self.config.system_prompt
        # 若消息列表已以 system 开头（如 Agent 侧 _format_messages 已注入完整系统提示），
        # 不再前置 LLMConfig.system_prompt，避免重复 system、上下文膨胀及下游 400。
        if prepend and not (messages and messages[0].role == MessageRole.SYSTEM):
            result.append({"role": "system", "content": prepend})
        for msg in messages:
            result.append(msg.to_dict())
        return result

    def get_tools_dict(
        self, tools: Optional[List[ToolDefinition]]
    ) -> Optional[List[Dict[str, Any]]]:
        """将工具定义转换为API格式"""
        if not tools:
            return None
        return [t.to_dict() for t in tools]

    @property
    def provider_name(self) -> str:
        return self.__class__.__name__
