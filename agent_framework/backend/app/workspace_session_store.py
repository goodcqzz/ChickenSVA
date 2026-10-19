"""
对话与工作区的一对一绑定（持久化到 JSON 文件）
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

from app.config import settings

logger = logging.getLogger(__name__)

_MAP_FILE = os.path.join(settings.workspace_base_path, ".session_workspaces.json")


def _load() -> Dict[str, Dict[str, Any]]:
    if not os.path.exists(_MAP_FILE):
        return {}
    try:
        with open(_MAP_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("读取 session-workspace 映射失败: %s", exc)
        return {}


def _save(data: Dict[str, Dict[str, Any]]) -> None:
    os.makedirs(settings.workspace_base_path, exist_ok=True)
    with open(_MAP_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_workspace_for_session(session_id: str) -> Optional[Dict[str, Any]]:
    if not session_id:
        return None
    entry = _load().get(session_id)
    if not entry:
        return None
    workspace_id = entry.get("workspace_id")
    root = os.path.join(settings.workspace_base_path, workspace_id or "")
    if not workspace_id or not os.path.isdir(root):
        return None
    return entry


def bind_session_workspace(
    session_id: str,
    workspace_id: str,
    workspace_type: str,
) -> None:
    if not session_id or not workspace_id:
        return
    data = _load()
    data[session_id] = {
        "workspace_id": workspace_id,
        "workspace_type": workspace_type,
        "updated_at": datetime.utcnow().isoformat(),
    }
    _save(data)


def unbind_session(session_id: str) -> None:
    if not session_id:
        return
    data = _load()
    if session_id in data:
        del data[session_id]
        _save(data)
