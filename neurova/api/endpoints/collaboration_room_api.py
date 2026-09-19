"""协作房间端点 — 群聊房间的读取与发言入口（挂 /v1/collaboration/rooms）。

薄控制器：仅做鉴权、成员归属解析、编排调用；逻辑在 RoomStore/RoomBus/RoomTurnRouter。
实时订阅复用既有 session_sync WS/SSE（session_id=room_id），此处不新增传输端点。
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

router = APIRouter()


class PostMessageBody(BaseModel):
    text: str


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
    actor = str(current_user.get("user_id") or current_user.get("id") or "")
    meta = getattr(project, "metadata", {}) or {}
    await get_room_turn_router().handle_user_message(
        room_id, text, actor, _member_dicts(project), meta.get("responder_agent_id", "")
    )
    return {"code": 0, "message": "success", "data": {"ok": True}}


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
