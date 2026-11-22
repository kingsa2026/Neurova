# -*- coding: utf-8 -*-
"""U8 park 查询端点（D-T2 已拍板：REST 轮询；WS 推送/webhook 不做）。

模型/调用方凭 park_id 幂等取回长命令的迟交结果：

- ``GET /v1/tools/park/{park_id}``——running 返回轮询提示（poll_after）；
  completed 返回完整工具结果；failed 返回诚实失败原因（如超 park 上限）。
  同一 park_id 重复查询返回同一份已存结果（幂等）。

鉴权与工具面同源（登录用户）；结果读取走 ``tool_executor.parkResultSnapshot``
单一事实源（进程内主存 → 落盘副本），本模块不自建第二份存储。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from neurova.api.auth import get_current_user
from neurova.core.logger import get_logger
from neurova.tool_executor import parkResultSnapshot

logger = get_logger(__name__)

#: 鉴权同工具面（tool_schema 同款装配：登录用户可查）。
router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/park/{park_id}")
async def getParkedToolResult(park_id: str):
    """按 park_id 幂等查询 park 中的长命令结果（U8 迟交回灌的 REST 取回面）。"""
    entry: Optional[dict] = parkResultSnapshot(park_id)
    if entry is None:
        raise HTTPException(
            status_code=404, detail=f"park_id 不存在或已过期: {park_id}")
    status = str(entry.get("status") or "running")
    data = {
        "park_id": park_id,
        "tool_name": entry.get("tool_name"),
        "status": status,
        "poll_after": entry.get("poll_after"),
        "max_wait_s": entry.get("max_wait_s"),
        "parked_at": entry.get("parked_at"),
        "completed_at": entry.get("completed_at"),
    }
    if status == "completed":
        data["success"] = bool(entry.get("success"))
        data["result"] = entry.get("result")
    elif status == "failed":
        data["success"] = False
        data["error"] = entry.get("error")
    return {"code": 0, "message": "ok", "data": data}
