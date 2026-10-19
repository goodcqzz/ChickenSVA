"""
LLM提供商工厂

根据配置创建对应的LLM提供商实例
"""

import logging
from typing import Dict, Type

from app.llm.base import BaseLLMProvider, LLMConfig
from app.llm.openai_compatible import OpenAICompatibleProvider

logger = logging.getLogger(__name__)

_PROVIDER_REGISTRY: Dict[str, Type[BaseLLMProvider]] = {
    "qwen": OpenAICompatibleProvider,
    "deepseek": OpenAICompatibleProvider,
    "openrouter": OpenAICompatibleProvider,
}


class LLMFactory:
    """
    LLM提供商工厂

    根据提供商名称创建对应的LLM实例
    """

    @staticmethod
    def create(config: LLMConfig) -> BaseLLMProvider:
        """
        创建LLM提供商实例

        Args:
            config: LLM配置

        Returns:
            LLM提供商实例

        Raises:
            ValueError: 不支持的提供商
        """
        provider_class = _PROVIDER_REGISTRY.get(config.provider)
        if not provider_class:
            raise ValueError(
                f"不支持的LLM提供商: {config.provider}, "
                f"支持的提供商: {list(_PROVIDER_REGISTRY.keys())}"
            )

        logger.info(f"创建LLM提供商: {config.provider}/{config.model}")
        return provider_class(config)

    @staticmethod
    def register_provider(name: str, provider_class: Type[BaseLLMProvider]) -> None:
        """
        注册新的LLM提供商

        Args:
            name: 提供商名称
            provider_class: 提供商类
        """
        _PROVIDER_REGISTRY[name] = provider_class
        logger.info(f"注册LLM提供商: {name}")

    @staticmethod
    def get_supported_providers() -> list:
        """获取所有支持的提供商"""
        return list(_PROVIDER_REGISTRY.keys())
