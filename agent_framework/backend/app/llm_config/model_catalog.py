"""
模型目录模块

负责从供应商 API 拉取模型列表，并进行本地缓存与过滤。
"""

import logging
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

import httpx

from .providers import ProviderRegistry, ProviderConfig

logger = logging.getLogger(__name__)

# 内存缓存：provider_id -> (timestamp, models)
_models_cache: Dict[str, tuple] = {}
_CACHE_TTL_SECONDS = 300


@dataclass
class ModelEntry:
    """标准化的模型条目"""
    id: str
    name: str
    provider: str
    description: str = ""
    max_tokens: int = 8192
    context_window: int = 8192
    # 原始 API 返回的元数据
    raw_meta: Dict[str, Any] = field(default_factory=dict)


async def fetch_models_for_provider(
    provider_id: str,
    api_key: str,
    custom_base_url: Optional[str] = None,
    force_refresh: bool = False,
) -> List[ModelEntry]:
    """
    从供应商 API 拉取模型列表。

    Args:
        provider_id: 供应商 ID
        api_key: API 密钥
        custom_base_url: 自定义 base_url（可选）
        force_refresh: 是否强制刷新缓存

    Returns:
        模型条目列表
    """
    now = time.time()
    if not force_refresh and provider_id in _models_cache:
        ts, models = _models_cache[provider_id]
        if now - ts < _CACHE_TTL_SECONDS:
            logger.debug(f"使用缓存的模型列表 [{provider_id}]")
            return models

    provider = ProviderRegistry.get(provider_id)
    if not provider:
        logger.warning(f"未知供应商: {provider_id}")
        return []

    if not provider.supports_models_endpoint:
        logger.debug(f"供应商 [{provider_id}] 不支持 /models 接口，返回内置列表")
        return _get_builtin_models(provider_id)

    base_url = ProviderRegistry.get_base_url(provider_id, custom_base_url)
    if not base_url:
        return []

    headers = provider.build_auth_header(api_key)
    headers["Content-Type"] = "application/json"
    headers.update(provider.default_headers)

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
            response = await client.get(
                f"{base_url}{provider.models_endpoint}", headers=headers
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as e:
        logger.warning(f"拉取模型列表失败 [{provider_id}]: HTTP {e.response.status_code} - {e.response.text[:200]}")
        return _get_builtin_models(provider_id)
    except httpx.ConnectTimeout:
        logger.warning(f"拉取模型列表失败 [{provider_id}]: 连接超时，无法访问 {base_url}")
        return _get_builtin_models(provider_id)
    except httpx.ReadTimeout:
        logger.warning(f"拉取模型列表失败 [{provider_id}]: 读取超时")
        return _get_builtin_models(provider_id)
    except httpx.NetworkError as e:
        logger.warning(f"拉取模型列表失败 [{provider_id}]: 网络错误 - {type(e).__name__}")
        return _get_builtin_models(provider_id)
    except Exception as e:
        logger.warning(f"拉取模型列表失败 [{provider_id}]: {type(e).__name__} - {e}")
        return _get_builtin_models(provider_id)

    models = _parse_models_response(provider_id, data)
    _models_cache[provider_id] = (now, models)
    logger.info(f"从 [{provider_id}] 拉取到 {len(models)} 个模型")
    return models


def _parse_models_response(provider_id: str, data: Dict[str, Any]) -> List[ModelEntry]:
    """解析 /models 返回数据为标准 ModelEntry"""
    models: List[ModelEntry] = []
    raw_list = data.get("data", []) if isinstance(data, dict) else data
    if not isinstance(raw_list, list):
        return _get_builtin_models(provider_id)

    for item in raw_list:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id") or item.get("model", "")
        if not model_id:
            continue

        # 尝试从原始元数据中提取更多信息
        meta = item
        name = model_id
        description = ""
        max_tokens = 8192
        context_window = 8192

        # OpenRouter 风格
        if "name" in item:
            name = item["name"]
        if "description" in item:
            description = item["description"]
        if "top_provider" in item and isinstance(item["top_provider"], dict):
            tp = item["top_provider"]
            if tp.get("max_completion_tokens"):
                max_tokens = tp["max_completion_tokens"]
            if tp.get("context_length"):
                context_window = tp["context_length"]

        # OpenAI 风格
        if "object" in item and item["object"] == "model":
            name = item.get("id", name)

        models.append(
            ModelEntry(
                id=model_id,
                name=name,
                provider=provider_id,
                description=description,
                max_tokens=max_tokens,
                context_window=context_window,
                raw_meta=meta,
            )
        )

    # 去重并排序
    seen = set()
    unique_models = []
    for m in models:
        if m.id not in seen:
            seen.add(m.id)
            unique_models.append(m)
    unique_models.sort(key=lambda x: x.id)
    return unique_models


def _get_builtin_models(provider_id: str) -> List[ModelEntry]:
    """返回内置模型列表（作为兜底）"""
    builtins: Dict[str, List[ModelEntry]] = {
        "qwen": [
            ModelEntry("qwen-max", "通义千问-Max", "qwen", "通义千问系列最强模型，适用于复杂任务", 8192, 32768),
            ModelEntry("qwen-plus", "通义千问-Plus", "qwen", "性能均衡，适合大多数场景", 8192, 131072),
            ModelEntry("qwen-turbo", "通义千问-Turbo", "qwen", "快速响应，适合简单任务", 4096, 131072),
            ModelEntry("qwen-coder-plus", "通义千问-Coder-Plus", "qwen", "代码专用模型", 8192, 131072),
            ModelEntry("qwen2.5-72b-instruct", "Qwen2.5-72B", "qwen", "开源 72B 指令模型", 8192, 131072),
            ModelEntry("qwen2.5-14b-instruct", "Qwen2.5-14B", "qwen", "开源 14B 指令模型", 8192, 131072),
        ],
        "deepseek": [
            ModelEntry("deepseek-v4-flash", "DeepSeek V4 Flash", "deepseek", "V4 快速（平台默认）", 8192, 131072),
            ModelEntry("deepseek-v4-pro", "DeepSeek V4 Pro", "deepseek", "V4 强模型", 8192, 131072),
            ModelEntry("deepseek-chat", "DeepSeek-V3", "deepseek", "通用对话模型", 8192, 64000),
            ModelEntry("deepseek-reasoner", "DeepSeek-R1", "deepseek", "深度推理模型", 8192, 64000),
            ModelEntry("deepseek-coder", "DeepSeek-Coder", "deepseek", "代码专用模型", 8192, 64000),
        ],
        "openrouter": [
            ModelEntry(
                "openai/gpt-4o",
                "GPT-4o",
                "openrouter",
                "通过 OpenRouter 调用；建议填写 Key 后点「刷新」拉取完整列表",
                8192,
                128000,
            ),
            ModelEntry(
                "anthropic/claude-3.5-sonnet",
                "Claude 3.5 Sonnet",
                "openrouter",
                "OpenRouter 路由至 Anthropic",
                8192,
                200000,
            ),
            ModelEntry(
                "google/gemini-2.0-flash-001",
                "Gemini 2.0 Flash",
                "openrouter",
                "OpenRouter 路由",
                8192,
                1000000,
            ),
        ],
    }
    return builtins.get(provider_id, [])


class ModelCatalog:
    """模型目录管理器（同步封装，供非异步代码使用）"""

    @staticmethod
    def get_cached_models(provider_id: str) -> List[ModelEntry]:
        """获取缓存的模型列表（不触发网络请求）"""
        if provider_id in _models_cache:
            return _models_cache[provider_id][1]
        return _get_builtin_models(provider_id)

    @staticmethod
    def clear_cache(provider_id: Optional[str] = None) -> None:
        """清除模型缓存"""
        global _models_cache
        if provider_id:
            _models_cache.pop(provider_id, None)
        else:
            _models_cache.clear()

    @staticmethod
    def to_dict_list(models: List[ModelEntry]) -> List[Dict[str, Any]]:
        return [
            {
                "id": m.id,
                "name": m.name,
                "provider": m.provider,
                "description": m.description,
                "max_tokens": m.max_tokens,
                "context_window": m.context_window,
            }
            for m in models
        ]
