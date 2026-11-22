"""U9+U16 agent 侧认证加固判据（先红后绿批）。

红=当前实现四处旧形态：URL 携 token、无全窗 watchdog（挂在半开连接上不重试）、
数据通道无 auth、收到 superseded 不退避。绿=拨号→TLS→握手→auth 整窗 15s watchdog
（指数退避保留）、首消息 auth（控制面 service 型/数据面 agent 型）、superseded 干净
退出且退避不回抢、URL 兼容开关回旧形态。

假中继用 `websockets.serve` 起在本机临时端口，与 agent 真拨真连，钉同一套线格式。

跑法：`.venv/Scripts/python.exe -m pytest tests/unit/tunnel -q --timeout=300`
"""
import asyncio
import json
import os
import time

import pytest

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_tunnel_0123456789")

from neurova.tunnel import protocol  # noqa: E402
from neurova.tunnel.agent import TunnelAgent  # noqa: E402

SECRET = "enrollment-token-agent-test"
INSTANCE = "nv-agent-upgrade"


async def _startFakeRelay(handler):
    import websockets

    server = await websockets.serve(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port


# ---------------------------------------------------------------------------
# U16 · 令牌签发/验签口径（线格式单源 protocol.py）
# ---------------------------------------------------------------------------


class TestTokenShaping:
    def test_sign_verify_roundtrip_all_types(self):
        for tokenType in protocol.TUNNEL_TOKEN_TYPES:
            token = protocol.signTunnelToken(SECRET, tokenType)
            verdict = protocol.verifyTunnelToken(token, SECRET, protocol.TUNNEL_TOKEN_TYPES)
            assert verdict["ok"] and verdict["type"] == tokenType and not verdict["legacy"], verdict

    def test_verify_rejects_tampered_and_foreign_secret(self):
        token = protocol.signTunnelToken(SECRET, protocol.TOKEN_TYPE_AGENT)
        flipped = token[:-1] + ("0" if token[-1] != "0" else "1")
        assert not protocol.verifyTunnelToken(flipped, SECRET,
                                              protocol.TUNNEL_TOKEN_TYPES)["ok"]
        assert not protocol.verifyTunnelToken(token, "other-secret",
                                              protocol.TUNNEL_TOKEN_TYPES)["ok"]

    def test_unknown_type_refuses_to_sign(self):
        with pytest.raises(ValueError):
            protocol.signTunnelToken(SECRET, "root")

    def test_legacy_downgrade_rules(self):
        data = protocol.verifyTunnelToken(SECRET, SECRET, protocol.DATA_PLANE_TOKEN_TYPES)
        assert data["ok"] and data["legacy"] and data["type"] == protocol.TOKEN_TYPE_AGENT, data
        control = protocol.verifyTunnelToken(SECRET, SECRET, protocol.CONTROL_PLANE_TOKEN_TYPES)
        assert not control["ok"], control
        assert control["reason"] == protocol.TUNNEL_ERROR_TOKEN_TYPE_REJECTED, control

    def test_channel_allowlists(self):
        assert protocol.TOKEN_TYPE_USER in protocol.CONTROL_PLANE_TOKEN_TYPES
        assert protocol.TOKEN_TYPE_SERVICE in protocol.CONTROL_PLANE_TOKEN_TYPES
        assert protocol.TOKEN_TYPE_AGENT not in protocol.CONTROL_PLANE_TOKEN_TYPES
        assert protocol.TOKEN_TYPE_AGENT in protocol.DATA_PLANE_TOKEN_TYPES
        assert protocol.TOKEN_TYPE_SERVICE in protocol.DATA_PLANE_TOKEN_TYPES
        assert protocol.TOKEN_TYPE_USER not in protocol.DATA_PLANE_TOKEN_TYPES


# ---------------------------------------------------------------------------
# U9.1+U16 · agent 控制连接：首消息 auth（service 型），URL 不再携 token
# ---------------------------------------------------------------------------


class TestAgentControlAuth:
    def test_agent_authenticates_then_registers(self):
        """真拨号：首条消息必须是 auth(service)，且 URL 不带准入令牌；随后转 via_relay。"""
        seenFrames = []
        seenPaths = []

        async def controlHandler(ws):
            seenPaths.append(ws.request.path)
            first = json.loads(await ws.recv())
            seenFrames.append(first)
            if first.get("type") != protocol.FRAME_AUTH:
                await ws.send(json.dumps({"type": protocol.FRAME_ERROR,
                                          "code": protocol.TUNNEL_ERROR_AUTH_REJECTED}))
                return
            await ws.send(json.dumps({"type": protocol.FRAME_REGISTERED,
                                      "routeId": "route-abc-123"}))
            async for _ in ws:
                pass

        async def scenario():
            server, port = await _startFakeRelay(controlHandler)
            agent = TunnelAgent(relayUrl=f"ws://127.0.0.1:{port}",
                                enrollmentToken=SECRET, instanceId=INSTANCE,
                                connectWindowSeconds=5, reconnectBackoffSeconds=0.05)
            agent.start()
            for _ in range(100):
                if agent.tunnelStatus()["state"] == "via_relay":
                    break
                await asyncio.sleep(0.05)
            status = agent.tunnelStatus()
            await agent.stop()
            server.close()
            await server.wait_closed()
            return status

        status = asyncio.run(scenario())
        assert seenFrames and seenFrames[0]["type"] == protocol.FRAME_AUTH, seenFrames
        assert seenFrames[0]["tokenType"] == protocol.TOKEN_TYPE_SERVICE, seenFrames
        verdict = protocol.verifyTunnelToken(seenFrames[0]["token"], SECRET,
                                             protocol.CONTROL_PLANE_TOKEN_TYPES)
        assert verdict["ok"] and verdict["type"] == protocol.TOKEN_TYPE_SERVICE, verdict
        assert protocol.ENROLLMENT_TOKEN_PARAM not in seenPaths[0], seenPaths[0]
        assert f"instanceId={INSTANCE}" in seenPaths[0], seenPaths[0]
        assert status["state"] == "via_relay", status
        assert status["route_id"] == "route-abc-123", status

    def test_agent_falls_back_to_url_token_when_switch_on(self, monkeypatch):
        """回滚闸门：开关打开时 agent 回旧形态（token 进 URL，先收 registered）。"""
        monkeypatch.setenv(protocol.URL_TOKEN_COMPAT_ENV, "1")
        seenPaths = []

        async def controlHandler(ws):
            seenPaths.append(ws.request.path)
            await ws.send(json.dumps({"type": protocol.FRAME_REGISTERED, "routeId": "route-old"}))
            async for _ in ws:
                pass

        async def scenario():
            server, port = await _startFakeRelay(controlHandler)
            agent = TunnelAgent(relayUrl=f"ws://127.0.0.1:{port}",
                                enrollmentToken=SECRET, instanceId=INSTANCE,
                                connectWindowSeconds=5, reconnectBackoffSeconds=0.05)
            agent.start()
            for _ in range(100):
                if agent.tunnelStatus()["state"] == "via_relay":
                    break
                await asyncio.sleep(0.05)
            status = agent.tunnelStatus()
            await agent.stop()
            server.close()
            await server.wait_closed()
            return status

        status = asyncio.run(scenario())
        assert seenPaths, "agent 未拨号"
        assert f"{protocol.ENROLLMENT_TOKEN_PARAM}={SECRET}" in seenPaths[0], seenPaths[0]
        assert status["state"] == "via_relay", status


# ---------------------------------------------------------------------------
# U9.3 · 全窗 watchdog：拨号→TLS→握手→auth 整窗超时强制放弃并重试
# ---------------------------------------------------------------------------


class TestDialWatchdog:
    def test_dial_to_auth_window_enforced_with_retry(self):
        """auth 迟迟不来 ⇒ 整窗到点强制放弃、按退避重试，不许挂在半开连接上。"""
        attempts = []

        async def hangingAuth(ws):
            attempts.append(time.time())
            try:
                await asyncio.sleep(30)   # 收到 auth 也不回 registered：模拟半开
            except asyncio.CancelledError:
                raise

        async def scenario():
            server, port = await _startFakeRelay(hangingAuth)
            agent = TunnelAgent(relayUrl=f"ws://127.0.0.1:{port}",
                                enrollmentToken=SECRET, instanceId=INSTANCE,
                                connectWindowSeconds=0.3, reconnectBackoffSeconds=0.05)
            runTask = asyncio.create_task(agent.run())
            sawRelayDown = False
            for _ in range(60):          # 轮询采样：重试循环中 state 会在两态间交替
                if agent.tunnelStatus()["state"] == "relay_down":
                    sawRelayDown = True
                await asyncio.sleep(0.025)
            status = agent.tunnelStatus()
            await agent.stop()
            try:
                await asyncio.wait_for(runTask, timeout=5)
            except Exception:  # noqa: BLE001 - stop 后任务收尾形态不限
                pass
            server.close()
            await server.wait_closed()
            return status, sawRelayDown

        status, sawRelayDown = asyncio.run(scenario())
        assert len(attempts) >= 2, f"watchdog 超时后未强制重试：attempts={attempts}"
        assert sawRelayDown, status
        assert "timeout" in status["last_error"].lower(), status

    def test_slow_handshake_within_window_still_serves(self):
        """窗口内（哪怕握手慢一点）auth 成功 ⇒ 正常转 via_relay，不被误杀。"""
        async def slowHandler(ws):
            await asyncio.sleep(0.2)   # 慢一点但在窗口内
            first = json.loads(await ws.recv())
            assert first["type"] == protocol.FRAME_AUTH
            await ws.send(json.dumps({"type": protocol.FRAME_REGISTERED, "routeId": "route-ok"}))
            async for _ in ws:
                pass

        async def scenario():
            server, port = await _startFakeRelay(slowHandler)
            agent = TunnelAgent(relayUrl=f"ws://127.0.0.1:{port}",
                                enrollmentToken=SECRET, instanceId=INSTANCE,
                                connectWindowSeconds=5, reconnectBackoffSeconds=0.05)
            agent.start()
            for _ in range(100):
                if agent.tunnelStatus()["state"] == "via_relay":
                    break
                await asyncio.sleep(0.05)
            status = agent.tunnelStatus()
            await agent.stop()
            server.close()
            await server.wait_closed()
            return status

        status = asyncio.run(scenario())
        assert status["state"] == "via_relay", status


# ---------------------------------------------------------------------------
# U9.2 · agent 收到 superseded：干净退出并退避，不立刻回抢
# ---------------------------------------------------------------------------


class TestSupersededHandling:
    def test_superseded_frame_exits_cleanly_and_backs_off(self):
        connections = []

        async def controlHandler(ws):
            connections.append(time.time())
            first = json.loads(await ws.recv())
            if first.get("type") != protocol.FRAME_AUTH:
                return
            await ws.send(json.dumps({"type": protocol.FRAME_REGISTERED, "routeId": "route-x"}))
            await ws.send(json.dumps({"type": protocol.FRAME_SUPERSEDED, "routeId": "route-x"}))
            await ws.close(code=4409, reason="superseded")
            try:
                await asyncio.sleep(30)   # 观察期：agent 是否立刻回抢
            except asyncio.CancelledError:
                raise

        async def scenario():
            server, port = await _startFakeRelay(controlHandler)
            agent = TunnelAgent(relayUrl=f"ws://127.0.0.1:{port}",
                                enrollmentToken=SECRET, instanceId=INSTANCE,
                                connectWindowSeconds=5, reconnectBackoffSeconds=30)
            agent.start()
            await asyncio.sleep(1.0)      # 退避 2s+ ⇒ 观察窗内不得出现第二条连接
            duringWindow = len(connections)
            statusMid = agent.tunnelStatus()
            await asyncio.sleep(3.0)      # 退避到点 ⇒ 应已重连（干净退出而非死挂）
            afterWindow = len(connections)
            statusAfter = agent.tunnelStatus()
            await agent.stop()
            server.close()
            await server.wait_closed()
            return duringWindow, statusMid, afterWindow, statusAfter

        duringWindow, statusMid, afterWindow, statusAfter = asyncio.run(scenario())
        assert duringWindow == 1, f"superseded 后未退避，立刻回抢：{connections}"
        assert statusMid["last_error"], statusMid
        assert "superseded" in statusMid["last_error"].lower(), statusMid
        assert afterWindow >= 2, f"退避到点未重连（死挂）：{connections}"
        assert statusAfter["last_error"], statusAfter


# ---------------------------------------------------------------------------
# U9.1+U16 · 数据通道：首条 auth（agent 型）→ auth_ok → hello
# ---------------------------------------------------------------------------


class TestDataChannelAuth:
    def test_data_stream_sends_auth_before_hello(self):
        seenFrames = []

        async def dataHandler(ws):
            while True:
                frame = json.loads(await ws.recv())
                seenFrames.append(frame)
                if frame.get("type") == protocol.FRAME_AUTH:
                    await ws.send(json.dumps({"type": protocol.FRAME_AUTH_OK}))
                elif frame.get("type") == "hello":
                    await ws.send(json.dumps({"type": protocol.FRAME_END}))
                    return

        async def scenario():
            server, port = await _startFakeRelay(dataHandler)
            agent = TunnelAgent(relayUrl=f"ws://127.0.0.1:{port}",
                                enrollmentToken=SECRET, instanceId=INSTANCE,
                                localBaseUrl="http://127.0.0.1:1")  # 不可达：流以 error 帧收场
            await agent._serveStream({"streamId": "s-1", "kind": "http",
                                      "method": "GET", "path": "/x", "headers": {}})
            server.close()
            await server.wait_closed()

        asyncio.run(scenario())
        assert len(seenFrames) >= 2, seenFrames
        assert seenFrames[0]["type"] == protocol.FRAME_AUTH, seenFrames
        assert seenFrames[0]["tokenType"] == protocol.TOKEN_TYPE_AGENT, seenFrames
        verdict = protocol.verifyTunnelToken(seenFrames[0]["token"], SECRET,
                                             protocol.DATA_PLANE_TOKEN_TYPES)
        assert verdict["ok"] and verdict["type"] == protocol.TOKEN_TYPE_AGENT, verdict
        assert seenFrames[1]["type"] == "hello", seenFrames

    def test_data_stream_respects_auth_rejection(self):
        """数据通道 auth 被拒 ⇒ 不再发 hello（不把流量送进未授权通道）。"""
        seen = []

        async def dataHandler(ws):
            frame = json.loads(await ws.recv())
            seen.append(frame.get("type"))
            await ws.send(json.dumps({"type": protocol.FRAME_ERROR,
                                      "code": protocol.TUNNEL_ERROR_TOKEN_TYPE_REJECTED}))
            await ws.close(code=4403)
            try:
                extra = await asyncio.wait_for(ws.recv(), timeout=0.5)
                seen.append(json.loads(extra).get("type"))
            except Exception:  # noqa: BLE001 - 没有后续帧是期望形态
                pass

        async def scenario():
            server, port = await _startFakeRelay(dataHandler)
            agent = TunnelAgent(relayUrl=f"ws://127.0.0.1:{port}",
                                enrollmentToken=SECRET, instanceId=INSTANCE,
                                localBaseUrl="http://127.0.0.1:1")
            await agent._serveStream({"streamId": "s-1", "kind": "http",
                                      "method": "GET", "path": "/x", "headers": {}})
            server.close()
            await server.wait_closed()

        asyncio.run(scenario())
        assert seen == [protocol.FRAME_AUTH], seen
