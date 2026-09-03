"""Token 用量持久化历史（SQLite）——使用统计看板的唯一历史数据源

为什么单独建库不并进 usage_accounting:
- usage_accounting 是进程内内存单例（重启归零、无时间戳/用户维度），
  语义是"对账与成本核算"，保持纯内存不影响其既有契约与测试。
- 持久化历史是"按天/按模型/按用户聚合"的新维度：每次 LLM 调用入账一行，
  写不进去就静默跳过（主流程零影响），读不出来就回退空/0（诚实统计）。

表 llm_usage:
  id / ts(ISO 时间戳) / usage_date(本地日 YYYY-MM-DD) / user_id(默认 anonymous)
  / model / provider / prompt_tokens / completion_tokens / total_tokens / estimated

单例 get_usage_history()/reset_usage_history()（对齐 usage_accounting 模式）；
DB 路径默认 data/usage_history.db，env NEUROVA_USAGE_HISTORY_DB 可覆盖（测试隔离）。
"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

DEFAULT_DB_PATH = Path("data") / "usage_history.db"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS llm_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    usage_date TEXT NOT NULL,
    user_id TEXT NOT NULL DEFAULT 'anonymous',
    model TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    estimated INTEGER NOT NULL DEFAULT 0
)
"""

_CREATE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_llm_usage_date ON llm_usage (usage_date)",
    "CREATE INDEX IF NOT EXISTS idx_llm_usage_user_date ON llm_usage (user_id, usage_date)",
    "CREATE INDEX IF NOT EXISTS idx_llm_usage_user_model ON llm_usage (user_id, model)",
)


class UsageHistoryStore:
    """token 用量历史落盘 + 聚合查询（线程安全，失败静默）。"""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = (
            db_path
            or os.environ.get("NEUROVA_USAGE_HISTORY_DB")
            or str(DEFAULT_DB_PATH)
        )
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        try:
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                with self._connect() as conn:
                    conn.execute(_CREATE_TABLE)
                    for index_sql in _CREATE_INDEXES:
                        conn.execute(index_sql)
        except Exception:
            pass  # 落盘不可用 → 内存记账主流程不受影响

    # ── 写入 ────────────────────────────────────────────────────────────────

    def record(
        self,
        *,
        ts: Optional[str] = None,
        usage_date: Optional[str] = None,
        user_id: str = "anonymous",
        model: str,
        provider: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        estimated: bool = False,
    ) -> None:
        """记一次 LLM 调用（一行）。任何失败都静默——仅为附加统计。"""
        prompt_tokens = int(prompt_tokens or 0)
        completion_tokens = int(completion_tokens or 0)
        total = prompt_tokens + completion_tokens
        if ts is None:
            ts = datetime.now().isoformat(timespec="seconds")
        if usage_date is None:
            usage_date = date.today().isoformat()
        try:
            with self._lock:
                with self._connect() as conn:
                    conn.execute(
                        """
                        INSERT INTO llm_usage (
                            ts, usage_date, user_id, model, provider,
                            prompt_tokens, completion_tokens, total_tokens, estimated
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            ts,
                            usage_date,
                            str(user_id or "anonymous"),
                            str(model or "unknown"),
                            str(provider or ""),
                            prompt_tokens,
                            completion_tokens,
                            total,
                            1 if estimated else 0,
                        ),
                    )
        except Exception:
            pass

    # ── 聚合查询（异常回退空/0，不抛） ─────────────────────────────────────

    def _where(self, user_id: Optional[str]) -> Tuple[str, List[Any]]:
        if user_id:
            return "WHERE user_id = ?", [str(user_id)]
        return "", []

    def daily_totals(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """按天聚合 [{usage_date, tokens, calls}]，按日期升序（全历史）。"""
        try:
            where, params = self._where(user_id)
            with self._lock:
                with self._connect() as conn:
                    rows = conn.execute(
                        f"""
                        SELECT usage_date,
                               SUM(total_tokens) AS tokens,
                               COUNT(*) AS calls
                        FROM llm_usage
                        {where}
                        GROUP BY usage_date
                        ORDER BY usage_date
                        """,
                        params,
                    ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def daily_by_model(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """按天×模型聚合 [{usage_date, model, tokens}]，按日-模型升序。"""
        try:
            where, params = self._where(user_id)
            with self._lock:
                with self._connect() as conn:
                    rows = conn.execute(
                        f"""
                        SELECT usage_date, model,
                               SUM(total_tokens) AS tokens
                        FROM llm_usage
                        {where}
                        GROUP BY usage_date, model
                        ORDER BY usage_date, model
                        """,
                        params,
                    ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def model_totals(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """按模型累计 [{model, tokens, calls}]，按模型名排序。"""
        try:
            where, params = self._where(user_id)
            with self._lock:
                with self._connect() as conn:
                    rows = conn.execute(
                        f"""
                        SELECT model,
                               SUM(total_tokens) AS tokens,
                               COUNT(*) AS calls
                        FROM llm_usage
                        {where}
                        GROUP BY model
                        ORDER BY model
                        """,
                        params,
                    ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def peak_daily(self, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """全历史单日 token 峰值（使用统计的"峰值 Token 数"）；空库返回 None。"""
        try:
            where, params = self._where(user_id)
            with self._lock:
                with self._connect() as conn:
                    row = conn.execute(
                        f"""
                        SELECT usage_date, SUM(total_tokens) AS tokens
                        FROM llm_usage
                        {where}
                        GROUP BY usage_date
                        ORDER BY tokens DESC, usage_date DESC
                        LIMIT 1
                        """,
                        params,
                    ).fetchone()
            return dict(row) if row else None
        except Exception:
            return None

    def total(self, user_id: Optional[str] = None) -> Dict[str, int]:
        """全历史累计 {tokens, calls}；异常回退零态。"""
        try:
            where, params = self._where(user_id)
            with self._lock:
                with self._connect() as conn:
                    row = conn.execute(
                        f"""
                        SELECT COALESCE(SUM(total_tokens), 0) AS tokens,
                               COUNT(*) AS calls
                        FROM llm_usage
                        {where}
                        """,
                        params,
                    ).fetchone()
            return {"tokens": int(row["tokens"] or 0), "calls": int(row["calls"] or 0)}
        except Exception:
            return {"tokens": 0, "calls": 0}


def compute_streaks(active_dates: Iterable[str], today: date) -> Tuple[int, int]:
    """活跃日期集 → (当前连续天数, 最长连续天数)。

    当前连续：锚点=今天；今天未活跃则回退昨天；锚点不在活跃集 → 0。
    最长连续：全历史最长的连续活跃日 run。
    输入容忍乱序/重复/非法字符串（忽略）。
    """
    parsed: set = set()
    for d in active_dates:
        try:
            if isinstance(d, str):
                parsed.add(datetime.strptime(d[:10], "%Y-%m-%d").date())
            else:  # date/datetime 对象
                parsed.add(getattr(d, "date", lambda: d)())
        except Exception:
            continue
    if not parsed:
        return (0, 0)

    ordered = sorted(parsed)
    longest = 1
    run = 1
    for prev, cur in zip(ordered, ordered[1:]):
        if (cur - prev).days == 1:
            run += 1
            if run > longest:
                longest = run
        else:
            run = 1

    anchor = today if today in parsed else today - timedelta(days=1)
    if anchor not in parsed:
        return (0, longest)
    current = 1
    cursor = anchor
    while (cursor - timedelta(days=1)) in parsed:
        current += 1
        cursor -= timedelta(days=1)
    return (current, longest)


# ── 单例（对齐 usage_accounting 模式） ─────────────────────────────────────

_usage_history: Optional[UsageHistoryStore] = None
_usage_lock = threading.Lock()


def get_usage_history() -> UsageHistoryStore:
    global _usage_history
    if _usage_history is None:
        with _usage_lock:
            if _usage_history is None:
                _usage_history = UsageHistoryStore()
    return _usage_history


def reset_usage_history() -> None:
    global _usage_history
    with _usage_lock:
        _usage_history = None
