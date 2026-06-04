from __future__ import annotations

"""
Agent 管理接口 - Agent Endpoint

功能:
1. 列出所有 Agent (GET /api/v1/agents)
2. 获取 Agent 详情 (GET /api/v1/agents/{agent_id})
3. 创建 Agent (POST /api/v1/agents)
4. 删除 Agent (DELETE /api/v1/agents/{agent_id})
5. 获取 Agent 统计 (GET /api/v1/agents/{agent_id}/stats)
6. 切换 Agent (POST /api/v1/agents/{agent_id}/switch)
7. 获取/更新宪法 (GET/PUT /api/v1/agents/{agent_id}/constitution)
"""

import datetime
import json
import logging
import os
from pathlib import Path
import time
import traceback
import typing
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi import Path as FastAPIPath
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()


class AgentInfo(BaseModel):
    """Agent 信息"""
    agent_id: str
    name: str
    description: str = ""
    model: str = ""
    status: str = "unknown"
    created_at: Optional[str] = None
    last_active: Optional[str] = None
    memory_enabled: bool = False
    tools_count: int = 0


class CreateAgentRequest(BaseModel):
    """创建 Agent 请求"""
    name: str = Field(..., description="Agent 名称")
    description: str = Field(default="", description="Agent 描述")
    model: Optional[str] = Field(default=None, description="LLM 模型")
    enable_memory: bool = Field(default=True, description="启用记忆")
    config: Dict[str, Any] = Field(default_factory=dict, description="额外配置")


class UpdateConstitutionRequest(BaseModel):
    """更新宪法请求"""
    constitution: Dict[str, Any] = Field(..., description="宪法内容")


class UpdatePersonalityRequest(BaseModel):
    """更新性格请求"""
    personality: Dict[str, Any] = Field(..., description="性格配置")


class DecisionRequest(BaseModel):
    """决策请求"""
    context: str = Field(..., description="决策上下文")
    options: List[str] = Field(default=[], description="可选项")
    constraints: List[str] = Field(default=[], description="约束条件")


def _get_request_id(request: Request) -> str:
    """安全获取 request_id"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _get_app_state():
    """获取应用状态"""
    from neurova.api.endpoints import get_app_state
    return get_app_state()


def load_agents_config() -> Dict[str, Any]:
    """加载 Agent 配置列表"""
    config_path = Path("agents.json")
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load agents config: {e}")
    return {}


def agent_to_info(agent) -> Dict[str, Any]:
    """将 Agent 对象转换为信息字典"""
    # 从 config 获取 agent_id
    agent_id = "unknown"
    name = "Unknown"
    description = ""
    enable_memory = False
    
    if hasattr(agent, "config"):
        config = agent.config
        agent_id = getattr(config, "agent_id", "unknown")
        name = getattr(config, "name", "Unknown")
        description = getattr(config, "description", "")
        enable_memory = getattr(config, "enable_memory", False)
    
    info = {
        "agent_id": agent_id,
        "name": name,
        "description": description,
        "model": "",
        "status": "running",
        "memory_enabled": enable_memory,
        "tools_count": 0,
    }

    # 获取模型信息
    if hasattr(agent, "config"):
        config = agent.config
        if hasattr(config, "llm_config"):
            info["model"] = getattr(config.llm_config, "model", "")

    # 获取工具数量
    if hasattr(agent, "tool_executor"):
        executor = agent.tool_executor
        if hasattr(executor, "get_tool_count"):
            info["tools_count"] = executor.get_tool_count()

    return info


def get_agent_from_state(agent_id: str = "default"):
    """从 app state 获取 Agent"""
    state = _get_app_state()
    if not state:
        return None
    return state.get("agents", {}).get(agent_id)


@router.get("", response_model=List[AgentInfo])
async def list_agents(request: Request):
    """列出所有 Agent"""
    request_id = _get_request_id(request)
    state = _get_app_state()

    agents = []
    if state:
        agent_dict = state.get("agents", {})
        for agent_id, agent in agent_dict.items():
            info = agent_to_info(agent)
            agents.append(AgentInfo(**info))

    # 也从配置文件加载
    config = load_agents_config()
    if config and "agents" in config:
        for agent_cfg in config["agents"]:
            agent_id = agent_cfg.get("agent_id", "unknown")
            # 检查是否已存在
            if not any(a.agent_id == agent_id for a in agents):
                agents.append(AgentInfo(
                    agent_id=agent_id,
                    name=agent_cfg.get("name", "Unknown"),
                    description=agent_cfg.get("description", ""),
                    model=agent_cfg.get("model", ""),
                    status="config_only",
                ))

    return agents


@router.get("/{agent_id}", response_model=AgentInfo)
async def get_agent(request: Request, agent_id: str = FastAPIPath(...)):
    """获取 Agent 详情"""
    request_id = _get_request_id(request)

    agent = get_agent_from_state(agent_id)
    if not agent:
        # 尝试从配置加载
        config = load_agents_config()
        if config and "agents" in config:
            for agent_cfg in config["agents"]:
                if agent_cfg.get("agent_id") == agent_id:
                    return AgentInfo(
                        agent_id=agent_id,
                        name=agent_cfg.get("name", "Unknown"),
                        description=agent_cfg.get("description", ""),
                        model=agent_cfg.get("model", ""),
                        status="config_only",
                    )
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    info = agent_to_info(agent)
    return AgentInfo(**info)


@router.post("", response_model=AgentInfo)
async def create_agent(request: Request, body: CreateAgentRequest):
    """创建 Agent"""
    request_id = _get_request_id(request)

    try:
        from neurova.agent_core import Agent, AgentConfig

        agent_id = str(uuid.uuid4())[:8]
        workspace_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "agent_workspaces", agent_id)
        os.makedirs(workspace_path, exist_ok=True)
        config = AgentConfig(
            name=body.name,
            agent_id=agent_id,
            enable_memory=body.enable_memory,
            workspace_path=workspace_path,
        )

        agent = Agent(config=config)

        # 添加到全局状态
        state = _get_app_state()
        if state:
            agents = state.get("agents", {})
            agents[agent_id] = agent

        info = agent_to_info(agent)
        return AgentInfo(**info)

    except Exception as e:
        logger.error(f"Create agent error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create agent: {str(e)}")


@router.delete("/{agent_id}")
async def delete_agent(request: Request, agent_id: str = FastAPIPath(...)):
    """删除 Agent"""
    request_id = _get_request_id(request)

    state = _get_app_state()
    if not state:
        raise HTTPException(status_code=503, detail="App state not available")

    agents = state.get("agents", {})
    if agent_id not in agents:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    # 关闭 Agent
    agent = agents[agent_id]
    if hasattr(agent, "shutdown"):
        try:
            agent.shutdown()
        except Exception as e:
            logger.warning(f"Agent shutdown error: {e}")

    # 移除
    del agents[agent_id]

    return {"code": 0, "message": f"Agent '{agent_id}' deleted"}


@router.get("/{agent_id}/stats")
async def get_agent_stats(request: Request, agent_id: str = FastAPIPath(...)):
    """获取 Agent 统计"""
    request_id = _get_request_id(request)

    agent = get_agent_from_state(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    stats = {
        "agent_id": agent_id,
        "uptime": 0,
        "conversations": 0,
        "messages": 0,
        "tools_used": 0,
        "memories": 0,
    }

    # 获取统计信息
    if hasattr(agent, "get_stats"):
        try:
            agent_stats = agent.get_stats()
            stats.update(agent_stats)
        except Exception as e:
            logger.warning(f"Get agent stats error: {e}")

    return {"code": 0, "data": stats}


@router.post("/{agent_id}/switch")
async def switch_agent(request: Request, agent_id: str = FastAPIPath(...)):
    """切换默认 Agent"""
    request_id = _get_request_id(request)

    state = _get_app_state()
    if not state:
        raise HTTPException(status_code=503, detail="App state not available")

    agents = state.get("agents", {})
    if agent_id not in agents:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    state["default_agent_id"] = agent_id

    return {"code": 0, "message": f"Switched to agent '{agent_id}'"}


@router.get("/{agent_id}/constitution")
async def get_constitution(request: Request, agent_id: str = FastAPIPath(...)):
    """获取 Agent 宪法"""
    request_id = _get_request_id(request)

    agent = get_agent_from_state(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    constitution = {}
    if hasattr(agent, "get_constitution"):
        try:
            constitution = agent.get_constitution()
        except Exception as e:
            logger.warning(f"Get constitution error: {e}")

    return {"code": 0, "data": {"constitution": constitution}}


@router.put("/{agent_id}/constitution")
async def update_constitution(
    request: Request,
    agent_id: str = FastAPIPath(...),
    body: UpdateConstitutionRequest = Body(...),
):
    """更新 Agent 宪法"""
    request_id = _get_request_id(request)

    agent = get_agent_from_state(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    if hasattr(agent, "update_constitution"):
        try:
            agent.update_constitution(body.constitution)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to update constitution: {str(e)}")

    return {"code": 0, "message": "Constitution updated"}


@router.post("/{agent_id}/decision")
async def make_decision(
    request: Request,
    agent_id: str = FastAPIPath(...),
    body: DecisionRequest = Body(...),
):
    """请求 Agent 做出决策"""
    request_id = _get_request_id(request)

    agent = get_agent_from_state(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    try:
        # 使用 Agent 的 chat 方法进行决策
        prompt = f"请根据以下上下文做出决策:\n\n上下文: {body.context}"
        if body.options:
            prompt += f"\n\n可选项: {', '.join(body.options)}"
        if body.constraints:
            prompt += f"\n\n约束条件: {', '.join(body.constraints)}"

        response = await agent.chat(user_input=prompt)

        return {
            "code": 0,
            "data": {
                "decision": response,
                "agent_id": agent_id,
            },
        }
    except Exception as e:
        logger.error(f"Decision error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Decision failed: {str(e)}")


@router.post("/{agent_id}/rebuild-loop")
async def rebuild_loop(request: Request, agent_id: str = FastAPIPath(...), model: str = Query(default=None)):
    """重建 Agent Loop（热切换模型）"""
    request_id = _get_request_id(request)

    agent = get_agent_from_state(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    loop_rebuilt = False
    try:
        if hasattr(agent, "rebuild_loop"):
            loop_rebuilt = agent.rebuild_loop(model=model)
    except Exception as e:
        logger.error(f"Rebuild loop error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Rebuild loop failed: {str(e)}")

    return {
        "code": 0,
        "data": {
            "loop_rebuilt": loop_rebuilt,
            "agent_id": agent_id,
            "model": model,
        },
    }
