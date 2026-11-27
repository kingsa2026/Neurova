# -*- coding: utf-8 -*-
"""B4：排队 run 管理面 REST（/v1/swarm-queue，admin 门）。

读：GET      /                        队列有序快照（位次/优先级/任务书/入队时刻）
改：PATCH    /{subagent_id}/priority  调整优先级（返回新位次）
取消：DELETE /{subagent_id}           出队并落诚实终态（failed/subagent_cancelled）
修订：POST   /{subagent_id}/task      任务书修订（排队改写/在跑 steer/不可为诚实拒绝）

单源在 ``run_queue.RunQueue`` + ``SwarmManager`` 管理方法；本路由只做协议面。
未知/不在队 id 诚实 404；在跑 run 的 steer 不可达等业务性拒绝以 200+mode=rejected
如实返回（决策非故障）。
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from neurova.api.auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])


async def requireAdmin(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """admin 门：队列管理是运维面，非 admin 403。"""
    if str((current_user or {}).get("role") or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="swarm 队列管理面仅限管理员")
    return current_user


class PriorityBody(BaseModel):
    priority: str


class TaskBody(BaseModel):
    task: str


class GrantBody(BaseModel):
    kind: str
    team_id: str = ""
    session_key: str = ""
    run_id: str = ""
    action: str
    level: str
    expires_at: str


GRANT_API_ENV = "NEUROVA_SWARM_GRANT_API"


def _grantApiEnabled() -> None:
    if (os.environ.get(GRANT_API_ENV) or "").strip().lower() not in ("1", "true", "on", "yes"):
        raise HTTPException(status_code=404, detail="审批 grant 管理面未开启")


def _grantActor(admin: Dict[str, Any]) -> str:
    actor = str(admin.get("user_id") or admin.get("id") or "").strip()
    if not actor:
        raise HTTPException(status_code=403, detail="无法确定 grant 操作者")
    return actor


def _grantDeadline(value: str) -> float:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="expires_at 必须是带时区的 ISO 时间") from exc
    if parsed.tzinfo is None:
        raise HTTPException(status_code=400, detail="expires_at 必须带时区")
    deadline = parsed.timestamp()
    if deadline <= time.time():
        raise HTTPException(status_code=400, detail="expires_at 必须晚于当前时间")
    return deadline


@router.get("/grants", dependencies=[Depends(_grantApiEnabled)])
async def listApprovalGrants(
    team_id: str = "", session_key: str = "",
    _admin: Dict[str, Any] = Depends(requireAdmin),
) -> Dict[str, Any]:
    from neurova.agent.approval_chain import listGrants

    rows = listGrants(team_id=team_id, session_key=session_key)
    for row in rows:
        row["revocable"] = not bool(row.get("revoked"))
    return {"grants": rows}


@router.post("/grants", dependencies=[Depends(_grantApiEnabled)])
async def createApprovalGrant(
    body: GrantBody,
    admin: Dict[str, Any] = Depends(requireAdmin),
) -> Dict[str, Any]:
    from neurova.agent.approval_chain import acceptAlways, acceptSessionGrant

    try:
        common = {
            "action": body.action,
            "level": body.level,
            "granted_by": _grantActor(admin),
            "expires_at": _grantDeadline(body.expires_at),
        }
        if body.kind == "team":
            grant = acceptAlways(body.team_id, **common)
        elif body.kind == "session":
            grant = acceptSessionGrant(
                body.session_key, body.run_id, body.team_id, **common)
        else:
            raise HTTPException(status_code=400, detail="kind 仅支持 team/session")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"grant": grant}


@router.delete("/grants/{grant_id}", dependencies=[Depends(_grantApiEnabled)])
async def revokeApprovalGrant(
    grant_id: str,
    admin: Dict[str, Any] = Depends(requireAdmin),
) -> Dict[str, Any]:
    from neurova.agent.approval_chain import revokeGrant

    if not revokeGrant(grant_id, _grantActor(admin)):
        raise HTTPException(status_code=404, detail="grant 不存在或已撤销")
    return {"grant_id": grant_id, "revoked": True}


def _manager():
    from neurova.agent.swarm import get_swarm_manager

    return get_swarm_manager()


@router.get("")
async def runQueueSnapshot(_admin: Dict[str, Any] = Depends(requireAdmin)) -> Dict[str, Any]:
    """排队 run 有序快照：优先级降序 + 同级先来先服务，位次从 1 起。"""
    queue = _manager().runQueueSnapshot()
    return {"queue": queue, "total": len(queue)}


@router.patch("/{subagent_id}/priority")
async def setPriority(subagent_id: str, body: PriorityBody,
                      _admin: Dict[str, Any] = Depends(requireAdmin)) -> Dict[str, Any]:
    try:
        position = _manager().setRunQueuePriority(subagent_id, body.priority)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"subagent {subagent_id} 不在队列中，无法调整优先级")
    return {"subagent_id": subagent_id, "priority": body.priority, "position": position}


@router.delete("/{subagent_id}")
async def cancelQueued(subagent_id: str,
                       _admin: Dict[str, Any] = Depends(requireAdmin)) -> Dict[str, Any]:
    try:
        return _manager().cancelQueuedRun(subagent_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"subagent {subagent_id} 不在队列中，无法取消")


@router.post("/{subagent_id}/task")
async def editTask(subagent_id: str, body: TaskBody,
                   _admin: Dict[str, Any] = Depends(requireAdmin)) -> Dict[str, Any]:
    manager = _manager()
    state = manager.status(subagent_id)
    # status 的错误形态是 {"error": ...}（无 subagent_id）；run 投影自身带
    # "error": None 键，不能以键存在性判未找到。
    if "subagent_id" not in state:
        raise HTTPException(status_code=404, detail=str(state.get("error") or "未找到子 Agent 运行记录"))
    try:
        return manager.editRunTask(subagent_id, body.task)
    except ValueError as e:  # noqa: PERF203 - 空任务书等入参错误 → 400
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/settle")
async def settleIdleRunsExplicit(
        _admin: Dict[str, Any] = Depends(requireAdmin)) -> Dict[str, Any]:
    """A5 显式驱动：admin 显式触发一次闲置 run 结算（POST /v1/swarm-queue/settle）。

    不受 NEUROVA_SWARM_AUTO_SETTLE 默认关限制——admin 显式调用即执行；
    九重护栏与闲置阈值照常生效。返回结算结果三桶（settled/skipped/failed）。
    """
    return _manager().settleIdleRunsNow()
