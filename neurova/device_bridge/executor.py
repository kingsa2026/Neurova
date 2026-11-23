# -*- coding: utf-8 -*-
"""``device_*`` 工具的统一执行入口（ToolExecutor 的七个薄委托都落到这里）。

职责：工具名 → 能力动作归一、参数校验（fail-closed，缺参/越权 scheme 拒绝）、
从身份通道取 user_id（``get_request_user_id``——移动 WS chat 链路在
``_handle_chat_send`` 已写入；不在这里造第二条身份通道），然后交给路由器。
本模块不做风险审批（P1 治理卡接线），也不直接碰 WS。
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from neurova.core.identity_context import get_request_user_id
from neurova.core.logger import get_logger
from neurova.device_bridge.router import getDeviceBridgeRouter

logger = get_logger(__name__)

__all__ = ["TOOL_ACTIONS", "executeDeviceTool"]

#: 工具名 → 能力词表动作（词表单源在 tunnel/protocol.DEVICE_CAPABILITIES；
#: 这里的每个动作都必须是词表成员——由 tests/unit/device_bridge 钉住）。
TOOL_ACTIONS: Dict[str, str] = {
    "device_open_url": "open_url",
    "device_open_app": "open_app",
    "device_clipboard_read": "clipboard_read",
    "device_clipboard_write": "clipboard_write",
    "device_app_list": "app_list",
    "device_env": "device_env",
    "device_notification_read": "notification_read",
}


def _refused(action: str, refusal_code: str, message: str,
             escalation: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from neurova.computer_use.action_result import refused as actionRefused
    from neurova.computer_use.action_result import attach

    return attach(
        {"success": False, "action": action,
         "error": {"code": refusal_code, "message": message}},
        actionRefused("device", refusal_code, escalation=escalation))


def _buildPayload(toolName: str, params: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """参数归一与校验。返回 ``(payload, refusalResult)``：合法二选一。"""
    params = params or {}
    if toolName == "device_open_url":
        url = str(params.get("url") or "").strip()
        # P0 只放行 http/https：自定义 scheme（weixin:// 等）涉及应用唤起面，
        # 留给 device_open_app / P1 治理，不放这里开口子。
        if not url.lower().startswith(("http://", "https://")):
            return None, _refused("open_url", "missing_params",
                                  "url 必须是 http/https 地址")
        return {"url": url}, None
    if toolName == "device_clipboard_write":
        text = params.get("text")
        if not isinstance(text, str) or not text:
            return None, _refused("clipboard_write", "missing_params",
                                  "text 必须是非空字符串")
        return {"text": text}, None
    if toolName == "device_notification_read":
        limit = params.get("limit", 10)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 10
        return {"limit": max(1, min(limit, 50))}, None
    if toolName == "device_open_app":
        app = str(params.get("app") or "").strip()
        if not app:
            return None, _refused("open_app", "missing_params",
                                  "app 必须是应用名或包名")
        return {"app": app}, None
    # clipboard_read / app_list / device_env 无参数
    return {}, None


async def executeDeviceTool(toolName: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """ToolExecutor → 设备桥的唯一入口（七个 device_* 工具的薄委托目标）。"""
    action = TOOL_ACTIONS.get(toolName)
    if action is None:
        # 内部契约错误（分派表只放行七个名字）；显式抛错不静默
        raise ValueError(f"未知设备桥工具: {toolName!r}")
    payload, refusal = _buildPayload(toolName, params)
    if refusal is not None:
        return refusal
    userId = get_request_user_id()
    if not userId:
        return _refused(action, "permission_required",
                        "当前上下文没有请求身份，无法定位属主设备",
                        escalation={"reason": "missing_request_identity"})
    return await getDeviceBridgeRouter().execute(
        user_id=userId, action=action, payload=payload)
