# -*- coding: utf-8 -*-
"""设备桥路由器：命令派发 → 账本落账 → 等端上回执 → 终态收敛。

一次 ``execute`` 的完整链路（对齐计划 §4 协议）：

1. 总闸校验（默认关）；
2. 选设备：该用户的在线连接里挑**宣称了该能力**的；前台连接优先；
3. 后台不可靠动作在 ``app_state != foreground`` 时诚实拒绝（能力协商的运行半边）；
4. ``beginCommand`` 幂等登记（``mobile_ws_commands``，键 = (pairing_id, command_id)）；
5. ``device:execute`` 经 LedgerWs **先落账再发送**（断线重连 sync_resume 会重放，
   端上按 command_id 去重）；
6. 等 ``device:result``（future 由 WS 循环 :meth:`onResult` 唤醒），超时按
   ``device_timeout`` 收敛终态——失败也要 settle，否则同 id 重试永远撞
   already_running（与 chat 指令记账同一教训）；
7. 结果统一附 ``action_result``（route=device，封闭契约）。
"""
from __future__ import annotations

import asyncio
import threading
import uuid
from typing import Any, Dict, Optional, Tuple

from neurova.core.logger import get_logger
from neurova.device_bridge.config import defaultCommandTimeoutMs, deviceBridgeEnabled
from neurova.device_bridge.registry import DeviceConnectionRegistry, getDeviceBridgeRegistry
from neurova.tunnel.protocol import (
    DEVICE_ERROR_BRIDGE_DISABLED,
    DEVICE_ERROR_OFFLINE,
    DEVICE_ERROR_TIMEOUT,
    FRAME_DEVICE_EXECUTE,
    FRAME_DEVICE_RESULT,
)

logger = get_logger(__name__)

__all__ = [
    "BACKGROUND_UNSAFE_ACTIONS",
    "DeviceBridgeRouter",
    "getDeviceBridgeRouter",
    "resetDeviceBridgeRouter",
]

#: 后台态不可靠动作（aico 的运行前能力过滤同语义）：安卓 10+ 后台启动 Activity
#: 受限、后台读剪贴板有前台判定、屏幕观察/注入本就需要前台。后台态收到这些
#: 动作直接结构化拒绝（background_unavailable），绝不假装执行。
BACKGROUND_UNSAFE_ACTIONS = frozenset({
    "open_url", "open_app", "clipboard_read", "screen_observe", "screen_gesture",
})

#: 拒绝码 → 用户可读说明（诚实失败面； refusal_code 本身是封闭契约，见 action_result）
_REFUSAL_MESSAGES = {
    "device_offline": "当前没有在线设备可执行该动作（设备未连接或已断开）",
    "device_offline_queued": "设备当前离线，命令已入队并已发唤醒信令；设备回连后将自动补执行",
    "device_timeout": "设备在窗口内未回执（可能已离线或动作未完成）",
    "device_bridge_disabled": "设备桥总闸未开启（NEUROVA_DEVICE_BRIDGE_ENABLED）",
    "unsupported_method": "在线设备未宣称该能力（运行前能力过滤）",
    "background_unavailable": "该动作在设备后台不可靠，需要设备回到前台",
    "backend_error": "设备执行失败",
}


class DeviceBridgeRouter:
    """命令派发与回执收敛（实例可注入注册表便于测试；默认用全局单例）。"""

    def __init__(self, registry: Optional[DeviceConnectionRegistry] = None):
        self._registry = registry
        self._lock = threading.RLock()
        #: (pairing_id, command_id) → Future；device:result 到达即 resolve
        self._pending: Dict[Tuple[str, str], asyncio.Future] = {}

    # -- 选设备 ------------------------------------------------------------

    def _registryOrGlobal(self) -> DeviceConnectionRegistry:
        return self._registry if self._registry is not None else getDeviceBridgeRegistry()

    # -- 派发 ---------------------------------------------------------------

    async def execute(self, *, user_id: str, action: str,
                      payload: Optional[Dict[str, Any]] = None,
                      timeout_ms: Optional[int] = None,
                      intent: str = "", task_id: str = "") -> Dict[str, Any]:
        from neurova.computer_use.action_result import refused as actionRefused
        from neurova.computer_use.action_result import attach

        if not deviceBridgeEnabled():
            return attach(
                {"success": False, "action": action,
                 "error": {"code": DEVICE_ERROR_BRIDGE_DISABLED,
                           "message": _REFUSAL_MESSAGES["device_bridge_disabled"]}},
                actionRefused("device", "device_bridge_disabled"))

        if not task_id:
            return attach(
                {"success": False, "action": action,
                 "error": {"code": "task_window_required",
                           "message": "设备命令必须携带有效 task_id 的显式任务窗口"}},
                actionRefused("device", "task_window_required"))

        connections = self._registryOrGlobal().onlineForUser(user_id)
        if not connections:
            # B7 离线唤醒闭环：有在册设备 → 命令入账待执行 + 唤醒信令；
            # 连在册设备都没有 → 诚实 device_offline。
            return await self._queueOffline(user_id, action, payload, intent, task_id)

        capable = [c for c in connections if c.claims(action)]
        if not capable:
            return attach(
                {"success": False, "action": action,
                 "error": {"code": "capability_unsupported",
                           "message": _REFUSAL_MESSAGES["unsupported_method"]}},
                actionRefused("device", "unsupported_method", escalation={
                    "capability": action,
                    "online_capabilities": sorted(
                        {cap for conn in connections for cap in conn.capabilities}),
                }))

        # 前台优先；全后台时按后台闸判定
        capable.sort(key=lambda c: 0 if c.app_state == "foreground" else 1)
        conn = capable[0]
        window = self._taskWindow(conn.pairing_id, task_id)
        if window is None:
            return self._taskWindowRefusal(action, conn.pairing_id, task_id)
        if conn.app_state != "foreground" and action in BACKGROUND_UNSAFE_ACTIONS:
            return attach(
                {"success": False, "action": action,
                 "error": {"code": "capability_unavailable_in_background",
                           "message": _REFUSAL_MESSAGES["background_unavailable"]}},
                actionRefused("device", "background_unavailable"))

        windowMs = int(timeout_ms) if timeout_ms and int(timeout_ms) > 0 \
            else defaultCommandTimeoutMs()
        commandId = f"dev-{uuid.uuid4().hex}"
        frame = {
            "type": FRAME_DEVICE_EXECUTE,
            "command_id": commandId,
            "action": action,
            "payload": dict(payload or {}),
            "timeout_ms": windowMs,
            "intent": intent,
            "task_id": task_id,
            "window_expires_at": window["expires_at_ms"],
        }
        # 幂等登记：新命令 None；同 id 已收敛回原终态（replayed）；运行中回冲突。
        prior = conn.ledger_ws.commandPriorFrame(commandId, FRAME_DEVICE_EXECUTE, frame)
        if prior is not None:
            return self._normalize(prior, action, conn.pairing_id, replayed=True)

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        key = (conn.pairing_id, commandId)
        with self._lock:
            self._pending[key] = future
        try:
            # 先落账再发送（LedgerWs 统一出口；帧内注入 seq/epoch）
            await conn.ledger_ws.send_json(frame)
            try:
                resultFrame = await asyncio.wait_for(future, timeout=windowMs / 1000.0)
            except asyncio.TimeoutError:
                timeoutFrame = {
                    "type": FRAME_DEVICE_RESULT, "command_id": commandId,
                    "status": "error",
                    "error": {"code": DEVICE_ERROR_TIMEOUT,
                              "message": _REFUSAL_MESSAGES["device_timeout"]},
                }
                conn.ledger_ws.settleCommand(commandId, timeoutFrame)
                logger.warning("device command timeout: %s action=%s", commandId, action)
                return attach(
                    {"success": False, "action": action,
                     "error": {"code": DEVICE_ERROR_TIMEOUT,
                               "message": _REFUSAL_MESSAGES["device_timeout"]}},
                    actionRefused("device", "device_timeout"))
            # 终态收敛（成功与失败都要落，重放才不悬空）
            conn.ledger_ws.settleCommand(commandId, resultFrame)
            return self._normalize(resultFrame, action, conn.pairing_id)
        finally:
            with self._lock:
                self._pending.pop(key, None)

    # -- 离线入队（B7）-------------------------------------------------------

    async def _queueOffline(self, user_id: str, action: str,
                            payload: Optional[Dict[str, Any]], intent: str,
                            task_id: str) -> Dict[str, Any]:
        """设备离线但有在册设备：命令入账待执行 + 唤醒信令（B7）。

        execute 帧直接落入该设备的 WS 账本（当前 epoch），设备回连后
        sync_resume 按 seq 补拉到该帧 → 端上按 command_id 去重执行 → 回执在
        :meth:`onResult` 里对入队命令收敛账本。agent 侧立即拿到
        ``device_offline_queued``（诚实未执行，勿重复下发）。
        """
        from neurova.api.endpoints.mobile_pairing import listDevicesForUser
        from neurova.api.mobile_ws_ledger import getMobileWsLedger
        from neurova.computer_use.action_result import refused as actionRefused
        from neurova.computer_use.action_result import attach

        devices = listDevicesForUser(user_id)
        if not devices:
            return attach(
                {"success": False, "action": action,
                 "error": {"code": DEVICE_ERROR_OFFLINE,
                           "message": _REFUSAL_MESSAGES["device_offline"]}},
                actionRefused("device", "device_offline"))
        target = max(devices, key=lambda d: float(d.get("last_active")
                                                  or d.get("paired_at") or 0))
        pairingId = str(target.get("pairing_id") or "")
        window = self._taskWindow(pairingId, task_id)
        if window is None:
            return self._taskWindowRefusal(action, pairingId, task_id)
        commandId = f"dev-{uuid.uuid4().hex}"
        frame = {
            "type": FRAME_DEVICE_EXECUTE,
            "command_id": commandId,
            "action": action,
            "payload": dict(payload or {}),
            "timeout_ms": defaultCommandTimeoutMs(),
            "intent": intent,
            "task_id": task_id,
            "window_expires_at": window["expires_at_ms"],
        }
        ledger = getMobileWsLedger()
        _, prior = ledger.beginCommand(commandId, pairingId, FRAME_DEVICE_EXECUTE, frame)
        if prior is not None:
            return self._normalize(prior, action, pairingId, replayed=True)
        # 落账到设备最近一次连接的 epoch：重连 sync_resume 按 seq 补拉即可见；
        # 另经 hello 重投递钩子兜底（runningCommands），双路都幂等。
        ledger.appendEvent(pairingId, ledger.currentEpoch(pairingId), frame)
        wake = _pushWakeSignal(user_id, commandId)
        logger.info("device offline queue: command=%s pairing=%s wake_push=%s",
                    commandId, pairingId, wake)
        return attach(
            {"success": False, "action": action, "pairing_id": pairingId,
             "queued": True, "command_id": commandId,
             "error": {"code": "device_offline_queued",
                       "message": _REFUSAL_MESSAGES["device_offline_queued"]}},
            actionRefused("device", "device_offline_queued"))

    @staticmethod
    def _taskWindow(pairing_id: str, task_id: str) -> Optional[Dict[str, Any]]:
        from neurova.api.mobile_ws_ledger import getMobileWsLedger

        return getMobileWsLedger().taskWindow(pairing_id, task_id)

    def _taskWindowRefusal(self, action: str, pairing_id: str,
                           task_id: str) -> Dict[str, Any]:
        from neurova.api.mobile_ws_ledger import getMobileWsLedger
        from neurova.computer_use.action_result import refused as actionRefused
        from neurova.computer_use.action_result import attach

        current = getMobileWsLedger().taskWindow(pairing_id)
        code = "task_window_expired" if current is None else "task_window_mismatch"
        return attach(
            {"success": False, "action": action, "pairing_id": pairing_id,
             "error": {"code": code, "message": "显式任务窗口无效、已到期或 task_id 不匹配"}},
            actionRefused("device", code))

    # -- 回执入口（WS 循环调用） ---------------------------------------------

    def onResult(self, pairingId: str, frame: Dict[str, Any]) -> bool:
        """``device:result`` 到达：唤醒等待中的 execute。无在等命令返回 False
        （迟到回执——命令多半已按超时收敛），不抛不重发。

        B7：离线入队命令的回执没有在等 future，但**必须收敛账本**——否则
        入队命令永远 running。收敛范围由账本单源判定（仅 running 收敛）：
        在线超时命令的迟到回执不改写既有终态，未知命令不凭空落账。
        """
        commandId = str(frame.get("command_id") or "")
        if not commandId:
            return False
        with self._lock:
            future = self._pending.get((pairingId, commandId))
        if future is None or future.done():
            try:
                from neurova.api.mobile_ws_ledger import getMobileWsLedger

                getMobileWsLedger().settleRunningCommand(commandId, pairingId, frame)
            except Exception as exc:  # noqa: BLE001 - 收敛失败留痕，不上抛
                logger.warning("queued command settle failed: %s", exc)
            return False
        future.set_result(frame)
        return True

    def pendingCount(self) -> int:
        with self._lock:
            return len(self._pending)

    # -- 归一 -----------------------------------------------------------------

    @staticmethod
    def _normalize(resultFrame: Dict[str, Any], action: str, pairingId: str,
                   replayed: bool = False) -> Dict[str, Any]:
        from neurova.computer_use.action_result import build as buildActionResult
        from neurova.computer_use.action_result import refused as actionRefused
        from neurova.computer_use.action_result import attach

        data = resultFrame.get("data") if isinstance(resultFrame.get("data"), dict) else {}
        error = resultFrame.get("error") if isinstance(resultFrame.get("error"), dict) else {}
        if str(resultFrame.get("status") or "") == "ok":
            result: Dict[str, Any] = {
                "success": True, "action": action, "pairing_id": pairingId, "data": data,
            }
            if replayed:
                result["replayed"] = True
            return attach(result, buildActionResult(
                "device", "confirmed", delivery="background", evidence=["delivery_ack"]))
        code = str(error.get("code") or "backend_error")
        message = str(error.get("message") or _REFUSAL_MESSAGES["backend_error"])
        result = {
            "success": False, "action": action, "pairing_id": pairingId,
            "error": {"code": code, "message": message},
        }
        if replayed:
            result["replayed"] = True
        return attach(result, actionRefused("device", "backend_error",
                                            escalation={"device_code": code}))


def _pushWakeSignal(user_id: str, commandId: str) -> Dict[str, int]:
    """B7 离线唤醒信令：复用 push_sender 既有扇出（信令-only，正文不过推送通道）。

    信令类型 ``device_command_pending``：端上收到即拉起 WS 连接，经 sync_resume
    补拉入队帧后执行。凭据未配置/无令牌时如实记 failed，不影响入队语义。
    """
    try:
        from types import SimpleNamespace

        from neurova.notifications.push_sender import pushNotificationToUser

        return pushNotificationToUser(user_id, SimpleNamespace(
            notification_id=commandId, notification_type="device_command_pending"))
    except Exception as exc:  # noqa: BLE001 - 唤醒失败不阻断入队，留痕即可
        logger.warning("device wake push failed (user=%s command=%s): %s",
                       user_id, commandId, exc)
        return {"sent": 0, "skipped": 0, "failed": 0}


# 进程级单例（DCL + RLock，仓规）
_router_instance: Optional[DeviceBridgeRouter] = None
_router_lock = threading.RLock()


def getDeviceBridgeRouter() -> DeviceBridgeRouter:
    global _router_instance
    if _router_instance is not None:
        return _router_instance
    with _router_lock:
        if _router_instance is None:
            _router_instance = DeviceBridgeRouter()
        return _router_instance


def resetDeviceBridgeRouter() -> None:
    """重置单例（测试专用）。"""
    global _router_instance
    with _router_lock:
        _router_instance = None
