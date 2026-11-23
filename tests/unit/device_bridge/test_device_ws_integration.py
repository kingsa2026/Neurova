# -*- coding: utf-8 -*-
"""B1/B2 WS 集成红灯判据：真 `/api/v1/mobile/ws` 循环里的设备桥帧族。

场景（全走生产代码路径，LLM 用契约替身）：
1. 手机连上 WS，发 `device:hello` → 收 `device:hello_ok`，能力落库；
2. 同一连接发 `chat:send`，替身 agent 内部调用 device 工具 → 手机收到
   `device:execute`（账本帧带 seq）→ 手机回 `device:result` → 工具收敛，
   chat 流正常 done；
3. 未知能力 → `unknown_capabilities` 结构化拒绝（fail-closed，不静默过滤）；
4. REST 读面 `GET /pairing/devices/{id}/capabilities`（JWT+属主）读到 hello 快照；
   他人设备 404。
"""
import asyncio
import inspect
import json
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import mobile_pairing as mobile_ep

PAIRING_CODE = "DEVICE-CODE-1"
OWNER = "u-device"
AGENT_ID = "device-agent"


class _DeviceToolAgent:
    """真 Agent.chat 契约替身：聊天中调用一次 device 工具（生产路径同款）。"""

    def __init__(self) -> None:
        self.config = SimpleNamespace(agent_id=AGENT_ID, owner_user_id=OWNER,
                                      llm_model="test-model")
        self.calls: List[Dict[str, Any]] = []

    async def chat(self, **kwargs):
        from neurova.agent_core import Agent

        inspect.signature(Agent.chat).bind(None, **kwargs)
        self.calls.append(dict(kwargs))
        from neurova.device_bridge.executor import executeDeviceTool

        result = await executeDeviceTool("device_env", {})
        data = result.get("data") or {}
        return {"text": f"电量 {data.get('battery')}", "success": True}


@pytest.fixture(autouse=True)
def _freshState(tmp_path, monkeypatch):
    import asyncio

    from neurova.api import mobile_ws_ledger as wsledger
    from neurova.device_bridge.registry import resetDeviceBridgeRegistry
    from neurova.device_bridge.router import resetDeviceBridgeRouter

    monkeypatch.setenv("NEUROVA_MOBILE_WS_LEDGER_DB", str(tmp_path / "ws_ledger.db"))
    monkeypatch.setenv("NEUROVA_MOBILE_DEVICES_DB", str(tmp_path / "mobile_devices.db"))
    monkeypatch.setenv("NEUROVA_DEVICE_BRIDGE_ENABLED", "1")
    wsledger.resetMobileWsLedger()
    resetDeviceBridgeRegistry()
    resetDeviceBridgeRouter()
    mobile_ep.resetDeviceRegistry()
    yield
    wsledger.resetMobileWsLedger()
    resetDeviceBridgeRegistry()
    resetDeviceBridgeRouter()
    mobile_ep.resetDeviceRegistry()


@pytest.fixture()
def wsClient(monkeypatch):
    agent = _DeviceToolAgent()
    import neurova.api.endpoints as endpointsModule

    monkeypatch.setattr(endpointsModule, "get_agent_instance", lambda agent_id="": agent)

    mobile_ep._pairing_codes.clear()
    mobile_ep._ws_connections.clear()
    monkeypatch.setitem(
        mobile_ep._pairing_codes, PAIRING_CODE,
        {"status": "confirmed", "user_id": OWNER, "pairing_id": "pair-device"},
    )
    # 生产顺序：confirm 时设备已入在册库（registry.register）；测试走 code 通道
    # 直连，这里补齐同款在册事实，hello 的 recordHello 才有行可更新。
    mobile_ep.getDeviceRegistry().register(
        pairingId="pair-device", userId=OWNER, deviceName="测试机",
        deviceType="mobile", deviceId="dev-device-1", deviceSecret="sec-device-1")

    app = FastAPI()
    app.include_router(mobile_ep.router, prefix="/api/v1/mobile")
    client = TestClient(app)
    client.agent = agent  # type: ignore[attr-defined]
    return client


def _hello(ws) -> Dict[str, Any]:
    ws.send_json({"type": "device:hello", "platform": "android",
                  "protocol_version": 1,
                  "capabilities": ["open_url", "device_env", "clipboard_read"],
                  "app_state": "foreground"})
    return json.loads(ws.receive_text())


class TestDeviceHello:
    def test_hello_is_acked_and_persisted(self, wsClient):
        with wsClient.websocket_connect(f"/api/v1/mobile/ws?code={PAIRING_CODE}") as ws:
            ack = _hello(ws)
        assert ack["type"] == "device:hello_ok"
        assert ack["accepted_capabilities"] == ["open_url", "device_env", "clipboard_read"]
        row = mobile_ep.getDeviceRegistry().get("pair-device")
        assert row["platform"] == "android"
        assert row["app_state"] == "foreground"
        assert "device_env" in row["capabilities_json"]

    def test_unknown_capabilities_rejected_fail_closed(self, wsClient):
        with wsClient.websocket_connect(f"/api/v1/mobile/ws?code={PAIRING_CODE}") as ws:
            ws.send_json({"type": "device:hello", "platform": "android",
                          "protocol_version": 1,
                          "capabilities": ["open_url", "launch_nukes"],
                          "app_state": "foreground"})
            reply = json.loads(ws.receive_text())
        assert reply["type"] == "error"
        assert reply["code"] == "unknown_capabilities"
        assert "launch_nukes" in reply["message"]
        # 未通过校验的 hello 不得落库
        row = mobile_ep.getDeviceRegistry().get("pair-device")
        assert row["platform"] == ""


class TestDeviceCommandOverChat:
    def test_agent_tool_reaches_phone_and_settles(self, wsClient):
        with wsClient.websocket_connect(f"/api/v1/mobile/ws?code={PAIRING_CODE}") as ws:
            ack = _hello(ws)
            assert ack["type"] == "device:hello_ok"
            ws.send_json({"type": "chat:send", "content": "查一下电量",
                          "session_id": "sess-device-1", "command_id": "cmd-d-1"})
            sawExecute = None
            done = None
            seenTypes: List[str] = []
            seenFrames: List[Dict[str, Any]] = []
            for _ in range(50):
                frame = json.loads(ws.receive_text())
                seenTypes.append(str(frame.get("type")))
                seenFrames.append(frame)
                if frame.get("type") == "device:execute":
                    sawExecute = frame
                    ws.send_json({"type": "device:result",
                                  "command_id": frame["command_id"],
                                  "status": "ok", "data": {"battery": 0.77}})
                if frame.get("type") in ("chat:done", "chat:error", "error"):
                    done = frame
                    break
                assert frame.get("type") != "sync_snapshot_required"
            assert sawExecute is not None, f"手机端应收到 device:execute，实收帧={json.dumps(seenFrames, ensure_ascii=False)[:800]}"
            assert sawExecute["action"] == "device_env"
            assert isinstance(sawExecute.get("seq"), int) and sawExecute["seq"] > 0
            assert done is not None and done.get("type") == "chat:done", f"终态帧异常: {done}"
        # 替身 agent 的 chat 确实被走过一次（工具结果经 device:result 收敛）
        assert len(wsClient.agent.calls) == 1

    def test_command_replay_after_reconnect_does_not_reexecute(self, wsClient):
        """同 command_id 的 chat:send 重发只执行一次（既有幂等语义不被设备桥破坏）：
        第二次发送回放原终态（chat:done replayed），设备命令不再下发。"""
        executed: List[Dict[str, Any]] = []
        with wsClient.websocket_connect(f"/api/v1/mobile/ws?code={PAIRING_CODE}") as ws:
            _hello(ws)
            # 第一轮：真实执行（设备命令下发 → 回执 → chat 终态）
            ws.send_json({"type": "chat:send", "content": "查电量",
                          "session_id": "sess-device-2", "command_id": "cmd-dup-1"})
            sawExecute = 0
            while True:
                frame = json.loads(ws.receive_text())
                if frame.get("type") == "device:execute":
                    sawExecute += 1
                    executed.append(frame)
                    ws.send_json({"type": "device:result",
                                  "command_id": frame["command_id"],
                                  "status": "ok", "data": {"battery": 0.5}})
                if frame.get("type") in ("chat:done", "chat:error", "error"):
                    break
            assert sawExecute == 1
            # 第二轮：同 command_id 重发 → 回放原终态，设备命令零下发
            ws.send_json({"type": "chat:send", "content": "查电量",
                          "session_id": "sess-device-2", "command_id": "cmd-dup-1"})
            replayed = False
            while True:
                frame = json.loads(ws.receive_text())
                assert frame.get("type") != "device:execute", "重放不得再次下发设备命令"
                if frame.get("type") == "chat:done":
                    replayed = bool(frame.get("replayed"))
                    break
                if frame.get("type") == "error":
                    break
            assert replayed is True, "重放轮应带 replayed 标记的 chat:done"
        assert len(executed) == 1  # 两轮合计只有一次真实设备命令


class TestCapabilitiesRest:
    def test_owner_reads_hello_snapshot(self, wsClient):
        from neurova.api.auth import create_access_token

        token = create_access_token({"sub": OWNER})
        # 连接存活期内查询：online 读数来自 device bridge 在线登记
        with wsClient.websocket_connect(f"/api/v1/mobile/ws?code={PAIRING_CODE}") as ws:
            _hello(ws)
            resp = wsClient.get(
                "/api/v1/mobile/pairing/devices/pair-device/capabilities",
                headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["capabilities"] == ["open_url", "device_env", "clipboard_read"]
        assert body["platform"] == "android"
        assert body["app_state"] == "foreground"
        assert body["online"] is True

    def test_other_users_device_is_not_found(self, wsClient):
        from neurova.api.auth import create_access_token

        with wsClient.websocket_connect(f"/api/v1/mobile/ws?code={PAIRING_CODE}") as ws:
            _hello(ws)
        token = create_access_token({"sub": "u-intruder"})
        resp = wsClient.get(
            "/api/v1/mobile/pairing/devices/pair-device/capabilities",
            headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 404

    def test_requires_auth(self, wsClient):
        resp = wsClient.get(
            "/api/v1/mobile/pairing/devices/pair-device/capabilities")
        assert resp.status_code in (401, 403)


class TestNotificationEventIngest:
    """A5 推送路径：手机 device:event → JSONL 账本 → 属主 REST 读面。"""

    def test_notification_events_roundtrip(self, wsClient):
        from neurova.api.auth import create_access_token

        token = create_access_token({"sub": OWNER})
        with wsClient.websocket_connect(f"/api/v1/mobile/ws?code={PAIRING_CODE}") as ws:
            _hello(ws)
            ws.send_json({
                "type": "device:event", "event_kind": "notification_batch",
                "items": [{"package": "com.example", "title": "验证码",
                           "text": "123456", "posted_at": 1}],
            })
            # 触发一次 pong 往返确保 device:event 已被处理（同连接顺序语义）
            ws.send_json({"type": "ping"})
            while True:
                frame = json.loads(ws.receive_text())
                if frame.get("type") == "pong":
                    break
        resp = wsClient.get(
            "/api/v1/mobile/pairing/devices/pair-device/notification-events?limit=10",
            headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        events = resp.json()["data"]["events"]
        assert len(events) == 1
        assert events[0]["item"]["title"] == "验证码"
        assert events[0]["pairing_id"] == "pair-device"

    def test_notification_events_other_user_404(self, wsClient):
        from neurova.api.auth import create_access_token

        token = create_access_token({"sub": "u-intruder"})
        with wsClient.websocket_connect(f"/api/v1/mobile/ws?code={PAIRING_CODE}") as ws:
            _hello(ws)
        resp = wsClient.get(
            "/api/v1/mobile/pairing/devices/pair-device/notification-events",
            headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 404
