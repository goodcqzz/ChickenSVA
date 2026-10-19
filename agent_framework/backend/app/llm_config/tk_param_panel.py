"""
参数面板生成模块

提供动态参数面板的元数据生成，可用于 Tkinter GUI 或 Web 前端。

核心思路：
- 根据能力表生成控件定义列表
- 每个控件包含：类型、标签、范围、默认值、是否禁用等
- 前端/桌面端根据控件定义渲染界面
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

from .capabilities import (
    get_model_capabilities,
    CapabilityResult,
    capabilities_to_dict,
)


@dataclass
class ParamControl:
    """参数控件定义"""
    param_name: str
    label: str
    label_zh: str
    control_type: str  # slider, number, switch, select, text
    enabled: bool = True
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    default: Any = None
    choices: Optional[List[str]] = None
    fixed: Optional[Any] = None
    help_text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "param_name": self.param_name,
            "label": self.label,
            "label_zh": self.label_zh,
            "control_type": self.control_type,
            "enabled": self.enabled,
            "default": self.default,
            "help_text": self.help_text,
        }
        if self.min is not None:
            d["min"] = self.min
        if self.max is not None:
            d["max"] = self.max
        if self.step is not None:
            d["step"] = self.step
        if self.choices is not None:
            d["choices"] = self.choices
        if self.fixed is not None:
            d["fixed"] = self.fixed
        return d


# 参数UI元数据
_PARAM_UI_META: Dict[str, Dict[str, Any]] = {
    "temperature": {
        "label": "Temperature",
        "label_zh": "温度",
        "control_type": "slider",
        "help_text": "控制输出随机性。值越低越确定，值越高越创造性。",
    },
    "top_p": {
        "label": "Top P",
        "label_zh": "采样阈值",
        "control_type": "number",
        "help_text": "核采样阈值。与 Temperature 建议只调其中一个。",
    },
    "top_k": {
        "label": "Top K",
        "label_zh": "Top K",
        "control_type": "number",
        "help_text": "仅考虑概率最高的 K 个 token。",
    },
    "max_tokens": {
        "label": "Max Tokens",
        "label_zh": "最大长度",
        "control_type": "number",
        "help_text": "生成内容的最大 token 数。",
    },
    "frequency_penalty": {
        "label": "Frequency Penalty",
        "label_zh": "频率惩罚",
        "control_type": "number",
        "help_text": "降低重复用词的概率。",
    },
    "presence_penalty": {
        "label": "Presence Penalty",
        "label_zh": "存在惩罚",
        "control_type": "number",
        "help_text": "增加讨论新主题的概率。",
    },
    "reasoning_effort": {
        "label": "Reasoning Effort",
        "label_zh": "推理强度",
        "control_type": "select",
        "help_text": "推理模型的思考深度。",
    },
    "web_search": {
        "label": "Online Search",
        "label_zh": "联网搜索",
        "control_type": "switch",
        "help_text": "允许模型搜索互联网获取最新信息。",
    },
    "vision": {
        "label": "Vision",
        "label_zh": "视觉",
        "control_type": "readonly",
        "help_text": "模型是否支持图像输入（来自能力表，不可配置）。",
    },
}


def generate_param_controls(
    provider_id: str,
    model_name: str,
    api_meta: Optional[Dict[str, Any]] = None,
) -> List[ParamControl]:
    """
    根据模型能力表生成参数控件定义列表。

    Returns:
        控件定义列表，按预设顺序排列。
    """
    capabilities = get_model_capabilities(provider_id, model_name, api_meta)
    controls: List[ParamControl] = []

    for param_name, meta in _PARAM_UI_META.items():
        cap = capabilities.get(param_name)
        if cap is None:
            continue

        enabled = cap.supported
        default = cap.default if cap.default is not None else meta.get("default")

        control = ParamControl(
            param_name=param_name,
            label=meta["label"],
            label_zh=meta["label_zh"],
            control_type=meta["control_type"],
            enabled=enabled,
            min=cap.min,
            max=cap.max,
            step=cap.step,
            default=default,
            choices=cap.choices,
            fixed=cap.fixed,
            help_text=meta["help_text"],
        )
        controls.append(control)

    return controls


def get_param_panel_metadata(
    provider_id: str,
    model_name: str,
    api_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    获取完整的参数面板元数据（供前端使用）。

    Returns:
        {
            "provider": str,
            "model": str,
            "controls": List[Dict],
            "capabilities": Dict[str, Dict],
        }
    """
    controls = generate_param_controls(provider_id, model_name, api_meta)
    capabilities = get_model_capabilities(provider_id, model_name, api_meta)
    return {
        "provider": provider_id,
        "model": model_name,
        "controls": [c.to_dict() for c in controls],
        "capabilities": capabilities_to_dict(capabilities),
    }
