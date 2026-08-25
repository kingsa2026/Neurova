"""
ACP 消息协议 API — Agent 间标准消息通信端点

提供：
- GET  /agents            列出已注册到 ACP 的 Agent
- POST /agents/register   把运行时 Agent 注册到 ACP
- POST /send              同步派发消息（fire-and-forget）
- POST /request           请求-响应（等待接收方 TASK_RESULT）
- POST /teams/orchestrate AgentTeam 多角色步骤编排
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from neurova.core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


class ACPRegisterRequest(BaseModel):
    """Agent 注册请求"""

    agent_ids: Optional[List[str]] = None  # None 注册全部运行时 Agent


class ACPSendRequest(BaseModel):
    """消息派发请求"""

    sender_id: str = "system"
    receiver_id: str
    action: str = "chat"
    params: Dict[str, Any] = {}
    data: Dict[str, Any] = {}


class ACPRequestMessage(ACPSendRequest):
    """请求-响应消息（额外等待超时）"""

    timeout: float = 30.0


class TeamMemberSpec(BaseModel):
    """编排团队成员（agent 与角色绑定）"""

    agent_id: str
    role: str = "participant"  # coordinator/author/reviewer/...


class TeamOrchestrateRequest(BaseModel):
    """AgentTeam 多角色编排请求"""

    goal: str
    steps: List[Dict[str, Any]]  # [{"role": "author", "action": "chat", "params": {"task": "..."}}]
    members: Optional[List[TeamMemberSpec]] = None  # 不传则用已注册 Agent（role=participant）
    step_timeout: float = 30.0


@router.get("/agents")
async def list_acp_agents():
    """列出已注册到 ACP 的 Agent"""
    from neurova.agent.protocols.acp_runtime import get_acp_runtime

    runtime = get_acp_runtime()
    return {"agents": runtime.list_agents(), "stats": runtime.get_stats()}


@router.post("/agents/register")
async def register_acp_agents(request: ACPRegisterRequest):
    """把运行时 Agent 注册到 ACP 消息中枢"""
    from neurova.agent.protocols.agent_adapter import register_runtime_agents

    try:
        result = register_runtime_agents(request.agent_ids)
        return {"code": 0, "message": "success", "data": result}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"ACP 注册失败: {str(e)}")


@router.post("/send")
async def acp_send(request: ACPSendRequest):
    """同步派发 ACP 消息（fire-and-forget）"""
    from neurova.agent.protocols.acp_runtime import get_acp_runtime
    from neurova.agent.protocols.message_protocol import AgentMessage, MessageType

    runtime = get_acp_runtime()
    if request.receiver_id not in runtime.list_agents():
        raise HTTPException(status_code=404, detail=f"接收方未注册: {request.receiver_id}")

    message = AgentMessage(
        type=MessageType.TASK_ASSIGNMENT,
        sender_id=request.sender_id,
        receiver_id=request.receiver_id,
        action=request.action,
        params=request.params,
        data=request.data,
    )
    delivery = runtime.send(message)
    return {
        "code": 0,
        "message": "sent",
        "data": {
            "message_id": delivery.message_id,
            "status": delivery.status.value if hasattr(delivery.status, "value") else str(delivery.status),
        },
    }


@router.post("/request")
async def acp_request(request: ACPRequestMessage):
    """请求-响应：等待接收方返回 TASK_RESULT"""
    from neurova.agent.protocols.acp_runtime import get_acp_runtime
    from neurova.agent.protocols.message_protocol import AgentMessage, MessageType

    runtime = get_acp_runtime()
    if request.receiver_id not in runtime.list_agents():
        raise HTTPException(status_code=404, detail=f"接收方未注册: {request.receiver_id}")

    message = AgentMessage(
        type=MessageType.TASK_ASSIGNMENT,
        sender_id=request.sender_id,
        receiver_id=request.receiver_id,
        action=request.action,
        params=request.params,
        data=request.data,
    )
    reply = await runtime.request(message, timeout=request.timeout)
    if reply is None:
        raise HTTPException(status_code=504, detail=f"等待响应超时（{request.timeout}s）")

    return {
        "code": 0,
        "message": "success",
        "data": {
            "message_id": reply.message_id,
            "sender": reply.sender_id,
            "action": reply.action,
            "result": reply.data,
        },
    }


@router.post("/teams/orchestrate")
async def acp_team_orchestrate(request: TeamOrchestrateRequest):
    """AgentTeam 多角色步骤编排

    steps 每步: {"role": "author|reviewer|coordinator|...", "action": "chat",
                 "params": {"task": "该步骤的任务描述"}}
    角色需已通过 /agents/register 注册（角色→成员映射由 AgentTeam 管理）。
    """
    from neurova.agent.protocols.acp_runtime import get_acp_runtime
    from neurova.agent.team import AgentTeam
    from neurova.api.endpoints import get_agent_instance

    runtime = get_acp_runtime()
    team = AgentTeam(runtime=runtime)

    # 成员构建：优先用请求指定的 agent→role 映射，否则用全部已注册 Agent
    if request.members:
        member_specs = [(m.agent_id, m.role) for m in request.members]
    else:
        member_specs = [(aid, "participant") for aid in runtime.list_agents()]

    for agent_id, role in member_specs:
        agent = get_agent_instance(agent_id)
        if agent is None:
            continue
        try:
            from neurova.agent.templates.collaboration_template import AgentRole

            role_enum = AgentRole(role)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"未知角色: {role}")
        team.add_member(agent_id, role_enum, _wrap_handler(agent))

    if not team.list_members():
        raise HTTPException(status_code=400, detail="团队成员为空：请先注册 Agent 到 ACP")

    try:
        orchestration = await team.orchestrate(request.goal, request.steps, step_timeout=request.step_timeout)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"编排失败: {str(e)}")

    return {
        "code": 0,
        "message": "success",
        "data": {
            "trace_id": getattr(orchestration, "trace_id", None),
            "steps": [
                {
                    "role": getattr(s, "role", None) and getattr(s.role, "value", str(s.role)),
                    "agent_id": getattr(s, "agent_id", ""),
                    "success": getattr(s, "success", False),
                    "result": getattr(s, "result", None),
                    "error": getattr(s, "error", None),
                    "duration": getattr(s, "duration", 0.0),
                }
                for s in getattr(orchestration, "steps", [])
            ],
        },
    }


def _wrap_handler(agent: Any):
    """复用 agent_adapter 的消息处理器"""
    from neurova.agent.protocols.agent_adapter import make_agent_handler

    return make_agent_handler(agent)
