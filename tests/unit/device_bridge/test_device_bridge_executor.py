# -*- coding: utf-8 -*-
"""B3 执行器层红灯判据（工具名 → 动作/载荷归一 → 路由器）。

判据：
- 七个工具名映射到封闭能力词表；未知工具名显式抛错（内部契约，不静默）；
- 参数缺失 → missing_params（refused，retry=never）；
- 无请求身份 → permission_required（身份通道单源：get_request_user_id）；
- 身份 + 在线设备 → 透传路由器（结果带 action_result）。
"""
import asyncio
from typing import Any, Dict, List

import pytest

from neurova.api import mobile_ws_ledger as wsledger
from neurova.core.identity_context import set_request_user_id
from neurova.device_bridge.executor import TOOL_ACTIONS, executeDeviceTool
from neurova.device_bridge.registry import resetDeviceBridgeRegistry
from neurova.device_bridge.router import getDeviceBridgeRouter, resetDeviceBridgeRouter

OWNER = "u-exec"
PAIRING = "pair-exec-1"


class FakeRawWs:
    def __init__(self) -> None:
        self.sent: List[Dict[str, Any]] = []

    async def send_json(self, frame: Dict[str, Any]) -> None:
        self.sent.append(frame)


@pytest.fixture(autouse=True)
def _envAndSingletons(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_MOBILE_WS_LEDGER_DB", str(tmp_path / "ws_ledger.db"))
    monkeypatch.setenv("NEUROVA_DEVICE_BRIDGE_ENABLED", "1")
    wsledger.resetMobileWsLedger()
    resetDeviceBridgeRegistry()
    resetDeviceBridgeRouter()
    yield
    wsledger.resetMobileWsLedger()
    resetDeviceBridgeRegistry()
    resetDeviceBridgeRouter()


@pytest.fixture()
def wired(tmp_path):
    """在全局注册表登记一台在线设备；返回 (registry, raw_ws, ledger)。"""
    from neurova.device_bridge.registry import getDeviceBridgeRegistry

    ledger = wsledger.MobileWsLedger(db_path=tmp_path / "ws_ledger.db")
    registry = getDeviceBridgeRegistry()
    raw = FakeRawWs()
    registry.register(PAIRING, OWNER, wsledger.LedgerWs(raw, ledger, PAIRING, 1))
    registry.updateHello(PAIRING, platform="android",
                         capabilities=["open_url", "device_env", "clipboard_read",
                                       "clipboard_write", "app_list",
                                       "notification_read"],
                         appState="foreground")
    return registry, raw, ledger


class TestToolActionMapping:
    def test_seven_tools_map_to_closed_vocabulary(self):
        assert TOOL_ACTIONS == {
            "device_open_url": "open_url",
            "device_open_app": "open_app",
            "device_clipboard_read": "clipboard_read",
            "device_clipboard_write": "clipboard_write",
            "device_app_list": "app_list",
            "device_env": "device_env",
            "device_notification_read": "notification_read",
        }

    def test_unknown_tool_name_raises(self):
        with pytest.raises(ValueError):
            asyncio.run(executeDeviceTool("device_launch_missiles", {}))


class TestParamValidation:
    def test_open_url_requires_url(self, wired):
        registry, raw, ledger = wired
        set_request_user_id(OWNER)
        result = asyncio.run(executeDeviceTool("device_open_url", {}))
        assert result["success"] is False
        assert result["action_result"]["refusal_code"] == "missing_params"
        assert raw.sent == []  # 未派发任何帧

    def test_clipboard_write_requires_text(self, wired):
        registry, raw, ledger = wired
        set_request_user_id(OWNER)
        result = asyncio.run(executeDeviceTool("device_clipboard_write", {}))
        assert result["success"] is False
        assert result["action_result"]["refusal_code"] == "missing_params"

    def test_open_url_rejects_non_http_scheme(self, wired):
        registry, raw, ledger = wired
        set_request_user_id(OWNER)
        result = asyncio.run(executeDeviceTool("device_open_url",
                                               {"url": "javascript:alert(1)"}))
        assert result["success"] is False
        assert result["action_result"]["refusal_code"] == "missing_params"
        assert raw.sent == []


class TestIdentityChannel:
    def test_missing_identity_is_permission_required(self, wired):
        registry, raw, ledger = wired
        result = asyncio.run(executeDeviceTool("device_env", {}))
        assert result["success"] is False
        assert result["action_result"]["refusal_code"] == "permission_required"
        assert raw.sent == []

    def test_identity_flows_to_device_selection(self, wired):
        """身份来自 identity 通道（移动 WS chat 链路已 set_request_user_id）：
        同一注册表里别的用户的设备不可被指派。"""
        registry, raw, ledger = wired
        set_request_user_id("u-other")
        result = asyncio.run(executeDeviceTool("device_env", {}))
        assert result["success"] is False
        assert result["error"]["code"] == "device_offline"

    def test_owner_identity_reaches_device(self, wired):
        registry, raw, ledger = wired
        set_request_user_id(OWNER)

        async def scenario():
            import asyncio as aio
            task = aio.create_task(executeDeviceTool("device_env", {}))
            for _ in range(100):
                await aio.sleep(0.01)
                if raw.sent:
                    break
            frame = raw.sent[0]
            router = getDeviceBridgeRouter()
            router.onResult(PAIRING, {"type": "device:result",
                                      "command_id": frame["command_id"],
                                      "status": "ok", "data": {"battery": 0.5}})
            return await task

        result = asyncio.run(scenario())
        assert result["success"] is True
        assert result["data"] == {"battery": 0.5}
        assert result["action_result"]["route"] == "device"
