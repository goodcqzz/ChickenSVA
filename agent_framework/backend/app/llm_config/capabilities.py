"""
模型能力表模块

提供“接口元数据 + 本地能力表 + 兜底规则”的组合能力查询。

能力来源优先级：
1. 接口实时返回的模型元数据（如 OpenRouter 的 supported_parameters）
2. 本地维护的模型能力表（MODEL_CAPABILITY_OVERRIDES）
3. 供应商级默认规则（PROVIDER_DEFAULT_CAPS）
4. 安全兜底规则（SAFE_FALLBACK_CAPS）
"""

import logging
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 本地模型能力覆盖表
# ---------------------------------------------------------------------------
# 格式简化：True/False 表示是否支持；dict 表示特殊限制（如 fixed 值）

MODEL_CAPABILITY_OVERRIDES: Dict[str, Dict[str, Dict[str, Any]]] = {
    "openai": {
        "gpt-4o": {
            "temperature": True,
            "top_p": True,
            "top_k": False,
            "max_tokens": True,
            "frequency_penalty": True,
            "presence_penalty": True,
            "reasoning_effort": False,
            "web_search": False,
            "vision": True,
        },
        "gpt-4o-mini": {
            "temperature": True,
            "top_p": True,
            "top_k": False,
            "max_tokens": True,
            "frequency_penalty": True,
            "presence_penalty": True,
            "reasoning_effort": False,
            "web_search": False,
            "vision": True,
        },
        "gpt-4-turbo": {
            "temperature": True,
            "top_p": True,
            "top_k": False,
            "max_tokens": True,
            "frequency_penalty": True,
            "presence_penalty": True,
            "reasoning_effort": False,
            "web_search": False,
            "vision": True,
        },
        "gpt-3.5-turbo": {
            "temperature": True,
            "top_p": True,
            "top_k": False,
            "max_tokens": True,
            "frequency_penalty": True,
            "presence_penalty": True,
            "reasoning_effort": False,
            "web_search": False,
            "vision": False,
        },
        "o1-preview": {
            "temperature": {"fixed": 1},
            "top_p": False,
            "top_k": False,
            "max_tokens": True,
            "frequency_penalty": False,
            "presence_penalty": False,
            "reasoning_effort": True,
            "web_search": False,
            "vision": False,
        },
        "o1-mini": {
            "temperature": {"fixed": 1},
            "top_p": False,
            "top_k": False,
            "max_tokens": True,
            "frequency_penalty": False,
            "presence_penalty": False,
            "reasoning_effort": True,
            "web_search": False,
            "vision": False,
        },
    },
    "qwen": {
        "qwen-max": {
            "temperature": True,
            "top_p": True,
            "top_k": True,
            "max_tokens": True,
            "frequency_penalty": False,
            "presence_penalty": False,
            "reasoning_effort": False,
            "web_search": True,
            "web_search_route": "dashscope_chat",
            "vision": True,
        },
        "qwen-plus": {
            "temperature": True,
            "top_p": True,
            "top_k": True,
            "max_tokens": True,
            "frequency_penalty": False,
            "presence_penalty": False,
            "reasoning_effort": False,
            "web_search": True,
            "web_search_route": "dashscope_chat",
            "vision": True,
        },
        "qwen-turbo": {
            "temperature": True,
            "top_p": True,
            "top_k": True,
            "max_tokens": True,
            "frequency_penalty": False,
            "presence_penalty": False,
            "reasoning_effort": False,
            "web_search": False,
            "vision": False,
        },
        "qwen-coder-plus": {
            "temperature": True,
            "top_p": True,
            "top_k": True,
            "max_tokens": True,
            "frequency_penalty": False,
            "presence_penalty": False,
            "reasoning_effort": False,
            "web_search": False,
            "vision": False,
        },
        "qwen2.5-72b-instruct": {
            "temperature": True,
            "top_p": True,
            "top_k": True,
            "max_tokens": True,
            "frequency_penalty": False,
            "presence_penalty": False,
            "reasoning_effort": False,
            "web_search": False,
            "vision": False,
        },
        "qwen2.5-14b-instruct": {
            "temperature": True,
            "top_p": True,
            "top_k": True,
            "max_tokens": True,
            "frequency_penalty": False,
            "presence_penalty": False,
            "reasoning_effort": False,
            "web_search": False,
            "vision": False,
        },
    },
    "kimi": {
        "moonshot-v1-8k": {
            "temperature": True,
            "top_p": True,
            "top_k": False,
            "max_tokens": True,
            "frequency_penalty": True,
            "presence_penalty": True,
            "reasoning_effort": False,
            "web_search": True,
            "vision": False,
        },
        "moonshot-v1-32k": {
            "temperature": True,
            "top_p": True,
            "top_k": False,
            "max_tokens": True,
            "frequency_penalty": True,
            "presence_penalty": True,
            "reasoning_effort": False,
            "web_search": True,
            "vision": False,
        },
        "moonshot-v1-128k": {
            "temperature": True,
            "top_p": True,
            "top_k": False,
            "max_tokens": True,
            "frequency_penalty": True,
            "presence_penalty": True,
            "reasoning_effort": False,
            "web_search": True,
            "vision": False,
        },
        "kimi-k2-0711-preview": {
            "temperature": {"fixed": 1},
            "top_p": True,
            "top_k": False,
            "max_tokens": True,
            "frequency_penalty": True,
            "presence_penalty": True,
            "reasoning_effort": False,
            "web_search": True,
            "vision": True,
        },
        "kimi-k2.5": {
            "temperature": {"fixed": 1},
            "top_p": True,
            "top_k": False,
            "max_tokens": True,
            "frequency_penalty": True,
            "presence_penalty": True,
            "reasoning_effort": False,
            "web_search": True,
            "vision": True,
        },
        "kimi-k2.6": {
            "temperature": {"fixed": 1},
            "top_p": True,
            "top_k": False,
            "max_tokens": True,
            "frequency_penalty": True,
            "presence_penalty": True,
            "reasoning_effort": False,
            "web_search": True,
            "vision": True,
        },
    },
    "deepseek": {
        "deepseek-chat": {
            "temperature": True,
            "top_p": True,
            "top_k": False,
            "max_tokens": True,
            # 官方文档已标记为 deprecated，部分网关对非法组合更严格，统一不传
            "frequency_penalty": False,
            "presence_penalty": False,
            "reasoning_effort": False,
            "web_search": False,
            "vision": False,
        },
        "deepseek-reasoner": {
            "temperature": True,
            "top_p": True,
            "top_k": False,
            "max_tokens": True,
            "frequency_penalty": False,
            "presence_penalty": False,
            "reasoning_effort": False,
            "web_search": False,
            "vision": False,
        },
        "deepseek-coder": {
            "temperature": True,
            "top_p": True,
            "top_k": False,
            "max_tokens": True,
            "frequency_penalty": False,
            "presence_penalty": False,
            "reasoning_effort": False,
            "web_search": False,
            "vision": False,
        },
        "deepseek-v4-flash": {
            "temperature": True,
            "top_p": True,
            "top_k": False,
            "max_tokens": {"max": 8192, "default": 2048},
            "frequency_penalty": False,
            "presence_penalty": False,
            "reasoning_effort": False,
            "web_search": False,
            "vision": False,
        },
        "deepseek-v4-pro": {
            "temperature": True,
            "top_p": True,
            "top_k": False,
            "max_tokens": {"max": 8192, "default": 4096},
            "frequency_penalty": False,
            "presence_penalty": False,
            "reasoning_effort": False,
            "web_search": False,
            "vision": False,
        },
    },
    "claude": {
        "claude-3-opus-20240229": {
            "temperature": True,
            "top_p": True,
            "top_k": False,
            "max_tokens": True,
            "frequency_penalty": False,
            "presence_penalty": False,
            "reasoning_effort": False,
            "web_search": False,
            "vision": True,
        },
        "claude-3-5-sonnet-20241022": {
            "temperature": True,
            "top_p": True,
            "top_k": False,
            "max_tokens": True,
            "frequency_penalty": False,
            "presence_penalty": False,
            "reasoning_effort": False,
            "web_search": False,
            "vision": True,
        },
        "claude-3-5-haiku-20241022": {
            "temperature": True,
            "top_p": True,
            "top_k": False,
            "max_tokens": True,
            "frequency_penalty": False,
            "presence_penalty": False,
            "reasoning_effort": False,
            "web_search": False,
            "vision": True,
        },
        "claude-3-haiku-20240307": {
            "temperature": True,
            "top_p": True,
            "top_k": False,
            "max_tokens": True,
            "frequency_penalty": False,
            "presence_penalty": False,
            "reasoning_effort": False,
            "web_search": False,
            "vision": True,
        },
    },
}

# ---------------------------------------------------------------------------
# 供应商级默认能力规则
# ---------------------------------------------------------------------------

PROVIDER_DEFAULT_CAPS: Dict[str, Dict[str, Any]] = {
    "qwen": {
        "temperature": True,
        "top_p": True,
        "top_k": True,
        "max_tokens": {"max": 8192, "default": 2048},
        "frequency_penalty": False,
        "presence_penalty": False,
        "reasoning_effort": False,
        "web_search": False,
        "vision": False,
    },
    "deepseek": {
        "temperature": True,
        "top_p": True,
        "top_k": False,
        "max_tokens": {"max": 8192, "default": 2048},
        "frequency_penalty": False,
        "presence_penalty": False,
        "reasoning_effort": False,
        "web_search": False,
        "vision": False,
    },
    "openrouter": {
        "temperature": True,
        "top_p": True,
        "top_k": False,
        "max_tokens": {"max": 16384, "default": 2048},
        "frequency_penalty": True,
        "presence_penalty": True,
        "reasoning_effort": False,
        "web_search": False,
        "vision": False,
    },
}

# ---------------------------------------------------------------------------
# 安全兜底规则
# ---------------------------------------------------------------------------

SAFE_FALLBACK_CAPS: Dict[str, Any] = {
    "temperature": True,
    "top_p": True,
    "top_k": False,
    "max_tokens": True,
    "frequency_penalty": False,
    "presence_penalty": False,
    "reasoning_effort": False,
    "web_search": False,
    "vision": False,
}

# ---------------------------------------------------------------------------
# 参数规范定义
# ---------------------------------------------------------------------------

PARAM_SPECS: Dict[str, Dict[str, Any]] = {
    "temperature": {"min": 0.0, "max": 2.0, "default": 0.7, "step": 0.1},
    "top_p": {"min": 0.0, "max": 1.0, "default": 0.95, "step": 0.05},
    "top_k": {"min": 1, "max": 100, "default": 50, "step": 1},
    "max_tokens": {"min": 1, "max": 131072, "default": 2048, "step": 1},
    "frequency_penalty": {"min": -2.0, "max": 2.0, "default": 0.0, "step": 0.1},
    "presence_penalty": {"min": -2.0, "max": 2.0, "default": 0.0, "step": 0.1},
    "reasoning_effort": {"choices": ["low", "medium", "high"], "default": "medium"},
    "web_search": {"default": False},
    "vision": {"default": False},
}

# ---------------------------------------------------------------------------
# 结果结构
# ---------------------------------------------------------------------------

@dataclass
class CapabilityResult:
    """单个参数的能力结果"""
    supported: bool
    min: Optional[float] = None
    max: Optional[float] = None
    default: Any = None
    step: Optional[float] = None
    choices: Optional[List[str]] = None
    fixed: Optional[Any] = None  # 如果设置，表示该参数只能为此值
    route: Optional[str] = None  # 特殊路由，如 web_search_route

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"supported": self.supported}
        if self.min is not None:
            d["min"] = self.min
        if self.max is not None:
            d["max"] = self.max
        if self.default is not None:
            d["default"] = self.default
        if self.step is not None:
            d["step"] = self.step
        if self.choices is not None:
            d["choices"] = self.choices
        if self.fixed is not None:
            d["fixed"] = self.fixed
        if self.route is not None:
            d["route"] = self.route
        return d


# ---------------------------------------------------------------------------
# 核心函数
# ---------------------------------------------------------------------------

def _normalize_override_value(value: Any, param_name: str) -> CapabilityResult:
    """将简化的覆盖值转换为 CapabilityResult"""
    if isinstance(value, bool):
        spec = PARAM_SPECS.get(param_name, {})
        if value:
            return CapabilityResult(
                supported=True,
                min=spec.get("min"),
                max=spec.get("max"),
                default=spec.get("default"),
                step=spec.get("step"),
                choices=spec.get("choices"),
            )
        return CapabilityResult(supported=False)

    if isinstance(value, dict):
        spec = PARAM_SPECS.get(param_name, {})
        fixed = value.get("fixed")
        route = value.get("web_search_route") or value.get("route")
        if fixed is not None:
            return CapabilityResult(
                supported=True,
                fixed=fixed,
                default=fixed,
                min=spec.get("min"),
                max=spec.get("max"),
            )
        return CapabilityResult(
            supported=value.get("supported", True),
            min=value.get("min", spec.get("min")),
            max=value.get("max", spec.get("max")),
            default=value.get("default", spec.get("default")),
            step=value.get("step", spec.get("step")),
            choices=value.get("choices", spec.get("choices")),
            route=route,
        )

    # 其他类型，按不支持处理
    return CapabilityResult(supported=False)


def _resolve_capability(
    param_name: str,
    api_meta: Optional[Dict[str, Any]],
    model_override: Optional[Dict[str, Any]],
    provider_default: Optional[Dict[str, Any]],
    fallback: Optional[Dict[str, Any]],
) -> CapabilityResult:
    """
    按优先级合并能力来源。
    优先级: api_meta > model_override > provider_default > fallback
    """
    # 1. 接口实时元数据（如 OpenRouter supported_parameters）
    if api_meta is not None:
        supported_params = api_meta.get("supported_parameters", [])
        if supported_params and param_name in supported_params:
            spec = PARAM_SPECS.get(param_name, {})
            return CapabilityResult(
                supported=True,
                min=spec.get("min"),
                max=spec.get("max"),
                default=spec.get("default"),
                step=spec.get("step"),
                choices=spec.get("choices"),
            )
        if supported_params and param_name not in supported_params:
            return CapabilityResult(supported=False)

    # 2. 本地模型覆盖表
    if model_override is not None and param_name in model_override:
        return _normalize_override_value(model_override[param_name], param_name)

    # 3. 供应商默认
    if provider_default is not None and param_name in provider_default:
        return _normalize_override_value(provider_default[param_name], param_name)

    # 4. 安全兜底
    if fallback is not None and param_name in fallback:
        return _normalize_override_value(fallback[param_name], param_name)

    # 最终兜底：不支持
    return CapabilityResult(supported=False)


def get_model_capabilities(
    provider_id: str,
    model_name: str,
    api_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, CapabilityResult]:
    """
    获取指定模型的完整能力表。

    Args:
        provider_id: 供应商 ID
        model_name: 模型名称
        api_meta: 接口返回的原始模型元数据（可选）

    Returns:
        参数名 -> CapabilityResult 的字典
    """
    model_override = None
    provider_models = MODEL_CAPABILITY_OVERRIDES.get(provider_id, {})
    if model_name in provider_models:
        model_override = provider_models[model_name]
    else:
        # 前缀匹配（如 qwen3-xxx、deepseek-v4-xxx 变体）
        best_key = ""
        for known_model, caps in provider_models.items():
            if model_name.startswith(known_model) and len(known_model) > len(best_key):
                model_override = caps
                best_key = known_model
            elif known_model.startswith(model_name) and len(model_name) > len(best_key):
                model_override = caps
                best_key = model_name

    # 通义：未收录的 qwen* 模型沿用 qwen-plus 能力（top_k / 联网等）
    if model_override is None and provider_id == "qwen" and model_name.startswith("qwen"):
        model_override = provider_models.get("qwen-plus")
    # DeepSeek V4 变体
    if model_override is None and provider_id == "deepseek" and model_name.startswith("deepseek-v4"):
        model_override = provider_models.get("deepseek-v4-pro")

    provider_default = PROVIDER_DEFAULT_CAPS.get(provider_id)
    fallback = SAFE_FALLBACK_CAPS

    result: Dict[str, CapabilityResult] = {}
    for param_name in PARAM_SPECS.keys():
        result[param_name] = _resolve_capability(
            param_name, api_meta, model_override, provider_default, fallback
        )

    # 额外：从接口元数据收紧 max_tokens 上限（OpenRouter / OpenAI 等）
    if api_meta:
        mct = api_meta.get("max_completion_tokens")
        if mct is None and isinstance(api_meta.get("top_provider"), dict):
            mct = api_meta["top_provider"].get("max_completion_tokens")
        if mct is not None:
            mt = result.get("max_tokens")
            if mt and mt.supported:
                try:
                    mt.max = float(mct)
                except (TypeError, ValueError):
                    pass

    return result


def capabilities_to_dict(caps: Dict[str, CapabilityResult]) -> Dict[str, Dict[str, Any]]:
    """将能力表转换为可序列化的字典"""
    return {k: v.to_dict() for k, v in caps.items()}
