# -*- coding: utf-8 -*-
"""B3 设备桥路由器红灯判据（选设备 → 幂等登记 → 派发 → 回执收敛）。

计划卡 B3：`neurova/device_bridge/` 执行包。判据：
- 总闸 `NEUROVA_DEVICE_BRIDGE_ENABLED` 默认关：未开时结构化拒绝 device_bridge_disabled；
- 无在线设备 → device_offline；能力未宣称 → unsupported_method（带 escalation）；
- 后台不可靠动作（open_url/open_app/clipboard_read/screen_*）在 app_state=background
  时 → background_unavailable（对齐 aico 的运行前能力过滤语义）；
- 正常链：device:execute 经 LedgerWs 先落账再发（帧带 seq），device:result 收敛
  future，命令落终态（同 command_id 重放得 replayed 终态）；
- 超时 → device_timeout 且 pending 清理（迟到的 result 不再误收）；
- 参数缺失/无身份 → missing_params / permission_required（executor 层）。
"""
import asyncio
import json
from typing import Any, Dict, List

import pytest

from neurova.api import mobile_ws_ledger as wsledger
from neurova.device_bridge.registry import (
    DeviceConnectionRegistry,
    resetDeviceBridgeRegistry,
)
from neurova.device_bridge.router import DeviceBridgeRouter, resetDeviceBridgeRouter

OWNER = "u-bridge"
PAIRING = "pair-bridge-1"


class FakeRawWs:
    """替身底层 WS：只记录 send_json 收到的帧（LedgerWs 会注入 seq/epoch）。"""

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
def ledger(tmp_path):
    store = wsledger.MobileWsLedger(db_path=tmp_path / "ws_ledger.db")
    yield store
    store.close()


def _registerDevice(registry: DeviceConnectionRegistry, ledger, *,
                    pairing: str = PAIRING, user: str = OWNER,
                    capabilities: List[str] = None, appState: str = "foreground") -> FakeRawWs:
    raw = FakeRawWs()
    conn = registry.register(pairing, user, wsledger.LedgerWs(raw, ledger, pairing, 1))
    registry.updateHello(pairing, platform="android",
                         capabilities=capabilities or ["open_url"],
                         appState=appState)
    return raw


class TestDisabledGate:
    def test_bridge_disabled_by_default(self, monkeypatch, ledger):
        monkeypatch.delenv("NEUROVA_DEVICE_BRIDGE_ENABLED", raising=False)
        registry = DeviceConnectionRegistry()
        _registerDevice(registry, ledger)
        router = DeviceBridgeRouter(registry)
        result = asyncio.run(router.execute(
            user_id=OWNER, action="open_url", payload={"url": "https://example.com"}))
        assert result["success"] is False
        assert result["error"]["code"] == "device_bridge_disabled"
        assert result["action_result"]["refusal_code"] == "device_bridge_disabled"

    def test_disabled_even_with_online_device(self, monkeypatch, ledger):
        monkeypatch.setenv("NEUROVA_DEVICE_BRIDGE_ENABLED", "0")
        registry = DeviceConnectionRegistry()
        _registerDevice(registry, ledger)
        router = DeviceBridgeRouter(registry)
        result = asyncio.run(router.execute(
            user_id=OWNER, action="device_env", payload={}))
        assert result["error"]["code"] == "device_bridge_disabled"


class TestDeviceSelection:
    def test_no_online_device_is_device_offline(self, ledger):
        router = DeviceBridgeRouter(DeviceConnectionRegistry())
        result = asyncio.run(router.execute(
            user_id="u-nobody", action="open_url", payload={"url": "https://example.com"}))
        assert result["success"] is False
        assert result["error"]["code"] == "device_offline"
        assert result["action_result"]["retry"] == "retry"

    def test_capability_not_claimed_is_unsupported(self, ledger):
        registry = DeviceConnectionRegistry()
        _registerDevice(registry, ledger, capabilities=["device_env"])
        router = DeviceBridgeRouter(registry)
        result = asyncio.run(router.execute(
            user_id=OWNER, action="open_url", payload={"url": "https://example.com"}))
        assert result["success"] is False
        assert result["error"]["code"] == "capability_unsupported"
        assert result["action_result"]["refusal_code"] == "unsupported_method"
        assert result["action_result"]["retry"] == "never"

    def test_offline_device_record_is_not_dispatched(self, ledger, tmp_path):
        """注销（断线）后的设备不得再收到命令——registry 是唯一在线事实源。"""
        registry = DeviceConnectionRegistry()
        raw = _registerDevice(registry, ledger)
        router = DeviceBridgeRouter(registry)
        registry.unregister(PAIRING)
        result = asyncio.run(router.execute(
            user_id=OWNER, action="open_url", payload={"url": "https://example.com"}))
        assert result["error"]["code"] == "device_offline"
        assert raw.sent == []


class TestBackgroundGating:
    def test_background_device_rejects_foreground_only_action(self, ledger):
        registry = DeviceConnectionRegistry()
        _registerDevice(registry, ledger, capabilities=["open_url", "device_env"],
                        appState="background")
        router = DeviceBridgeRouter(registry)
        result = asyncio.run(router.execute(
            user_id=OWNER, action="open_url", payload={"url": "https://example.com"}))
        assert result["success"] is False
        assert result["error"]["code"] == "capability_unavailable_in_background"
        assert result["action_result"]["refusal_code"] == "background_unavailable"

    def test_background_device_still_serves_safe_action(self, ledger):
        registry = DeviceConnectionRegistry()
        raw = _registerDevice(registry, ledger, capabilities=["device_env"],
                              appState="background")
        router = DeviceBridgeRouter(registry)
        task = asyncio.run(_drive(router, raw, action="device_env", payload={},
                                  data={"battery": 0.8}))
        assert task["success"] is True


class TestCommandRoundtrip:
    def test_happy_path_sends_journaled_frame_and_settles(self, ledger):
        registry = DeviceConnectionRegistry()
        raw = _registerDevice(registry, ledger, capabilities=["open_url"])
        router = DeviceBridgeRouter(registry)
        result = asyncio.run(_drive(router, raw, action="open_url",
                                    payload={"url": "https://example.com"},
                                    data={"opened": True}))
        assert result["success"] is True
        assert result["data"] == {"opened": True}
        assert result["pairing_id"] == PAIRING
        card = result["action_result"]
        assert card["route"] == "device" and card["effect"] == "confirmed"
        assert card["delivery"] == "background" and card["evidence"] == ["delivery_ack"]
        # 下发帧经过账本（带 seq），且是 device:execute 形态
        sent = raw.sent[0]
        assert sent["type"] == "device:execute"
        assert sent["action"] == "open_url"
        assert sent["payload"] == {"url": "https://example.com"}
        assert isinstance(sent["seq"], int) and sent["seq"] > 0
        # 命令已收敛：同 command_id 再登记得到回放终态
        _, prior = ledger.beginCommand(sent["command_id"], PAIRING, "device:execute", {})
        assert prior is not None and prior.get("replayed") is True
        assert prior["type"] == "device:result"

    def test_error_result_from_device_is_honest_failure(self, ledger):
        registry = DeviceConnectionRegistry()
        raw = _registerDevice(registry, ledger, capabilities=["clipboard_read"])
        router = DeviceBridgeRouter(registry)
        result = asyncio.run(_drive(router, raw, action="clipboard_read", payload={},
                                    status="error",
                                    error={"code": "clipboard_denied", "message": "系统拒绝"}))
        assert result["success"] is False
        assert result["error"]["code"] == "clipboard_denied"
        assert result["action_result"]["effect"] == "refused"
        assert result["action_result"]["refusal_code"] == "backend_error"

    def test_timeout_settles_and_drops_late_result(self, ledger):
        registry = DeviceConnectionRegistry()
        raw = _registerDevice(registry, ledger, capabilities=["open_url"])
        router = DeviceBridgeRouter(registry)

        async def scenario():
            task = asyncio.create_task(router.execute(
                user_id=OWNER, action="open_url",
                payload={"url": "https://example.com"}, timeout_ms=50))
            await asyncio.sleep(0.05)
            frame = raw.sent[0]
            return await task, frame

        result, frame = asyncio.run(scenario())
        assert result["success"] is False
        assert result["error"]["code"] == "device_timeout"
        # 迟到的回执不得误收进已超时的命令
        assert router.onResult(PAIRING, {"type": "device:result",
                                         "command_id": frame["command_id"],
                                         "status": "ok", "data": {}}) is False
        # 再发同 id 不会把超时误报成"仍在运行"——已按失败终态收敛
        _, prior = ledger.beginCommand(frame["command_id"], PAIRING, "device:execute", {})
        assert prior is not None and prior.get("replayed") is True

    def test_late_result_after_success_is_ignored(self, ledger):
        registry = DeviceConnectionRegistry()
        raw = _registerDevice(registry, ledger, capabilities=["device_env"])
        router = DeviceBridgeRouter(registry)

        async def scenario():
            task = asyncio.create_task(router.execute(
                user_id=OWNER, action="device_env", payload={}, timeout_ms=2000))
            await asyncio.sleep(0.05)
            frame = raw.sent[0]
            delivered = router.onResult(PAIRING, {
                "type": "device:result", "command_id": frame["command_id"],
                "status": "ok", "data": {"battery": 0.9}})
            return await task, delivered

        result, delivered = asyncio.run(scenario())
        assert delivered is True and result["success"] is True
        assert router.onResult(PAIRING, {"type": "device:result",
                                         "command_id": raw.sent[0]["command_id"],
                                         "status": "ok", "data": {}}) is False


async def _drive(router: DeviceBridgeRouter, raw: FakeRawWs, *, action: str,
                 payload: Dict[str, Any], data: Dict[str, Any] = None,
                 status: str = "ok", error: Dict[str, Any] = None,
                 timeout_ms: int = 2000) -> Dict[str, Any]:
    """驱动一次完整往返：派发 → 等帧下发 → 模拟手机回执 → 收结果。"""
    task = asyncio.create_task(router.execute(
        user_id=OWNER, action=action, payload=payload, timeout_ms=timeout_ms))
    for _ in range(100):
        await asyncio.sleep(0.01)
        if raw.sent:
            break
    frame = raw.sent[0]
    delivered = router.onResult(PAIRING, {
        "type": "device:result", "command_id": frame["command_id"],
        "status": status, "data": data or {}, "error": error})
    assert delivered is True
    return await task
