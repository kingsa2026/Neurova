# -*- coding: utf-8 -*-
"""AIGC 生成用量历史（SQLite）——图/视频/音频生成计数与耗时的持久统计。

对齐 usage_history 的独立建库模式（不并入 token 维度 llm_usage：AIGC 计量单位
是「张/条/秒」不是 tokens）。每次生成入账一行；写不进静默跳过（主流程零影响），
读不出回退空（诚实统计）。

表 aigc_gen_usage:
  id / ts(ISO) / usage_date(本地日) / user_id / kind(image|video|audio)
  / provider / model / protocol / status(success|failed) / items(产物数)
  / duration_ms

单例 get_aigc_usage()/reset_aigc_usage()；DB 默认 data/aigc_usage.db，
env NEUROVA_AIGC_USAGE_DB 可覆盖（测试隔离）。
"""
from __future__ import annotations

import os
import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_DB_PATH = Path("data") / "aigc_usage.db"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS aigc_gen_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    usage_date TEXT NOT NULL,
    user_id TEXT NOT NULL DEFAULT 'anonymous',
    kind TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    protocol TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'success',
    items INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER NOT NULL DEFAULT 0
)
"""

_CREATE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_aigc_usage_date ON aigc_gen_usage (usage_date)",
    "CREATE INDEX IF NOT EXISTS idx_aigc_usage_user_date ON aigc_gen_usage (user_id, usage_date)",
)


class AigcUsageHistory:
    """AIGC 生成用量账（RLock 保护，风格对齐 UsageHistory）。"""

    def __init__(self, db_path: Optional[str] = None) -> None:
        env_path = os.environ.get("NEUROVA_AIGC_USAGE_DB")
        self._db_path = Path(db_path or env_path or DEFAULT_DB_PATH)
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        # 对齐 usage_history P1-E5：常驻连接必须 check_same_thread=False +
        # isolation_level=None（autocommit）——否则端点线程写/主线程读触发
        # same-thread 限制被静默吞（record 看似 OK 实未写），且隐式事务
        # 永久不可见（统计恒 0）。
        conn = sqlite3.connect(str(self._db_path), timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.isolation_level = None
        return conn

    def _ensure_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = self._connect()
            # 多语句 executescript 必须以分号分隔（缺分隔符会静默建表失败）
            self._conn.executescript(
                _CREATE_TABLE + ";\n" + ";\n".join(_CREATE_INDEXES) + ";")
        return self._conn

    def record(self, *, kind: str, user_id: str = "", provider: str = "",
               model: str = "", protocol: str = "", status: str = "success",
               items: int = 1, duration_ms: float = 0.0) -> None:
        """入账一次生成（写失败只 debug 级静默，不影响主流程）。"""
        try:
            now = datetime.now()
            with self._lock:
                conn = self._ensure_conn()
                conn.execute(
                    "INSERT INTO aigc_gen_usage (ts, usage_date, user_id, kind,"
                    " provider, model, protocol, status, items, duration_ms)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (now.isoformat(timespec="seconds"), now.date().isoformat(),
                     user_id or "anonymous", kind, provider or "", model or "",
                     protocol or "", status or "success", max(0, int(items)),
                     max(0, int(duration_ms))))
        except Exception:  # noqa: BLE001 — 统计写入永不阻断生成主流程
            pass

    def summary(self, user_id: Optional[str] = None, days: int = 30) -> Dict[str, Any]:
        """近 N 天聚合：按天/按类型/总计（failed 单列）。"""
        try:
            with self._lock:
                conn = self._ensure_conn()
                since = (date.today() - timedelta(days=max(1, days) - 1)).isoformat()
                where = "WHERE usage_date >= ?"
                args: List[Any] = [since]
                if user_id:
                    where += " AND user_id = ?"
                    args.append(user_id)
                daily = [dict(r) for r in conn.execute(
                    f"SELECT usage_date, kind, status, SUM(items) AS items,"
                    f" COUNT(*) AS calls, SUM(duration_ms) AS duration_ms"
                    f" FROM aigc_gen_usage {where}"
                    f" GROUP BY usage_date, kind, status ORDER BY usage_date", args)]
                total = conn.execute(
                    f"SELECT kind, status, SUM(items) AS items, COUNT(*) AS calls,"
                    f" SUM(duration_ms) AS duration_ms FROM aigc_gen_usage {where}"
                    f" GROUP BY kind, status", args).fetchall()
            return {
                "daily": daily,
                "totals": [dict(r) for r in total],
                "days": days,
            }
        except Exception:  # noqa: BLE001 — 读失败回空账（诚实空）
            return {"daily": [], "totals": [], "days": days}

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:  # noqa: BLE001
                    pass
                self._conn = None


_instance: Optional[AigcUsageHistory] = None
_instance_lock = threading.Lock()


def get_aigc_usage() -> AigcUsageHistory:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = AigcUsageHistory()
    return _instance


def reset_aigc_usage() -> None:
    global _instance
    with _instance_lock:
        if _instance is not None:
            _instance.close()
        _instance = None
