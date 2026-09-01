"""
首页数据 API

提供 Dashboard 首页所需的数据（全部真实来源，禁止硬编码/随机伪造）：
1. GET /home/data - 首页汇总数据（agent/会话/token/调用/记忆 真实统计）
2. GET /home/trends - 7 天活跃趋势（会话按天真实聚合；无日维度历史的数据返回空数组）
3. GET /stats/system - 系统统计（psutil）

数据源约定：
- agent_count: app_state["agents"]
- conversation_count / 日趋势: SessionRepository.list_sessions()（sessions/ 目录）
- token_consumption / llm_call_count: TokenUsageAccounting 单例（进程内真实记账）
- memory_count: MemoryManager.get_memory_count()（记忆单例）
- 所有数据源异常时回退 0/空数组，端点不抛错（容错风格与其余端点一致）
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query, Request

from neurova.core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


def _get_app_state(request: Request) -> Any:
    """获取全局应用状态（Dict，由 app.py 通过 set_app_state 注入）

    注意：不能使用 request.app.state（Starlette State 对象），
    真正的 agent 列表在 neurova.api.endpoints 模块级 _app_state 中。
    """
    from neurova.api.endpoints import get_app_state

    return get_app_state()


def _real_conversation_count() -> int:
    """真实会话总数（会话仓库扫描，异常回退 0）。"""
    try:
        from neurova.session_repository import get_session_repository

        return len(get_session_repository().list_sessions())
    except Exception:
        return 0


def _real_token_stats() -> Dict[str, int]:
    """真实 token/调用统计（进程级记账器快照，异常回退 0）。"""
    try:
        from neurova.core.usage_accounting import get_usage_accounting

        total = get_usage_accounting().snapshot().get("total", {})
        return {
            "calls": int(total.get("calls", 0)),
            "tokens": int(total.get("total_tokens", 0)),
        }
    except Exception:
        return {"calls": 0, "tokens": 0}


def _count_persist_rows(db_path: str) -> int:
    """单个 persist 库的行数；损坏/缺失返回 0。"""
    try:
        import sqlite3

        conn = sqlite3.connect(db_path)
        total = int(conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
        conn.close()
        return total
    except Exception:
        return 0


def _GLOB_AGENT_WORKSPACES() -> list:
    """标准布局兜底：agent_workspaces/*/memory/neurova_memories_persist.db。"""
    try:
        import glob
        from pathlib import Path

        base_dir = Path(__file__).resolve().parents[3] / "agent_workspaces"  # 项目根
        return glob.glob(str(base_dir / "*" / "memory" / "neurova_memories_persist.db"))
    except Exception:
        return []


def _runtime_agent_persist_dbs() -> list:
    """运行时 agent 实例的真实持久化库路径（覆盖自定义 workspace 的新建 agent）。"""
    try:
        from neurova.api.endpoints import get_app_state

        app_state = get_app_state() or {}
        agents = app_state.get("agents", {}) or {}
        dbs = []
        for agent in agents.values():
            mm = getattr(getattr(agent, "memory_agent", None), "memory_manager", None)
            if mm is None:
                mm = getattr(agent, "memory_manager", None)
            db = getattr(mm, "_persist_db_path", None) or None
            if db and os.path.exists(db):
                dbs.append(str(db))
        return dbs
    except Exception:
        return []


def _sum_agent_persist_counts() -> Optional[int]:
    """聚合所有 agent 的持久化记忆行数（多 agent 独立记忆库设计）。

    初始设计：每个 agent 有独立的记忆数据库（agent_workspaces/<agent_id>/memory/）。
    Dashboard 的"记忆总数"是系统级 KPI，必须汇总全部 agent，否则只统计默认
    agent——其他 agent 写入的记忆会被漏计（统计口径缺陷）。

    主源：运行时 agent 实例枚举（agent.memory_manager._persist_db_path，覆盖
    新建 agent 的自定义 workspace 路径）；兜底：标准布局 glob。返回 None
    表示聚合不可用，调用方回退默认 agent 计数。
    """
    try:
        dbs = _runtime_agent_persist_dbs()
        if not dbs:
            dbs = _GLOB_AGENT_WORKSPACES()
        return sum(_count_persist_rows(db) for db in dbs)
    except Exception:
        return None


def _real_memory_count() -> int:
    """系统级真实记忆总数。

    主源：所有 agent 工作区 persist DB 行数聚合（多 agent 独立库设计）；
    回退：默认 agent MemoryManager 单例 get_memory_count；再失败返回 0。

    历史根因（原实现读 app_state["memory_manager"]，但 app.py 的 set_app_state
    从未注入该键 → 恒 0；后改单例仍只覆盖 default agent）。
    """
    try:
        aggregated = _sum_agent_persist_counts()
        if aggregated is not None:
            return int(aggregated)
    except Exception:
        pass
    try:
        from neurova.cognitive_layers.memory_layer.manager import get_memory_manager

        return int(get_memory_manager().get_memory_count() or 0)
    except Exception:
        return 0


def _parse_day(created_at: Any) -> Optional[str]:
    """从会话 created_at 提取 YYYY-MM-DD；不可解析返回 None。

    SessionRecord.created_at 为本地时间 datetime.now().isoformat()，
    无时区后缀，直接取前 10 字符即可（ttz 后缀不影响取位）。
    """
    s = str(created_at or "")
    if len(s) < 10:
        return None
    day = s[:10]
    try:
        datetime.strptime(day, "%Y-%m-%d")
        return day
    except ValueError:
        return None


def _aggregate_daily(days: int) -> Dict[str, list]:
    """会话按天聚合（确定性）。

    返回与 days 等长的每日活跃 agent 数 / 会话数 / 消息数。
    """
    from neurova.session_repository import get_session_repository

    sessions = get_session_repository().list_sessions()

    first = datetime.now() - timedelta(days=days - 1)
    labels = [(first + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]

    agent_by_day: Dict[str, set] = {d: set() for d in labels}
    conv_by_day = {d: 0 for d in labels}
    msg_by_day = {d: 0 for d in labels}

    for s in sessions:
        day = _parse_day(s.get("created_at"))
        if day not in conv_by_day:
            continue  # 超出窗口的记录不参与
        conv_by_day[day] += 1
        msg_by_day[day] += int(s.get("total_messages", 0) or 0)
        agent_id = str(s.get("agent_id") or "default")
        agent_by_day[day].add(agent_id)

    def as_list(counter):
        return [counter[d] for d in labels]

    short_labels = [d[5:] for d in labels]  # MM-DD
    return {
        "labels": short_labels,
        "agent_data": [len(agent_by_day[d]) for d in labels],
        "conv_data": as_list(conv_by_day),
        "msg_data": as_list(msg_by_day),
    }


@router.get("/home/data")
async def get_home_data(request: Request):
    """获取首页汇总数据（真实统计）"""
    try:
        # 尝试从实际模块获取数据
        app_state = _get_app_state(request)

        # 获取 agent 数量（从 app_state["agents"] 字典统计）
        agent_count = 0
        if app_state:
            agents = app_state.get("agents") or {}
            if isinstance(agents, dict):
                agent_count = len(agents)

        token_stats = _real_token_stats()

        return {
            "welcome_message": "欢迎使用 Neurova",
            "quick_stats": {
                "total_conversations": _real_conversation_count(),
                "total_memories": _real_memory_count(),
                "total_skills": 0,
            },
            "stats": {
                "agent_count": agent_count,
                "conversation_count": _real_conversation_count(),
                "memory_count": _real_memory_count(),
                "token_consumption": token_stats["tokens"],
                "plugin_count": 0,
                "public_skill_count": 0,
                "sleep_count": 0,
                "sleep_log_count": 0,
                "llm_call_count": token_stats["calls"],
                "evolution_count": 0,
                "custom_skill_count": 0,
                "skill_iteration_count": 0,
            },
            "memory_categories": {
                "short_term": 0,
                "long_term": 0,
                "episodic": 0,
                "semantic": 0,
            },
            "skill_categories": {
                "conversation": 0,
                "code": 0,
                "search": 0,
                "creation": 0,
                "other": 0,
            },
            "agent_capabilities": {
                "reasoning": 50,
                "creativity": 50,
                "knowledge": 50,
                "communication": 50,
                "problem_solving": 50,
            },
            # trends 数字（对比基线）已弃用：真实 delta 由前端从 /home/trends 序列派生，
            # 此处恒 0（无独立历史基线，保持字段兼容，不再伪造）。
            "trends": {
                "agent_trend": 0,
                "conversation_trend": 0,
                "memory_trend": 0,
                "token_trend": 0,
                "plugin_trend": 0,
            },
            "recommended_actions": [
                {
                    "title": "创建第一个 Agent",
                    "description": "开始与 AI 助手对话",
                    "action": "create_agent",
                    "priority": "high",
                }
            ],
            "system_status": {
                "status": "running",
                "uptime": "0h 0m",
                "version": "1.0.0",
            },
        }
    except Exception as e:
        logger.error(f"获取首页数据失败: {e}", exc_info=True)
        return {"error": str(e)}


@router.get("/home/trends")
async def get_home_trends(request: Request, days: int = Query(default=7, ge=1, le=90)):
    """获取 7 天活跃趋势（会话真实按天聚合，确定性输出）

    token/llm 无日维度历史源（记账器仅进程累计）→ data 返回空数组，
    绝不使用随机数/示例数据伪造。
    """
    try:
        agg = _aggregate_daily(days)
        labels = agg["labels"]
        empty = {"labels": labels, "data": []}

        return {
            "agent_trend": {"labels": labels, "data": agg["agent_data"]},
            "token_trend": dict(empty),
            "memory_trend": dict(empty),
            "conversation_trend": {"labels": labels, "data": agg["conv_data"]},
            "message_trend": {"labels": labels, "data": agg["msg_data"]},
            "skill_trend": dict(empty),
            "llm_trend": dict(empty),
        }
    except Exception as e:
        logger.error(f"获取趋势数据失败: {e}", exc_info=True)
        return {"error": str(e)}


@router.get("/stats/system")
async def get_system_stats(request: Request):
    """获取系统统计"""
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
        # psutil 未安装时返回基本数据
        return {
            "cpu": {"percent": 0, "count": 0},
            "memory": {"total": 0, "used": 0, "percent": 0},
            "disk": {"total": 0, "used": 0, "percent": 0},
            "status": "running",
            "version": "1.0.0",
        }
    except Exception as e:
        logger.error(f"获取系统统计失败: {e}", exc_info=True)
        return {"error": str(e)}
