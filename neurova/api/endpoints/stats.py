from __future__ import annotations

"""
统计接口 - Stats Endpoint

功能:
1. 获取系统统计 (GET /api/v1/stats)
2. 获取 Agent 统计 (GET /api/v1/stats/agents)
3. 获取使用统计 (GET /api/v1/stats/usage)
4. 获取性能统计 (GET /api/v1/stats/performance)
"""

from neurova.core.logger import get_logger
import time
import uuid
from typing import Dict, List

from fastapi import APIRouter, Request
from pydantic import BaseModel

from neurova.api.endpoints import get_app_state

logger = get_logger(__name__)

router = APIRouter()


class SystemStats(BaseModel):
    """系统统计"""

    uptime: float = 0
    agents_count: int = 0
    total_conversations: int = 0
    total_messages: int = 0
    total_memories: int = 0
    total_tools_used: int = 0
    cpu_usage: float = 0
    memory_usage: float = 0


class AgentStats(BaseModel):
    """Agent 统计"""

    agent_id: str
    name: str
    conversations: int = 0
    messages: int = 0
    memories: int = 0
    tools_used: int = 0
    uptime: float = 0


class UsageStats(BaseModel):
    """使用统计"""

    daily_requests: Dict[str, int] = {}
    total_requests: int = 0
    avg_response_time: float = 0
    error_rate: float = 0


def _get_request_id(request: Request) -> str:
    """安全获取 request_id"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _get_app_state():
    """获取应用状态"""
    return get_app_state()


@router.get("", response_model=SystemStats)
async def get_system_stats(request: Request):
    """获取系统统计"""
    _get_request_id(request)

    state = _get_app_state()
    stats = SystemStats()

    if state:
        stats.agents_count = len(state.get("agents", {}))

        # 获取运行时间
        start_time = state.get("start_time", time.time())
        stats.uptime = time.time() - start_time

    # 获取系统资源使用情况
    try:
        import psutil

        stats.cpu_usage = psutil.cpu_percent()
        stats.memory_usage = psutil.virtual_memory().percent
    except ImportError:
        pass

    return stats


@router.get("/system")
async def get_system_info(request: Request):
    """获取系统信息（前端 Dashboard 用）"""
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


@router.get("/agents", response_model=List[AgentStats])
async def get_agents_stats(request: Request):
    """获取 Agent 统计"""
    _get_request_id(request)

    state = _get_app_state()
    agents_stats = []

    if state:
        agents = state.get("agents", {})
        for agent_id, agent in agents.items():
            stat = AgentStats(
                agent_id=agent_id,
                name=getattr(agent, "name", "Unknown"),
            )

            # 获取 Agent 统计
            if hasattr(agent, "get_stats"):
                try:
                    agent_stats = agent.get_stats()
                    stat.conversations = agent_stats.get("conversations", 0)
                    stat.messages = agent_stats.get("messages", 0)
                    stat.memories = agent_stats.get("memories", 0)
                    stat.tools_used = agent_stats.get("tools_used", 0)
                except Exception:
                    pass

            agents_stats.append(stat)

    return agents_stats


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


@router.get("/usage", response_model=UsageStats)
async def get_usage_stats(request: Request):
    """获取使用统计"""
    _get_request_id(request)

    # TODO: 从数据库或缓存加载使用统计
    return UsageStats(
        daily_requests={},
        total_requests=0,
        avg_response_time=0,
        error_rate=0,
    )


@router.get("/performance")
async def get_performance_stats(request: Request):
    """获取性能统计"""
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
