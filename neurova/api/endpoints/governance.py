"""
治理中心 API — Governance Endpoint

功能（方案 P0-1.5 + 人工确认弹窗）:
1. 白名单 CRUD: GET/POST /api/v1/governance/whitelist, DELETE /{entry_id}
2. 审批流: GET /approvals/pending, POST /{request_id}/approve（批准后重放执行）,
   POST /{request_id}/reject
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()


# ── 依赖获取 ────────────────────────────────────────────────────


def _get_governance():
    from neurova.security.governance import get_governance

    return get_governance()


def _get_approvals():
    from neurova.security.approval_manager import get_approval_manager

    return get_approval_manager()


def _pending_status():
    from neurova.security.approval_manager import ApprovalStatus

    return ApprovalStatus.PENDING


def _get_agent():
    from neurova.api.endpoints import get_app_state

    state = get_app_state()
    if not state:
        return None
    try:
        return state.get_agent()
    except Exception:
        agent = state.get("agent")
        return agent


class WhitelistEntryRequest(BaseModel):
    """新增白名单条目"""

    pattern: str = Field(..., min_length=1, description="匹配模式")
    match_type: str = Field("prefix", description="prefix / exact / regex")
    tool: Optional[str] = Field(None, description="限定工具名；空为全局")
    note: str = Field("", description="备注")


class ApprovalActionRequest(BaseModel):
    """审批动作"""

    note: str = ""
    approved_by: str = "user"


# ── 白名单 ──────────────────────────────────────────────────────


@router.get("/whitelist")
async def list_whitelist(request: Request):
    """列出白名单条目"""
    gov = _get_governance()
    return {"code": 0, "data": {"entries": gov.list_whitelist_entries()}}


@router.post("/whitelist")
async def add_whitelist(request: Request, body: WhitelistEntryRequest):
    """新增白名单条目"""
    if body.match_type not in ("prefix", "exact", "regex"):
        raise HTTPException(status_code=422, detail="match_type 必须是 prefix/exact/regex")
    gov = _get_governance()
    entry = gov.add_whitelist_entry(
        pattern=body.pattern.strip(),
        match_type=body.match_type,
        tool=body.tool or None,
        note=body.note,
    )
    logger.info("白名单新增: %s (%s)", body.pattern, body.match_type)
    return {"code": 0, "data": {"entry": entry}}


@router.delete("/whitelist/{entry_id}")
async def delete_whitelist(request: Request, entry_id: str):
    """删除白名单条目"""
    gov = _get_governance()
    if not gov.remove_whitelist_entry(entry_id):
        raise HTTPException(status_code=404, detail=f"白名单条目不存在: {entry_id}")
    return {"code": 0, "message": "已删除"}


# ── 审批流 ──────────────────────────────────────────────────────


@router.get("/approvals/pending")
async def list_pending_approvals(request: Request):
    """待审批列表"""
    am = _get_approvals()
    pending = [r.to_dict() for r in am.get_pending_requests()]
    return {"code": 0, "data": {"requests": pending}}


@router.get("/approvals/{request_id}")
async def get_approval_detail(request: Request, request_id: str):
    """审批请求详情"""
    am = _get_approvals()
    req = am.get_request(request_id)
    if req is None:
        raise HTTPException(status_code=404, detail=f"审批请求不存在: {request_id}")
    return {"code": 0, "data": {"request": req.to_dict()}}


@router.post("/approvals/{request_id}/approve")
async def approve_and_execute(request: Request, request_id: str,
                              body: ApprovalActionRequest):
    """
    批准并重放执行。

    批准该审批请求后，立即按 metadata 中存储的 tool_name/params 重放执行，
    返回真实执行结果。重放跳过治理预检（skip_governance），因为本次执行
    已经获得用户授权。
    """
    am = _get_approvals()
    req = am.get_request(request_id)
    if req is None:
        raise HTTPException(status_code=404, detail=f"审批请求不存在: {request_id}")
    if req.status != _pending_status():
        raise HTTPException(status_code=409, detail=f"审批请求状态为 {req.status}，无法批准")

    metadata: Dict[str, Any] = req.metadata or {}
    tool_name = metadata.get("tool_name")
    params = metadata.get("params") or {}

    if not am.approve_request(request_id, approved_by=body.approved_by, note=body.note):
        raise HTTPException(status_code=500, detail="批准操作失败")

    # 无可重放内容（纯记录型请求）→ 仅返回批准结果
    if not tool_name:
        return {"code": 0, "data": {"approved": True, "executed": False}}

    agent = _get_agent()
    if agent is None:
        return {
            "code": 0,
            "data": {"approved": True, "executed": False,
                     "message": "Agent 未就绪，稍后可通过历史记录手动执行"},
        }

    from neurova.tool_executor import ToolExecutor

    executor = ToolExecutor(agent)
    result = await executor._execute_single_tool(tool_name, params, skip_governance=True)
    logger.info("审批 %s 已批准并重放执行: %s", request_id, tool_name)
    return {"code": 0, "data": {"approved": True, "executed": True, "result": result}}


@router.post("/approvals/{request_id}/reject")
async def reject_approval(request: Request, request_id: str,
                          body: ApprovalActionRequest):
    """拒绝审批请求"""
    am = _get_approvals()
    req = am.get_request(request_id)
    if req is None:
        raise HTTPException(status_code=404, detail=f"审批请求不存在: {request_id}")
    if not am.reject_request(request_id, rejected_by=body.approved_by, note=body.note):
        raise HTTPException(status_code=500, detail="拒绝操作失败")
    logger.info("审批 %s 已拒绝", request_id)
    return {"code": 0, "data": {"approved": False}}
