"""协作房间端点 — 群聊房间的读取与发言入口（挂 /v1/collaboration/rooms）。

薄控制器：仅做鉴权、成员归属解析、编排调用；逻辑在 RoomStore/RoomBus/RoomTurnRouter。
实时订阅复用既有 session_sync WS/SSE（session_id=room_id），此处不新增传输端点。

S9：房间发言经 handleRoomSwarmReply 回灌蜂群审批/候选（人在环闭环）；另开
审批判定 / 候选拦截 / pending 读面三个动作端点——鉴权复用既有三级谓词
（admin/owner/成员），判定与拦截限群主/admin（群主制度），不新造权限体系。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from neurova.api.auth import get_current_user
from neurova.api.endpoints import get_agent_instance
from neurova.collaboration.collaboration_isolation import MemberRole, get_collaboration_manager
from neurova.collaboration.room_store import get_room_store
from neurova.collaboration.room_turn_router import get_room_turn_router
from neurova.core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


class PostMessageBody(BaseModel):
    text: str


class StartCollaborationBody(BaseModel):
    """S11 入口二：房间"发起协作"动作的请求体。"""

    task: str
    budget_seconds: Optional[float] = None
    max_members: Optional[int] = None


class ApprovalDecisionBody(BaseModel):
    decision: str  # approve | reject
    note: str = ""


class UpdateRoomBody(BaseModel):
    """编辑房间：名称/描述/默认应答者 + 期望成员全集（做增删 diff）。"""

    name: Optional[str] = None
    description: Optional[str] = None
    responder_agent_id: Optional[str] = None
    members: Optional[List[str]] = None


def _require_project(room_id: str) -> Any:
    manager = get_collaboration_manager()
    if manager is None:
        raise HTTPException(status_code=503, detail="Collaboration service not available")
    project = manager.get_project(room_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Room '{room_id}' not found")
    return project


def _room_actor(current_user: Dict[str, Any]) -> str:
    return str(current_user.get("user_id") or current_user.get("id") or "")


def _require_room_member(project: Any, actor: str, current_user: Dict[str, Any]) -> None:
    """三级鉴权谓词（admin/owner/成员）——房间全部动作端点共用同一判据。"""
    members = project.members or {}
    if not (current_user.get("role") == "admin" or actor == project.owner_id or actor in members):
        raise HTTPException(status_code=403, detail="仅房间成员可执行该操作")


def _require_room_decisioner(project: Any, actor: str, current_user: Dict[str, Any]) -> None:
    """判定/拦截权限 = 群主（project.owner_id）或平台 admin（群主制度；与桥接同口径）。"""
    _require_room_member(project, actor, current_user)
    if not (current_user.get("role") == "admin" or actor == project.owner_id):
        raise HTTPException(
            status_code=403,
            detail="仅群主或平台管理员可判定/拦截；普通成员的房间回复将记为议见")


def _agent_display_name(agent_id: str) -> str:
    """解析 agent 显示名（get_agent_instance.config.name）；未加载/异常则回落 id。"""
    try:
        agent = get_agent_instance(agent_id)
        name = getattr(getattr(agent, "config", None), "name", None) if agent is not None else None
        return name or agent_id
    except Exception:  # noqa: BLE001 - 名称解析失败回落 id，不阻断房间
        return agent_id


def _member_dicts(project: Any) -> List[Dict[str, str]]:
    # 成员 id → 显示名（房间头/@提及/resolve_targets 全链路一致）；过滤空 id（/start 未传 owner 的历史脏行）。
    return [{"id": mid, "name": _agent_display_name(mid)} for mid in (project.members or {}).keys() if mid]


@router.get("/rooms/{room_id}")
async def get_room(room_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    project = _require_project(room_id)
    meta = getattr(project, "metadata", {}) or {}
    return {
        "code": 0,
        "message": "success",
        "data": {
            "id": project.project_id,
            "name": project.name,
            "description": project.description,
            "owner": getattr(project, "owner_id", ""),
            "members": _member_dicts(project),
            "responder_agent_id": meta.get("responder_agent_id", ""),
        },
    }


@router.get("/rooms/{room_id}/messages")
async def get_room_messages(
    room_id: str,
    limit: int = Query(default=200, ge=1, le=500),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    _require_project(room_id)
    return {"code": 0, "message": "success", "data": get_room_store().history(room_id, limit=limit)}


@router.post("/rooms/{room_id}/messages")
async def post_room_message(
    room_id: str,
    body: PostMessageBody,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    project = _require_project(room_id)
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text 不能为空")
    actor = _room_actor(current_user)
    # §3.1-P2（2026-11-16 审计）：发言成员校验——与 update_room 同一判据
    # （admin/owner/成员）；否则任意登录用户可向任意房间写入并消耗他人 agent token。
    _require_room_member(project, actor, current_user)
    meta = getattr(project, "metadata", {}) or {}
    await get_room_turn_router().handle_user_message(
        room_id, text, actor, _member_dicts(project), meta.get("responder_agent_id", "")
    )
    # S9 人在环闭环：房间回复回灌蜂群审批/候选（无 pending 时为普通聊天，不动作）
    from neurova.agent.approval_chain import handleRoomSwarmReply

    bridge = handleRoomSwarmReply(
        room_id, actor, isAdmin=current_user.get("role") == "admin", text=text)
    return {"code": 0, "message": "success", "data": {"ok": True, "swarm_bridge": bridge}}


@router.post("/rooms/{room_id}/collaboration")
async def start_room_collaboration(
    room_id: str,
    body: StartCollaborationBody,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """S11 入口二：用户经房间"发起协作"动作直发多 agent 协作。

    发起人须为房间成员（三级鉴权谓词复用）；编排交 SwarmManager（与入口一
    同一套引擎）；执行事件回房间广播，终态报告以 candidate 落房间。
    """
    project = _require_project(room_id)
    actor = _room_actor(current_user)
    _require_room_member(project, actor, current_user)
    text = (body.task or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="task 不能为空")
    meta = getattr(project, "metadata", {}) or {}
    result = await get_room_turn_router().orchestrateRoomCollaboration(
        room_id, text, actor, _member_dicts(project),
        responder_agent_id=meta.get("responder_agent_id", ""),
        budgetSeconds=body.budget_seconds,
        maxMembers=body.max_members,
    )
    if not result.get("success"):
        raise HTTPException(status_code=409, detail=result.get("error", "协作发起未成功"))
    return {"code": 0, "message": "success", "data": result}


@router.get("/rooms/{room_id}/swarm/pending")
async def room_swarm_pending(
    room_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """房间当前待裁决审批单与可拦截候选（S9 房间呈现面的读数）。"""
    project = _require_project(room_id)
    _require_room_member(project, _room_actor(current_user), current_user)
    from neurova.agent.approval_chain import roomPendingApprovals, roomPendingCandidates

    return {
        "code": 0,
        "message": "success",
        "data": {
            "approvals": roomPendingApprovals(room_id),
            "candidates": roomPendingCandidates(room_id),
        },
    }


@router.post("/rooms/{room_id}/approvals/{request_id}/decide")
async def decide_room_approval(
    room_id: str,
    request_id: str,
    body: ApprovalDecisionBody,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """房间审批卡显式判定（群主/admin；普通成员走房间回复记议见）。"""
    project = _require_project(room_id)
    actor = _room_actor(current_user)
    _require_room_decisioner(project, actor, current_user)
    from neurova.agent.approval_chain import (
        clearRoomApprovalPending,
        decideSwarmApproval,
    )
    from neurova.collaboration.room_bus import publishRoomSystemMessage

    result = decideSwarmApproval(
        request_id, body.decision, note=str(body.note or ""),
        decidedBy=actor, decidedByChannel="room",
    )
    if not result.get("success"):
        raise HTTPException(status_code=409, detail=result.get("error", "裁决未生效"))
    clearRoomApprovalPending(request_id)
    # S10：批准的是团队沉淀提议（team_consolidation）时，把登记的成员+职责快照
    # 落成固定团队（人批准才写 teams_api；两个裁决入口共用同一回灌单源）。
    if str(result.get("decision")) == "approve":
        try:
            from neurova.api.endpoints import teams_api

            applied = teams_api.applyTeamProposalDecision(
                request_id, "approve", decidedBy=actor)
            if applied.get("applied"):
                result["team_created"] = applied.get("team")
        except Exception as e:  # noqa: BLE001 - 沉淀回灌失败不影响裁决本身
            logger.warning("团队沉淀回灌失败 (%s): %s", request_id, e)
        # S13 收尾（波M 移交项②）：批准的是项目治理申请（人类成员写入/可见性放宽）
        # 时，同点回灌生效——与团队沉淀同一裁决出口、同一回灌单源
        # （applyProjectGovernanceDecision），等待预算耗尽后房间裁决仍能落地。
        try:
            from neurova.tool_executor import applyProjectGovernanceDecision

            projectApplied = applyProjectGovernanceDecision(
                request_id, decidedBy=actor,
                decidedByChannel=str(result.get("decided_by_channel") or "room"))
            if projectApplied.get("applied"):
                result["project_governance_applied"] = projectApplied
        except Exception as e:  # noqa: BLE001 - 治理回灌失败不影响裁决本身
            logger.warning("项目治理回灌失败 (%s): %s", request_id, e)
    verb = "批准" if body.decision == "approve" else "驳回"
    publishRoomSystemMessage(
        room_id,
        f"【裁决】{actor} 已{verb}审批单 {request_id}（生效）",
        meta={"kind": "swarm_approval", "request_id": request_id,
              "status": result.get("status", ""), "decided_by": actor},
    )
    return {"code": 0, "message": "success", "data": result}


@router.post("/rooms/{room_id}/candidates/{candidate_id}/{action}")
async def room_candidate_action(
    room_id: str,
    candidate_id: str,
    action: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """房间候选直接处置：intercept（拦截否决）/ merge（采纳 CAS 合入）——群主/admin。"""
    project = _require_project(room_id)
    actor = _room_actor(current_user)
    _require_room_decisioner(project, actor, current_user)
    act = str(action or "").strip().lower()
    if act not in ("intercept", "merge"):
        raise HTTPException(status_code=400, detail="action 仅支持 intercept/merge")
    from neurova.agent.swarm import get_swarm_manager

    outcome = get_swarm_manager().applyRoomCandidateAction(candidate_id, act, actor=actor)
    if not outcome.get("success"):
        raise HTTPException(status_code=409, detail=outcome.get("error", "候选处置未生效"))
    return {"code": 0, "message": "success", "data": outcome}


class EscalationResolveBody(BaseModel):
    """房间升级卡处置请求（M13）。"""

    action: str = "steer"  # steer（注入指示继续）/ cancel（叫停）
    note: str = ""


@router.post("/rooms/{room_id}/escalations/{subagent_id}/resolve")
async def resolve_room_escalation(
    room_id: str,
    subagent_id: str,
    body: EscalationResolveBody,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """M13（拍板接提交口）：房间升级卡处置——steer（注入指示继续）/ cancel（叫停）。

    复用既有编排单源机制，不新造语义：steer 走 SwarmManager.updateSubagent
    （SteerQueue 注入，成员下一工具轮可见）；cancel 走 SwarmManager.cancelRun
    （幂等叫停落账）。判定权 = admin/群主（与审批裁决同口径）；处置结果以
    system 消息上墙（kind=swarm_escalate、status=resolved）闭环。
    """
    project = _require_project(room_id)
    actor = _room_actor(current_user)
    _require_room_decisioner(project, actor, current_user)
    action = str(body.action or "").strip().lower()
    if action not in ("steer", "cancel"):
        raise HTTPException(status_code=400, detail="action 仅支持 steer/cancel")
    note = str(body.note or "").strip()
    if action == "steer" and not note:
        raise HTTPException(status_code=400, detail="steer 处置必须附指示内容（note）")
    from neurova.agent.swarm import get_swarm_manager

    swarm = get_swarm_manager()
    if action == "cancel":
        result = swarm.cancelRun(subagent_id, reason=note or f"房间升级处置（{actor}）")
    else:
        result = await swarm.updateSubagent(subagent_id, note, mode="steer")
    if not result.get("success", True):
        raise HTTPException(status_code=409, detail=str(result.get("error") or "处置未生效"))
    from neurova.collaboration.room_bus import publishRoomSystemMessage

    verb = "叫停" if action == "cancel" else "注入指示"
    publishRoomSystemMessage(
        room_id,
        f"【升级处置】{actor} 对 {subagent_id} {verb}：{note or '（无备注）'}",
        meta={"kind": "swarm_escalate", "subagent_id": subagent_id,
              "status": "resolved", "resolve_action": action, "decided_by": actor},
    )
    return {"code": 0, "message": "success",
            "data": {"success": True, "action": action, "subagent_id": subagent_id}}


@router.put("/rooms/{room_id}")
async def update_room(
    room_id: str,
    body: UpdateRoomBody,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """编辑已发起的协作房间（admin/owner/成员可编）：名称/描述/默认应答者 + 成员增删。"""
    manager = get_collaboration_manager()
    if manager is None:
        raise HTTPException(status_code=503, detail="Collaboration service not available")
    project = manager.get_project(room_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Room '{room_id}' not found")

    uid = str(current_user.get("user_id") or current_user.get("id") or "")
    is_admin = current_user.get("role") == "admin"
    members = project.members or {}
    # 鉴权：admin / owner / 成员
    if not (is_admin or uid == project.owner_id or uid in members):
        raise HTTPException(status_code=403, detail="无权编辑该房间")
    # update_project 内部校验“调用者需为成员且可编辑”；owner 恒为成员，故用 owner_id 作写入者。
    write_user = project.owner_id or uid

    updates: Dict[str, Any] = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.description is not None:
        updates["description"] = body.description
    if body.responder_agent_id is not None:
        updates["metadata"] = {"responder_agent_id": body.responder_agent_id}
    if updates:
        manager.update_project(room_id, write_user, updates)

    if body.members is not None:
        desired = {m for m in body.members if m}
        current = {m for m in members.keys() if m}
        for mid in current - desired:
            if mid != project.owner_id:  # owner 永不被移除
                manager.remove_project_member(room_id, write_user, mid)
        for mid in desired - current:
            manager.add_project_member(room_id, write_user, mid, MemberRole.EDITOR)

    return {"code": 0, "message": "success", "data": {"ok": True}}
