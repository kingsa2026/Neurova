"""
治理中心 API — Governance Endpoint

功能（方案 P0-1.5 + 人工确认弹窗）:
1. 白名单 CRUD: GET/POST /api/v1/governance/whitelist, DELETE /{entry_id}
2. 审批流: GET /approvals/pending, POST /{request_id}/approve（批准后重放执行）,
   POST /{request_id}/reject
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal, Optional

from neurova.security.approval_relay import hasApprovalWaiter

from fastapi import APIRouter, Depends, HTTPException, Query, Request
import typing

from neurova.api.deps import require_admin

# 模块级依赖实例：测试可用 dependency_overrides 覆盖
_governance_admin_dep = require_admin()
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
async def list_whitelist(request: Request, _admin: Any = Depends(_governance_admin_dep)):
    """列出白名单条目"""
    gov = _get_governance()
    return {"code": 0, "data": {"entries": gov.list_whitelist_entries()}}


@router.post("/whitelist")
async def add_whitelist(request: Request, body: WhitelistEntryRequest, _admin: Any = Depends(_governance_admin_dep)):
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
async def delete_whitelist(request: Request, entry_id: str, _admin: Any = Depends(_governance_admin_dep)):
    """删除白名单条目"""
    gov = _get_governance()
    if not gov.remove_whitelist_entry(entry_id):
        raise HTTPException(status_code=404, detail=f"白名单条目不存在: {entry_id}")
    return {"code": 0, "message": "已删除"}


# ── 审批流 ──────────────────────────────────────────────────────


@router.get("/approvals/pending")
async def list_pending_approvals(
    request: Request,
    surface: typing.Optional[str] = Query(default=None, description="按调用面过滤（P1-2 HITL surface）"), _admin: Any = Depends(_governance_admin_dep),):
    """待审批列表。

    surface 参数（P1-2 HITL surface 安全模型）：传 service_api/openapi/console
    时按接收方裁剪表过滤——API 面只见 web 表单来源，console 面只收
    console/backstage；无 surface 声明的存量请求保守默认仅 console 可见。
    缺省（不过滤）行为不变。
    """
    am = _get_approvals()
    pending = am.get_pending_requests()
    if surface:
        from neurova.security.hitl_surface import filter_requests_for_surface

        pending = filter_requests_for_surface(pending, surface)
    return {"code": 0, "data": {"requests": [r.to_dict() for r in pending]}}


@router.get("/approvals/{request_id}")
async def get_approval_detail(request: Request, request_id: str, _admin: Any = Depends(_governance_admin_dep)):
    """审批请求详情"""
    am = _get_approvals()
    req = am.get_request(request_id)
    if req is None:
        raise HTTPException(status_code=404, detail=f"审批请求不存在: {request_id}")
    return {"code": 0, "data": {"request": req.to_dict()}}


def _deliverApprovalOutcome(agent: Any, metadata: Dict[str, Any], tool_name: str,
                            result: Any) -> bool:
    """把带外批准的执行终态投进会话的晚到通路；返回是否真的投出去了。

    三条纪律：
    - 成败判据**不自持**，走 `ToolExecutor._result_is_success`（全仓唯一判据），
      在这里重推一遍就是造第二份定义。
    - 投递目标是 `agent.tool_executor.tool_coordinator` —— 必须是 agent 自己那个
      实例。`ChatPipeline.tool_executor` 是 `agent.tool_executor` 的 property，
      换一个 executor 就等于投进一个没人排水的 coordinator（静默丢单）。
    - 没有回投地址（A 之前创建的老审批单、或带外手工建的请求）要**明说**无法回投，
      静默丢弃正是本片在修的病；再拿静默丢弃去"修"静默丢弃没有意义。
    """
    coordinator = getattr(getattr(agent, "tool_executor", None), "tool_coordinator", None)
    if coordinator is None:
        logger.warning("审批重放无法回投：agent 未装配 tool_coordinator（工具 %s）", tool_name)
        return False

    executor = getattr(agent, "tool_executor", None)
    judge = getattr(executor, "_result_is_success", None)
    success = bool(judge(result)) if callable(judge) else bool(
        isinstance(result, dict) and result.get("success")
    )
    error = None
    if not success and isinstance(result, dict):
        error = str(result.get("error") or result.get("message") or "")[:400] or "执行失败"

    coordinator.recordApprovalOutcome(
        tool_name,
        metadata.get("tool_call_id"),
        success=success,
        session_id=metadata.get("session_id"),
        result=result if success else None,
        error=error,
    )
    if not metadata.get("tool_call_id"):
        logger.warning(
            "审批重放结果已投递但缺回投地址（tool_call_id 缺失，会话 %r）："
            "模型侧只能看到工具名，配不上是哪一次调用",
            metadata.get("session_id"),
        )
    return True


@router.post("/approvals/{request_id}/approve")
async def approve_and_execute(request: Request, request_id: str,
                              body: ApprovalActionRequest, _admin: Any = Depends(_governance_admin_dep)):
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

    # R3-4：kind=profile_grant 的审批批准后落附身授权（无 tool_name 重放，
    # 批准本身即授权动作，须在下方"无可重放内容"早返回之前处理）。
    if metadata.get("kind") == "profile_grant":
        try:
            from neurova.security.profile_grant import mint_from_approval

            minted = mint_from_approval(metadata, approved_by=str(body.approved_by or ""))
            logger.info("profile 附身授权已铸造: %s (minted=%s)", request_id, minted)
        except Exception as _pg_err:  # noqa: BLE001
            logger.warning("profile 授权铸造失败: %s", _pg_err)

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

    # G5-B/C：有人在等（咽喉仍阻塞在本次调用上）→ **不在这里重放**。
    # 咽喉醒来后会在完整管线里执行（钩子/超时/审计/大输出折叠一条不缺）；
    # 端点再放一次就是同一条命令跑两遍——对 exec_command 这类工具是正确性问题。
    if hasApprovalWaiter(request_id):
        logger.info("审批 %s 由等待中的原调用执行，端点不重放", request_id)
        return {
            "code": 0,
            "data": {"approved": True, "executed": False, "resumed_in_turn": True},
        }

    executor = ToolExecutor(agent)
    result = await executor._execute_single_tool(tool_name, params, skip_governance=True)
    logger.info("审批 %s 已批准并重放执行: %s", request_id, tool_name)

    # 带外批准（原轮次早已收尾）→ 终态必须回到会话，否则模型那次调用永远停在
    # 「待用户确认」而工具其实已经跑完。走的是与"超时转后台"同一条晚到通路。
    _deliverApprovalOutcome(agent, metadata, tool_name, result)

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
                          body: ApprovalActionRequest, _admin: Any = Depends(_governance_admin_dep)):
    """拒绝审批请求"""
    am = _get_approvals()
    req = am.get_request(request_id)
    if req is None:
        raise HTTPException(status_code=404, detail=f"审批请求不存在: {request_id}")
    if not am.reject_request(request_id, rejected_by=body.approved_by, note=body.note):
        raise HTTPException(status_code=500, detail="拒绝操作失败")
    logger.info("审批 %s 已拒绝", request_id)

    # 拒绝也要有终态：有人在等时中继已把它叫醒（返回 approval_denied）；
    # 无人等（原轮次已收尾）则与批准同路投递晚到提示，否则模型那次调用
    # 永远停在「待用户确认」——用户其实已经答复了，只是答复没人送回去。
    if not hasApprovalWaiter(request_id):
        agent = _get_agent()
        reqMeta = (getattr(req, "metadata", None) or {}) if req else {}
        toolName = str(reqMeta.get("tool_name") or "")
        coordinator = getattr(getattr(agent, "tool_executor", None), "tool_coordinator", None)
        if agent is not None and toolName and coordinator is not None:
            coordinator.recordApprovalOutcome(
                toolName,
                reqMeta.get("tool_call_id"),
                success=False,
                session_id=reqMeta.get("session_id"),
                error=f"用户拒绝了该操作: {body.note or '未说明原因'}",
            )

    return {"code": 0, "data": {"approved": False}}


# ── RSI 升级提案审批出口（遗留事项 ①） ─────────────────────────
# SelfImprovementProposer 的 escalation 提案保持 PENDING 等待人工评审，
# 但此前无任何 API 消费 approve_and_apply/reject_proposal——发散升级提案
# 永远滞留。此处委托 RSI 单例（agent_core 注入 evolution 单例）暴露审批面。


_RSI_NOT_READY = "RSI 编排器未初始化：本轮没有可报的进化状态（不是进化一切正常）"


def _rsi_not_ready(agent_id: str) -> "HTTPException":
    return HTTPException(
        status_code=503,
        detail=f"agent {agent_id!r} 上没有 RSI 编排器：{_RSI_NOT_READY}",
    )


def _get_rsi_orchestrator(agent_id: Optional[str] = None):
    """按 agent 定位 RSI 编排器 —— 与 `_get_agent()` 同源，不读进程级单例属性。

    历史实现是 `getattr(get_evolution_orchestrator(), "rsi_orchestrator", None)`：
    每个 agent 构造编排器时都往那**一个**属性上写，后构造者覆盖前者，于是
    "待审列表 / 批准 / 拒绝"永远作用在最后那个 agent 上（工单 011 证据）。
    指名了 agent 而它不在池中时返回 None 而**不回落**：回落到默认 agent 等于把
    批准动作装进别人的技能库，是本单要拆的缺陷而不是可接受的兜底。
    """
    state = None
    from neurova.api.endpoints import get_app_state

    state = get_app_state()
    if not state:
        return None
    try:
        agent = state.get_agent(agent_id) if agent_id else state.get_agent()
    except Exception:  # noqa: BLE001 - 与 _get_agent() 的既有容错同形
        agent = None
    return getattr(agent, "rsi_orchestrator", None) if agent is not None else None


class RsiApproveRequest(BaseModel):
    """RSI 提案批准"""

    approved_by: str = Field(..., min_length=1, description="批准者（人类评审 gate）")
    tool_sequence: Optional[List[str]] = Field(
        default=None,
        description="批准人补交的可执行工具序列；manifest 缺 tool_sequence 时必须在此补上，"
        "否则该提案按 not_supported 拒绝（工单 010）",
    )


class RsiRejectRequest(BaseModel):
    """RSI 提案拒绝"""

    reason: str = ""


@router.get("/rsi/status")
async def get_rsi_status(
    agent_id: Optional[str] = None, _admin: Any = Depends(_governance_admin_dep)
):
    """RSI 状态只读面（工单 012）：阶段、最近一轮晋升判据三态、候选统计、回滚留痕、告警。

    这里**不**提供 `available:false` 的静默 200：`orchestrator.get_status()` 此前
    生产零调用方，而"RSI 根本没装配"与"RSI 跑了一轮什么都没改"在观测上是两件
    相反的事，压成同一个 200 就是把前者读成后者（工单 011 同一条证据）。
    """
    rsi = _get_rsi_orchestrator(agent_id)
    if rsi is None:
        raise _rsi_not_ready(agent_id)
    return {"code": 0, "data": rsi.get_status()}


@router.get("/rsi/proposals/pending")
async def list_pending_rsi_proposals(
    agent_id: Optional[str] = None, _admin: Any = Depends(_governance_admin_dep)
):
    """列出 RSI 升级提案（PENDING 状态）"""
    rsi = _get_rsi_orchestrator(agent_id)
    if rsi is None:
        raise _rsi_not_ready(agent_id)
    proposer = rsi.self_improvement_proposer
    proposals = [p.to_dict() for p in proposer.list_pending_proposals()]
    return {"code": 0, "data": {"proposals": proposals, "agent_id": rsi.agent_id}}


@router.get("/rsi/proposals")
async def list_rsi_proposals(
    state: Literal["all", "pending", "applied", "rejected", "rolled_back"] = "all",
    agent_id: Optional[str] = None,
    _admin: Any = Depends(_governance_admin_dep),
):
    """全状态提案列表。只有 PENDING 可见时，"批准过什么、结果如何"永久消失，
    回滚与事后审计都无从下手（工单 011，读的是工单 010 的 `list_all_proposals()`）。"""
    rsi = _get_rsi_orchestrator(agent_id)
    if rsi is None:
        raise _rsi_not_ready(agent_id)
    proposer = rsi.self_improvement_proposer
    proposals = (
        proposer.list_all_proposals() if state == "all"
        else [p for p in proposer.list_all_proposals() if p.status.value == state]
    )
    return {
        "code": 0,
        "data": {
            "proposals": [p.to_dict() for p in proposals],
            "state": state,
            "agent_id": rsi.agent_id,
        },
    }


@router.post("/rsi/proposals/{proposal_id}/approve")
async def approve_rsi_proposal(
    proposal_id: str,
    body: RsiApproveRequest,
    agent_id: Optional[str] = None,
    _admin: Any = Depends(_governance_admin_dep),
):
    """人工批准并应用 RSI 升级提案（状态机守卫：仅 PENDING）"""
    rsi = _get_rsi_orchestrator(agent_id)
    if rsi is None:
        raise _rsi_not_ready(agent_id)
    result = rsi.self_improvement_proposer.approve_and_apply(
        proposal_id, approver=body.approved_by, tool_sequence=body.tool_sequence
    )
    if result is None or not getattr(result, "success", False):
        error = getattr(result, "error", "") or "批准失败"
        if "not found" in error:
            raise HTTPException(status_code=404, detail=error)
        raise HTTPException(status_code=409, detail=error)
    logger.info("RSI 提案 %s 已批准并应用（by %s）", proposal_id, body.approved_by)
    # 生效证据（工单 010）：装了哪个技能、回灌后注册表是否真取得到。
    # 只回 "applied: true" 就是本单拆掉的那个假象本身。
    return {
        "code": 0,
        "data": {
            "applied": True,
            "applied_skill_id": getattr(result, "applied_skill_id", ""),
            "registry_hit": bool(getattr(result, "registry_hit", False)),
            "result": getattr(result, "to_dict", lambda: {})(),
        },
    }


@router.post("/rsi/proposals/{proposal_id}/reject")
async def reject_rsi_proposal(
    proposal_id: str,
    body: RsiRejectRequest,
    agent_id: Optional[str] = None,
    _admin: Any = Depends(_governance_admin_dep),
):
    """拒绝 RSI 升级提案（状态机守卫：仅 PENDING）"""
    rsi = _get_rsi_orchestrator(agent_id)
    if rsi is None:
        raise _rsi_not_ready(agent_id)
    if not rsi.self_improvement_proposer.reject_proposal(proposal_id, reason=body.reason):
        raise HTTPException(
            status_code=404,
            detail=f"提案不存在或非 PENDING 状态: {proposal_id}",
        )
    logger.info("RSI 提案 %s 已拒绝", proposal_id)
    return {"code": 0, "data": {"rejected": True}}


# ── 技能归档读面 + 回滚写面（工单 011）────────────────────────


class SkillRollbackRequest(BaseModel):
    """技能回滚动作"""

    operator: str = Field(..., min_length=1, description="操作者（回滚留痕要记是谁按的）")
    agent_id: Optional[str] = Field(default=None, description="目标 agent；留空取默认 agent")


def _skill_rollback_context(agent_id: Optional[str] = None):
    """按 agent 定位回滚面所需的 (存档库, 注册表, 技能服务)。

    三者必须**同源同一 agent**：存档库里的 skill_id 只能经该 agent 的注册表
    取到执行体，写盘也只能写回该 agent 的技能库。取不到就返回 None ——
    调用方据此返 503，而不是回落到默认 agent（那会把回滚装进别人的技能库）。
    """
    state = None
    from neurova.api.endpoints import get_app_state

    state = get_app_state()
    if not state:
        return None
    try:
        agent = state.get_agent(agent_id) if agent_id else state.get_agent()
    except Exception:  # noqa: BLE001 - 与 _get_agent() 的既有容错同形
        agent = None
    if agent is None:
        return None
    registry = getattr(agent, "skill_registry", None) or getattr(agent, "_skill_registry", None)
    if registry is None:
        return None
    resolved_id = str(getattr(getattr(agent, "config", None), "agent_id", "") or agent_id or "default")
    from neurova.evolution.skill_experience import get_skill_experience_store
    from neurova.skills import library_service as _lib

    try:
        service = _lib.get_library(_lib.POOL_AGENT, resolved_id)
    except ValueError as bad_key:
        logger.warning("技能库路由非法（agent_id=%s）：%s", resolved_id, bad_key)
        return None
    return get_skill_experience_store(), registry, service


def _skill_surface_not_ready(agent_id: Optional[str]) -> "HTTPException":
    return HTTPException(
        status_code=503,
        detail=(
            f"agent {agent_id!r} 上没有可用的技能回滚面（注册表或技能库未装配）："
            "无法区分'没有归档'与'没装配'，故不返回空列表"
        ),
    )


@router.get("/skills/{skill_id}/archives")
async def list_skill_archives(
    skill_id: str,
    agent_id: Optional[str] = None,
    _admin: Any = Depends(_governance_admin_dep),
):
    """归档读面：该技能保留的可回滚快照（由重建与回滚有界写入）。

    `get_archives` 此前在顶层 `neurova/` 零生产调用方 —— 归档只写不读，
    等于没有回滚窗口（人无从知道能退回哪一版）。
    """
    context = _skill_rollback_context(agent_id)
    if context is None:
        raise _skill_surface_not_ready(agent_id)
    store, _registry, _service = context
    return {
        "code": 0,
        "data": {"skill_id": skill_id, "archives": store.get_archives(skill_id)},
    }


@router.post("/skills/{skill_id}/rollback")
async def rollback_skill_to_archive(
    skill_id: str,
    body: SkillRollbackRequest,
    _admin: Any = Depends(_governance_admin_dep),
):
    """回滚到最近一次归档的定义（写面：留痕可选审计）。

    归档为空时显式 409 拒绝：静默成功会让"按钮点了没反应"变成"看起来回滚了"
    ——那正是本单要消灭的形态。回滚后工具面随之变化，依赖 006 的停用生效判据。
    """
    context = _skill_rollback_context(body.agent_id)
    if context is None:
        raise _skill_surface_not_ready(body.agent_id)
    store, registry, service = context
    if not store.get_archives(skill_id):
        raise HTTPException(
            status_code=409,
            detail=f"技能 {skill_id} 没有可回滚的归档（空归档不得静默成功）",
        )
    if not store.rollback_skill(
        skill_id, registry, skill_service=service, operator=body.operator
    ):
        raise HTTPException(
            status_code=409,
            detail=f"技能 {skill_id} 回滚未生效（注册表里取不到该技能或落盘失败）",
        )
    logger.info("技能 %s 已回滚至最近归档（操作者 %s）", skill_id, body.operator)
    return {
        "code": 0,
        "data": {
            "rolled_back": True,
            "skill_id": skill_id,
            "operator": body.operator,
            "archives_left": len(store.get_archives(skill_id)),
        },
    }


# ── 治理设置（治理遗留收口 2026-09-05） ────────────────────────
# 独立于 /v1/settings 扁平 kv 的治理设置面：Step9.96 LLM 成本门控与
# RSI 部署阶段的管理入口，require_admin + JSON 持久化。


def _governance_settings_path():
    from neurova.security.governance_settings import settings_path

    return settings_path()


# ── Agent 运行限制设置（Token 预算 / Loop 轮次，2026-09-07）──


@router.get("/agent-limits")
async def get_agent_limits(admin=Depends(_governance_admin_dep)):
    """Agent 运行限制（仅管理员）：token_budget / max_loop_rounds"""
    from neurova.security.agent_limits_settings import get_effective_limits

    return {"code": 0, "data": get_effective_limits()}


class AgentLimitsUpdate(BaseModel):
    """Agent 运行限制更新"""

    token_budget: Optional[int] = Field(None, ge=1000, le=10_000_000)
    max_loop_rounds: Optional[int] = Field(None, ge=2, le=200)


@router.put("/agent-limits")
async def update_agent_limits(body: AgentLimitsUpdate, admin=Depends(_governance_admin_dep)):
    """更新 Agent 运行限制（仅管理员）"""
    from neurova.security.agent_limits_settings import (
        get_effective_limits,
        save_agent_limits,
    )

    payload = {k: v for k, v in body.model_dump().items() if v is not None}
    if not payload:
        raise HTTPException(status_code=422, detail="无有效更新字段")
    if not save_agent_limits(payload):
        raise HTTPException(status_code=500, detail="Agent 运行限制保存失败")
    return {"code": 0, "data": get_effective_limits()}


# ── 工具结果溢出阈值（P1-#6，2026-09-13 设置-高级）──────────────────


def _tool_offload_payload() -> dict:
    from neurova.security import tool_offload_settings as tos

    return {
        "threshold_kb": tos.get_threshold_kb(),
        "min_kb": tos.MIN_THRESHOLD_KB,
        "max_kb": tos.MAX_THRESHOLD_KB,
        "default_kb": tos.DEFAULT_THRESHOLD_KB,
    }


@router.get("/tool-offload")
async def get_tool_offload(admin=Depends(_governance_admin_dep)):
    """工具结果溢出阈值（仅管理员）：可重现大结果超阈值落工作区文件留指针"""
    return {"code": 0, "data": _tool_offload_payload()}


class ToolOffloadUpdate(BaseModel):
    """工具溢出阈值更新（范围外 422；8–512KB，2026-09-13 拍板）"""

    threshold_kb: int = Field(..., ge=8, le=512)


@router.put("/tool-offload")
async def update_tool_offload(body: ToolOffloadUpdate, admin=Depends(_governance_admin_dep)):
    """更新工具结果溢出阈值（仅管理员）"""
    from neurova.security import tool_offload_settings as tos

    if not tos.save_settings({"threshold_kb": body.threshold_kb}):
        raise HTTPException(status_code=500, detail="工具溢出阈值保存失败")
    return {"code": 0, "data": _tool_offload_payload()}


@router.get("/settings")
async def get_governance_settings(admin=Depends(_governance_admin_dep)):
    """治理设置（仅管理员）"""
    from neurova.security.governance_settings import load_governance_settings

    return {"code": 0, "data": load_governance_settings()}


# ── LLM 429 重试设置──


@router.get("/llm-retry")
async def get_llm_retry_settings(admin=Depends(_governance_admin_dep)):
    """LLM 429 重试/切换容错参数（仅管理员）"""
    from neurova.security.llm_retry_settings import get_effective_llm_retry_settings

    return {"code": 0, "data": get_effective_llm_retry_settings()}


class LlmRetrySettingsUpdate(BaseModel):
    """LLM 429 重试设置更新

    max_retries：同模型最大等待重试次数；interval：重试间隔秒（服务端
    Retry-After 优先）；wait_cap：单次等待封顶秒；max_switches：连续失败
    模型容错数（任一模型成功出内容即归零重计）。
    """

    max_retries: Optional[int] = Field(None, ge=0, le=50)
    interval: Optional[float] = Field(None, ge=1.0, le=600.0)
    wait_cap: Optional[float] = Field(None, ge=1.0, le=3600.0)
    max_switches: Optional[int] = Field(None, ge=1, le=20)


@router.put("/llm-retry")
async def update_llm_retry_settings(body: LlmRetrySettingsUpdate, admin=Depends(_governance_admin_dep)):
    """更新 LLM 429 重试设置（仅管理员；env 显式设置仍优先于持久化值）"""
    from neurova.security.llm_retry_settings import (
        get_effective_llm_retry_settings,
        save_llm_retry_settings,
    )

    payload = {k: v for k, v in body.model_dump().items() if v is not None}
    if not payload:
        raise HTTPException(status_code=422, detail="无有效更新字段")
    if not save_llm_retry_settings(payload):
        raise HTTPException(status_code=500, detail="LLM 429 重试设置保存失败")
    return {"code": 0, "data": get_effective_llm_retry_settings()}


class GovernanceSettingsUpdate(BaseModel):
    """治理设置更新（rsi_phase: 0..4；conversation_rules_enabled: LLM 成本门控；
    metacog_gate_enabled: V3 调控门，命中教训的工具执行前拦截；
    crystallization_llm_gate_enabled: 结晶候选是否送 LLM 裁决（关=直写存储引擎）；
    skill_auto_retire_enabled: 技能淘汰是否执行禁用（关=只上报候选）；
    compression_economics_enabled: 压缩经济性判据（关=沿用既有"必然装不下就
    等比缩小"的行为，默认关 ⇒ 现网零变更）"""

    conversation_rules_enabled: Optional[bool] = None
    rsi_phase: Optional[int] = Field(None, ge=0, le=4)
    metacog_gate_enabled: Optional[bool] = None
    crystallization_llm_gate_enabled: Optional[bool] = None
    skill_auto_retire_enabled: Optional[bool] = None
    compression_economics_enabled: Optional[bool] = None


@router.put("/settings")
async def update_governance_settings(body: GovernanceSettingsUpdate, admin=Depends(_governance_admin_dep)):
    """更新治理设置（仅管理员）"""
    from neurova.security.governance_settings import (
        load_governance_settings,
        save_governance_settings,
    )

    payload = {k: v for k, v in body.model_dump().items() if v is not None}
    if not payload:
        raise HTTPException(status_code=422, detail="无有效更新字段")
    if not save_governance_settings(payload):
        raise HTTPException(status_code=500, detail="治理设置保存失败")
    return {"code": 0, "data": load_governance_settings()}


# ── 桌面动作审计（R3-4， §3）──


@router.get("/desktop-audit")
async def list_desktop_audit(
    request: Request,
    tool: Optional[str] = Query(default=None, description="按工具名过滤"),
    user: Optional[str] = Query(default=None, description="按用户 ID 过滤"),
    days: int = Query(default=7, ge=0, le=365, description="时间窗（天），0=不限"),
    needs_human: Optional[bool] = Query(default=None, description="只看需人工行"),
    limit: int = Query(default=200, ge=1, le=2000),
    _admin: Any = Depends(_governance_admin_dep),
):
    """桌面动作审计查询（仅管理员；元数据白名单，无内容字段）。"""
    import time

    from neurova.security.desktop_audit import get_desktop_audit_store

    since = (time.time() - days * 86400) if days else None
    rows = get_desktop_audit_store().query_actions(
        tool=tool, user=user, since=since, needs_human=needs_human, limit=limit
    )
    return {"code": 0, "data": {"entries": rows}}


# ── profile 附身授权管理（R3-4）─────────────────────────────────


class ProfileGrantRequest(BaseModel):
    user_id: str
    profile: str
    scope: str = Field("session", description="task/session/long")


@router.get("/profile-grants")
async def list_profile_grants(request: Request, _admin: Any = Depends(_governance_admin_dep)):
    """列出有效 profile 授权（仅管理员）。"""
    from neurova.security.profile_grant import get_profile_grant_store

    return {"code": 0, "data": {"grants": get_profile_grant_store().list_grants()}}


@router.post("/profile-grants")
async def mint_profile_grant(request: Request, body: ProfileGrantRequest, _admin: Any = Depends(_governance_admin_dep)):
    """直接铸造 profile 授权（管理员显式授予；正常路径走审批批准后自动铸造）。"""
    from neurova.security.profile_grant import get_profile_grant_store

    ok = get_profile_grant_store().mint(body.user_id, body.profile, scope=body.scope, approved_by="admin")
    if not ok:
        raise HTTPException(status_code=422, detail="授权铸造失败（user_id/profile 不能为空）")
    return {"code": 0, "data": {"granted": True}}


@router.delete("/profile-grants")
async def revoke_profile_grant(
    request: Request, user_id: str = Query(...), profile: str = Query(...),
    _admin: Any = Depends(_governance_admin_dep),
):
    """撤销 profile 授权。"""
    from neurova.security.profile_grant import get_profile_grant_store

    ok = get_profile_grant_store().revoke(user_id, profile)
    if not ok:
        raise HTTPException(status_code=404, detail="无该授权")
    return {"code": 0, "data": {"revoked": True}}
