"""BYOK（用户自带 Key）判定与日志脱敏。"""

from __future__ import annotations

import json
from typing import Any, Dict


def user_brought_own_key(llm_config_dict: Dict[str, Any] | None) -> bool:
    """用户是否在 WebSocket 消息中携带了非空 API Key。"""
    if not llm_config_dict:
        return False
    for field in ("api_key", "apiKey"):
        val = llm_config_dict.get(field)
        if isinstance(val, str) and val.strip():
            return True
    return False


def redact_ws_payload_for_log(data: str, max_len: int = 200) -> str:
    """脱敏 WebSocket 消息后再写日志，避免 api_key 泄露。"""
    try:
        obj = json.loads(data)
        if not isinstance(obj, dict):
            return data[:max_len]
        payload = obj.get("payload")
        if isinstance(payload, dict):
            payload = dict(payload)
            llm_cfg = payload.get("llm_config")
            if isinstance(llm_cfg, dict):
                llm_cfg = dict(llm_cfg)
                for key in ("api_key", "apiKey"):
                    if llm_cfg.get(key):
                        llm_cfg[key] = "***"
                payload["llm_config"] = llm_cfg
            obj = {**obj, "payload": payload}
        return json.dumps(obj, ensure_ascii=False)[:max_len]
    except (json.JSONDecodeError, TypeError):
        return data[:max_len]
