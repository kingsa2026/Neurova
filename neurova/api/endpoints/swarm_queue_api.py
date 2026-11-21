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
