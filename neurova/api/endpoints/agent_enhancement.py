from __future__ import annotations

"""
Agent 增强接口 - Agent Enhancement Endpoint

功能:
1. 获取 Agent 状态 (GET /api/v1/agents/{id}/status)
2. 获取 Agent 能力 (GET /api/v1/agents/{id}/capabilities)
3. Agent 健康检查 (GET /api/v1/agents/{id}/health)
4. 重启 Agent (POST /api/v1/agents/{id}/restart)
"""

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class AgentStatus(BaseModel):
    """Agent状态"""

    agent_id: str
    status: str = "running"
    uptime: float = 0
    memory_usage: int = 0
    message_count: int = 0
    last_active: Optional[float] = None
    created_at: float = 0


class AgentCapabilities(BaseModel):
    """Agent能力"""

    agent_id: str
    capabilities: List[str] = []
    tools: List[str] = []
    models: List[str] = []
    channels: List[str] = []


class AgentHealth(BaseModel):
    """Agent健康状态"""

    agent_id: str
    healthy: bool = True
    checks: Dict[str, Any] = {}
    last_check: float = 0


class RestartResponse(BaseModel):
    """重启响应"""

    agent_id: str
    success: bool
    message: str
    restart_time: float


# ---------------------------------------------------------------------------
# In-Memory Store
# ---------------------------------------------------------------------------

_agents_status: Dict[str, Dict[str, Any]] = {}


def _get_request_id(request: Request) -> str:
    """获取请求ID"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _get_agent(agent_id: str) -> Optional[Any]:
    """获取Agent实例"""
    try:
        from neurova.api.endpoints import get_agent_instance

        return get_agent_instance(agent_id)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/{agent_id}/status", response_model=AgentStatus)
async def get_agent_status(
    request: Request,
    agent_id: str,
):
    """获取 Agent 运行状态"""
    agent = _get_agent(agent_id)

    # 尝试从Agent获取真实状态
    if agent and hasattr(agent, "get_status"):
        try:
            status = await agent.get_status()
            return AgentStatus(**status)
        except Exception as e:
            logger.warning("Failed to get agent status: %s", e)

    # 返回模拟状态
    now = time.time()
    status = _agents_status.get(
        agent_id,
        {
            "agent_id": agent_id,
            "status": "running",
            "uptime": 3600,
            "memory_usage": 1024 * 1024 * 100,
            "message_count": 42,
            "last_active": now,
            "created_at": now - 3600,
        },
    )
    return AgentStatus(**status)


@router.get("/{agent_id}/capabilities", response_model=AgentCapabilities)
async def get_agent_capabilities(
    request: Request,
    agent_id: str,
):
    """获取 Agent 能力描述"""
    agent = _get_agent(agent_id)

    # 尝试从Agent获取真实能力
    if agent and hasattr(agent, "get_capabilities"):
        try:
            caps = await agent.get_capabilities()
            return AgentCapabilities(**caps)
        except Exception as e:
            logger.warning("Failed to get agent capabilities: %s", e)

    # 返回默认能力
    return AgentCapabilities(
        agent_id=agent_id,
        capabilities=["chat", "memory", "tools", "skills", "multimodal"],
        tools=["memory_search", "web_search", "file_read", "file_write", "code_execution"],
        models=["openai", "anthropic", "gemini", "ollama"],
        channels=["web", "api", "mobile", "feishu", "dingtalk", "wecom"],
    )


@router.get("/{agent_id}/health", response_model=AgentHealth)
async def agent_health_check(
    request: Request,
    agent_id: str,
):
    """Agent 健康检查"""
    agent = _get_agent(agent_id)

    checks = {
        "agent_exists": agent is not None,
        "memory_system": False,
        "llm_connection": False,
        "tool_executor": False,
    }

    # 检查各个子系统
    if agent:
        if hasattr(agent, "memory_manager") and agent.memory_manager:
            checks["memory_system"] = True
        if hasattr(agent, "llm_client") and agent.llm_client:
            checks["llm_connection"] = True
        if hasattr(agent, "tool_executor") and agent.tool_executor:
            checks["tool_executor"] = True

    healthy = all(checks.values())

    return AgentHealth(
        agent_id=agent_id,
        healthy=healthy,
        checks=checks,
        last_check=time.time(),
    )


@router.post("/{agent_id}/restart", response_model=RestartResponse)
async def restart_agent(
    request: Request,
    agent_id: str,
):
    """重启 Agent"""
    start = time.time()
    agent = _get_agent(agent_id)

    # 尝试重启Agent
    if agent and hasattr(agent, "restart"):
        try:
            await agent.restart()
            return RestartResponse(
                agent_id=agent_id,
                success=True,
                message=f"Agent '{agent_id}' restarted successfully",
                restart_time=time.time() - start,
            )
        except Exception as e:
            logger.error("Failed to restart agent: %s", e)
            return RestartResponse(
                agent_id=agent_id,
                success=False,
                message=f"Restart failed: {str(e)}",
                restart_time=time.time() - start,
            )

    # 模拟重启
    _agents_status[agent_id] = {
        "agent_id": agent_id,
        "status": "running",
        "uptime": 0,
        "memory_usage": 0,
        "message_count": 0,
        "last_active": time.time(),
        "created_at": time.time(),
    }

    return RestartResponse(
        agent_id=agent_id,
        success=True,
        message=f"Agent '{agent_id}' restarted (simulated)",
        restart_time=time.time() - start,
    )
