"""
安装根目录解析（开源 / 任意路径部署）。

优先级：
1. 环境变量 CHICKENSV_ROOT 或 PROJECT_AI3_ROOT
2. 自动推断：含 agent_framework 与 mcp 的仓库根目录
"""

from __future__ import annotations

import os
from pathlib import Path
from functools import lru_cache


@lru_cache(maxsize=1)
def get_install_root() -> Path:
    for key in ("CHICKENSV_ROOT", "PROJECT_AI3_ROOT"):
        raw = os.environ.get(key, "").strip()
        if raw:
            return Path(raw).expanduser().resolve()

    # .../agent_framework/backend/app/paths.py -> repo root = parents[3]
    here = Path(__file__).resolve()
    if len(here.parents) >= 4:
        candidate = here.parents[3]
        if (candidate / "agent_framework").is_dir() and (candidate / "mcp").is_dir():
            return candidate
    if len(here.parents) >= 3:
        return here.parents[2].parent
    return Path.cwd().resolve()


def data_dir() -> Path:
    return get_install_root() / "data"


def refpanel_dir() -> Path:
    return get_install_root() / "refpanel"


def annotation_dir() -> Path:
    return get_install_root() / "annotation"


def workspace_dir() -> Path:
    return get_install_root() / "agent_framework" / "data"
