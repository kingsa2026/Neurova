"""
首页数据 API

提供 Dashboard 首页所需的数据：
1. GET /home/data - 首页汇总数据
2. GET /home/trends - 趋势数据
3. GET /stats/system - 系统统计
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query, Request

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_app_state(request: Request) -> Any:
    """获取应用状态"""
    return getattr(request.app, "state", None)


@router.get("/home/data")
async def get_home_data(request: Request):
    """获取首页汇总数据"""
    try:
        # 尝试从实际模块获取数据
        app_state = _get_app_state(request)
        
        # 获取 agent 数量
        agent_count = 0
        if app_state and hasattr(app_state, "agent"):
            agent_count = 1  # 当前 agent
        
        # 获取记忆数量
        memory_count = 0
        if app_state and hasattr(app_state, "memory_manager"):
            try:
                mm = app_state.memory_manager
                if hasattr(mm, "get_stats"):
                    stats = mm.get_stats()
                    memory_count = stats.get("total_memories", 0)
            except Exception:
                pass
        
        return {
            "welcome_message": "欢迎使用 Neurova",
            "quick_stats": {
                "total_conversations": 0,
                "total_memories": memory_count,
                "total_skills": 0,
            },
            "stats": {
                "agent_count": agent_count,
                "conversation_count": 0,
                "memory_count": memory_count,
                "token_consumption": 0,
                "plugin_count": 0,
                "public_skill_count": 0,
                "sleep_count": 0,
                "sleep_log_count": 0,
                "llm_call_count": 0,
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
    """获取趋势数据"""
    try:
        now = datetime.now(timezone.utc)
        labels = []
        for i in range(days - 1, -1, -1):
            d = now - timedelta(days=i)
            labels.append(d.strftime("%m-%d"))
        
        # 生成示例趋势数据
        def _trend_data(base: int = 0) -> Dict[str, Any]:
            data = []
            for i in range(days):
                data.append(base + random.randint(0, 5))
            return {"labels": labels, "data": data}
        
        return {
            "agent_trend": _trend_data(1),
            "token_trend": _trend_data(100),
            "memory_trend": _trend_data(0),
            "conversation_trend": _trend_data(0),
            "skill_trend": _trend_data(0),
            "llm_trend": _trend_data(0),
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
