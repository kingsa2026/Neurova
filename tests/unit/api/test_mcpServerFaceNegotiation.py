# -*- coding: utf-8 -*-
"""MCP 服务端面的版本协商 / ping / Accept（断点②，§6-302）。

缺陷形状：`mcp_server_api.py` 曾把 `_PROTOCOL_VERSION = "2025-03-26"` 钉成字面量，
`initialize` **无条件回声它**——不做 spec 要求的协商（服务端支持所请求版本则回声，
否则回让自己最新的支持版本）。后果：只支持 2025-06-18/2025-11-25 的客户端按 spec
必须断开，本仓导出的 MCP 面对它们不可达。同时 `ping` 落进 `-32601` 分支，
而 spec 要求服务端必须应答 ping。

本批口径（甲案）：支持集取官方 SDK 的 `HANDSHAKE_PROTOCOL_VERSIONS` 单源，协商规则
与 SDK 服务端实现同形（`mcp/server/runner.py:_negotiate_initialize`），
**不在仓内另抄一份版本号列表**——所以本档既测行为，也测「取的是同一份对象」。

§6-339 换运输后本档跟改的两件事，都不是放宽：
① 挂载走 `mountFace`、鉴权用**真令牌**（`dependency_overrides` 对 `app.mount` 出来的
   ASGI 应用不生效，留着它只会得到"绿得没有依据"）；
② `initialize` 的 params 按 §6-340 裁定甲要求三件齐，原先"只带 protocolVersion"的
   取样是 spec 非法形状，补全它；"什么都不带"那一格随之改判成"缺 protocolVersion 即拒"。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS, LATEST_HANDSHAKE_VERSION

from neurova.api import auth as nf_auth
from neurova.api.endpoints import mcp_server_api
from neurova.tool_layers.mcp_server import NeurovaMCPServer

ENDPOINT = "/api/v1/mcp"


def _rpc(method, params=None, id_=1):
    return {"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}


def _initializeParams(version):
    """spec 要求的三件齐：protocolVersion + capabilities + clientInfo。"""
    return {
        "protocolVersion": version,
        "capabilities": {},
        "clientInfo": {"name": "neurova-negotiation-judge", "version": "1"},
    }


@pytest.fixture
def client(monkeypatch):
    server = NeurovaMCPServer(storage=None, skill_registry=None)
    monkeypatch.setattr(mcp_server_api, "_get_mcp_server", lambda: server)

    app = FastAPI()
    mcp_server_api.mountFace(app, ENDPOINT, "Neurova MCP Server Face")
    token = nf_auth.create_access_token({"sub": "u1", "neuser_id": "1", "role": "user"})
    with TestClient(app) as entered:
        entered.headers.update({"Authorization": f"Bearer {token}"})
        yield entered


class TestProtocolVersionNegotiation:
    @pytest.mark.parametrize("requested", HANDSHAKE_PROTOCOL_VERSIONS)
    def test_supportedVersionIsEchoedBack(self, client, requested):
        resp = client.post(ENDPOINT, json=_rpc("initialize", _initializeParams(requested)))
        assert resp.status_code == 200
        assert resp.json()["result"]["protocolVersion"] == requested

    def test_unsupportedVersionGetsNewestSupportedCounterOffer(self, client):
        # spec：不支持请求版本时，回自己支持的最新版本（不是把旧字面量硬塞回去）
        resp = client.post(ENDPOINT, json=_rpc("initialize", _initializeParams("2099-01-01")))
        assert resp.json()["result"]["protocolVersion"] == LATEST_HANDSHAKE_VERSION

    def test_missingProtocolVersionIsRejected(self, client):
        """§6-340 裁定甲的落点之一：连 `protocolVersion` 都没有 → 不是"反提案"，是拒。

        原判据把"什么都不带"读成"没请求版本 ⇒ 反提案最新"，那是现面不校验 params 的
        副作用；换面后这条语义归 -32602（`testMcpFaceRidesSdkTransport.py` 另有正检格）。
        """
        resp = client.post(ENDPOINT, json=_rpc("initialize", {}))
        assert resp.json()["error"]["code"] == -32602, resp.json()

    def test_supportedSetIsSdkSingleSourceNotACopy(self):
        # 钉的是取数身份而非取值：今天抄对了不等于明天不漂
        assert mcp_server_api.SUPPORTED_HANDSHAKE_VERSIONS is HANDSHAKE_PROTOCOL_VERSIONS

    def test_capabilitiesStayToolsOnly(self, client):
        # 版本号升上去，能力声明不许跟着虚报（本面确实没实现 resources/prompts）
        resp = client.post(
            ENDPOINT, json=_rpc("initialize", _initializeParams(LATEST_HANDSHAKE_VERSION))
        )
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
        # 反向钉：加了 Accept 闸不得把既有不显式设 Accept 的客户端挡掉。
        # 取样从 initialize 换成 tools/list——不是躲开 params 校验，这一格问的从来是 Accept。
        resp = client.post(ENDPOINT, json=_rpc("tools/list"))
        assert resp.status_code == 200
