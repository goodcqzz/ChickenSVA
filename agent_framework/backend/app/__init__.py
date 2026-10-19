"""
应用主模块

导出FastAPI应用实例和配置
"""

from app.config import settings
from app.main import app

__all__ = ["app", "settings"]
