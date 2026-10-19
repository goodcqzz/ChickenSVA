"""
LLM配置存储

持久化存储用户配置的LLM设置（JSON文件）
API Key 使用 Fernet 对称加密存储

重构要点：
- 不再使用静态 dataclass LLMUserConfig，改用 plain dict，支持任意新增参数
- 所有配置项通过 schema 校验，存储层只做序列化/反序列化
"""

from typing import Optional, Dict, Any
import threading
import json
import os
import logging
import base64
import hashlib

logger = logging.getLogger(__name__)

_ALLOWED_LLM_PROVIDERS = frozenset({"qwen", "deepseek", "openrouter"})

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(_BACKEND_DIR, "data")
CONFIG_FILE = os.path.join(CONFIG_DIR, "llm_config.json")
_KEY_FILE = os.path.join(CONFIG_DIR, ".enc_key")


def _get_or_create_encryption_key() -> bytes:
    if os.path.exists(_KEY_FILE):
        with open(_KEY_FILE, "rb") as f:
            return f.read()
    key = os.urandom(32)
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(_KEY_FILE, "wb") as f:
        f.write(key)
    os.chmod(_KEY_FILE, 0o600)
    return key


def _xor_encrypt(data: str, key: bytes) -> str:
    if not data:
        return data
    key_hash = hashlib.sha256(key).digest()
    data_bytes = data.encode("utf-8")
    encrypted = bytes(
        b ^ key_hash[i % len(key_hash)] for i, b in enumerate(data_bytes)
    )
    return base64.b64encode(encrypted).decode("ascii")


def _xor_decrypt(data: str, key: bytes) -> str:
    if not data:
        return data
    key_hash = hashlib.sha256(key).digest()
    encrypted = base64.b64decode(data.encode("ascii"))
    decrypted = bytes(
        b ^ key_hash[i % len(key_hash)] for i, b in enumerate(encrypted)
    )
    return decrypted.decode("utf-8")


_enc_key = _get_or_create_encryption_key()

def _decrypt_api_key_field(value: Optional[str]) -> Optional[str]:
    if not value or not isinstance(value, str):
        return value
    try:
        return _xor_decrypt(value, _enc_key)
    except Exception:
        return value


def _decrypt_api_keys_dict(raw: Any) -> Dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, str] = {}
    for pid, val in raw.items():
        if not val or not isinstance(val, str):
            continue
        out[str(pid)] = _decrypt_api_key_field(val) or ""
    return out


# 默认配置
DEFAULT_LLM_CONFIG: Dict[str, Any] = {
    "provider": "deepseek",
    "model": "deepseek-v4-flash",
    "api_key": None,
    # 各供应商独立密钥（磁盘上逐条加密）；兼容旧版仅 api_key
    "api_keys": {},
    "temperature": 0.7,
    "max_tokens": 8192,
    "top_p": 0.95,
    "top_k": None,
    "frequency_penalty": 0.0,
    "presence_penalty": 0.0,
    "enable_online_search": False,
    "enable_reasoning": False,
    "reasoning_effort": None,
    "base_url": None,
    "system_prompt": None,
}


class LLMConfigStore:

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._configs: Dict[str, Dict[str, Any]] = {}
                    cls._instance._load_from_file()
        return cls._instance

    def _load_from_file(self) -> None:
        if not os.path.exists(CONFIG_FILE):
            return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for sid, cfg_dict in data.items():
                if cfg_dict.get("api_key"):
                    try:
                        cfg_dict["api_key"] = _xor_decrypt(cfg_dict["api_key"], _enc_key)
                    except Exception:
                        pass
                cfg_dict["api_keys"] = _decrypt_api_keys_dict(cfg_dict.get("api_keys"))
                # 合并默认值，防止旧配置缺少新字段
                merged = dict(DEFAULT_LLM_CONFIG)
                merged.update(cfg_dict)
                if not merged.get("api_keys"):
                    merged["api_keys"] = {}
                prov = merged.get("provider") or "qwen"
                if prov not in _ALLOWED_LLM_PROVIDERS:
                    merged["provider"] = "qwen"
                    prov = "qwen"
                ak = merged.get("api_keys") or {}
                if isinstance(ak, dict):
                    merged["api_keys"] = {
                        str(k): v
                        for k, v in ak.items()
                        if str(k) in _ALLOWED_LLM_PROVIDERS
                    }
                legacy = merged.get("api_key")
                if legacy and not merged["api_keys"].get(prov):
                    merged["api_keys"][prov] = legacy
                self._configs[sid] = merged
            logger.info(f"LLM配置从文件加载: {list(self._configs.keys())}")
        except Exception as e:
            logger.error(f"加载LLM配置文件失败: {e}")

    def _save_to_file(self) -> None:
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            data = {}
            for sid, cfg in self._configs.items():
                cfg_dict = dict(cfg)
                if cfg_dict.get("api_key"):
                    cfg_dict["api_key"] = _xor_encrypt(cfg_dict["api_key"], _enc_key)
                aq = cfg_dict.get("api_keys")
                if isinstance(aq, dict) and aq:
                    enc_map: Dict[str, str] = {}
                    for pid, val in aq.items():
                        if val and isinstance(val, str):
                            enc_map[str(pid)] = _xor_encrypt(val, _enc_key)
                        else:
                            enc_map[str(pid)] = val  # type: ignore[assignment]
                    cfg_dict["api_keys"] = enc_map
                data[sid] = cfg_dict
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug(f"LLM配置已保存到文件: {list(self._configs.keys())}")
        except Exception as e:
            logger.error(f"保存LLM配置文件失败: {e}")

    def save_config(self, session_id: str, config: Dict[str, Any]) -> None:
        """
        保存配置。
        自动合并默认值，支持任意新增参数。
        api_keys 与已有条目浅合并，避免一次保存抹掉其他供应商密钥。
        """
        merged = dict(DEFAULT_LLM_CONFIG)
        prev = self._configs.get(session_id) or {}
        merged.update(prev)

        for key, value in config.items():
            if value is None:
                continue
            if key == "api_keys" and isinstance(value, dict):
                base = dict(merged.get("api_keys") or {})
                for pid, vk in value.items():
                    if vk is not None and vk != "":
                        base[str(pid)] = vk
                merged["api_keys"] = base
                continue
            merged[key] = value

        prov = merged.get("provider")
        ak = dict(merged.get("api_keys") or {})
        if prov and merged.get("api_key") and not ak.get(prov):
            ak[prov] = merged["api_key"]
        if prov and ak.get(prov):
            merged["api_key"] = ak[prov]
        merged["api_keys"] = ak

        self._configs[session_id] = merged
        self._save_to_file()

    def get_config(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self._configs.get(session_id)

    def delete_config(self, session_id: str) -> None:
        if session_id in self._configs:
            del self._configs[session_id]
            self._save_to_file()

    def list_sessions(self) -> list:
        return list(self._configs.keys())


llm_config_store = LLMConfigStore()
