"""
供应商配置模块

管理 LLM 供应商的 endpoint、headers、鉴权方式等元数据。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import json
import os

logger = __import__("logging").getLogger(__name__)


@dataclass
class ProviderConfig:
    """单个供应商配置"""
    id: str
    name: str
    name_zh: str
    base_url: str
    auth_type: str = "bearer"  # bearer, api_key_header, query_param
    auth_header_name: str = "Authorization"
    auth_header_prefix: str = "Bearer"
    models_endpoint: str = "/models"
    chat_endpoint: str = "/chat/completions"
    supports_models_endpoint: bool = True
    supports_streaming: bool = True
    api_key_required: bool = True
    default_headers: Dict[str, str] = field(default_factory=dict)
    # 额外字段，用于特殊处理
    extra: Dict[str, Any] = field(default_factory=dict)

    def build_auth_header(self, api_key: str) -> Dict[str, str]:
        """根据鉴权类型构建请求头"""
        if not api_key:
            return {}
        if self.auth_type == "bearer":
            return {self.auth_header_name: f"{self.auth_header_prefix} {api_key}"}
        elif self.auth_type == "api_key_header":
            return {self.auth_header_name: api_key}
        return {}


class ProviderRegistry:
    """供应商注册表"""

    _PROVIDERS: Dict[str, ProviderConfig] = {
        "qwen": ProviderConfig(
            id="qwen",
            name="Qwen",
            name_zh="通义千问",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            supports_models_endpoint=True,
            extra={
                "docs_url": "https://help.aliyun.com/zh/dashscope",
                "web_search_param": "enable_search",
                "web_search_route": "dashscope_chat",
            },
        ),
        "deepseek": ProviderConfig(
            id="deepseek",
            name="DeepSeek",
            name_zh="DeepSeek",
            base_url="https://api.deepseek.com/v1",
            supports_models_endpoint=True,
            extra={"docs_url": "https://platform.deepseek.com/docs"},
        ),
        "openrouter": ProviderConfig(
            id="openrouter",
            name="OpenRouter",
            name_zh="OpenRouter",
            base_url="https://openrouter.ai/api/v1",
            supports_models_endpoint=True,
            default_headers={
                "HTTP-Referer": "https://localhost",
                "X-Title": "Agent Framework",
            },
            extra={"docs_url": "https://openrouter.ai/docs"},
        ),
    }

    @classmethod
    def get(cls, provider_id: str) -> Optional[ProviderConfig]:
        return cls._PROVIDERS.get(provider_id)

    @classmethod
    def list_providers(cls) -> List[ProviderConfig]:
        return list(cls._PROVIDERS.values())

    @classmethod
    def list_ids(cls) -> List[str]:
        return list(cls._PROVIDERS.keys())

    @classmethod
    def register(cls, config: ProviderConfig) -> None:
        cls._PROVIDERS[config.id] = config
        logger.info(f"注册供应商: {config.id}")

    @classmethod
    def get_base_url(cls, provider_id: str, custom_base_url: Optional[str] = None) -> str:
        if custom_base_url:
            return custom_base_url.rstrip("/")
        cfg = cls.get(provider_id)
        if cfg:
            return cfg.base_url
        return ""


def get_provider_config(provider_id: str) -> Optional[ProviderConfig]:
    return ProviderRegistry.get(provider_id)


# 配置文件路径（用于用户自定义供应商）
_CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
)
_PROVIDERS_CONFIG_FILE = os.path.join(_CONFIG_DIR, "providers_config.json")


def load_user_providers() -> Dict[str, ProviderConfig]:
    """加载用户自定义供应商配置"""
    if not os.path.exists(_PROVIDERS_CONFIG_FILE):
        return {}
    try:
        with open(_PROVIDERS_CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        result = {}
        for pid, pdict in data.items():
            result[pid] = ProviderConfig(**pdict)
        return result
    except Exception as e:
        logger.warning(f"加载用户供应商配置失败: {e}")
        return {}


def save_user_providers(providers: Dict[str, ProviderConfig]) -> None:
    """保存用户自定义供应商配置"""
    try:
        os.makedirs(_CONFIG_DIR, exist_ok=True)
        data = {}
        for pid, cfg in providers.items():
            data[pid] = {
                "id": cfg.id,
                "name": cfg.name,
                "name_zh": cfg.name_zh,
                "base_url": cfg.base_url,
                "auth_type": cfg.auth_type,
                "auth_header_name": cfg.auth_header_name,
                "auth_header_prefix": cfg.auth_header_prefix,
                "models_endpoint": cfg.models_endpoint,
                "chat_endpoint": cfg.chat_endpoint,
                "supports_models_endpoint": cfg.supports_models_endpoint,
                "supports_streaming": cfg.supports_streaming,
                "api_key_required": cfg.api_key_required,
                "default_headers": cfg.default_headers,
                "extra": cfg.extra,
            }
        with open(_PROVIDERS_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存用户供应商配置失败: {e}")
