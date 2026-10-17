# -*- coding: utf-8 -*-
"""MCP 服务端面的版本协商 / ping / Accept（断点②）。

缺陷形状：`mcp_server_api.py` 把 `_PROTOCOL_VERSION = "2025-03-26"` 钉成字面量，
`initialize` **无条件回声它**——不做 spec 要求的协商（服务端支持所请求版本则回声，
否则回让自己最新的支持版本）。后果：只支持 2025-06-18/2025-11-25 的客户端按 spec
必须断开，本仓导出的 MCP 面对它们不可达。同时 `ping` 落进 `-32601` 分支，
而 spec 要求服务端必须应答 ping。

本批口径（甲案）：支持集取官方 SDK 的 `HANDSHAKE_PROTOCOL_VERSIONS` 单源，协商规则
与 SDK 服务端实现同形（`mcp/server/runner.py:_negotiate_initialize`），
**不在仓内另抄一份版本号列表**——所以本档既测行为，也测「取的是同一份对象」。
"""

import pytest

from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS, LATEST_HANDSHAKE_VERSION

from neurova.api.endpoints import mcp_server_api

ENDPOINT = "/api/v1/mcp"


def _rpc(method, params=None, id_=1):
    return {"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}


@pytest.fixture
def client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from neurova.api import auth as nf_auth
    from neurova.tool_layers.mcp_server import NeurovaMCPServer

    server = NeurovaMCPServer(storage=None, skill_registry=None)
    monkeypatch.setattr(mcp_server_api, "_get_mcp_server", lambda: server)

    app = FastAPI()
    app.include_router(mcp_server_api.router, prefix=ENDPOINT)
    app.dependency_overrides[nf_auth.get_current_user_or_service] = lambda: {
        "user_id": "u1", "username": "u", "role": "user", "neuser_id": "1",
    }
    return TestClient(app)


class TestProtocolVersionNegotiation:
    @pytest.mark.parametrize("requested", HANDSHAKE_PROTOCOL_VERSIONS)
    def test_supportedVersionIsEchoedBack(self, client, requested):
        resp = client.post(ENDPOINT, json=_rpc("initialize", {"protocolVersion": requested}))
        assert resp.status_code == 200
        assert resp.json()["result"]["protocolVersion"] == requested

    def test_unsupportedVersionGetsNewestSupportedCounterOffer(self, client):
        # spec：不支持请求版本时，回自己支持的最新版本（不是把旧字面量硬塞回去）
        resp = client.post(ENDPOINT, json=_rpc("initialize", {"protocolVersion": "2099-01-01"}))
        assert resp.json()["result"]["protocolVersion"] == LATEST_HANDSHAKE_VERSION

    def test_missingRequestedVersionGetsCounterOffer(self, client):
        resp = client.post(ENDPOINT, json=_rpc("initialize", {}))
        assert resp.json()["result"]["protocolVersion"] == LATEST_HANDSHAKE_VERSION

    def test_supportedSetIsSdkSingleSourceNotACopy(self):
        # 钉的是取数身份而非取值：今天抄对了不等于明天不漂
        assert mcp_server_api.SUPPORTED_HANDSHAKE_VERSIONS is HANDSHAKE_PROTOCOL_VERSIONS

    def test_capabilitiesStayToolsOnly(self, client):
        # 版本号升上去，能力声明不许跟着虚报（本面确实没实现 resources/prompts）
        resp = client.post(ENDPOINT, json=_rpc("initialize", {"protocolVersion": LATEST_HANDSHAKE_VERSION}))
        capabilities = resp.json()["result"]["capabilities"]
        assert "tools" in capabilities
        assert "resources" not in capabilities
        assert "prompts" not in capabilities


class TestPingAndAccept:
    def test_pingGetsEmptyResultNotMethodNotFound(self, client):
        resp = client.post(ENDPOINT, json=_rpc("ping"))
        body = resp.json()
        assert "error" not in body, body
        assert body["result"] == {}

    def test_acceptJsonAloneIsServed(self, client):
        resp = client.post(ENDPOINT, json=_rpc("tools/list"), headers={"Accept": "application/json"})
        assert resp.status_code == 200

    def test_acceptWildcardIsServed(self, client):
        resp = client.post(ENDPOINT, json=_rpc("tools/list"), headers={"Accept": "*/*"})
        assert resp.status_code == 200

    def test_acceptSseOnlyRejectedAsNotAcceptable(self, client):
        # 本面只产 JSON 响应体（无 SSE 流），按 SDK JSON 模式的同一规则校验 Accept
        resp = client.post(ENDPOINT, json=_rpc("tools/list"), headers={"Accept": "text/event-stream"})
        assert resp.status_code == 406

    def test_defaultAcceptStillWorks(self, client):
        # 反向钉：加了 Accept 闸不得把既有不显式设 Accept 的客户端挡掉
        resp = client.post(ENDPOINT, json=_rpc("initialize", {"protocolVersion": "2025-03-26"}))
        assert resp.status_code == 200
