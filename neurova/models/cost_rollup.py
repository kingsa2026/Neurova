"""Hourly Cost Rollup Automation

把 llm_calls 明细按小时预聚合进 llm_calls_rollup，加速看板/报表查询。
后台任务定期跑上一小时聚合，也支持按需强制聚合与历史回填。

技术栈：SQLite（经 LlmCostStore），对齐系统一数据库，不使用外部 PG 驱动。
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Optional

from neurova.core.logger import get_logger
from neurova.models.cost_store import LlmCostStore, get_llm_cost_store

logger = get_logger(__name__)


class HourlyRollupManager:
    """小时成本聚合管理器（线程后台任务，SQLite 落盘）。"""

    def __init__(self, store: Optional[LlmCostStore] = None):
        self._store = store
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._interval_seconds = 3600
        self._last_run_at: Optional[datetime] = None

    def _ensure_store(self) -> Optional[LlmCostStore]:
        if self._store is None:
            self._store = get_llm_cost_store()
        return self._store

    def start_background_job(self, interval_seconds: int = 3600) -> bool:
        """启动后台聚合线程。账本未装配则不启动（默认关）。"""
        if self._ensure_store() is None:
            logger.warning("llm_cost store 未装配，rollup 后台任务不启动")
            return False
        if self._running:
            return True
        self._interval_seconds = max(60, interval_seconds)
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("Hourly rollup 后台任务已启动 (interval=%ss)", self._interval_seconds)
        return True

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        while self._running:
            try:
                self.run_rollup()
            except Exception as e:  # noqa: BLE001 - 后台任务绝不因单次失败退出
                logger.error("Hourly rollup 执行失败: %s", e)
            # 分段睡眠，便于 stop() 及时生效
            slept = 0
            while self._running and slept < self._interval_seconds:
                time.sleep(min(5, self._interval_seconds - slept))
                slept += 5

    def run_rollup(self, hour: Optional[datetime] = None) -> int:
        """聚合指定小时（默认上一小时）。返回受影响行数。"""
        store = self._ensure_store()
        if store is None:
            raise RuntimeError("llm_cost store 未装配，无法 rollup")
        target = hour or (
            datetime.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        )
        affected = store.rollup_hour(target)
        self._last_run_at = datetime.now()
        logger.info("Rollup 完成: hour=%s affected=%s", target.isoformat(), affected)
        return affected

    def force_rollup_for_range(
        self, start_time: datetime, end_time: datetime
    ) -> int:
        """回填 [start_time, end_time) 覆盖的每个小时。返回累计受影响行数。"""
        store = self._ensure_store()
        if store is None:
            raise RuntimeError("llm_cost store 未装配，无法 rollup")
        total = 0
        cursor = start_time.replace(minute=0, second=0, microsecond=0)
        while cursor < end_time:
            total += store.rollup_hour(cursor)
            cursor += timedelta(hours=1)
        return total

    @property
    def status(self) -> Dict[str, object]:
        return {
            "store_ready": self._ensure_store() is not None,
            "running": self._running,
            "last_run_at": self._last_run_at.isoformat() if self._last_run_at else None,
        }


# ── 全局实例管理（对齐 get_*/reset_* 工厂惯例） ────────────────────────

_rollup_manager: Optional[HourlyRollupManager] = None
_rollup_lock = threading.Lock()


def get_rollup_manager() -> HourlyRollupManager:
    global _rollup_manager
    if _rollup_manager is None:
        with _rollup_lock:
            if _rollup_manager is None:
                _rollup_manager = HourlyRollupManager()
    return _rollup_manager


def reset_rollup_manager() -> None:
    global _rollup_manager
    if _rollup_manager is not None:
        _rollup_manager.stop()
    _rollup_manager = None


# ── 常用报表 SQL（SQLite 方言，供前端/报表直查参考） ────────────────────


def get_optimized_cost_queries() -> Dict[str, str]:
    return {
        "daily_cost_by_agent": """
            SELECT substr(called_at,1,10) AS date,
                   agent_id,
                   SUM(cost) AS daily_cost,
                   SUM(input_tokens) AS total_input_tokens,
                   SUM(output_tokens) AS total_output_tokens
            FROM llm_calls
            WHERE called_at >= datetime('now','-30 days')
            GROUP BY date, agent_id
            ORDER BY date DESC, daily_cost DESC
        """,
        "hourly_trend": """
            SELECT hour,
                   SUM(total_cost) AS hourly_total,
                   SUM(call_count) AS call_count
            FROM llm_calls_rollup
            WHERE hour >= datetime('now','-24 hours')
            GROUP BY hour
            ORDER BY hour DESC
        """,
        "provider_breakdown": """
            SELECT provider,
                   SUM(total_cost) AS total_cost,
                   SUM(total_input) AS total_input,
                   SUM(total_output) AS total_output
            FROM llm_calls_rollup
            WHERE hour >= datetime('now','-7 days')
            GROUP BY provider
            ORDER BY total_cost DESC
        """,
        "model_usage_ranking": """
            SELECT model,
                   SUM(call_count) AS call_count,
                   SUM(total_output) AS total_tokens,
                   SUM(total_cost) AS total_cost
            FROM llm_calls_rollup
            WHERE hour >= datetime('now','-30 days')
            GROUP BY model
            ORDER BY total_cost DESC
            LIMIT 20
        """,
    }
