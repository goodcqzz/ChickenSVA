"""
LLM 统一 Schema

前后端共享的配置模型、请求/响应模型。
目标是消除 base.py / llm_config_store.py / api/llm.py 中重复且不兼容的定义。
"""

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, model_validator


class LLMSettings(BaseModel):
    """LLM 配置设置 — 前后端统一的数据模型"""
    provider: str = Field(default="deepseek", description="供应商ID")
    model: str = Field(default="deepseek-v4-flash", description="模型ID")
    api_key: Optional[str] = Field(default=None, description="API密钥")
    temperature: float = Field(default=0.7, ge=0, le=2)
    # 长上下文模型（如 Kimi 256k）的元数据会超过 200k，与前端/目录一致放宽上限
    max_tokens: int = Field(default=8192, ge=1, le=2_097_152)
    top_p: float = Field(default=0.95, ge=0, le=1)
    top_k: Optional[int] = Field(default=None, ge=1, le=100)
    frequency_penalty: float = Field(default=0, ge=-2, le=2)
    presence_penalty: float = Field(default=0, ge=-2, le=2)
    enable_online_search: bool = Field(default=False)
    enable_reasoning: bool = Field(default=False)
    reasoning_effort: Optional[str] = Field(default=None)
    base_url: Optional[str] = Field(default=None, description="自定义endpoint")
    system_prompt: Optional[str] = Field(default=None)

    @model_validator(mode="before")
    @classmethod
    def sanitize_numeric_fields(cls, data: Any) -> Any:
        """
        前端 Element Plus 等控件可能提交空字符串或非严格数字类型，避免 422。
        """
        if not isinstance(data, dict):
            return data
        d = dict(data)

        def blank_to_none(v: Any) -> bool:
            return v is None or v == "" or (isinstance(v, str) and v.strip() == "")

        # top_k：空表示未使用
        if "top_k" in d and blank_to_none(d.get("top_k")):
            d["top_k"] = None
        elif isinstance(d.get("top_k"), str) and not blank_to_none(d.get("top_k")):
            try:
                d["top_k"] = int(float(str(d["top_k"]).strip()))
            except (TypeError, ValueError):
                d["top_k"] = None

        def coerce_float(key: str, default: float) -> None:
            if key not in d:
                return
            v = d[key]
            if blank_to_none(v):
                d[key] = default
                return
            if isinstance(v, (int, float)):
                d[key] = float(v)
                return
            if isinstance(v, str):
                try:
                    d[key] = float(v.strip())
                except (TypeError, ValueError):
                    d[key] = default

        def coerce_int(key: str, default: int) -> None:
            if key not in d:
                return
            v = d[key]
            if blank_to_none(v):
                d[key] = default
                return
            if isinstance(v, bool):
                d[key] = default
                return
            if isinstance(v, int):
                d[key] = v
                return
            if isinstance(v, float):
                d[key] = int(v)
                return
            if isinstance(v, str):
                try:
                    d[key] = int(float(v.strip()))
                except (TypeError, ValueError):
                    d[key] = default

        coerce_float("temperature", 0.7)
        coerce_int("max_tokens", 2048)
        coerce_float("top_p", 0.95)
        coerce_float("frequency_penalty", 0.0)
        coerce_float("presence_penalty", 0.0)
        return d

    class Config:
        json_schema_extra = {
            "example": {
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "api_key": "sk-xxx",
                "temperature": 0.7,
                "max_tokens": 8192,
                "top_p": 0.95,
                "enable_online_search": False,
                "enable_reasoning": False,
            }
        }

    def to_backend_config(self) -> Dict[str, Any]:
        """转换为后端 LLMConfig 构造用的 dict"""
        return {
            "provider": self.provider,
            "model": self.model,
            "api_key": self.api_key or "",
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "frequency_penalty": self.frequency_penalty,
            "presence_penalty": self.presence_penalty,
            "enable_online_search": self.enable_online_search,
            "enable_reasoning": self.enable_reasoning,
            "system_prompt": self.system_prompt or "",
            "base_url": self.base_url,
        }


class LLMActiveConfigPublic(BaseModel):
    """服务端已保存的 LLM 配置（不含明文密钥），供前端与对话全局对齐"""

    provider: str = "deepseek"
    model: str = "deepseek-v4-flash"
    temperature: float = 0.7
    max_tokens: int = 8192
    top_p: float = 0.95
    top_k: Optional[int] = None
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    enable_online_search: bool = False
    enable_reasoning: bool = False
    reasoning_effort: Optional[str] = None
    base_url: Optional[str] = None
    api_key_configured: bool = False
    api_keys_present: Dict[str, bool] = Field(default_factory=dict)


class ModelInfoSchema(BaseModel):
    """模型信息 schema"""
    id: str
    name: str
    provider: str
    description: str = ""
    max_tokens: int = 8192
    context_window: int = 8192
    # 供应商 /models 返回的原始条目（用于能力合并，如 OpenRouter supported_parameters）
    raw_meta: Optional[Dict[str, Any]] = None


class CapabilitiesLookupRequest(BaseModel):
    """带接口元数据的能力表查询（优先合并 supported_parameters 等）"""
    provider: str
    model: str
    raw_meta: Optional[Dict[str, Any]] = Field(
        default=None,
        description="可选：来自 /models 单条模型的原始 JSON",
    )


class ProviderModelsSchema(BaseModel):
    """提供商模型列表 schema"""
    provider: str
    models: List[ModelInfoSchema]


class CapabilityParamSchema(BaseModel):
    """单个参数能力 schema"""
    supported: bool
    min: Optional[float] = None
    max: Optional[float] = None
    default: Any = None
    step: Optional[float] = None
    choices: Optional[List[str]] = None
    fixed: Optional[Any] = None
    route: Optional[str] = None


class ParamControlSchema(BaseModel):
    """参数控件定义 schema"""
    param_name: str
    label: str
    label_zh: str
    control_type: str
    enabled: bool = True
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    default: Any = None
    choices: Optional[List[str]] = None
    fixed: Optional[Any] = None
    help_text: str = ""


class CapabilitiesResponseSchema(BaseModel):
    """能力表响应 schema"""
    provider: str
    model: str
    capabilities: Dict[str, CapabilityParamSchema]
    controls: List[ParamControlSchema]
    # 是否合并了请求中传入的 raw_meta（便于前端调试）
    used_raw_meta: bool = False


class TestConnectionRequest(BaseModel):
    """测试连接请求"""
    provider: str
    model: str
    api_key: str
    base_url: Optional[str] = None


class TestConnectionResponse(BaseModel):
    """测试连接响应"""
    success: bool
    message: str
    provider: str
    model: str
    latency_ms: Optional[int] = None
    tested_params: Optional[Dict[str, Any]] = None
    actual_error: Optional[str] = None
    capabilities: Optional[Dict[str, CapabilityParamSchema]] = None


class ProviderMetaSchema(BaseModel):
    """供应商元数据 schema"""
    id: str
    name: str
    name_zh: str
    base_url: str
    supports_models_endpoint: bool = True
    default_model: str


class LLMConfigResponseSchema(BaseModel):
    """LLM配置保存响应"""
    success: bool
    message: str
    config: Optional[LLMSettings] = None
