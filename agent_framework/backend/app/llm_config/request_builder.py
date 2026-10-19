"""
请求构建模块

根据模型能力表构造请求 payload，避免传错参数。
"""

import logging
from typing import Dict, Any, Optional, List

from .capabilities import (
    get_model_capabilities,
    CapabilityResult,
    capabilities_to_dict,
)
from .providers import ProviderRegistry

logger = logging.getLogger(__name__)


def sanitize_deepseek_chat_messages(
    messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    DeepSeek 兼容 OpenAI 格式，但对 tool 轮次较敏感：
    - assistant 且含 tool_calls 时，空 content 用 null 更符合文档（string nullable）。
    - tool 消息示例中仅使用 role / tool_call_id / content，去掉 name 避免网关校验差异。
    """
    out: List[Dict[str, Any]] = []
    for msg in messages:
        m = dict(msg)
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            content = m.get("content")
            if content is None or (isinstance(content, str) and content.strip() == ""):
                m["content"] = None
        elif role == "tool":
            m.pop("name", None)
        out.append(m)
    return out


def filter_params_by_capabilities(
    params: Dict[str, Any],
    capabilities: Dict[str, CapabilityResult],
) -> Dict[str, Any]:
    """
    根据能力表过滤请求参数，只保留支持的参数。

    同时会自动修正固定值参数（如 temperature fixed=1）。
    """
    filtered: Dict[str, Any] = {}

    for key, value in params.items():
        if key == "model" or key == "messages" or key == "stream" or key == "tools" or key == "tool_choice":
            # 核心参数始终保留
            filtered[key] = value
            continue

        cap = capabilities.get(key)
        if not cap:
            # 未知参数：保留但打日志（兼容未来参数）
            logger.debug(f"未知参数 '{key}'，按原样保留")
            filtered[key] = value
            continue

        if not cap.supported:
            logger.debug(f"参数 '{key}' 不被当前模型支持，已过滤")
            continue

        if cap.fixed is not None:
            # 固定值参数，强制修正
            if value != cap.fixed:
                logger.warning(
                    f"参数 '{key}' 当前模型要求固定值 {cap.fixed}，"
                    f"原值 {value} 已被修正"
                )
            filtered[key] = cap.fixed
            continue

        # 范围校验与修正
        if cap.min is not None and isinstance(value, (int, float)):
            if value < cap.min:
                logger.warning(
                    f"参数 '{key}' 值 {value} 低于最小值 {cap.min}，已修正"
                )
                value = cap.min
        if cap.max is not None and isinstance(value, (int, float)):
            if value > cap.max:
                logger.warning(
                    f"参数 '{key}' 值 {value} 超过最大值 {cap.max}，已修正"
                )
                value = cap.max

        filtered[key] = value

    return filtered


def build_request_payload(
    provider_id: str,
    model_name: str,
    messages: List[Dict[str, Any]],
    params: Dict[str, Any],
    tools: Optional[List[Dict[str, Any]]] = None,
    stream: bool = False,
    api_meta: Optional[Dict[str, Any]] = None,
    enable_reasoning: bool = False,
) -> Dict[str, Any]:
    """
    构建完整的请求 payload，自动根据能力表过滤参数。

    Args:
        provider_id: 供应商 ID
        model_name: 模型名称
        messages: 消息列表
        params: 用户传入的参数（temperature, max_tokens 等）
        tools: 工具定义列表
        stream: 是否流式
        api_meta: 接口元数据（可选）
        enable_reasoning: 是否希望使用推理/思考链（仅部分模型有意义）

    Returns:
        过滤后的请求 payload
    """
    capabilities = get_model_capabilities(provider_id, model_name, api_meta)

    # 基础 payload（DeepSeek 对消息体做轻量规范化）
    msg_list: List[Dict[str, Any]] = (
        sanitize_deepseek_chat_messages([dict(m) for m in messages])
        if provider_id == "deepseek"
        else messages
    )
    payload: Dict[str, Any] = {
        "model": model_name,
        "messages": msg_list,
        "stream": stream,
    }

    # 合并用户参数
    user_params = dict(params)
    user_params.pop("model", None)
    user_params.pop("messages", None)
    user_params.pop("stream", None)

    # 特殊：联网搜索参数转换
    # 目前只有 Qwen (百炼) 的兼容接口通过 enable_search 参数支持联网搜索
    # 其他供应商（如 Kimi）可能通过 tools 或其他方式支持，不在此自动注入
    enable_search = user_params.pop("enable_online_search", False)
    if enable_search and provider_id == "qwen":
        payload["enable_search"] = True

    # 过滤参数
    filtered = filter_params_by_capabilities(user_params, capabilities)
    payload.update(filtered)

    # 添加工具
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    # DeepSeek V4：thinking 默认开启；若发生了 tool call，后续轮必须把上一轮 assistant 的
    # reasoning_content 原样回传，否则官方会返回 400。当前 Agent 流式/记忆未采集该字段，
    # 故在「请求中带 tools」或用户关闭推理时，显式关闭 thinking，保证工具链可用。
    if provider_id == "deepseek" and model_name.startswith("deepseek-v4"):
        if tools is not None or not enable_reasoning:
            payload["thinking"] = {"type": "disabled"}

    logger.debug(
        f"构建请求 [{provider_id}/{model_name}] 参数: "
        f"{ {k: v for k, v in payload.items() if k not in ('messages',)} }"
    )
    return payload


def get_safe_params_for_probe(provider_id: str, model_name: str) -> Dict[str, Any]:
    """
    获取用于参数探测的安全参数组合。
    使用 build_request_payload 过滤，确保只发送该模型支持的参数。
    """
    params = {
        "temperature": 0.7,
        "max_tokens": 1,
        "top_p": 0.95,
    }
    return build_request_payload(
        provider_id=provider_id,
        model_name=model_name,
        messages=[{"role": "user", "content": "Hi"}],
        params=params,
        stream=False,
    )
