# -*- coding: utf-8 -*-
"""跨 agent 审批链（P3-1，评测报告 G-11）：子代理运行中权限请求 → 父代理/用户。

危险分级（Two-Man-Rule 式三档）：
- **L0** 可逆低危：自动放行 + 审批单记账（interactive / auto_approve 皆放行）；
- **L1** 中危：interactive 模式"代理给父"——审批单进既有 ``ApprovalManager``，
  信封投父会话邮箱，父代理用 ``decide_subagent_approval`` 裁决；
  auto_approve 模式自动放行；
- **L2** 高危/不可逆：**强制人工**——任何模式都不自动放行；审批卡经通知中心
  镜像给用户（ApprovalManager 既有出口），父代理或用户裁决。

S9 房间桥接：run 带协作房间（``run.room_id``）时，L1/L2 审批卡同步投递到协作房间
（sender_type=system 房间消息，零新表零新协议）；人在房间回复经
:func:`handleRoomSwarmReply` 回灌 :func:`decideSwarmApproval` 判定——判定权仍在
审批链单源，房间只做"呈现 + 应答回灌"。决策权限复用房间群主制度：仅群主
（project.owner_id）或平台 admin 可判定，普通成员回复只记议见。

单源纪律（教义第 6 条）：审批单只落在既有 ``ApprovalManager``（SQLite 状态机 +
governance API + 站内通知镜像），本模块只做蜂群侧的分级、投递与等待唤醒，
**不建第二套审批存储**。等待/唤醒复用 ``approval_relay``——与工具 ASK 同一条通路；
声明的等级只升不降：动作命中 ``DangerousCommandDetector`` 时 L0 至少升到 L1。
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

LEVEL_L0 = "L0"
LEVEL_L1 = "L1"
LEVEL_L2 = "L2"
LEVELS = (LEVEL_L0, LEVEL_L1, LEVEL_L2)

MODE_INTERACTIVE = "interactive"
MODE_AUTO_APPROVE = "auto_approve"
APPROVAL_MODE_ENV = "NEUROVA_SWARM_APPROVAL_MODE"
APPROVAL_WAIT_ENV = "NEUROVA_SWARM_APPROVAL_WAIT_S"
#: 等待预算默认与审批单过期尺度一致（ApprovalManager.DEFAULT_EXPIRY_SECONDS = 300s）
DEFAULT_WAIT_SECONDS = 300.0


def normalizeLevel(value: str) -> str:
    """审批等级归一：仅接受 L0/L1/L2（大小写容忍），否则 ValueError。"""
    level = str(value or "").strip().upper()
    if level not in LEVELS:
        raise ValueError(f"审批等级仅支持 {LEVELS}，收到 {value!r}")
    return level


def approvalMode() -> str:
    """审批模式：interactive（默认，L1 代理给父）| auto_approve（L0/L1 自动放行）。

    L2 不受模式影响——强制人工不是灰度项。
    """
    raw = (os.environ.get(APPROVAL_MODE_ENV) or "").strip().lower()
    return MODE_AUTO_APPROVE if raw == MODE_AUTO_APPROVE else MODE_INTERACTIVE


def approvalWaitSeconds() -> float:
    """等待裁决的预算（秒）；env 可覆盖，非法回落默认。<=0 视作不阻塞等待。"""
    raw = (os.environ.get(APPROVAL_WAIT_ENV) or "").strip()
    if not raw:
        return DEFAULT_WAIT_SECONDS
    try:
        return float(raw)
    except ValueError:
        logger.warning("审批等待预算 %s=%r 不是数字，回落默认 %ss",
                       APPROVAL_WAIT_ENV, raw, DEFAULT_WAIT_SECONDS)
        return DEFAULT_WAIT_SECONDS


def classifyActionLevel(action: str, declaredLevel: str) -> str:
    """声明的等级只升不降：动作命中危险命令检测时 L0 至少升到 L1。

    L2 声明即生效（不可逆操作的裁决权不在自动规则手里）。
    """
    level = normalizeLevel(declaredLevel)
    if level != LEVEL_L0:
        return level
    try:
        from neurova.security.approval_manager import DangerousCommandDetector

        if DangerousCommandDetector().is_dangerous(str(action or "")):
            return LEVEL_L1
    except Exception as e:  # noqa: BLE001 - 检测器不可用不阻断请求，按声明档处理
        logger.debug("危险命令检测器不可用，按声明档 %s 处理: %s", level, e)
    return level


def _parentEnvelope(
    run: Any, request: Any, declared: str, effective: str, mode: str,
) -> Dict[str, Any]:
    return {
        "kind": "approval_request",
        "request_id": request.request_id,
        "subagent_id": run.subagent_id,
        "agent_id": run.agent_id,
        "agent_name": run.agent_name,
        "task": run.task,
        "action": request.command,
        "reason": request.description,
        "level": declared,
        "effective_level": effective,
        "mode": mode,
        "hint": "用 decide_subagent_approval 裁决；L2 不可逆操作必须转交用户确认",
    }


def _notifyParent(run: Any, envelope: Dict[str, Any]) -> None:
    """审批信封投父会话邮箱——经 ``SwarmManager.pushParentMail`` 唯一写点。

    邮箱写点单源钉子（test_subagentTerminalReachesParentMail）：``get_agent_mailbox``
    的生产面引用只许 swarm.py（写）与 loops/base.py（读）各一处；本模块直连邮箱
    就是第二事实源，故一律经蜂群管理器投递。审批属高优信件（S2 优先级队列），
    固定 ``priority="high"``。
    """
    try:
        from neurova.agent.swarm import get_swarm_manager

        get_swarm_manager().pushParentMail(run, "子代理审批", envelope, priority="high")
    except Exception as e:  # noqa: BLE001 - 通知失败不影响审批单本身
        logger.debug("审批请求邮箱投递失败 (%s): %s", envelope.get("request_id"), e)


def _recordRunApproval(run: Any, entry: Dict[str, Any]) -> None:
    """审批记录挂到 run（可观测面，to_dict 带出）；有界防无界增长。"""
    run.approvals.append(entry)
    if len(run.approvals) > 50:
        del run.approvals[:-50]


# ── 审计单源落点（S8 审批审计持久化）：请求/决定都进 neurova.security.audit_logger ──

APPROVAL_AUDIT_RESOURCE = "swarm_approval"
APPROVAL_REQUEST_ACTION = "swarm_approval_request"
APPROVAL_DECIDE_ACTION = "swarm_approval_decide"

_auditCountersLock = threading.RLock()
_auditCounters: Dict[str, int] = {}


def approvalAuditCounters() -> Dict[str, int]:
    """审批审计写面计数快照（失败可见性的"计数"半边，配 error 日志使用）。"""
    with _auditCountersLock:
        return dict(_auditCounters)


def _bumpAuditCounter(name: str) -> None:
    with _auditCountersLock:
        _auditCounters[name] = _auditCounters.get(name, 0) + 1


def _emitApprovalAudit(
    phase: str,
    operation: str,
    request: Any,
    *,
    actor: str,
    decision: str,
    latencyMs: float,
    runId: str = "",
    agentName: str = "",
    task: str = "",
    level: str = "",
    effective: str = "",
    mode: str = "",
    note: str = "",
    decidedByChannel: str = "",
) -> bool:
    """一次审批请求/决定落审计单源；fail-open——写失败不阻断审批主流程。

    字段对齐方案 S8：级别（level/effective_level）、动作（operation）、
    path_values（run_id/request_id 定位对）、发起 run（run_id/agent_id/
    member_session_id/parent_session_id）、决策人（decided_by/user_id）、
    决策（decision）、时延（latency_ms）。S9 房间回灌时 ``decided_by`` 记决策人的
    房间身份（用户 id），``decided_by_channel`` 标记裁决通道（room/parent_agent）。
    写失败（异常或返回 False）记 ``auditWriteFailures`` 计数 + error 日志，不静默吞。
    """
    from neurova.security.audit_logger import (
        AuditEventType,
        AuditSeverity,
        log_audit,
    )

    meta = getattr(request, "metadata", None) or {}
    requestId = str(getattr(request, "request_id", "") or "")
    runId = str(runId or meta.get("subagent_id") or "")
    level = str(level or meta.get("declared_level") or "")
    effective = str(effective or meta.get("effective_level") or "")
    mode = str(mode or meta.get("mode") or "")
    severityMap = {
        LEVEL_L0: AuditSeverity.LOW,
        LEVEL_L1: AuditSeverity.MEDIUM,
        LEVEL_L2: AuditSeverity.HIGH,
    }
    details: Dict[str, Any] = {
        "phase": phase,
        "request_id": requestId,
        "run_id": runId,
        "agent_id": str(getattr(request, "agent_id", "") or ""),
        "agent_name": str(agentName or ""),
        "task": str(task or "")[:200],
        "member_session_id": str(meta.get("member_session_id") or ""),
        "parent_session_id": str(meta.get("parent_session_id") or ""),
        "operation": str(operation or "")[:200],
        "reason": str(getattr(request, "description", "") or "")[:200],
        "level": level,
        "effective_level": effective,
        "mode": mode,
        "decision": str(decision or ""),
        "decided_by": str(actor or "") if phase == "decide" else "",
        "decided_by_channel": str(decidedByChannel or "") if phase == "decide" else "",
        "note": str(note or "")[:200],
        "path_values": [
            ["run_id", runId],
            ["request_id", requestId],
        ],
        "latency_ms": round(max(0.0, float(latencyMs)), 3),
    }
    try:
        ok = log_audit(
            AuditEventType.APPROVAL,
            severityMap.get(effective, AuditSeverity.MEDIUM),
            user_id=str(actor or ""),
            action=APPROVAL_REQUEST_ACTION if phase == "request" else APPROVAL_DECIDE_ACTION,
            details=details,
            resource_type=APPROVAL_AUDIT_RESOURCE,
            resource_id=runId,
            metadata={"source": "swarm"},
        )
    except Exception as exc:  # noqa: BLE001 - 审计异常不得影响审批主流程
        logger.error("审批审计写入异常（phase=%s request_id=%s）：%s", phase, requestId, exc)
        ok = False
    if not ok:
        _bumpAuditCounter("auditWriteFailures")
        logger.error(
            "审批审计未落库（phase=%s request_id=%s run_id=%s）——审批已生效，这条须人工复核",
            phase, requestId, runId,
        )
    return bool(ok)


def _pendingShape(
    request: Any, effective: str, why: str,
    timeout: bool = False, waited: float = 0.0,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "approved": False,
        "auto_approved": False,
        "pending": True,
        "request_id": request.request_id,
        "level": effective,
        "status": request.status.value,
        "pending_reason": why,
    }
    if timeout:
        payload["approval_timeout"] = True
        payload["waited_seconds"] = waited
    return payload


async def requestRunApproval(
    run: Any, action: str, reason: str = "", level: str = "L1", context: str = "",
) -> Dict[str, Any]:
    """子代理运行中权限请求的完整链路：建单 → 分级处置 → （需人裁时）等待唤醒。

    Returns:
        approved=True  → 可执行（auto 或有人批准）；
        approved=False 且 pending=True → 未获准也不得执行（待审/超时/无循环）；
        approved=False 且 denied=True → 已被明确拒绝。
    """
    from neurova.security.approval_manager import get_approval_manager
    from neurova.auth.user_group_model import currentUserTenantId

    started = time.time()
    act = str(action or "").strip()
    if not act:
        raise ValueError("action 不能为空（说明要请求执行什么操作）")
    declared = normalizeLevel(level)
    effective = classifyActionLevel(act, declared)
    mode = approvalMode()
    manager = get_approval_manager()
    request = manager.create_approval_request(
        agent_id=run.agent_id,
        user_id="",
        command=act[:500],
        description=(str(reason or "").strip()[:500] or "子代理运行中权限请求"),
        danger_reason=f"危险等级 {effective}" + (f"（声明 {declared}）" if effective != declared else ""),
        metadata={
            "source": "swarm",
            "subagent_id": run.subagent_id,
            "member_session_id": run.member_session_id,
            "parent_session_id": run.session_id or "",
            "declared_level": declared,
            "effective_level": effective,
            "mode": mode,
            "context": str(context or "")[:500],
            # A9b（§6.4）：发起者租户随单落档，裁决面据此做同租户校验
            "tenant_id": currentUserTenantId(),
        },
    )
    entry = {
        "request_id": request.request_id,
        "action": act[:200],
        "reason": str(reason or "")[:200],
        "level": declared,
        "effective_level": effective,
        "status": request.status.value,
        "at": time.time(),
    }
    _recordRunApproval(run, entry)
    _emitApprovalAudit(
        "request", act, request,
        actor=run.agent_id, decision="pending",
        latencyMs=(time.time() - started) * 1000,
        runId=run.subagent_id, agentName=run.agent_name, task=run.task,
        level=declared, effective=effective, mode=mode,
    )

    # ── 自动放行支路：L0，或 auto_approve 模式下的 L1 ──
    if effective == LEVEL_L0 or (effective == LEVEL_L1 and mode == MODE_AUTO_APPROVE):
        manager.approve_request(
            request.request_id,
            approved_by=f"auto_rule:{effective}",
            note="低危自动放行" if effective == LEVEL_L0 else "auto_approve 模式放行",
        )
        entry["status"] = "approved"
        _emitApprovalAudit(
            "decide", act, request,
            actor=f"auto_rule:{effective}", decision="approve",
            latencyMs=(time.time() - started) * 1000,
            runId=run.subagent_id, agentName=run.agent_name, task=run.task,
            level=declared, effective=effective, mode=mode,
        )
        return {
            "approved": True, "auto_approved": True, "pending": False,
            "request_id": request.request_id, "level": effective,
            "status": "approved", "decided_by": f"auto_rule:{effective}",
        }

    # ── 需人裁支路：L1(interactive) 代理给父；L2 强制人工 ──
    _notifyParent(run, _parentEnvelope(run, request, declared, effective, mode))
    # S9：run 带协作房间时，审批卡同步上墙（人在房间裁决；L0 自动放行不进房间）
    await notifyRoomApproval(run, request, declared, effective, mode)

    from neurova.security.approval_relay import (
        registerApprovalWaiter,
        unregisterApprovalWaiter,
    )

    waiter = registerApprovalWaiter(request.request_id)
    budget = approvalWaitSeconds()
    if waiter is None or budget <= 0:
        return _pendingShape(
            request, effective,
            "no_event_loop" if waiter is None else "wait_disabled",
        )
    try:
        status = await asyncio.wait_for(waiter, timeout=budget)
    except asyncio.TimeoutError:
        # 与工具 ASK 同语义：让出但不撤单——审批单保留，人工稍后仍可裁决
        unregisterApprovalWaiter(request.request_id, waiter)
        return _pendingShape(request, effective, "timeout", timeout=True, waited=budget)
    except asyncio.CancelledError:
        unregisterApprovalWaiter(request.request_id, waiter)
        raise
    unregisterApprovalWaiter(request.request_id, waiter)

    decided = manager.get_request(request.request_id)
    approved = status == "approved"
    entry["status"] = status
    payload: Dict[str, Any] = {
        "approved": approved, "auto_approved": False, "pending": False,
        "request_id": request.request_id, "level": effective, "status": status,
        "decided_by": (decided.approved_by if decided else "") or "",
        "note": (decided.approval_note if decided else "") or "",
    }
    if not approved:
        payload["denied"] = True
    return payload


def _deciderTenant(actor: str) -> str:
    """裁决人租户（部门根）；查不到/解析失败回落 default。"""
    try:
        from neurova.auth.user_group_model import resolveUserDepartment

        return str((resolveUserDepartment(actor) or {}).get("tenant_id") or "default")
    except Exception:
        return "default"


def _deciderIsPlatformAdmin(actor: str) -> bool:
    """裁决人是否平台 admin（users 表 role）；查询失败按非 admin（fail-closed）。"""
    try:
        from neurova.auth.user_model import UserModel

        model = UserModel()
        user = model.get_user_by_username(actor)
        if user is None:
            try:
                user = model.get_user_by_id(int(actor))
            except (TypeError, ValueError):
                user = None
        return bool(user is not None and getattr(user, "role", "") == "admin")
    except Exception:
        return False


def decideSwarmApproval(
    requestId: str, decision: str, note: str = "",
    decidedBy: str = "", decidedByChannel: str = "parent_agent",
) -> Dict[str, Any]:
    """父代理/房间裁决蜂群审批单（``decide_subagent_approval`` 工具与 S9 房间桥接的
    共同判定单源）。

    只认 ``metadata.source == "swarm"`` 的审批单——通用治理审批仍走 governance API；
    两条入口共享同一存储，职责分开。幂等：非 pending 一律失败返回（
    request/decision 幂等，防重复裁决）。S9：``decidedBy`` 传决策人房间身份（用户 id），
    审批单 approved_by 与审计的 decided_by 均记它；``decidedByChannel`` 标记裁决通道。
    """
    from neurova.security.approval_manager import ApprovalStatus, get_approval_manager

    rid = str(requestId or "").strip()
    if not rid:
        return {"success": False, "error": "request_id 不能为空"}
    act = str(decision or "").strip().lower()
    if act not in ("approve", "reject"):
        return {"success": False, "error": "decision 仅支持 approve/reject"}
    actor = str(decidedBy or "").strip() or "parent_agent"
    channel = str(decidedByChannel or "").strip() or "parent_agent"
    manager = get_approval_manager()
    request = manager.get_request(rid)
    if request is None:
        return {"success": False, "error": f"审批单不存在: {rid}"}
    if (request.metadata or {}).get("source") != "swarm":
        return {"success": False, "error": "非蜂群审批单——通用审批请走 governance 审批接口"}
    if request.status != ApprovalStatus.PENDING:
        return {
            "success": False,
            "error": f"审批单已裁决（status={request.status.value}）——裁决幂等，不重复受理",
        }
    # A9b（§6.4 租户隔离红线）：人裁通道校验裁决人租户==审批单租户（平台 admin
    # 例外）；parent_agent 通道是 L1 代理给父的既有链路（信任链在 spawn 时建立），
    # 不做用户租户判定。存量无租户单按 default 口径。
    if channel != "parent_agent":
        request_tenant = str((request.metadata or {}).get("tenant_id") or "default")
        decider_tenant = _deciderTenant(actor)
        if decider_tenant != request_tenant and not _deciderIsPlatformAdmin(actor):
            return {
                "success": False,
                "error": (
                    f"跨租户裁决被拒（§6.4）：裁决人租户 {decider_tenant!r} != "
                    f"审批单租户 {request_tenant!r}"
                ),
            }
    if act == "approve":
        ok = manager.approve_request(rid, approved_by=actor, note=str(note or ""))
    else:
        ok = manager.reject_request(rid, rejected_by=actor, note=str(note or ""))
    if not ok:
        return {"success": False, "error": "裁决未生效（审批单可能刚过期）"}
    decided = manager.get_request(rid)
    _emitApprovalAudit(
        "decide", request.command, request,
        actor=actor, decision=act,
        latencyMs=(time.time() - request.created_at.timestamp()) * 1000,
        note=str(note or ""), decidedByChannel=channel,
    )
    return {
        "success": True,
        "request_id": rid,
        "decision": act,
        "status": decided.status.value if decided else "",
        "decided_by": actor,
        "decided_by_channel": channel,
        "hint": "裁决结果将唤醒等待中的子代理",
    }


# ── S9 房间桥接：审批/升级/候选 × 协作房间 = 人在环闭环 ──────────────────
#
# 红线：房间只做"呈现 + 应答回灌"，判定权仍在审批链单源（decideSwarmApproval /
# ApprovalManager）。本段不建第二套审批存储——登记表只是"哪张审批单上墙在哪个房间"
# 的进程内索引（pending 匹配用），裁决一律回灌单源。

ROOM_MSG_KIND_APPROVAL = "swarm_approval"
ROOM_MSG_KIND_ESCALATE = "swarm_escalate"
ROOM_MSG_KIND_CANDIDATE = "swarm_candidate"

#: 房间回复的判定意图关键词（中文按子串、英文按词边界；先查拒绝防"不同意"误判）
ROOM_REJECT_KEYWORDS = ("拒绝", "驳回", "否决", "不同意", "reject", "deny")
ROOM_APPROVE_KEYWORDS = ("同意", "批准", "通过", "采纳", "准许", "approve", "yes")
#: 候选的房间动作关键词：拦截（否决候选，不进集成）与采纳（立即 CAS 合入）
ROOM_INTERCEPT_KEYWORDS = ("拦截", "叫停", "否决", "驳回", "拒绝", "intercept", "reject")
ROOM_MERGE_KEYWORDS = ("采纳", "合入", "合并", "通过", "同意", "accept", "merge", "approve")

#: pending 匹配登记表：request_id/candidate_id → room_id（进程内索引，终态即清）
_roomApprovalRegistry: Dict[str, str] = {}
_roomCandidateRegistry: Dict[str, str] = {}
_roomBridgeLock = threading.RLock()
_ROOM_REGISTRY_MAX = 500


def _roomRegistryPut(registry: Dict[str, str], key: str, roomId: str) -> None:
    with _roomBridgeLock:
        if key not in registry and len(registry) >= _ROOM_REGISTRY_MAX:
            oldest = next(iter(registry))
            registry.pop(oldest, None)
        registry[key] = roomId


def _roomRegistryPop(registry: Dict[str, str], key: str) -> None:
    with _roomBridgeLock:
        registry.pop(key, None)


def roomPendingApprovals(roomId: str) -> list:
    """某房间当前上墙待裁决的审批单 id（读面；API/前端刷新用）。"""
    with _roomBridgeLock:
        return [rid for rid, r in _roomApprovalRegistry.items() if r == roomId]


def roomPendingCandidates(roomId: str) -> list:
    """某房间当前可拦截的候选 id（读面；API/前端刷新用）。"""
    with _roomBridgeLock:
        return [cid for cid, r in _roomCandidateRegistry.items() if r == roomId]


def clearRoomApprovalPending(requestId: str) -> None:
    """审批单裁决完成后注销房间 pending 索引（显式判定端点路径用）。"""
    _roomRegistryPop(_roomApprovalRegistry, requestId)


def _matchRoomTarget(
    registry: Dict[str, str], roomId: str, text: str, exactOnly: bool = False,
) -> str:
    """pending-approval/candidate 匹配：文本点名 id 优先；``exactOnly=False`` 时
    唯一 pending 直接匹配（多单歧义且未点名 → 空串，宁缺毋滥）。"""
    with _roomBridgeLock:
        ids = [k for k, r in registry.items() if r == roomId]
    if not ids:
        return ""
    for key in ids:
        if key in text:
            return key
    return "" if exactOnly else (ids[0] if len(ids) == 1 else "")


def _canDecideInRoom(roomId: str, userId: str, isAdmin: bool) -> bool:
    """房间裁决权 = 平台 admin 或房间群主（project.owner_id）——复用群主制度单源。

    manager/project 不可用时 fail-closed（宁可记议见，不可放权）。
    """
    if isAdmin:
        return True
    uid = str(userId or "").strip()
    if not uid:
        return False
    try:
        from neurova.collaboration.collaboration_isolation import get_collaboration_manager

        manager = get_collaboration_manager()
        project = manager.get_project(roomId) if manager else None
        return bool(project and getattr(project, "owner_id", "") == uid)
    except Exception as e:  # noqa: BLE001 - 房间态不可读时不放权
        logger.debug("房间裁决权判定不可读 (room=%s): %s", roomId, e)
        return False


def parseRoomDecision(text: str) -> Optional[str]:
    """从房间回复解析判定意图：approve / reject / None（无法解析）。"""
    t = str(text or "").lower()
    if any(k in t for k in ROOM_REJECT_KEYWORDS):
        return "reject"
    if any(k in t for k in ROOM_APPROVE_KEYWORDS):
        return "approve"
    return None


def parseRoomCandidateAction(text: str) -> Optional[str]:
    """从房间回复解析候选动作：intercept（拦截）/ merge（采纳合入）/ None。"""
    t = str(text or "").lower()
    if any(k in t for k in ROOM_INTERCEPT_KEYWORDS):
        return "intercept"
    if any(k in t for k in ROOM_MERGE_KEYWORDS):
        return "merge"
    return None


def _roomDecisionNotice(userId: str, decision: str, requestId: str, result: Dict[str, Any]) -> str:
    verb = "批准" if decision == "approve" else "驳回"
    state = "生效" if result.get("success") else "未生效"
    return f"【裁决】{userId or '群主'} 已{verb}审批单 {requestId}（{state}）"


async def notifyRoomApproval(
    run: Any, request: Any, declared: str, effective: str, mode: str,
) -> bool:
    """L1/L2 审批卡投递到 run 所属协作房间（run.room_id 为空 = 不投）。

    投递成功后登记 pending 匹配索引，供 :func:`handleRoomSwarmReply` 回灌。
    """
    roomId = str(getattr(run, "room_id", "") or "").strip()
    if not roomId:
        return False
    action = str(getattr(request, "command", "") or "")
    reason = str(getattr(request, "description", "") or "")
    meta = {
        "kind": ROOM_MSG_KIND_APPROVAL,
        "request_id": request.request_id,
        "subagent_id": run.subagent_id,
        "agent_id": run.agent_id,
        "agent_name": run.agent_name,
        "action": action[:200],
        "reason": reason[:200],
        "level": effective,
        "declared_level": declared,
        "mode": mode,
    }
    content = (
        f"【审批请求】{run.agent_name} 请求执行：{action}\n"
        f"级别 {effective}（声明 {declared}）；原因：{reason}\n"
        "群主/管理员回复「同意/批准」或「拒绝/驳回」即可裁决。"
    )
    try:
        from neurova.collaboration.room_bus import publishRoomSystemMessage

        ok = publishRoomSystemMessage(roomId, content, meta=meta)
    except Exception as e:  # noqa: BLE001 - 房间投递失败不影响审批单本身
        logger.debug("审批卡房间投递失败 (%s): %s", request.request_id, e)
        return False
    if ok:
        _roomRegistryPut(_roomApprovalRegistry, request.request_id, roomId)
    return ok


def notifyRoomEscalation(run: Any, envelope: Dict[str, Any]) -> bool:
    """升级信封投递到 run 所属协作房间（同步入口，供 recordEscalation 调用）。"""
    roomId = str(getattr(run, "room_id", "") or "").strip()
    if not roomId:
        return False
    meta = {
        "kind": ROOM_MSG_KIND_ESCALATE,
        "subagent_id": run.subagent_id,
        "agent_name": run.agent_name,
        "reason": str(envelope.get("reason", ""))[:200],
        "severity": str(envelope.get("severity", ""))[:40],
        "suggested_action": str(envelope.get("suggested_action", ""))[:40],
    }
    question = str(envelope.get("question", "") or envelope.get("reason", ""))
    content = f"【升级】{run.agent_name}：{question}"
    try:
        from neurova.collaboration.room_bus import publishRoomSystemMessage

        return publishRoomSystemMessage(roomId, content, meta=meta)
    except Exception as e:  # noqa: BLE001 - 房间投递失败不影响升级主流程
        logger.debug("升级房间投递失败 (%s): %s", run.subagent_id, e)
        return False


def notifyRoomCandidate(run: Any, status: str, candidateId: str, detail: str = "") -> bool:
    """候选 submitted/merged/conflict 等状态事件投递到 run 所属协作房间。

    submitted 时登记可拦截索引；终态（merged/rejected/reviseRequired）注销。
    """
    roomId = str(getattr(run, "room_id", "") or "").strip()
    if not roomId:
        return False
    meta = {
        "kind": ROOM_MSG_KIND_CANDIDATE,
        "candidate_id": candidateId,
        "status": status,
        "subagent_id": run.subagent_id,
    }
    content = f"【结果候选】{candidateId} · {status}" + (f"：{detail}" if detail else "")
    try:
        from neurova.collaboration.room_bus import publishRoomSystemMessage

        ok = publishRoomSystemMessage(roomId, content, meta=meta)
    except Exception as e:  # noqa: BLE001 - 房间投递失败不影响候选主流程
        logger.debug("候选事件房间投递失败 (%s): %s", candidateId, e)
        return False
    if ok:
        if status == "submitted":
            _roomRegistryPut(_roomCandidateRegistry, candidateId, roomId)
        elif status in ("merged", "rejected", "reviseRequired"):
            _roomRegistryPop(_roomCandidateRegistry, candidateId)
    return ok


def _syncRoomRegistryFromHistory(roomId: str) -> None:
    """从房间历史补建 pending 索引（进程重启后登记表为空——房间历史是持久事实源）。

    审批单状态读 ApprovalManager 单源（SQLite 跨进程共享）：只补仍 pending 的
    swarm 审批卡；候选板在 SwarmManager 内存里，跨进程不可查——submitted 卡照登
    （处置时会诚实报"候选不存在"），不假装可判。
    """
    try:
        from neurova.collaboration.room_store import get_room_store
        from neurova.security.approval_manager import ApprovalStatus, get_approval_manager

        manager = get_approval_manager()
        for row in get_room_store().history(roomId, limit=100):
            meta = row.get("meta") or {}
            kind = meta.get("kind")
            if kind == ROOM_MSG_KIND_APPROVAL and meta.get("request_id"):
                rid = str(meta["request_id"])
                if rid in _roomApprovalRegistry:
                    continue
                req = manager.get_request(rid)
                if (req is not None and req.status == ApprovalStatus.PENDING
                        and (req.metadata or {}).get("source") == "swarm"):
                    _roomRegistryPut(_roomApprovalRegistry, rid, roomId)
            elif (kind == ROOM_MSG_KIND_CANDIDATE and meta.get("candidate_id")
                    and meta.get("status") == "submitted"):
                _roomRegistryPut(_roomCandidateRegistry, str(meta["candidate_id"]), roomId)
    except Exception as e:  # noqa: BLE001 - 补建失败不阻断回灌（登记表仍在的照常工作）
        logger.debug("房间 pending 索引补建失败 (room=%s): %s", roomId, e)


def handleRoomSwarmReply(
    roomId: str, userId: str, isAdmin: bool = False, text: str = "",
) -> Dict[str, Any]:
    """房间回复 → 蜂群回灌入口（API 层在房间用户消息落库后调用）。

    匹配本房间 pending 的审批单或候选：
    - 普通成员回复 → 只记议见（"recorded": "opinion"），不判定；
    - 群主/管理员回复 → 解析意图后回灌 :func:`decideSwarmApproval` /
      候选板动作，并在房间投一条裁决确认系统消息。
    无匹配返回 ``{"matched": ""}``——普通聊天不受影响。
    """
    roomId = str(roomId or "").strip()
    text = str(text or "").strip()
    if not roomId or not text:
        return {"matched": ""}

    # 进程重启后登记表为空——从房间历史（持久事实源）补建 pending 索引
    _syncRoomRegistryFromHistory(roomId)

    # 匹配顺序：文本点名 id 精确命中（审批/候选都可）优先；无点名时按唯一
    # pending 兜底（审批优先于候选）——防"拦截 <候选id>"被唯一审批单误吞。
    rid = _matchRoomTarget(_roomApprovalRegistry, roomId, text, exactOnly=True)
    cid = "" if rid else _matchRoomTarget(_roomCandidateRegistry, roomId, text, exactOnly=True)
    if not rid and not cid:
        rid = _matchRoomTarget(_roomApprovalRegistry, roomId, text)
    if not rid and not cid:
        cid = _matchRoomTarget(_roomCandidateRegistry, roomId, text)

    # ── 审批单匹配 ──
    if rid:
        if not _canDecideInRoom(roomId, userId, isAdmin):
            return {
                "matched": "approval", "request_id": rid, "recorded": "opinion",
                "decided_by": str(userId or ""),
                "hint": "仅群主或平台管理员可判定；本次回复已记为议见",
            }
        decision = parseRoomDecision(text)
        if decision is None:
            return {
                "matched": "approval", "request_id": rid, "decision": "unclear",
                "hint": "未能从回复解析出同意/拒绝，请明确表态（可附审批单号）",
            }
        result = decideSwarmApproval(
            rid, decision, note=text[:200], decidedBy=str(userId or ""),
            decidedByChannel="room",
        )
        _roomRegistryPop(_roomApprovalRegistry, rid)
        notice = _roomDecisionNotice(str(userId or ""), decision, rid, result)
        try:
            from neurova.collaboration.room_bus import publishRoomSystemMessage

            publishRoomSystemMessage(roomId, notice, meta={
                "kind": ROOM_MSG_KIND_APPROVAL, "request_id": rid,
                "status": result.get("status", ""), "decided_by": str(userId or ""),
            })
        except Exception as e:  # noqa: BLE001 - 确认消息失败不影响裁决
            logger.debug("裁决确认消息投递失败 (%s): %s", rid, e)
        return {
            "matched": "approval", "request_id": rid, "action": decision,
            "decided_by": str(userId or ""), "decision_result": result,
        }

    # ── 候选匹配 ──
    if cid:
        if not _canDecideInRoom(roomId, userId, isAdmin):
            return {
                "matched": "candidate", "candidate_id": cid, "recorded": "opinion",
                "hint": "仅群主或平台管理员可拦截/采纳候选；本次回复已记为议见",
            }
        action = parseRoomCandidateAction(text)
        if action is None:
            return {
                "matched": "candidate", "candidate_id": cid, "decision": "unclear",
                "hint": "请明确表态：拦截（否决）或采纳（合入），可附候选 id",
            }
        from neurova.agent.swarm import get_swarm_manager

        outcome = get_swarm_manager().applyRoomCandidateAction(
            cid, action, actor=str(userId or ""))
        return {
            "matched": "candidate", "candidate_id": cid,
            "action": "intercept" if action == "intercept" else "merge",
            "result": outcome,
        }

    return {"matched": ""}
