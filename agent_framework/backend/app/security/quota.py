"""
默认模型每日配额（SQLite 计数）。

设计：
- 仅当用户使用「平台默认 Key」（即未提供 BYOK）时才计数。
- 按 client_ip + UTC 日期作为主键累加。
- 超过 settings.default_model_daily_quota 后拒绝。
- BYOK 用户不受此限制（自付费）。

存储位置：与 sv_database / llm_config 同目录的 quota.db。
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DATA_DIR = os.path.join(_BACKEND_DIR, "data")
_DB_PATH = os.path.join(_DATA_DIR, "quota.db")


class DailyQuotaTracker:
    """每日配额计数器（线程安全）。"""

    def __init__(self, db_path: str = _DB_PATH) -> None:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5.0, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_quota (
                    ip          TEXT NOT NULL,
                    day_utc     TEXT NOT NULL,
                    used        INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (ip, day_utc)
                )
                """
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_quota_day ON daily_quota(day_utc)"
            )

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def get_used(self, ip: str) -> int:
        if not ip:
            return 0
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT used FROM daily_quota WHERE ip=? AND day_utc=?",
                (ip, self._today()),
            ).fetchone()
            return int(row[0]) if row else 0

    def get_remaining(self, ip: str) -> int:
        quota = settings.default_model_daily_quota
        if quota <= 0:
            return 10**9  # 视为不限
        return max(0, quota - self.get_used(ip))

    def try_consume(self, ip: str, n: int = 1) -> bool:
        """
        尝试消费 n 次配额。返回 True 表示通过（已 +n），False 表示已超额。
        quota<=0 表示不限制，永远返回 True。
        """
        quota = settings.default_model_daily_quota
        if quota <= 0:
            return True
        if not ip:
            return True
        day = self._today()
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT used FROM daily_quota WHERE ip=? AND day_utc=?",
                (ip, day),
            ).fetchone()
            used = int(row[0]) if row else 0
            if used + n > quota:
                return False
            c.execute(
                """
                INSERT INTO daily_quota(ip, day_utc, used) VALUES(?, ?, ?)
                ON CONFLICT(ip, day_utc) DO UPDATE SET used = used + excluded.used
                """,
                (ip, day, n),
            )
            c.commit()
            return True

    def cleanup_old(self, keep_days: int = 30) -> int:
        """删除 keep_days 之前的旧记录，返回删除条数。"""
        with self._lock, self._conn() as c:
            cur = c.execute(
                "DELETE FROM daily_quota WHERE day_utc < date('now', ?)",
                (f"-{int(keep_days)} day",),
            )
            c.commit()
            return cur.rowcount or 0


quota_tracker: Optional[DailyQuotaTracker] = None


def init_quota_tracker() -> DailyQuotaTracker:
    global quota_tracker
    if quota_tracker is None:
        quota_tracker = DailyQuotaTracker()
    return quota_tracker
