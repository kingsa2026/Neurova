"""llmCostStore — LLM 成本账本的 SQLite 持久层

Neurova 落地纪律（对齐 core/provider_usage.py 惯例）：
- **默认关**：install_llm_cost_store() 显式装配才落盘；未装配时零开销、
  零行为变化，副路径绝不阻断 agent 主流程。
- 落盘 llm_cost SQLite 表（llm_calls 明细 + llm_calls_rollup 小时聚合），
  env NEUROVA_LLM_COST_DB 可覆盖（测试隔离）。任何失败静默降级——
  成本统计是可观测副路径，不是对话关键路径。
- 短连接走 core.database.short_transaction（ADR 0014：成功提交/异常回滚+归还）。

设计说明：本模块取代此前基于 PostgreSQL/asyncpg 假设的实现，回归系统一
SQLite 技术栈，确保服务器启动不再因缺失驱动而中断。
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.core.data_root import get_data_root

logger = get_logger(__name__)

def defaultDbPath() -> Path:
    """默认库落点：数据根下的绝对路径（原值 `Path("data")` 随 CWD 漂移）。"""
    return get_data_root() / "llm_cost.db"

# llm_calls：每笔 LLM 调用记账（明细账）
_CREATE_CALLS = """
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    turn_id TEXT,
    session_id TEXT,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    direction TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    cost REAL NOT NULL DEFAULT 0.0,
    called_at TEXT NOT NULL
)
"""
_CREATE_CALLS_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_calls_ts ON llm_calls (called_at)"
)
_CREATE_CALLS_AGENT_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_calls_agent ON llm_calls (agent_id, called_at)"
)

# llm_calls_rollup：按 (agent, hour, provider, model) 预聚合，加速看板查询
_CREATE_ROLLUP = """
CREATE TABLE IF NOT EXISTS llm_calls_rollup (
    agent_id TEXT NOT NULL,
    hour TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    total_input INTEGER NOT NULL DEFAULT 0,
    total_output INTEGER NOT NULL DEFAULT 0,
    total_cost REAL NOT NULL DEFAULT 0.0,
    call_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (agent_id, hour, provider, model)
)
"""


class LlmCostStore:
    """LLM 成本账本存储（显式 install，默认关，SQLite 落盘）。"""

    _instance: Optional["LlmCostStore"] = None
    _instance_lock = threading.Lock()

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = (
            db_path
            or os.environ.get("NEUROVA_LLM_COST_DB")
            or str(defaultDbPath())
        )
        self._lock = threading.RLock()
        self._init_db()

    # ── install/uninstall（默认关门面） ──────────────────────────────────

    @classmethod
    def install(cls, db_path: Optional[str] = None) -> "LlmCostStore":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls(db_path)
        return cls._instance

    @classmethod
    def uninstall(cls) -> None:
        with cls._instance_lock:
            cls._instance = None

    @classmethod
    def get_installed(cls) -> Optional["LlmCostStore"]:
        with cls._instance_lock:
            return cls._instance

    # ── 连接与初始化 ──────────────────────────────────────────────────────

    @contextmanager
    def _connect(self):
        from neurova.core.database import short_transaction

        with short_transaction(str(self._db_path)) as conn:
            yield conn

    def _init_db(self) -> None:
        try:
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            with self._lock, self._connect() as conn:
                conn.execute(_CREATE_CALLS)
                conn.execute(_CREATE_CALLS_INDEX)
                conn.execute(_CREATE_CALLS_AGENT_INDEX)
                conn.execute(_CREATE_ROLLUP)
        except Exception as e:  # noqa: BLE001 - 初始化失败降级，绝不抛出
            logger.debug("llm_cost DB 初始化失败（统计副路径降级）: %s", e)

    # ── 写入 ──────────────────────────────────────────────────────────────

    def record_call(
        self,
        call_id: str,
        agent_id: str,
        provider: str,
        model: str,
        direction: str,
        input_tokens: int,
        output_tokens: int,
        cost: float,
        turn_id: Optional[str] = None,
        session_id: Optional[str] = None,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        called_at: Optional[datetime] = None,
    ) -> bool:
        """记录一笔 LLM 调用。失败静默返回 False（不阻断主流程）。"""
        ts = (called_at or datetime.now()).isoformat(timespec="seconds")
        try:
            with self._lock, self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO llm_calls (
                        call_id, agent_id, turn_id, session_id,
                        provider, model, direction,
                        input_tokens, output_tokens,
                        cache_read_tokens, cache_write_tokens,
                        cost, called_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        call_id,
                        agent_id,
                        turn_id,
                        session_id,
                        provider,
                        model,
                        direction,
                        int(input_tokens or 0),
                        int(output_tokens or 0),
                        int(cache_read_tokens or 0),
                        int(cache_write_tokens or 0),
                        float(cost or 0.0),
                        ts,
                    ),
                )
            return True
        except Exception as e:  # noqa: BLE001 - 落盘失败降级
            logger.debug("llm_cost 落盘失败: %s", e)
            return False

    # ── 小时聚合（rollup） ───────────────────────────────────────────────

    def rollup_hour(self, hour: datetime) -> int:
        """把指定小时窗口内的 llm_calls 聚合进 llm_calls_rollup。

        hour 为该小时起点（分/秒归零）。返回受影响聚合行数。
        SQLite 用 strftime 截断小时、INSERT..SELECT..GROUP BY 做聚合，
        以 ON CONFLICT DO UPDATE 实现幂等 upsert。
        """
        hour_start = hour.replace(minute=0, second=0, microsecond=0)
        hour_end = hour_start + timedelta(hours=1)
        start = hour_start.isoformat(timespec="seconds")
        end = hour_end.isoformat(timespec="seconds")
        hour_key = hour_start.strftime("%Y-%m-%dT%H:00:00")
        try:
            with self._lock, self._connect() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO llm_calls_rollup (
                        agent_id, hour, provider, model,
                        total_input, total_output, total_cost, call_count
                    )
                    SELECT
                        agent_id,
                        ?,
                        provider,
                        model,
                        SUM(input_tokens),
                        SUM(output_tokens),
                        SUM(cost),
                        COUNT(*)
                    FROM llm_calls
                    WHERE called_at >= ? AND called_at < ?
                    GROUP BY agent_id, provider, model
                    ON CONFLICT(agent_id, hour, provider, model) DO UPDATE SET
                        total_input = excluded.total_input,
                        total_output = excluded.total_output,
                        total_cost = excluded.total_cost,
                        call_count = excluded.call_count
                    """,
                    (hour_key, start, end),
                )
                return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        except Exception as e:  # noqa: BLE001 - 聚合失败降级
            logger.debug("llm_cost rollup 失败: %s", e)
            return 0

    # ── 查询（看板/报表） ────────────────────────────────────────────────

    def query_rollup_since(self, since_iso: str) -> List[Dict[str, Any]]:
        try:
            with self._lock, self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT agent_id, hour, provider, model,
                           total_input, total_output, total_cost, call_count
                    FROM llm_calls_rollup
                    WHERE hour >= ?
                    ORDER BY hour DESC
                    """,
                    (since_iso,),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def query_hourly_trend(self, hours: int = 24) -> List[Dict[str, Any]]:
        """近 N 小时成本趋势（走 rollup，快）。"""
        since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:00:00")
        try:
            with self._lock, self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT hour,
                           SUM(total_cost)  AS total_cost,
                           SUM(total_input) AS total_input,
                           SUM(total_output) AS total_output,
                           SUM(call_count)  AS call_count
                    FROM llm_calls_rollup
                    WHERE hour >= ?
                    GROUP BY hour
                    ORDER BY hour DESC
                    """,
                    (since,),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def query_daily_cost(self, days: int = 30) -> List[Dict[str, Any]]:
        """近 N 天每日成本（走明细账，保证 rollup 未跑时仍有数据）。"""
        since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        try:
            with self._lock, self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT substr(called_at, 1, 10) AS date,
                           SUM(cost)        AS total_cost,
                           SUM(input_tokens) AS total_input,
                           SUM(output_tokens) AS total_output,
                           COUNT(*)         AS call_count
                    FROM llm_calls
                    WHERE called_at >= ?
                    GROUP BY date
                    ORDER BY date DESC
                    """,
                    (since,),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def current_hour_summary(self) -> Dict[str, Any]:
        """当前小时成本概览（走明细账，实时准确）。"""
        hour_start = datetime.now().replace(minute=0, second=0, microsecond=0)
        start = hour_start.isoformat(timespec="seconds")
        try:
            with self._lock, self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT COALESCE(SUM(cost),0)         AS total_cost,
                           COALESCE(SUM(input_tokens),0) AS total_input,
                           COALESCE(SUM(output_tokens),0) AS total_output,
                           COUNT(DISTINCT agent_id)      AS active_agents
                    FROM llm_calls
                    WHERE called_at >= ?
                    """,
                    (start,),
                ).fetchone()
            return dict(row) if row else {}
        except Exception:
            return {}

    def get_agent_cost(
        self, agent_id: str, start: datetime, end: datetime
    ) -> Dict[str, Any]:
        try:
            with self._lock, self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT provider, model,
                           SUM(input_tokens)  AS total_input,
                           SUM(output_tokens) AS total_output,
                           SUM(cost)          AS total_cost
                    FROM llm_calls
                    WHERE agent_id = ? AND called_at BETWEEN ? AND ?
                    GROUP BY provider, model
                    ORDER BY total_cost DESC
                    """,
                    (agent_id, start.isoformat(timespec="seconds"),
                     end.isoformat(timespec="seconds")),
                ).fetchall()
            summary = [dict(r) for r in rows]
            return {
                "agent_id": agent_id,
                "summary": summary,
                "total_cost": sum(float(s["total_cost"] or 0) for s in summary),
            }
        except Exception:
            return {"agent_id": agent_id, "summary": [], "total_cost": 0.0}


# ── 模块级门面（对齐 provider_usage install 惯例） ──────────────────────


def install_llm_cost_store(db_path: Optional[str] = None) -> LlmCostStore:
    """显式装配成本账本（幂等）。未装配时系统无落盘行为（默认关）。"""
    return LlmCostStore.install(db_path)


def uninstall_llm_cost_store() -> None:
    LlmCostStore.uninstall()


def reset_llm_cost_store() -> None:
    """测试隔离用：等价 uninstall。"""
    LlmCostStore.uninstall()


def get_llm_cost_store() -> Optional[LlmCostStore]:
    """获取已装配的账本实例；未装配返回 None（调用方须容错）。"""
    return LlmCostStore.get_installed()
