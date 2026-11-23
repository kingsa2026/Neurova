# -*- coding: utf-8 -*-
"""设备桥治理（2026-11-23 计划卡 B4/B5）：风险分级门 + 审批扣住 + 熔断 + 审计。

与桌面运行门（computer_use.runtime_policy）同一套治理语义，落到设备域：

- **风险分级**（D4 拍板）：screen_*/notification_read/clipboard_read 为高敏
  （一律 require_approval，任何运行档不放行）；open_url/device_env 等低风险
  自动执行；review/sandbox 运行档下全部设备动作都须审批（手机没有沙箱平面，
  require_sandbox 语义降级为 require_approval）；
- **审批扣住**：走既有 ApprovalManager 单源建单，手机端经
  chat:approval_required 帧呈现审批卡（两端卡片组件同源），等待裁决默认 60s，
  超时/拒绝/过期一律结构化拒绝（permission_required + escalation 注明原因）；
- **熔断**（D5）：按会话记步数/时长双上限（默认 50 步 / 600s，env 可覆盖），
  超限结构化拒绝 device_budget_exhausted——熔断先于风险门（预算烧完连审批
  都不再创建）；
- **审计**（B5）：设备动作落 desktop_audit 审计库；处于蜂群 run 上下文
  （_currentSubagentIdVar）时同步落 H-4 事件账本（事件型 device_action）。
  tool_call_journal 经 ToolExecutor 执行咽喉自动覆盖，无需重复记。
"""
from __future__ import annotations

import asyncio
import os
import threading
import time
from typing import Any, Dict, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "ALWAYS_APPROVAL_ACTIONS",
    "classify_device_risk",
    "decide_device",
    "enforce_approval_gate",
    "auditDeviceAction",
    "resetBudgetState",
]

#: 任何运行档都须审批的高敏动作（D4 拍板；clipboard_read 属隐私读取同批）
ALWAYS_APPROVAL_ACTIONS = frozenset({
    "screen_observe", "screen_gesture", "notification_read", "clipboard_read",
})

#: 审批等待窗口（秒）——超时即拒，不悬挂
_APPROVAL_TIMEOUT_ENV = "NEUROVA_DEVICE_APPROVAL_TIMEOUT_S"
_DEFAULT_APPROVAL_TIMEOUT_S = 60.0

#: 熔断上限（D5：步数 50 / 时长 600s；env 可覆盖）
_MAX_STEPS_ENV = "NEUROVA_DEVICE_MAX_STEPS"
_MAX_DURATION_ENV = "NEUROVA_DEVICE_MAX_DURATION_S"
_DEFAULT_MAX_STEPS = 50
_DEFAULT_MAX_DURATION_S = 600.0

#: 会话级熔断账本：key → {"steps", "first_ts"}（key = session_id or user_id）
_budgetLock = threading.Lock()
_budget: Dict[str, Dict[str, float]] = {}

#: 在途审批等待计数（B7）：user_id → 等待中的审批单数。设备断线时 WS 收尸
#: 据此免取消聊天任务——审批通过后命令经离线入队 → 回连重投递照常执行。
_inFlightApprovals: Dict[str, int] = {}


def _actionOf(tool_name: str) -> str:
    """工具名 → 能力动作（单源：device_bridge.executor.TOOL_ACTIONS）。

    未登记的 device_* 工具（如 A4 批的 screen 系）按前缀剥离取动作名，
    保证治理词表先于工具落地也能对齐。
    """
    from neurova.device_bridge.executor import TOOL_ACTIONS

    if tool_name in TOOL_ACTIONS:
        return TOOL_ACTIONS[tool_name]
    if tool_name.startswith("device_"):
        return tool_name[len("device_"):]
    return tool_name


def classify_device_risk(action: str) -> str:
    """设备动作风险三档（封闭集；未知动作按 high 保守处置）。"""
    if action in {"screen_observe", "screen_gesture", "notification_read"}:
        return "high"
    if action in {"clipboard_read", "app_list"}:
        return "medium"
    if action in {"open_url", "open_app", "clipboard_write", "device_env"}:
        return "low"
    return "high"


def decide_device(action: str, mode: Optional[str] = None) -> Dict[str, Any]:
    """纯策略函数：设备动作 × 运行档 → proceed / require_approval。可独立测试。"""
    from neurova.computer_use.runtime_policy import (
        DesktopAction,
        DesktopRuntimeMode,
        get_runtime_mode,
    )

    if mode is None:
        mode = get_runtime_mode()
    try:
        m = DesktopRuntimeMode(mode)
    except ValueError:
        m = DesktopRuntimeMode.FULL
    risk = classify_device_risk(action)

    # 手机没有沙箱平面：review/sandbox 档语义降级为"全部须审批"
    if m in (DesktopRuntimeMode.REVIEW, DesktopRuntimeMode.SANDBOX):
        return {
            "action": DesktopAction.REQUIRE_APPROVAL.value,
            "risk": risk,
            "reason": "审核档：设备动作须用户确认",
        }
    if action in ALWAYS_APPROVAL_ACTIONS:
        return {
            "action": DesktopAction.REQUIRE_APPROVAL.value,
            "risk": risk,
            "reason": "高敏动作一律审批（D4）",
        }
    if risk == "high":
        # 未知/未登记动作按 high 保守处置：宁可多审批，不静默放行
        return {
            "action": DesktopAction.REQUIRE_APPROVAL.value,
            "risk": risk,
            "reason": "未登记动作按高风险保守处置",
        }
    return {
        "action": DesktopAction.PROCEED.value,
        "risk": risk,
        "reason": "低风险自动执行",
    }


# ── 熔断 ─────────────────────────────────────────────────────────────


def _budgetLimits() -> tuple:
    steps = int(os.environ.get(_MAX_STEPS_ENV, "").strip() or _DEFAULT_MAX_STEPS)
    duration = float(os.environ.get(_MAX_DURATION_ENV, "").strip() or _DEFAULT_MAX_DURATION_S)
    return max(1, steps), max(1.0, duration)


def _checkBudget(key: str) -> Optional[Dict[str, Any]]:
    """超限返回拒绝结果；未超限返回 None。惰性清理过期会话账目。"""
    from neurova.computer_use.action_result import refused as actionRefused
    from neurova.computer_use.action_result import attach

    maxSteps, maxDuration = _budgetLimits()
    now = time.time()
    with _budgetLock:
        stale = [k for k, v in _budget.items() if now - v["first_ts"] > maxDuration * 2]
        for k in stale:
            _budget.pop(k, None)
        entry = _budget.get(key)
    if entry is None:
        return None
    if now - entry["first_ts"] > maxDuration:
        return attach(
            {"success": False,
             "error": {"code": "device_budget_exhausted",
                       "message": f"设备命令时长超出熔断上限（{int(maxDuration)}s），本会话停止执行"}},
            actionRefused("device", "device_budget_exhausted",
                          escalation={"limit": "duration", "seconds": maxDuration}))
    if entry["steps"] >= maxSteps:
        return attach(
            {"success": False,
             "error": {"code": "device_budget_exhausted",
                       "message": f"设备命令步数超出熔断上限（{maxSteps} 步），本会话停止执行"}},
            actionRefused("device", "device_budget_exhausted",
                          escalation={"limit": "steps", "steps": maxSteps}))
    return None


def _noteCommand(key: str) -> None:
    with _budgetLock:
        entry = _budget.setdefault(
            key, {"steps": 0, "first_ts": time.time()})
        entry["steps"] += 1


def resetBudgetState() -> None:
    """清空熔断账本（测试专用）。"""
    with _budgetLock:
        _budget.clear()


# ── 审批扣住 ─────────────────────────────────────────────────────────


def _approvalTimeoutS() -> float:
    raw = os.environ.get(_APPROVAL_TIMEOUT_ENV, "").strip()
    if not raw:
        return _DEFAULT_APPROVAL_TIMEOUT_S
    try:
        return max(0.1, float(raw))
    except ValueError:
        return _DEFAULT_APPROVAL_TIMEOUT_S


def _refusal(action: str, refusal_code: str, message: str,
             escalation: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from neurova.computer_use.action_result import refused as actionRefused
    from neurova.computer_use.action_result import attach

    return attach(
        {"success": False, "action": action,
         "error": {"code": refusal_code, "message": message}},
        actionRefused("device", refusal_code, escalation=escalation))


async def _notifyMobileApproval(user_id: str, session_id: str,
                                request_id: str, tool_name: str,
                                params: Dict[str, Any], decision: Dict[str, Any]) -> None:
    """审批卡推送到该用户在线手机（chat:approval_required 帧；两端卡组件同源）。

    推送失败不阻断审批流程（审批单已落库，桌面端仍可裁决）。
    """
    from neurova.device_bridge.registry import getDeviceBridgeRegistry

    frame: Dict[str, Any] = {
        "type": "chat:approval_required",
        "session_id": session_id or "",
        "data": {
            "approval_id": request_id,
            "tool_name": tool_name,
            "params": params,
            "governance": {"kind": "device_bridge", "risk": decision["risk"]},
            "reason": decision["reason"],
        },
    }
    for conn in getDeviceBridgeRegistry().onlineForUser(user_id):
        try:
            await conn.ledger_ws.send_json(frame)
        except Exception as e:  # noqa: BLE001 - 推送失败不影响审批主流程
            logger.debug("审批卡推送失败（不阻断）: %s", e)


async def _waitForDecision(manager, request_id: str) -> tuple:
    """轮询审批裁决：approved → True；rejected/expired/timeout → (False, reason)。"""
    timeoutS = _approvalTimeoutS()
    deadline = time.time() + timeoutS
    while time.time() < deadline:
        request = manager.get_request(request_id)
        if request is None:
            return False, "approval_timeout"
        status = str(getattr(request.status, "value", request.status))
        if status == "approved":
            return True, ""
        if status in ("rejected", "expired"):
            return False, "approval_rejected"
        await asyncio.sleep(0.25)
    return False, "approval_timeout"


async def enforce_approval_gate(tool_name: str, params: Dict[str, Any], *,
                                agent_id: str = "", user_id: str = "",
                                session_id: str = "") -> Optional[Dict[str, Any]]:
    """设备工具治理咽喉：熔断 → 风险分级 → 审批扣住。

    返回 None = 放行（调用方继续执行）；返回 dict = 结构化拒绝（调用方直接
    以该结果收尾，不再执行）。
    """
    action = _actionOf(tool_name)
    budgetKey = session_id or user_id or "default"

    budgetRefusal = _checkBudget(budgetKey)
    if budgetRefusal is not None:
        return budgetRefusal

    decision = decide_device(action)
    if decision["action"] == "proceed":
        _noteCommand(budgetKey)
        return None

    # 审批扣住：既有 ApprovalManager 单源建单（手机审批卡 + 桌面审批面同源可裁决）
    from neurova.security.approval_manager import get_approval_manager

    manager = get_approval_manager()
    request = manager.create_approval_request(
        agent_id=agent_id or "",
        user_id=user_id or "",
        command=tool_name,
        description=f"设备桥动作待审批：{action}",
        danger_reason=decision["reason"],
        metadata={"device_action": action, "params": params,
                  "session_id": session_id, "risk": decision["risk"]},
    )
    await _notifyMobileApproval(user_id, session_id, request.request_id, tool_name,
                                params, decision)

    # B7：登记在途审批等待——设备断线时 WS 收尸据此**不取消**聊天任务，
    # 审批通过后命令经离线入队 → 回连重投递照常执行（否则审批单成孤儿）。
    _inFlightApprovals[user_id or ""] = _inFlightApprovals.get(user_id or "", 0) + 1
    try:
        approved, reason = await _waitForDecision(manager, request.request_id)
    finally:
        _inFlightApprovals[user_id or ""] = max(
            0, _inFlightApprovals.get(user_id or "", 0) - 1)
    if not approved:
        return _refusal(
            action, "permission_required",
            "设备动作未被批准（原因：%s）" % ("审批超时" if reason == "approval_timeout" else "已拒绝"),
            escalation={"reason": reason, "approval_id": request.request_id})
    _noteCommand(budgetKey)
    return None


def hasInFlightApproval(user_id: str) -> bool:
    """该用户是否有**在途**的设备桥审批等待（WS 断线收尸的免取消判据，B7）。"""
    return _inFlightApprovals.get(user_id or "", 0) > 0


# ── 审计（B5） ───────────────────────────────────────────────────────


def auditDeviceAction(tool_name: str, params: Dict[str, Any], result: Any,
                      duration_ms: float, *, user_id: str = "",
                      agent_id: str = "", session_id: str = "") -> None:
    """设备动作审计：desktop_audit 审计库 + 蜂群 run 上下文时落 H-4。

    审计永不阻断工具流（任何失败只留日志）。
    """
    action = _actionOf(tool_name)
    risk = classify_device_risk(action)
    try:
        from neurova.security.desktop_audit import get_desktop_audit_store

        get_desktop_audit_store().record_computer_action(
            tool_name, params, result, duration_ms,
            user_id=user_id, agent_id=agent_id, session_id=session_id)
    except Exception:  # noqa: BLE001 - 审计失败不阻断
        logger.debug("设备动作审计落库失败（不阻断）", exc_info=True)

    try:
        from neurova.agent import swarm
        from neurova.agent.swarm_event_log import appendRunEvent

        runId = swarm._currentSubagentIdVar.get()
        if runId:
            success = bool(result.get("success")) if isinstance(result, dict) else False
            appendRunEvent(runId, "device_action", {
                "tool": tool_name,
                "action": action,
                "risk": risk,
                "success": success,
                "session_id": session_id,
            })
    except Exception:  # noqa: BLE001 - H-4 留痕失败不阻断
        logger.debug("设备动作 H-4 留痕失败（不阻断）", exc_info=True)
