from __future__ import annotations

"""
统计接口 - Stats Endpoint（真实统计）

功能:
1. 获取系统统计 (GET /api/v1/stats) — overview + 7 天趋势（全部真实）
2. 获取 Agent 统计 (GET /api/v1/stats/agents) — 每 agent 会话/消息真实，
   tokens/api_calls/errors 无 agent 粒度源 → 诚实 0
3. 导出统计 (GET /api/v1/stats/export) — 真实汇总 JSON blob
4. 获取使用统计 (GET /api/v1/stats/usage) — 真实（会话按天 + prometheus 错误/延迟）
5. 系统资源 (GET /api/v1/stats/system / performance) — psutil
6. Token 用量 (GET /api/v1/stats/token-usage) — usage_accounting 快照

数据源约定（延续 home.py 的"诚实统计"契约）：
- agent 数/状态: app_state["agents"]
- 会话/消息/按天: SessionRepository（home._aggregate_daily）
- token/调用: home._real_token_stats（usage_accounting 单例）
- 记忆: home._real_memory_count（多 agent persist DB 聚合）
- 错误/延迟: analytics._read_llm_metrics（prometheus 埋点）
- 全部数据源异常回退 0/空，不伪造
"""

import time
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request

from neurova.api.deps import get_optional_user
from neurova.api.endpoints import get_app_state
from neurova.core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


def _get_request_id(request: Request) -> str:
    """安全获取 request_id"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _agent_status(agent: Any) -> str:
    status = getattr(agent, "status", None)
    if isinstance(status, str) and status:
        return status
    state = getattr(agent, "state", None)
    if isinstance(state, str) and state:
        return state
    # 与 /agents 列表端点口径一致（agent 实例无独立状态属性 → 运行中）
    return "running"


def _system_uptime() -> float:
    """进程运行时长：优先 app.py AppState.get_uptime()，回退 endpoints app_state。"""
    try:
        from neurova.api.app import get_app_state as _get_app

        st = _get_app()
        if st is not None and hasattr(st, "get_uptime"):
            return float(st.get_uptime() or 0.0)
    except Exception:
        pass
    try:
        state = get_app_state() or {}
        start_time = state.get("start_time", time.time())
        return max(0.0, time.time() - start_time)
    except Exception:
        return 0.0


def _build_overview() -> Dict[str, Any]:
    """系统级 overview（全部真实源，异常回退 0）。"""
    from neurova.api.endpoints import analytics, home

    try:
        state = get_app_state() or {}
        agents = state.get("agents") or {}
        agents_count = len(agents) if isinstance(agents, dict) else 0
    except Exception:
        agents_count = 0

    token_stats = home._real_token_stats()
    errors = 0
    try:
        errors = int(analytics._read_llm_metrics().get("failed_calls", 0) or 0)
    except Exception:
        errors = 0

    return {
        "agents": agents_count,
        "conversations": home._real_conversation_count(),
        "memories": home._real_memory_count(),
        "tokens": token_stats["tokens"],
        "api_calls": token_stats["calls"],
        "errors": errors,
        "uptime": _system_uptime(),
    }


def _build_trends(days: int = 7) -> List[Dict[str, Any]]:
    """会话/消息按天趋势（真实聚合，确定性）。"""
    from neurova.api.endpoints import home

    try:
        agg = home._aggregate_daily(days)
        return [{"label": l, "value": v} for l, v in zip(agg["labels"], agg["conv_data"])]
    except Exception:
        return []


@router.get("")
async def get_system_stats(request: Request):
    """获取系统统计（overview + 趋势，全部真实）"""
    _get_request_id(request)
    try:
        overview = _build_overview()
        trends = _build_trends()
        return {"overview": overview, "trends": trends}
    except Exception as e:
        logger.error(f"获取系统统计失败: {e}", exc_info=True)
        return {
            "overview": {
                "agents": 0, "conversations": 0, "memories": 0,
                "tokens": 0, "api_calls": 0, "errors": 0, "uptime": 0,
            },
            "trends": [],
        }


@router.get("/system")
async def get_system_info(request: Request):
    """获取系统信息（psutil 真实资源）"""
    try:
        import psutil

        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        return {
            "cpu": {
                "percent": cpu_percent,
                "count": psutil.cpu_count(),
            },
            "memory": {
                "total": memory.total,
                "used": memory.used,
                "percent": memory.percent,
            },
            "disk": {
                "total": disk.total,
                "used": disk.used,
                "percent": disk.percent,
            },
            "status": "running",
            "version": "1.0.0",
        }
    except ImportError:
        return {
            "cpu": {"percent": 0, "count": 0},
            "memory": {"total": 0, "used": 0, "percent": 0},
            "disk": {"total": 0, "used": 0, "percent": 0},
            "status": "running",
            "version": "1.0.0",
        }
    except Exception as e:
        logger.error(f"获取系统信息失败: {e}", exc_info=True)
        return {"error": str(e)}


@router.get("/agents")
async def get_agents_stats(request: Request):
    """获取 Agent 统计（每 agent 会话/消息真实，无粒度源字段诚实 0）"""
    _get_request_id(request)

    from neurova.session_repository import get_session_repository

    try:
        state = get_app_state() or {}
        agents = state.get("agents") or {}
    except Exception:
        agents = {}

    # 会话一次性扫描并按 agent 分组（真实摘要含 agent_id/total_messages）
    per_agent: Dict[str, Dict[str, int]] = {}
    try:
        sessions = get_session_repository().list_sessions()
        for s in sessions:
            aid = str(s.get("agent_id") or "default")
            bucket = per_agent.setdefault(aid, {"conversations": 0, "messages": 0})
            bucket["conversations"] += 1
            bucket["messages"] += int(s.get("total_messages", 0) or 0)
    except Exception:
        per_agent = {}

    names = {}
    for aid, agent in (agents or {}).items():
        names[aid] = getattr(agent, "name", str(aid))

    results = []
    for aid in sorted(set(list((agents or {}).keys()) + list(per_agent.keys()))):
        bucket = per_agent.get(aid, {"conversations": 0, "messages": 0})
        results.append(
            {
                "id": aid,
                "name": names.get(aid, str(aid)),
                "status": _agent_status(agents.get(aid)) if isinstance(agents, dict) and aid in (agents or {}) else "unknown",
                "conversations": bucket["conversations"],
                "messages": bucket["messages"],
                "tokens": 0,  # 记账器无 agent 粒度，诚实 0
                "api_calls": 0,
                "errors": 0,
            }
        )
    return results


@router.get("/token-usage")
async def get_token_usage(request: Request):
    """获取进程级 Token 用量（真实记账器快照，服务启动起累计）

    数据源: neurova.core.usage_accounting.TokenUsageAccounting 单例
    （multi_model_client.chat 每轮按 response.usage 真实记录）。
    进程重启归零是诚实语义（无持久化历史）。
    """
    _get_request_id(request)

    from neurova.core.usage_accounting import get_usage_accounting

    accounting = get_usage_accounting()
    snapshot = accounting.snapshot()

    by_model = [
        {
            "model": name,
            "calls": int(e.get("calls", 0)),
            "prompt_tokens": int(e.get("prompt_tokens", 0)),
            "completion_tokens": int(e.get("completion_tokens", 0)),
            "total_tokens": int(e.get("total_tokens", 0)),
        }
        for name, e in snapshot.get("by_model", {}).items()
    ]
    by_model.sort(key=lambda m: m["total_tokens"], reverse=True)

    return {
        "total": snapshot.get(
            "total",
            {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        ),
        "total_cost": snapshot.get("total_cost", 0.0),
        "by_model": by_model,
        "last_call": accounting.last_call(),
    }


def _empty_usage_overview(days: int, scope: str) -> Dict[str, Any]:
    """空库零态（契约完整，绝不 500）：summary 全 0、heatmap 连续窗口全 0。"""
    today = date.today()
    start = today - timedelta(days=days - 1)
    return {
        "scope": scope,
        "summary": {
            "total_tokens": 0,
            "total_calls": 0,
            "peak_daily_tokens": 0,
            "peak_daily_date": None,
            "longest_session_seconds": 0,
            "current_streak_days": 0,
            "longest_streak_days": 0,
            "active_days": 0,
        },
        "heatmap": [
            {"date": (start + timedelta(days=i)).isoformat(), "tokens": 0, "calls": 0}
            for i in range(days)
        ],
        "trends": [],
        "by_model": [],
    }


@router.get("/usage-overview")
async def get_usage_overview(
    request: Request,
    days: int = Query(default=365, ge=7, le=730, description="热力图窗口天数"),
    trend_days: int = Query(default=30, ge=7, le=365, description="趋势图窗口天数"),
    current_user: Optional[Dict[str, Any]] = Depends(get_optional_user),
):
    """使用统计总览（Kimi 式看板数据源，SQLite 持久化历史）。

    数据源: neurova.core.usage_history.UsageHistoryStore（multi_model_client
    每次 LLM 调用入账一行，落 data/usage_history.db，重启不归零）。
    登录用户 → scope=user（隔离该用户）；匿名 → scope=global（全部用户合计）。

    返回 summary（累计/单日峰值/最长会话时长/当前与最长连续天数/活跃天数）
    + heatmap（连续 days 天，无记录=0）+ trends（按天×模型）+ by_model。
    """
    _get_request_id(request)
    try:
        from neurova.core.usage_history import compute_streaks, get_usage_history

        user_id = (current_user or {}).get("user_id") or None
        scope = "user" if user_id else "global"
        history = get_usage_history()

        # 会话摘要（用户口径过滤；仅用于活跃日期/最长会话时长）
        sessions: List[Dict[str, Any]] = []
        try:
            from neurova.session_repository import get_session_repository

            sessions = get_session_repository().list_sessions(user_id=user_id or "")
        except Exception:
            sessions = []

        daily = history.daily_totals(user_id=user_id)
        daily_map = {r["usage_date"]: r for r in daily}

        today = date.today()
        start = today - timedelta(days=days - 1)
        heatmap = [
            {
                "date": (start + timedelta(days=i)).isoformat(),
                "tokens": int((daily_map.get((start + timedelta(days=i)).isoformat(), {}) or {}).get("tokens", 0) or 0),
                "calls": int((daily_map.get((start + timedelta(days=i)).isoformat(), {}) or {}).get("calls", 0) or 0),
            }
            for i in range(days)
        ]

        trend_start = (today - timedelta(days=trend_days - 1)).isoformat()
        trends = [
            {"date": r["usage_date"], "model": r["model"], "tokens": int(r["tokens"] or 0)}
            for r in history.daily_by_model(user_id=user_id)
            if r["usage_date"] >= trend_start
        ]

        by_model = sorted(
            (
                {"model": m["model"], "tokens": int(m["tokens"] or 0), "calls": int(m["calls"] or 0)}
                for m in history.model_totals(user_id=user_id)
            ),
            key=lambda m: m["tokens"],
            reverse=True,
        )

        total = history.total(user_id=user_id)
        peak = history.peak_daily(user_id=user_id)

        # 活跃日期集 = token 日期 ∪ 会话创建日期（聊天但无 token 的日子也算活跃）
        active_dates = {r["usage_date"] for r in daily}
        for s in sessions:
            created = str(s.get("created_at") or "")[:10]
            if len(created) == 10 and created[:4].isdigit():
                active_dates.add(created)
        current_streak, longest_streak = compute_streaks(active_dates, today)

        longest_session_seconds = 0
        for s in sessions:
            try:
                created = str(s.get("created_at") or "").replace("T", " ")
                updated = str(s.get("updated_at") or "").replace("T", " ")
                if not created or not updated:
                    continue
                delta = datetime.fromisoformat(updated) - datetime.fromisoformat(created)
                longest_session_seconds = max(longest_session_seconds, int(delta.total_seconds()))
            except Exception:
                continue

        return {
            "scope": scope,
            "summary": {
                "total_tokens": int(total["tokens"]),
                "total_calls": int(total["calls"]),
                "peak_daily_tokens": int(peak["tokens"] or 0) if peak else 0,
                "peak_daily_date": peak["usage_date"] if peak else None,
                "longest_session_seconds": longest_session_seconds,
                "current_streak_days": current_streak,
                "longest_streak_days": longest_streak,
                "active_days": len(active_dates),
            },
            "heatmap": heatmap,
            "trends": trends,
            "by_model": by_model,
        }
    except Exception as e:  # noqa: BLE001 - 诚实回退零态，绝不 500
        logger.error(f"获取使用统计总览失败: {e}", exc_info=True)
        scope = "user" if (current_user or {}).get("user_id") else "global"
        return _empty_usage_overview(days, scope)


@router.get("/export")
async def export_stats(request: Request):
    """导出统计汇总（JSON blob，供前端导出按钮下载）"""
    _get_request_id(request)

    from neurova.core.usage_accounting import get_usage_accounting

    try:
        overview = _build_overview()
        trends = _build_trends()
        agents = await get_agents_stats(request)
        accounting = get_usage_accounting().snapshot()
        return {
            "exported_at": time.time(),
            "overview": overview,
            "trends": trends,
            "agents": agents,
            "token_usage": accounting,
        }
    except Exception as e:
        logger.error(f"导出统计失败: {e}", exc_info=True)
        return {"exported_at": time.time(), "overview": {}, "trends": [], "agents": [], "token_usage": {}}


@router.get("/usage")
async def get_usage_stats(request: Request):
    """获取使用统计（真实：会话按天 + prometheus 调用/失败/延迟）"""
    _get_request_id(request)

    from neurova.api.endpoints import analytics, home

    metrics = analytics._read_llm_metrics()
    total = int(metrics.get("total_calls", 0) or 0)
    failed = int(metrics.get("failed_calls", 0) or 0)
    error_rate = round((failed / total) * 100, 2) if total else 0.0

    daily_requests: Dict[str, int] = {}
    try:
        agg = home._aggregate_daily(7)
        daily_requests = {l: v for l, v in zip(agg["labels"], agg["conv_data"])}
    except Exception:
        daily_requests = {}

    return {
        "daily_requests": daily_requests,
        "total_requests": total,
        "avg_response_time": metrics.get("avg_latency_ms", 0.0),
        "error_rate": error_rate,
    }


@router.get("/performance")
async def get_performance_stats(request: Request):
    """获取性能统计（psutil 系统资源真实）"""
    _get_request_id(request)

    stats = {
        "cpu_usage": 0,
        "memory_usage": 0,
        "disk_usage": 0,
        "network_io": {"bytes_sent": 0, "bytes_recv": 0},
        "active_connections": 0,
    }

    try:
        import psutil

        stats["cpu_usage"] = psutil.cpu_percent()
        stats["memory_usage"] = psutil.virtual_memory().percent
        stats["disk_usage"] = psutil.disk_usage("/").percent

        net_io = psutil.net_io_counters()
        stats["network_io"] = {
            "bytes_sent": net_io.bytes_sent,
            "bytes_recv": net_io.bytes_recv,
        }
    except ImportError:
        pass

    return {"code": 0, "data": stats}
