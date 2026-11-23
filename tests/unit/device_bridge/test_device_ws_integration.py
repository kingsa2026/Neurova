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


def _waitFor(ws, frameType: str, maxFrames: int = 60) -> Dict[str, Any]:
    """有界收帧：等到指定类型为止，超限即失败（防receive无限悬挂）。"""
    seen: List[str] = []
    for _ in range(maxFrames):
        frame = json.loads(ws.receive_text())
        if frame.get("type") == frameType:
            return frame
        seen.append(str(frame.get("type")))
    raise AssertionError(f"等待 {frameType} 超限，实收帧序列={seen}")


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


class TestOfflineQueueRedelivery:
    """B7 离线唤醒闭环（WS 集成）：设备离线 → 命令入账 + 唤醒信令；
    设备回连（hello）后立即补发仍在 running 的命令，回执收敛账本。"""

    def test_queued_command_redelivered_on_hello(self, wsClient, monkeypatch):
        from neurova.device_bridge.router import getDeviceBridgeRouter

        pushes: List[Any] = []
        monkeypatch.setattr("neurova.device_bridge.router._pushWakeSignal",
                            lambda uid, cid: pushes.append((uid, cid)) or
                            {"sent": 0, "skipped": 0, "failed": 1})
        router = getDeviceBridgeRouter()
        result = asyncio.run(router.execute(user_id=OWNER, action="device_env", payload={}))
        assert result["error"]["code"] == "device_offline_queued"
        assert result["queued"] is True and pushes == [(OWNER, result["command_id"])]
        commandId = result["command_id"]

        with wsClient.websocket_connect(f"/api/v1/mobile/ws?code={PAIRING_CODE}") as ws:
            ack = _hello(ws)
            assert ack["type"] == "device:hello_ok"
            # hello 后立即补发入队命令（新 seq、同 command_id）
            frame = json.loads(ws.receive_text())
            assert frame["type"] == "device:execute", frame
            assert frame["command_id"] == commandId
            assert frame["action"] == "device_env"
            assert isinstance(frame.get("seq"), int) and frame["seq"] > 0
            ws.send_json({"type": "device:result", "command_id": commandId,
                          "status": "ok", "data": {"battery": 0.9}})
        # 命令已收敛（同 id 重放得终态，不再是 running）
        from neurova.api.mobile_ws_ledger import getMobileWsLedger

        _, prior = getMobileWsLedger().beginCommand(commandId, "pair-device",
                                                    "device:execute", {})
        assert prior is not None and prior.get("replayed") is True
        assert prior["type"] == "device:result" and prior["status"] == "ok"


class TestApprovalDisconnectResume:
    """批二遗留联调：审批扣住期间设备断线，桌面侧批准后命令经 B7 入队，
    设备回连由 hello 重投递补执行。全程走真 WS 循环与真审批单源。"""

    def test_approval_held_across_disconnect_resumes_via_queue(
        self, wsClient, monkeypatch, tmp_path):
        from neurova.api.mobile_ws_ledger import getMobileWsLedger
        from neurova.security.approval_manager import ApprovalManager

        approvalManager = ApprovalManager(str(tmp_path / "workspace"))
        monkeypatch.setattr(
            "neurova.security.approval_manager.get_approval_manager",
            lambda **kwargs: approvalManager)

        # 替身 agent 走与 ToolExecutor 设备分支相同的治理→路由链
        # （clipboard_read 按 D4 一律 require_approval）
        class _GovernedAgent:
            config = SimpleNamespace(agent_id=AGENT_ID, owner_user_id=OWNER,
                                     llm_model="test-model")

            async def chat(self, **kwargs):
                from neurova.device_bridge.governance import enforce_approval_gate
                from neurova.device_bridge.router import getDeviceBridgeRouter

                gate = await enforce_approval_gate(
                    "device_clipboard_read", {}, agent_id=AGENT_ID,
                    user_id=OWNER, session_id="sess-approval")
                if gate is not None:
                    return {"text": f"拒绝：{gate.get('error')}", "success": False}
                result = await getDeviceBridgeRouter().execute(
                    user_id=OWNER, action="clipboard_read", payload={})
                payload = result.get("data") or result.get("error") or {}
                return {"text": f"剪贴板读取：{payload}", "success": True}

        import neurova.api.endpoints as endpointsModule

        monkeypatch.setattr(endpointsModule, "get_agent_instance",
                            lambda agent_id="": _GovernedAgent())

        pushes: List[Any] = []
        monkeypatch.setattr("neurova.device_bridge.router._pushWakeSignal",
                            lambda uid, cid: pushes.append((uid, cid)) or
                            {"sent": 0, "skipped": 0, "failed": 1})

        # 常驻 portal：两个 WS 会话必须共用同一事件循环——否则首个会话关闭时
        # portal 停摆，在途审批/入队任务会被一并冻结（联调悬挂的根因）。
        with wsClient as client:
            with client.websocket_connect(
                    f"/api/v1/mobile/ws?code={PAIRING_CODE}") as ws:
                ack = _hello(ws)
                assert ack["type"] == "device:hello_ok"
                ws.send_json({"type": "chat:send", "content": "读剪贴板",
                              "session_id": "sess-approval", "command_id": "cmd-appr-1"})
                frame = _waitFor(ws, "chat:approval_required")
                approvalId = frame["data"]["approval_id"]
                # 设备断线（未批准）——审批单仍在服务端等待
                ws.close()
            assert approvalManager.approve_request(approvalId, approved_by=OWNER)

            # 批准后工具放行，但设备已离线 → B7 入账待执行（轮询等 chat 任务走到入队）
            ledger = getMobileWsLedger()
            deadline = __import__("time").time() + 10
            while not ledger.runningCommands("pair-device") and __import__("time").time() < deadline:
                __import__("time").sleep(0.2)
            queued = ledger.runningCommands("pair-device")
            assert len(queued) == 1 and queued[0]["action"] == "clipboard_read"
            assert pushes == [(OWNER, queued[0]["command_id"])]

            # 设备回连：hello 重投递 → 收到入队命令 → 回执收敛
            # （配对码若被首连消费则重新补登记，保持与夹件同款在册事实）
            mobile_ep._pairing_codes[PAIRING_CODE] = {
                "status": "confirmed", "user_id": OWNER, "pairing_id": "pair-device"}
            with client.websocket_connect(
                    f"/api/v1/mobile/ws?code={PAIRING_CODE}") as ws:
                ack = _hello(ws)
                assert ack["type"] == "device:hello_ok"
                frame = _waitFor(ws, "device:execute")
                assert frame["command_id"] == queued[0]["command_id"]
                ws.send_json({"type": "device:result", "command_id": frame["command_id"],
                              "status": "ok", "data": {"clipboard": "内容"}})
        _, prior = ledger.beginCommand(queued[0]["command_id"], "pair-device",
                                       "device:execute", {})
        assert prior is not None and prior.get("replayed") is True
        assert prior["type"] == "device:result" and prior["status"] == "ok"


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
