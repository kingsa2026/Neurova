"""
治理中心 API — Governance Endpoint

功能（方案 P0-1.5 + 人工确认弹窗）:
1. 白名单 CRUD: GET/POST /api/v1/governance/whitelist, DELETE /{entry_id}
2. 审批流: GET /approvals/pending, POST /{request_id}/approve（批准后重放执行）,
   POST /{request_id}/reject
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal, Optional

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
    # 审批记忆（补课 3.2）：None=仅本次 / "exact"=记住精确命令 / "similar"=记住同类
    remember: Optional[Literal["exact", "similar"]] = Field(
        None, description="None/exact/similar"
    )


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

    if not am.approve_request(
        request_id, approved_by=body.approved_by, note=body.note, remember=body.remember
    ):
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

    # E3（P2）：MCP 工具 + remember 批准 → 铸造 (server, tool) 粒度持久授权，
    # 后续同名调用免审批直达（命令级 remember 由 ApprovalManager 负责，二者互补）
    if getattr(body, "remember", None) and str(tool_name).startswith("mcp."):
        try:
            from neurova.security.mcp_grants import get_tool_grant_store, parse_mcp_tool_name

            mcp_parts = parse_mcp_tool_name(tool_name)
            if mcp_parts:
                get_tool_grant_store().mint_grant(*mcp_parts, approved_by=str(body.approved_by or ""))
                logger.info("已铸造 MCP 工具持久授权: %s", tool_name)
        except Exception as _mint_err:
            logger.warning("MCP 工具授权铸造失败: %s", _mint_err)

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


# ── RSI 升级提案审批出口（遗留事项 ①） ─────────────────────────
# SelfImprovementProposer 的 escalation 提案保持 PENDING 等待人工评审，
# 但此前无任何 API 消费 approve_and_apply/reject_proposal——发散升级提案
# 永远滞留。此处委托 RSI 单例（agent_core 注入 evolution 单例）暴露审批面。


def _get_rsi_orchestrator():
    from neurova.evolution.closed_loop import get_evolution_orchestrator

    return getattr(get_evolution_orchestrator(), "rsi_orchestrator", None)


class RsiApproveRequest(BaseModel):
    """RSI 提案批准"""

    approved_by: str = Field(..., min_length=1, description="批准者（人类评审 gate）")


class RsiRejectRequest(BaseModel):
    """RSI 提案拒绝"""

    reason: str = ""


@router.get("/rsi/proposals/pending")
async def list_pending_rsi_proposals():
    """列出 RSI 升级提案（PENDING 状态）"""
    rsi = _get_rsi_orchestrator()
    if rsi is None:
        return {"code": 0, "data": {"proposals": [], "available": False}}
    proposer = rsi.self_improvement_proposer
    proposals = [p.to_dict() for p in proposer.list_pending_proposals()]
    return {"code": 0, "data": {"proposals": proposals, "available": True}}


@router.post("/rsi/proposals/{proposal_id}/approve")
async def approve_rsi_proposal(proposal_id: str, body: RsiApproveRequest):
    """人工批准并应用 RSI 升级提案（状态机守卫：仅 PENDING）"""
    rsi = _get_rsi_orchestrator()
    if rsi is None:
        raise HTTPException(status_code=503, detail="RSI 编排器未初始化")
    result = rsi.self_improvement_proposer.approve_and_apply(
        proposal_id, approver=body.approved_by
    )
    if result is None or not getattr(result, "success", False):
        error = getattr(result, "error", "") or "批准失败"
        if "not found" in error:
            raise HTTPException(status_code=404, detail=error)
        raise HTTPException(status_code=409, detail=error)
    logger.info("RSI 提案 %s 已批准并应用（by %s）", proposal_id, body.approved_by)
    return {"code": 0, "data": {"applied": True, "result": getattr(result, "to_dict", lambda: {})()}}


@router.post("/rsi/proposals/{proposal_id}/reject")
async def reject_rsi_proposal(proposal_id: str, body: RsiRejectRequest):
    """拒绝 RSI 升级提案（状态机守卫：仅 PENDING）"""
    rsi = _get_rsi_orchestrator()
    if rsi is None:
        raise HTTPException(status_code=503, detail="RSI 编排器未初始化")
    if not rsi.self_improvement_proposer.reject_proposal(proposal_id, reason=body.reason):
        raise HTTPException(
            status_code=404,
            detail=f"提案不存在或非 PENDING 状态: {proposal_id}",
        )
    logger.info("RSI 提案 %s 已拒绝", proposal_id)
    return {"code": 0, "data": {"rejected": True}}
