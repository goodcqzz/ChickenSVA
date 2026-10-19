"""
LLM 配置模块

提供供应商管理、模型目录、能力表和请求构建的统一入口。
"""

from .providers import ProviderRegistry, ProviderConfig, get_provider_config
from .model_catalog import ModelCatalog, fetch_models_for_provider
from .capabilities import (
    get_model_capabilities,
    CapabilityResult,
    capabilities_to_dict,
    MODEL_CAPABILITY_OVERRIDES,
    PROVIDER_DEFAULT_CAPS,
    SAFE_FALLBACK_CAPS,
)
from .request_builder import build_request_payload, filter_params_by_capabilities, get_safe_params_for_probe
from .tk_param_panel import generate_param_controls, get_param_panel_metadata

__all__ = [
    "ProviderRegistry",
    "ProviderConfig",
    "get_provider_config",
    "ModelCatalog",
    "fetch_models_for_provider",
    "get_model_capabilities",
    "CapabilityResult",
    "capabilities_to_dict",
    "MODEL_CAPABILITY_OVERRIDES",
    "PROVIDER_DEFAULT_CAPS",
    "SAFE_FALLBACK_CAPS",
    "build_request_payload",
    "filter_params_by_capabilities",
    "get_safe_params_for_probe",
    "generate_param_controls",
    "get_param_panel_metadata",
]
