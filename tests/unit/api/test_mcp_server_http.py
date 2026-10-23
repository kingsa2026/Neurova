"""P1-5 MCP server HTTP 面（TDD）——协议无关核心的 JSON-RPC 2.0 端点。

契约（§6-339 换面后按 §6-340 两裁同步，两条都写在这里，别只改代码不改契约）：
- POST /api/v1/mcp：JSON-RPC 2.0 单请求信封
  - initialize（params 三件齐：protocolVersion + capabilities + clientInfo）
    → {protocolVersion, capabilities: {tools:...}, serverInfo}
  - tools/list → {tools: [...]}
  - tools/call → {content: [{type:"text",...}], isError?}
- 鉴权：get_current_user_or_service（平台既有 JWT/服务令牌面）——本档用**真令牌**，
  理由见 fixture
- 通知请求（无 id）→ 202 空响应（MCP 语义）
- 协议错误 → JSON-RPC error 对象，不 500：未知方法 -32601；
  **没构成信封**的体走 HTTP 400 配 -32600（裁定乙），params 形状不合走 200 配 -32602（裁定甲）
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as nf_auth
from neurova.api.endpoints import mcp_server_api
from neurova.tool_layers.mcp_server import NeurovaMCPServer

ENDPOINT = "/api/v1/mcp"


@pytest.fixture
def client(monkeypatch):
    server = NeurovaMCPServer(storage=None)
    monkeypatch.setattr(mcp_server_api, "_get_mcp_server", lambda: server)

    app = FastAPI()
    mcp_server_api.mountFace(app, ENDPOINT, "Neurova MCP Server Face")
    token = nf_auth.create_access_token({"sub": "u1", "neuser_id": "1", "role": "user"})
    with TestClient(app) as entered:
        entered.headers.update({"Authorization": f"Bearer {token}"})
        yield entered


def _rpc(method, params=None, id_=1):
    return {"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}


def _initializeParams(version):
    return {
        "protocolVersion": version,
        "capabilities": {},
        "clientInfo": {"name": "neurova-http-judge", "version": "1"},
    }


class TestMcpHttpFace:
    def test_initialize(self, client):
        r = client.post(ENDPOINT, json=_rpc("initialize", _initializeParams("2025-03-26")))
        assert r.status_code == 200
        body = r.json()
        assert body["jsonrpc"] == "2.0" and body["id"] == 1
        assert body["result"]["protocolVersion"]
        assert "tools" in body["result"]["capabilities"]
        assert body["result"]["serverInfo"]["name"] == "neurova"

    def test_tools_list_empty(self, client):
        r = client.post(ENDPOINT, json=_rpc("tools/list"))
        assert r.status_code == 200
        assert r.json()["result"]["tools"] == []

    def test_tools_call_unknown_tool_is_error_content(self, client):
        r = client.post(ENDPOINT, json=_rpc("tools/call", {"name": "tool:nope", "arguments": {}}))
        assert r.status_code == 200
        result = r.json()["result"]
        assert result["isError"] is True
        assert "nope" in result["content"][0]["text"]

    def test_notification_returns_202(self, client):
        r = client.post(ENDPOINT, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert r.status_code == 202

    def test_unknown_method_json_rpc_error(self, client):
        r = client.post(ENDPOINT, json=_rpc("bogus/method"))
        assert r.status_code == 200
        err = r.json()["error"]
        assert err["code"] == -32601

    def test_envelopeWithoutMethodIs400InvalidRequest(self, client):
        """裁定乙的另一条形：有 jsonrpc/id 却没有 `method`。

        与 `test_McpFaceRidesSdkTransport.py` 那条不是重复取样——那条打的是
        `{"foo": 1}`（连 jsonrpc 字段都没有），这一条打的是"像信封却缺方法"，
        两形同码才算把这条收口钉住。
        """
        r = client.post(ENDPOINT, json={"jsonrpc": "2.0", "id": 1})
        assert r.status_code == 400, r.text[:200]
        assert r.json()["error"]["code"] == -32600
