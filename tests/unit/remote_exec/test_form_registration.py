# -*- coding: utf-8 -*-
"""W1a 批四：guest/tunnel/neuacp/mcp 四形态「连接成功点」登记统一端点注册表。

计划：docs/04-plans/2026-11-22-reference-ad-tool-security-upgrade-implementation-plan.md §4 W1a。

红→绿判据：
- 成功点触发登记：各形态 mock/桩「连接成功」后，findEndpoints 查得到对应 kind
  端点（自然键/属主/租户/能力/连接引用如实落库）；
- 失败点不登记：健康检查失败、动作报错、隧道 auth 被拒、进程 spawn 失败、
  MCP 会话建立失败——均不产生端点行；
- 拿不到可信租户/属主上下文时跳过不炸（debug 日志、原链路行为不变）；
- 凭据不落明文：connectionRef 只存 URL/引用名，token/密钥不出现在登记面。

跑法：`.venv/Scripts/python.exe -m pytest tests/unit/remote_exec/test_form_registration.py -q`
"""
from __future__ import annotations

import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

# 隧道令牌签发需要 JWT 密钥（与 tests/unit/tunnel 同一口径）
os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_form_reg_0123456789")

from neurova.core import connection_pool as connection_pool_mod  # noqa: E402
from neurova.guest_agent import client as guest_client_mod  # noqa: E402
from neurova.remote_exec import registry as registry_mod  # noqa: E402
from neurova.remote_exec.registry import (  # noqa: E402
    KIND_GUEST,
    KIND_MCP,
    KIND_NEUACP,
    KIND_TUNNEL,
    getRemoteEndpointRegistry,
)


@pytest.fixture()
def isolatedDataRoot(tmp_path, monkeypatch):
    """临时数据根 + 单例/连接池复位（对齐 test_registry.py，防跨测试串库）。"""
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
    connection_pool_mod.close_all_pools()
    registry_mod._REGISTRY_SINGLETON = None
    yield tmp_path
    connection_pool_mod.close_all_pools()
    registry_mod._REGISTRY_SINGLETON = None


# ── guest：GuestAgentClient 首次 health 成功 / 首个动作成功处登记 ────────────


def _stubGuestDaemon(monkeypatch, *, healthOk: bool = True, actionError: bool = False,
                     healthStatus: int = 200) -> None:
    """httpx.MockTransport 桩出 guest 守护进程（/health 与 /action 线格式）。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            if healthOk:
                return httpx.Response(healthStatus, json={"ok": True})
            return httpx.Response(healthStatus, json={"ok": False})
        if request.url.path == "/action":
            if actionError:
                return httpx.Response(200, json={"error": "guest agent 未知动作"})
            return httpx.Response(200, json={"success": True})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    realClient = httpx.Client

    def fakeClient(**kwargs):
        return realClient(transport=transport, **kwargs)

    monkeypatch.setattr(guest_client_mod.httpx, "Client", fakeClient)


class TestGuestRegistration:
    def test_healthSuccessRegistersGuestEndpoint(self, isolatedDataRoot, monkeypatch):
        """首次 health() 成功 → kind=guest 端点入库；token 不落明文。"""
        _stubGuestDaemon(monkeypatch, healthOk=True)
        from neurova.guest_agent.client import GuestAgentClient

        client = GuestAgentClient("http://127.0.0.1:8765", token="secret-token",
                                  ownerId="user-guest", tenantId="tenant-g")
        assert client.health() is True

        endpoints = getRemoteEndpointRegistry().findEndpoints(kind=KIND_GUEST)
        assert len(endpoints) == 1, "health 成功后应登记恰好一个 guest 端点"
        ep = endpoints[0]
        assert ep.name == "guest:http://127.0.0.1:8765"
        assert ep.connectionRef == "http://127.0.0.1:8765"
        assert ep.ownerId == "user-guest"
        assert ep.tenantId == "tenant-g"
        assert ep.capabilities == {"desktop": True}
        # 凭据不落明文：token 不得出现在登记面的任何字段
        blob = json.dumps({
            "connectionRef": ep.connectionRef, "meta": ep.meta,
            "capabilities": ep.capabilities, "name": ep.name,
        })
        assert "secret-token" not in blob

    def test_firstSuccessfulActionRegistersExactlyOnce(self, isolatedDataRoot, monkeypatch):
        """未做 health、首个动作成功 → 登记；后续动作重复成功不新增行（upsert 幂等）。"""
        _stubGuestDaemon(monkeypatch, actionError=False)
        from neurova.guest_agent.client import GuestAgentClient

        client = GuestAgentClient("http://127.0.0.1:8766", ownerId="user-guest")
        out = client.action("click", {"x": 1, "y": 2})
        assert out.get("success") is True
        assert len(getRemoteEndpointRegistry().findEndpoints(kind=KIND_GUEST)) == 1

        client.action("type", {"text": "hi"})
        assert len(getRemoteEndpointRegistry().findEndpoints(kind=KIND_GUEST)) == 1

    def test_healthFailureDoesNotRegister(self, isolatedDataRoot, monkeypatch):
        """health 失败（连接失败/非 ok）→ 不登记。"""
        _stubGuestDaemon(monkeypatch, healthOk=False, healthStatus=500)
        from neurova.guest_agent.client import GuestAgentClient

        client = GuestAgentClient("http://127.0.0.1:8767", ownerId="user-guest")
        assert client.health() is False
        assert getRemoteEndpointRegistry().findEndpoints(kind=KIND_GUEST) == []

    def test_actionErrorDoesNotRegister(self, isolatedDataRoot, monkeypatch):
        """动作返回结构化 error（HTTP 200）≠ 动作成功 → 不登记。"""
        _stubGuestDaemon(monkeypatch, actionError=True)
        from neurova.guest_agent.client import GuestAgentClient

        client = GuestAgentClient("http://127.0.0.1:8768", ownerId="user-guest")
        out = client.action("unknown_kind", {})
        assert "error" in out
        assert getRemoteEndpointRegistry().findEndpoints(kind=KIND_GUEST) == []

    def test_missingOwnerSkipsRegistrationWithoutCrash(self, isolatedDataRoot, monkeypatch):
        """拿不到可信属主身份 → 跳过登记且不炸（原链路 health 照常返回）。"""
        _stubGuestDaemon(monkeypatch, healthOk=True)
        from neurova.guest_agent.client import GuestAgentClient

        client = GuestAgentClient("http://127.0.0.1:8769")
        assert client.health() is True
        assert getRemoteEndpointRegistry().findEndpoints(kind=KIND_GUEST) == []

    def test_useRemoteSessionWiresOwnerIdentityIntoClient(self, isolatedDataRoot, monkeypatch):
        """use_remote_session 调用链把领用人身份传给客户端（owner=领用 user_id）。"""
        from neurova.computer_use import remote_backend as remote_backend_mod

        captured = {}

        class FakeClient:
            def __init__(self, base_url, token=None, ownerId="", tenantId=""):
                captured.update(base_url=base_url, token=token,
                                ownerId=ownerId, tenantId=tenantId)

            def close(self):
                pass

        monkeypatch.setattr(guest_client_mod, "GuestAgentClient", FakeClient)
        monkeypatch.setattr("neurova.computer_use.bind_remote_desktop", lambda m: object())
        monkeypatch.setattr("neurova.computer_use.unbind_remote_desktop", lambda t: None)

        session = SimpleNamespace(base_url="http://127.0.0.1:9999", token="tok",
                                  session_id="s1", user_id="user-x")
        pool = SimpleNamespace(claim=lambda uid: session, release=lambda sid: None)

        with remote_backend_mod.use_remote_session(pool, "user-x"):
            pass

        assert captured["base_url"] == "http://127.0.0.1:9999"
        assert captured["ownerId"] == "user-x"
        assert captured["tenantId"], "租户应经单源解析（解析失败回落 default，不为空）"


# ── tunnel：_dialAndAuth 收到 FRAME_REGISTERED 且 routeId 落定处登记 ─────────


async def _startFakeRelay(handler):
    import websockets

    server = await websockets.serve(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port


class TestTunnelRegistration:
    def test_registeredFrameRegistersTunnelEndpoint(self, isolatedDataRoot):
        """真拨号 → auth → FRAME_REGISTERED（routeId 落定）→ kind=tunnel 端点入库。"""
        from neurova.tunnel import protocol
        from neurova.tunnel.agent import TunnelAgent

        async def controlHandler(ws):
            first = json.loads(await ws.recv())
            if first.get("type") != protocol.FRAME_AUTH:
                await ws.send(json.dumps({"type": protocol.FRAME_ERROR,
                                          "code": protocol.TUNNEL_ERROR_AUTH_REJECTED}))
                return
            await ws.send(json.dumps({"type": protocol.FRAME_REGISTERED,
                                      "routeId": "route-reg-1"}))
            async for _ in ws:
                pass

        async def scenario():
            server, port = await _startFakeRelay(controlHandler)
            relayUrl = f"ws://127.0.0.1:{port}"
            agent = TunnelAgent(relayUrl=relayUrl, enrollmentToken="tok-form-reg",
                                instanceId="nv-form-reg", connectWindowSeconds=5,
                                reconnectBackoffSeconds=0.05)
            agent.start()
            for _ in range(100):
                if agent.tunnelStatus()["state"] == "via_relay":
                    break
                await asyncio.sleep(0.05)
            status = agent.tunnelStatus()
            await agent.stop()
            server.close()
            await server.wait_closed()
            return relayUrl, status

        relayUrl, status = asyncio.run(scenario())
        assert status["state"] == "via_relay", status
        assert status["route_id"] == "route-reg-1", status

        endpoints = getRemoteEndpointRegistry().findEndpoints(kind=KIND_TUNNEL)
        assert len(endpoints) == 1, "routeId 落定后应登记恰好一个 tunnel 端点"
        ep = endpoints[0]
        assert ep.name == "tunnel:route-reg-1"
        assert ep.connectionRef == relayUrl
        assert ep.ownerId == "nv-form-reg"
        assert ep.capabilities == {"proxy": True}
        # 准入令牌不落明文
        blob = json.dumps({"connectionRef": ep.connectionRef, "meta": ep.meta})
        assert "tok-form-reg" not in blob

    def test_authRejectionDoesNotRegister(self, isolatedDataRoot):
        """中继拒准（FRAME_ERROR）→ 连接失败 → 不登记。"""
        from neurova.tunnel import protocol
        from neurova.tunnel.agent import TunnelAgent

        async def controlHandler(ws):
            await ws.recv()
            await ws.send(json.dumps({"type": protocol.FRAME_ERROR,
                                      "code": protocol.TUNNEL_ERROR_AUTH_REJECTED}))
            async for _ in ws:
                pass

        async def scenario():
            server, port = await _startFakeRelay(controlHandler)
            agent = TunnelAgent(relayUrl=f"ws://127.0.0.1:{port}",
                                enrollmentToken="tok-form-reg", instanceId="nv-form-reg",
                                connectWindowSeconds=5, reconnectBackoffSeconds=0.05)
            agent.start()
            for _ in range(100):
                if agent.tunnelStatus()["state"] == "relay_down":
                    break
                await asyncio.sleep(0.05)
            status = agent.tunnelStatus()
            await agent.stop()
            server.close()
            await server.wait_closed()
            return status

        status = asyncio.run(scenario())
        assert status["state"] == "relay_down", status
        assert getRemoteEndpointRegistry().findEndpoints(kind=KIND_TUNNEL) == []


# ── neuacp：进程池 spawn 成功处登记（租户取池键租户段，§6.4 同源） ───────────


class FakeProcess:
    """进程替身：is_alive 属性 + terminate()（与 NeuacpClient 形状一致）。"""

    def __init__(self, alive: bool = True):
        self._alive = alive
        self.terminated = False

    @property
    def is_alive(self):
        return self._alive and not self.terminated

    def terminate(self):
        self.terminated = True


class TestNeuacpRegistration:
    def test_spawnSuccessRegistersNeuacpEndpoint(self, isolatedDataRoot):
        """spawn 成功（factory 返回存活进程）→ kind=neuacp 端点入库。"""
        from neurova.agent.neuacp.process_pool import NeuacpProcessPool, poolKey

        pool = NeuacpProcessPool(maxProcs=2, idleSeconds=600.0)
        key = poolKey("tenant-n", "gemini-cli", ["gemini", "--acp"], "/w/n")
        entry = pool.acquire(key, lambda: FakeProcess())
        try:
            endpoints = getRemoteEndpointRegistry().findEndpoints(kind=KIND_NEUACP)
            assert len(endpoints) == 1, "spawn 成功后应登记恰好一个 neuacp 端点"
            ep = endpoints[0]
            assert ep.name == "gemini-cli"
            assert ep.tenantId == "tenant-n"
            assert ep.capabilities == {"agent": True}
            # stdio 直启：连接引用=transport:命令头（不含任何参数/凭据）
            assert ep.connectionRef == "stdio:gemini"
        finally:
            pool.release(key, entry)
            pool.shutdown()

    def test_factoryFailureDoesNotRegister(self, isolatedDataRoot):
        """spawn 失败（factory 抛错）→ 不登记，且异常原样上抛（不吞）。"""
        from neurova.agent.neuacp.acp_client import NeuacpError
        from neurova.agent.neuacp.process_pool import NeuacpProcessPool, poolKey

        pool = NeuacpProcessPool(maxProcs=2, idleSeconds=600.0)
        key = poolKey("tenant-n", "opencode", ["opencode", "acp"], "/w/n")
        with pytest.raises(NeuacpError):
            pool.acquire(key, lambda: (_ for _ in ()).throw(NeuacpError("spawn 失败")))
        assert getRemoteEndpointRegistry().findEndpoints(kind=KIND_NEUACP) == []
        pool.shutdown()

    def test_tenantSegmentIsolationCarriesIntoRegistry(self, isolatedDataRoot):
        """同 tool 不同租户分别 spawn → 注册表两行，各归各租户（§6.4 同源）。"""
        from neurova.agent.neuacp.process_pool import NeuacpProcessPool, poolKey

        pool = NeuacpProcessPool(maxProcs=4, idleSeconds=600.0)
        keyT1 = poolKey("tenant-1", "opencode", ["opencode", "acp"], "/w/1")
        keyT2 = poolKey("tenant-2", "opencode", ["opencode", "acp"], "/w/2")
        entry1 = pool.acquire(keyT1, lambda: FakeProcess())
        entry2 = pool.acquire(keyT2, lambda: FakeProcess())
        try:
            endpoints = getRemoteEndpointRegistry().findEndpoints(kind=KIND_NEUACP)
            assert len(endpoints) == 2
            assert {ep.tenantId for ep in endpoints} == {"tenant-1", "tenant-2"}
            assert all(ep.name == "opencode" for ep in endpoints)
        finally:
            pool.release(keyT1, entry1)
            pool.release(keyT2, entry2)
            pool.shutdown()


# ── mcp：MCPToolClient.connect_server 成功处登记 ─────────────────────────────


class TestMcpRegistration:
    def test_connectSuccessRegistersMcpEndpoint(self, isolatedDataRoot):
        """远程 server 会话建立成功 → kind=mcp 端点入库（URL 作连接引用）。"""
        from neurova.tool_layers.mcp_client import MCPToolClient

        client = MCPToolClient(user_id="user-mcp")
        session = AsyncMock()
        session.list_tools.return_value = SimpleNamespace(tools=[])
        client._open_session = AsyncMock(return_value=session)

        ok = asyncio.run(client.connect_server(
            "srv-http", {"id": "srv-http", "transport": "http",
                         "url": "https://mcp.example.com/x"}))
        assert ok is True

        endpoints = getRemoteEndpointRegistry().findEndpoints(kind=KIND_MCP)
        assert len(endpoints) == 1, "连接成功后应登记恰好一个 mcp 端点"
        ep = endpoints[0]
        assert ep.name == "srv-http"
        assert ep.connectionRef == "https://mcp.example.com/x"
        assert ep.ownerId == "user-mcp"
        assert ep.tenantId, "租户应经单源解析（解析失败回落 default，不为空）"
        assert ep.capabilities == {"tools": True}

    def test_stdioConnectionRefCarriesNoCredentials(self, isolatedDataRoot):
        """stdio server：连接引用只存命令头引用名，env/args 中的密钥不落明文。"""
        from neurova.tool_layers.mcp_client import MCPToolClient

        client = MCPToolClient(user_id="user-mcp")
        session = AsyncMock()
        session.list_tools.return_value = SimpleNamespace(tools=[])
        client._open_session = AsyncMock(return_value=session)

        ok = asyncio.run(client.connect_server(
            "srv-stdio", {"id": "srv-stdio", "transport": "stdio", "command": "python",
                          "args": ["-m", "srv"], "env": {"API_KEY": "sk-secret-123"}}))
        assert ok is True

        endpoints = getRemoteEndpointRegistry().findEndpoints(kind=KIND_MCP)
        assert len(endpoints) == 1
        ep = endpoints[0]
        assert ep.connectionRef == "stdio:python"
        blob = json.dumps({"connectionRef": ep.connectionRef, "meta": ep.meta,
                           "capabilities": ep.capabilities})
        assert "sk-secret-123" not in blob

    def test_connectFailureDoesNotRegister(self, isolatedDataRoot):
        """会话建立失败 → connect_server False → 不登记。"""
        from neurova.tool_layers.mcp_client import MCPToolClient

        client = MCPToolClient(user_id="user-mcp")
        client._open_session = AsyncMock(side_effect=RuntimeError("连接被拒"))

        ok = asyncio.run(client.connect_server(
            "srv-bad", {"id": "srv-bad", "transport": "http",
                        "url": "https://mcp.example.com/bad"}))
        assert ok is False
        assert getRemoteEndpointRegistry().findEndpoints(kind=KIND_MCP) == []

    def test_registrationFailureDoesNotBreakConnection(self, isolatedDataRoot, monkeypatch):
        """注册表故障（登记失败）→ fail-soft：连接链路照常成功，不炸。"""
        from neurova.tool_layers.mcp_client import MCPToolClient

        def boom(*args, **kwargs):
            raise RuntimeError("registry down")

        monkeypatch.setattr(registry_mod.RemoteEndpointRegistry, "registerEndpoint", boom)

        client = MCPToolClient(user_id="user-mcp")
        session = AsyncMock()
        session.list_tools.return_value = SimpleNamespace(tools=[])
        client._open_session = AsyncMock(return_value=session)

        ok = asyncio.run(client.connect_server(
            "srv-ok", {"id": "srv-ok", "transport": "http",
                       "url": "https://mcp.example.com/ok"}))
        assert ok is True, "登记失败不得阻断连接成功主链路"
