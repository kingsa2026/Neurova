from __future__ import annotations

"""
分析接口 - Analytics Endpoint（真实统计）

数据源（全部真实，异常/无源回退 0 或空数组，不许伪造）：
- LLM 调用数/成功失败/延迟: prometheus 埋点
  （neurova_llm_calls_total + neurova_llm_call_seconds，multi_model_client 接线）
- 工具执行: prometheus 工具计数
  （neurova_tool_executions_total + neurova_tool_execution_seconds，tool_executor 接线）
- 会话/消息/按天/按小时/按 agent: SessionRepository（sessions/ 目录真实扫描）
- Token: TokenUsageAccounting 单例（进程内真实记账）

契约对齐前端 NeurUI/src/api/modules/analytics.ts：
- GET /api/v1/analytics/usage|performance|behavior|errors
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request

from neurova.api.deps import get_current_user
from neurova.core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

# ─────────────────────────────────────────────────────────────────────────────
# Prometheus 聚合辅助（模块级纯函数，测试可 monkeypatch）
# ─────────────────────────────────────────────────────────────────────────────


def _read_llm_metrics() -> Dict[str, Any]:
    """聚合 LLM 埋点（进程级 prometheus REGISTRY）。

    - total_calls/failed_calls: neurova_llm_calls_total（label success）
    - avg/p95: neurova_llm_call_seconds 直方图（跨 label 加和；
      p95 为样本 95 分位所在的 bucket 上限，无插值——诚实语义）
    - by_model: 按 (provider, model) 聚合 [calls/failed_calls/avg_ms]
    """
    try:
        from prometheus_client import REGISTRY

        # (provider, model) -> {calls, failed, sum_s, count}
        per_model: Dict[tuple, Dict[str, float]] = {}
        hist_sum = 0.0
        hist_count = 0
        buckets: Dict[float, float] = {}

        for mf in REGISTRY.collect():
            if mf.name == "neurova_llm_calls_total":
                for s in mf.samples:
                    key = (s.labels.get("provider", ""), s.labels.get("model", ""))
                    e = per_model.setdefault(key, {"calls": 0, "failed": 0, "sum_s": 0.0, "count": 0})
                    e["calls"] += int(s.value)
                    if s.labels.get("success") == "false":
                        e["failed"] += int(s.value)
            elif mf.name == "neurova_llm_call_seconds" and mf.type == "histogram":
                for s in mf.samples:
                    key = (s.labels.get("provider", ""), s.labels.get("model", ""))
                    if s.name.endswith("_sum"):
                        hist_sum += float(s.value)
                        e = per_model.setdefault(key, {"calls": 0, "failed": 0, "sum_s": 0.0, "count": 0})
                        e["sum_s"] += float(s.value)
                    elif s.name.endswith("_count"):
                        hist_count += int(s.value)
                        e = per_model.setdefault(key, {"calls": 0, "failed": 0, "sum_s": 0.0, "count": 0})
                        e["count"] += int(s.value)
                    elif s.name.endswith("_bucket") and s.labels.get("le") != "+Inf":
                        le = float(s.labels["le"])
                        buckets[le] = buckets.get(le, 0.0) + float(s.value)

        def _avg_ms(e: Dict[str, float]) -> float:
            return round((e["sum_s"] / e["count"]) * 1000, 2) if e["count"] else 0.0

        total_calls = sum(int(e["calls"]) for e in per_model.values())
        failed_calls = sum(int(e["failed"]) for e in per_model.values())

        avg_ms = round((hist_sum / hist_count) * 1000, 2) if hist_count else 0.0
        p95_ms = 0.0
        if hist_count:
            target = 0.95 * hist_count
            for le in sorted(buckets):
                if buckets[le] >= target:
                    p95_ms = round(le * 1000, 2)
                    break

        return {
            "total_calls": total_calls,
            "failed_calls": failed_calls,
            "avg_latency_ms": avg_ms,
            "p95_latency_ms": p95_ms,
            "by_model": [
                {
                    "model": model,
                    "provider": provider,
                    "calls": int(e["calls"]),
                    "failed_calls": int(e["failed"]),
                    "avg_ms": _avg_ms(e),
                }
                for (provider, model), e in sorted(per_model.items())
            ],
        }
    except Exception:
        logger.debug("llm metrics read failed", exc_info=True)
        return {"total_calls": 0, "failed_calls": 0, "avg_latency_ms": 0.0, "p95_latency_ms": 0.0, "by_model": []}


def _read_tool_metrics(top_n: int = 5) -> List[Dict[str, Any]]:
    """工具执行计数（按 tool_name 聚合），按调用数降序取前 top_n。"""
    try:
        from prometheus_client import REGISTRY

        per_tool: Dict[str, Dict[str, Any]] = {}
        for mf in REGISTRY.collect():
            if mf.name == "neurova_tool_executions_total":
                for s in mf.samples:
                    name = s.labels.get("tool_name", "?")
                    entry = per_tool.setdefault(
                        name, {"name": name, "usage_count": 0, "success_count": 0, "avg_duration_ms": 0.0}
                    )
                    entry["usage_count"] += int(s.value)
                    if s.labels.get("success") == "true":
                        entry["success_count"] += int(s.value)

        return sorted(per_tool.values(), key=lambda e: e["usage_count"], reverse=True)[:top_n]
    except Exception:
        logger.debug("tool metrics read failed", exc_info=True)
        return []


# ─────────────────────────────────────────────────────────────────────────────
# 站点数据辅助（复用 home.py 的既定真实聚合，跨模块引用以支持测试 patch）
# ─────────────────────────────────────────────────────────────────────────────


def _sessions() -> List[Dict[str, Any]]:
    """全部会话摘要（异常时空列表）。"""
    try:
        from neurova.session_repository import get_session_repository

        return get_session_repository().list_sessions()
    except Exception:
        return []


def _token_snapshot() -> Dict[str, int]:
    """Token/调用总额（记账器快照，异常回退 0）。"""
    try:
        from neurova.core.usage_accounting import get_usage_accounting

        total = get_usage_accounting().snapshot().get("total", {})
        return {
            "calls": int(total.get("calls", 0)),
            "tokens": int(total.get("total_tokens", 0)),
            "by_model": get_usage_accounting().snapshot().get("by_model", {}),
        }
    except Exception:
        return {"calls": 0, "tokens": 0, "by_model": {}}


def _uptime() -> float:
    """进程运行时长：优先 app.py AppState.get_uptime()，回退 endpoints app_state。"""
    try:
        from neurova.api.app import get_app_state as _get_app

        st = _get_app()
        if st is not None and hasattr(st, "get_uptime"):
            return float(st.get_uptime() or 0.0)
    except Exception:
        pass
    try:
        import time

        from neurova.api.endpoints import get_app_state

        state = get_app_state() or {}
        start = state.get("start_time", time.time())
        return max(0.0, time.time() - start)
    except Exception:
        return 0.0


def _peak_hours_from_sessions(sessions: List[Dict[str, Any]]) -> List[Dict[str, int]]:
    """会话创建时刻按小时聚合（真实分布），按小时升序。"""
    counter: Dict[int, int] = {}
    try:
        from datetime import datetime

        for s in sessions:
            created = str(s.get("created_at") or "")
            if len(created) < 13:
                continue
            try:
                hour = int(created[11:13])
            except ValueError:
                continue
            if 0 <= hour <= 23:
                counter[hour] = counter.get(hour, 0) + 1
    except Exception:
        return []
    return [{"hour": h, "requests": counter[h]} for h in sorted(counter)]


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/usage")
async def get_usage_stats(
    request: Request,
    period: str = Query(default="week", description="统计周期 day/week/month"),
    current_user: dict = Depends(get_current_user),
):
    """使用统计：会话/Token/调用/按 agent/按天趋势（真实）。"""
    _ = request
    try:
        from neurova.api.endpoints import home

        sessions = _sessions()
        token = _token_snapshot()

        # 按天聚合（会话+消息；复用 home 的确定性实现）
        daily_trend: List[Dict[str, Any]] = []
        try:
            agg = home._aggregate_daily(days=7)
            daily_trend = [
                {"date": d, "requests": c, "tokens": 0}
                for d, c in zip(agg["labels"], agg["conv_data"])
            ]
            # token 列取真值（根因修复 2026-09-03: 原先填 msg_per_day——消息数冒
            # 充 tokens；持久化历史已上线，按 MM-DD 对齐汇总）
            try:
                from neurova.core.usage_history import get_usage_history

                daily_tokens_mmdd = {
                    r["usage_date"][5:]: int(r["tokens"] or 0)
                    for r in get_usage_history().daily_totals()
                }
            except Exception:
                daily_tokens_mmdd = {}
            for i, item in enumerate(daily_trend):
                item["tokens"] = daily_tokens_mmdd.get(item["date"], 0)
        except Exception:
            daily_trend = []

        # 按 agent 会话数
        by_agent_counter: Dict[str, int] = {}
        for s in sessions:
            aid = str(s.get("agent_id") or "default")
            by_agent_counter[aid] = by_agent_counter.get(aid, 0) + 1

        by_model = [
            {"model": name, "requests": int(e.get("calls", 0)), "tokens": int(e.get("total_tokens", 0))}
            for name, e in token["by_model"].items()
        ]

        return {
            "period": period,
            "total_requests": token["calls"],
            "total_tokens": token["tokens"],
            "avg_latency_ms": 0.0,  # 无请求级延迟持久源，诚实 0（性能维度见 /performance）
            "by_agent": [
                {"agent_id": aid, "name": aid, "requests": n}
                for aid, n in sorted(by_agent_counter.items(), key=lambda kv: kv[1], reverse=True)
            ],
            "by_model": by_model,
            "daily_trend": daily_trend,
        }
    except Exception as e:
        logger.exception("Failed to get usage stats: %s", e)
        return {
            "period": period,
            "total_requests": 0,
            "total_tokens": 0,
            "avg_latency_ms": 0.0,
            "by_agent": [],
            "by_model": [],
            "daily_trend": [],
        }


@router.get("/performance")
async def get_performance_stats(
    request: Request,
    period: str = Query(default="week", description="统计周期 day/week/month"),
    current_user: dict = Depends(get_current_user),
):
    """性能统计：LLM 延迟分布/错误率/吞吐（prometheus 真实埋点）。"""
    _ = request
    try:
        m = _read_llm_metrics()
        total = m["total_calls"]
        failed = m["failed_calls"]
        uptime = _uptime()
        throughput = round(total / uptime, 3) if uptime > 0 else 0.0
        error_rate = round((failed / total) * 100, 2) if total else 0.0

        by_endpoint = [
            {"endpoint": f"{e['provider']}:{e['model']}", "avg_ms": e["avg_ms"], "count": e["calls"]}
            for e in m["by_model"]
        ]

        return {
            "period": period,
            "avg_latency_ms": m["avg_latency_ms"],
            "p95_latency_ms": m["p95_latency_ms"],
            "p99_latency_ms": 0.0,
            "error_rate": error_rate,
            "throughput_rps": throughput,
            "by_endpoint": by_endpoint,
        }
    except Exception as e:
        logger.exception("Failed to get performance stats: %s", e)
        return {
            "period": period,
            "avg_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
            "p99_latency_ms": 0.0,
            "error_rate": 0.0,
            "throughput_rps": 0.0,
            "by_endpoint": [],
        }


@router.get("/behavior")
async def get_behavior_stats(
    request: Request,
    period: str = Query(default="week", description="统计周期 day/week/month"),
    current_user: dict = Depends(get_current_user),
):
    """用户行为：真实工具使用排名 + 会话小时分布；无源项恒空。"""
    _ = request
    try:
        try:
            sessions = _sessions()
        except Exception:
            sessions = []
        return {
            "period": period,
            "top_tools": _read_tool_metrics(),
            "top_skills": [],  # 技能执行无独立埋点源，诚实空
            "conversation_patterns": [],  # 会话模式无结构化源，诚实空
            "peak_hours": _peak_hours_from_sessions(sessions),
        }
    except Exception as e:
        logger.exception("Failed to get behavior stats: %s", e)
        return {
            "period": period,
            "top_tools": [],
            "top_skills": [],
            "conversation_patterns": [],
            "peak_hours": [],
        }


@router.get("/errors")
async def get_error_stats(
    request: Request,
    period: str = Query(default="week", description="统计周期 day/week/month"),
    current_user: dict = Depends(get_current_user),
):
    """错误统计：LLM 失败计数（prometheus），按 provider 聚合；无明细源恒空。"""
    _ = request
    try:
        m = _read_llm_metrics()
        total = m["total_calls"]
        failed = m["failed_calls"]
        error_rate = round((failed / total) * 100, 2) if total else 0.0

        by_provider: Dict[str, int] = {}
        for e in m["by_model"]:
            if e["failed_calls"] > 0:
                by_provider[e["provider"]] = by_provider.get(e["provider"], 0) + e["failed_calls"]

        return {
            "period": period,
            "total_errors": failed,
            "error_rate": error_rate,
            "by_type": [{"type": p, "count": n} for p, n in sorted(by_provider.items())],
            "by_endpoint": [{"endpoint": p, "count": n} for p, n in sorted(by_provider.items())],
            "recent_errors": [],  # 无结构化错误明细源，诚实空
        }
    except Exception as e:
        logger.exception("Failed to get error stats: %s", e)
        return {
            "period": period,
            "total_errors": 0,
            "error_rate": 0.0,
            "by_type": [],
            "by_endpoint": [],
            "recent_errors": [],
        }
