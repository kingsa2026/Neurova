# -*- coding: utf-8 -*-
"""跨 agent 审批链（P3-1，评测报告 G-11）：子代理运行中权限请求 → 父代理/用户。

危险分级（Two-Man-Rule 式三档）：
- **L0** 可逆低危：自动放行 + 审批单记账（interactive / auto_approve 皆放行）；
- **L1** 中危：interactive 模式"代理给父"——审批单进既有 ``ApprovalManager``，
  信封投父会话邮箱，父代理用 ``decide_subagent_approval`` 裁决；
  auto_approve 模式自动放行；
- **L2** 高危/不可逆：**强制人工**——任何模式都不自动放行；审批卡经通知中心
  镜像给用户（ApprovalManager 既有出口），父代理或用户裁决。

单源纪律（教义第 6 条）：审批单只落在既有 ``ApprovalManager``（SQLite 状态机 +
governance API + 站内通知镜像），本模块只做蜂群侧的分级、投递与等待唤醒，
**不建第二套审批存储**。等待/唤醒复用 ``approval_relay``——与工具 ASK 同一条通路；
声明的等级只升不降：动作命中 ``DangerousCommandDetector`` 时 L0 至少升到 L1。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict

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
    """审批信封投父会话邮箱（与升级/终态回灌同一通道；失败不影响审批单本身）。"""
    if run.origin != "chat" or not run.session_id:
        return
    try:
        from neurova.agent.mailbox import get_agent_mailbox

        get_agent_mailbox().push(
            run.session_id,
            "[子代理审批] " + json.dumps(envelope, ensure_ascii=False),
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("审批请求邮箱投递失败 (%s): %s", envelope.get("request_id"), e)


def _recordRunApproval(run: Any, entry: Dict[str, Any]) -> None:
    """审批记录挂到 run（可观测面，to_dict 带出）；有界防无界增长。"""
    run.approvals.append(entry)
    if len(run.approvals) > 50:
        del run.approvals[:-50]


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

    # ── 自动放行支路：L0，或 auto_approve 模式下的 L1 ──
    if effective == LEVEL_L0 or (effective == LEVEL_L1 and mode == MODE_AUTO_APPROVE):
        manager.approve_request(
            request.request_id,
            approved_by=f"auto_rule:{effective}",
            note="低危自动放行" if effective == LEVEL_L0 else "auto_approve 模式放行",
        )
        entry["status"] = "approved"
        return {
            "approved": True, "auto_approved": True, "pending": False,
            "request_id": request.request_id, "level": effective,
            "status": "approved", "decided_by": f"auto_rule:{effective}",
        }

    # ── 需人裁支路：L1(interactive) 代理给父；L2 强制人工 ──
    _notifyParent(run, _parentEnvelope(run, request, declared, effective, mode))

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


def decideSwarmApproval(requestId: str, decision: str, note: str = "") -> Dict[str, Any]:
    """父代理裁决蜂群审批单（``decide_subagent_approval`` 工具实现）。

    只认 ``metadata.source == "swarm"`` 的审批单——通用治理审批仍走 governance API；
    两条入口共享同一存储，职责分开。幂等：非 pending 一律失败返回（AutoSwarm 式
    request/decision 幂等，防重复裁决）。
    """
    from neurova.security.approval_manager import ApprovalStatus, get_approval_manager

    rid = str(requestId or "").strip()
    if not rid:
        return {"success": False, "error": "request_id 不能为空"}
    act = str(decision or "").strip().lower()
    if act not in ("approve", "reject"):
        return {"success": False, "error": "decision 仅支持 approve/reject"}
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
    if act == "approve":
        ok = manager.approve_request(rid, approved_by="parent_agent", note=str(note or ""))
    else:
        ok = manager.reject_request(rid, rejected_by="parent_agent", note=str(note or ""))
    if not ok:
        return {"success": False, "error": "裁决未生效（审批单可能刚过期）"}
    decided = manager.get_request(rid)
    return {
        "success": True,
        "request_id": rid,
        "decision": act,
        "status": decided.status.value if decided else "",
        "decided_by": "parent_agent",
        "hint": "裁决结果将唤醒等待中的子代理",
    }
