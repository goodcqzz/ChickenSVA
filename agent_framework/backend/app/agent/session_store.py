"""
会话历史持久化（SQLite）

将 ConversationMemory 序列化后落盘，使后端进程重启或客户端断线重连后仍能恢复上下文。
设计要点：
- 单文件 SQLite，零外部依赖；所有写操作加进程内锁，并通过 asyncio.to_thread 放到线程池，避免阻塞事件循环。
- 全部操作 best-effort：任何异常只记录日志，绝不向上抛出影响正常对话。
- 仅存对话消息（to_dict()），不存任何 API Key / LLM 配置。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class SessionStore:
    """基于 SQLite 的会话历史存储。"""

    def __init__(self, db_path: str, ttl_days: int = 7) -> None:
        self._db_path = db_path
        self._ttl_seconds = max(0, int(ttl_days)) * 86400
        self._lock = threading.Lock()
        self._ensure_dir()
        self._init_db()

    def _ensure_dir(self) -> None:
        parent = Path(self._db_path).expanduser().resolve().parent
        parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _init_db(self) -> None:
        try:
            with self._lock, self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS sessions (
                        session_id TEXT PRIMARY KEY,
                        payload    TEXT NOT NULL,
                        updated_at REAL NOT NULL
                    )
                    """
                )
                conn.commit()
        except Exception as e:  # pragma: no cover
            logger.warning("会话存储初始化失败（将禁用持久化）：%s", e)

    # ---------- 同步内部实现 ----------

    def _load_sync(self, session_id: str) -> Optional[List[Dict[str, Any]]]:
        try:
            with self._lock, self._connect() as conn:
                row = conn.execute(
                    "SELECT payload FROM sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
            if not row:
                return None
            data = json.loads(row[0])
            if isinstance(data, list):
                return data
            return None
        except Exception as e:
            logger.warning("会话加载失败 [%s]：%s", session_id, e)
            return None

    def _save_sync(self, session_id: str, messages: List[Dict[str, Any]]) -> None:
        try:
            payload = json.dumps(messages, ensure_ascii=False)
            with self._lock, self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO sessions (session_id, payload, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        payload = excluded.payload,
                        updated_at = excluded.updated_at
                    """,
                    (session_id, payload, time.time()),
                )
                conn.commit()
        except Exception as e:
            logger.warning("会话保存失败 [%s]：%s", session_id, e)

    def _delete_sync(self, session_id: str) -> None:
        try:
            with self._lock, self._connect() as conn:
                conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
                conn.commit()
        except Exception as e:
            logger.warning("会话删除失败 [%s]：%s", session_id, e)

    def _prune_sync(self) -> int:
        if self._ttl_seconds <= 0:
            return 0
        cutoff = time.time() - self._ttl_seconds
        try:
            with self._lock, self._connect() as conn:
                cur = conn.execute("DELETE FROM sessions WHERE updated_at < ?", (cutoff,))
                conn.commit()
                return cur.rowcount or 0
        except Exception as e:
            logger.warning("会话清理失败：%s", e)
            return 0

    # ---------- 异步对外接口 ----------

    async def load(self, session_id: str) -> Optional[List[Dict[str, Any]]]:
        return await asyncio.to_thread(self._load_sync, session_id)

    async def save(self, session_id: str, messages: List[Dict[str, Any]]) -> None:
        await asyncio.to_thread(self._save_sync, session_id, messages)

    async def delete(self, session_id: str) -> None:
        await asyncio.to_thread(self._delete_sync, session_id)

    async def prune(self) -> int:
        return await asyncio.to_thread(self._prune_sync)
