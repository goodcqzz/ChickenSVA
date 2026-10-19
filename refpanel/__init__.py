#!/usr/bin/env python3
"""
参考面板模块 - 基因型填充参考面板管理
提供参考面板的发现、验证和管理功能
"""

from .panel_manager import PanelManager, PanelInfo
from .panel_validator import PanelValidator, PanelValidationResult, ValidationSeverity
from .beagle_runner import BeagleRunner, ImputationTask, ImputationStatus
from .panel_index import PanelIndex, IndexInfo

__version__ = "2.0.0"
__all__ = [
    "PanelManager",
    "PanelInfo",
    "PanelValidator",
    "PanelValidationResult",
    "ValidationSeverity",
    "BeagleRunner",
    "ImputationTask",
    "ImputationStatus",
    "PanelIndex",
    "IndexInfo"
]
