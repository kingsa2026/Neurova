"""Cost Rollup API Endpoints

成本聚合管理、按需回填、看板指标查询。走 SQLite 账本（LlmCostStore），
不使用外部数据库驱动，确保服务器启动不再因缺失依赖而中断。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException

from neurova.models.cost_rollup import (
    get_optimized_cost_queries,
    get_rollup_manager,
)
from neurova.models.cost_store import get_llm_cost_store

router = APIRouter(prefix="/cost-rollup", tags=["cost-rollup"])


def _require_store():
    store = get_llm_cost_store()
    if store is None:
        raise HTTPException(
            status_code=503,
            detail="LLM cost store 未装配（默认关）。请调用 install_llm_cost_store() 后重试。",
        )
    return store


# ── 看板指标 ────────────────────────────────────────────────────────────


@router.get("/dashboard/metrics")
def get_dashboard_metrics_endpoint():
    """当前小时 + 近 7 天看板指标（走账本，快）。"""
    store = _require_store()
    cur = store.current_hour_summary()
    return {
        "current_hour": {
            "cost": float(cur.get("total_cost") or 0),
            "input_tokens": int(cur.get("total_input") or 0),
            "output_tokens": int(cur.get("total_output") or 0),
            "active_agents": int(cur.get("active_agents") or 0),
        },
        "last_7_days": store.query_daily_cost(days=7),
        "hourly_trend": store.query_hourly_trend(hours=24),
    }


# ── 聚合管理 ────────────────────────────────────────────────────────────


@router.post("/rollup/now")
def force_rollup_now():
    """立即聚合上一小时。"""
    manager = get_rollup_manager()
    if not manager.status["store_ready"]:
        _require_store()  # 抛出 503
    affected = manager.run_rollup()
    return {"success": True, "affected_rows": affected}


@router.post("/rollup/range")
def force_rollup_range(start_time: datetime, end_time: datetime):
    """回填指定时间范围（逐小时聚合）。"""
    if start_time >= end_time:
        raise HTTPException(status_code=400, detail="start_time 必须早于 end_time")
    manager = get_rollup_manager()
    if not manager.status["store_ready"]:
        _require_store()
    total = manager.force_rollup_for_range(start_time, end_time)
    return {"success": True, "affected_rows": total, "range": [start_time.isoformat(), end_time.isoformat()]}


@router.get("/rollup/status")
def get_rollup_status():
    """聚合系统状态：是否装配、是否运行、上次运行时间。"""
    manager = get_rollup_manager()
    return manager.status


# ── 报表查询 ────────────────────────────────────────────────────────────


@router.get("/queries/{query_name}")
def get_optimized_query(query_name: str):
    """获取指定优化报表 SQL（SQLite 方言）。"""
    queries = get_optimized_cost_queries()
    if query_name not in queries:
        raise HTTPException(
            status_code=404,
            detail=f"Query not found: {query_name}. Available: {list(queries.keys())}",
        )
    return {"name": query_name, "sql": queries[query_name]}


@router.get("/history/daily")
def get_daily_history(days: int = 30):
    """近 N 天每日成本历史。"""
    store = _require_store()
    return {"days": days, "history": store.query_daily_cost(days=days)}


@router.get("/history/hourly")
def get_hourly_history(hours: int = 24):
    """近 N 小时成本趋势（走 rollup）。"""
    store = _require_store()
    return {"hours": hours, "trend": store.query_hourly_trend(hours=hours)}


@router.get("/agent/{agent_id}/cost")
def get_agent_cost(
    agent_id: str,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
):
    """指定 agent 在时间窗内的成本汇总。"""
    store = _require_store()
    end = end or datetime.now()
    start = start or (end.replace(hour=0, minute=0, second=0, microsecond=0))
    return store.get_agent_cost(agent_id, start, end)
