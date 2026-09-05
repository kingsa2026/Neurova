"""P1-5 MCP server HTTP 面（TDD）——协议无关核心的 JSON-RPC 2.0 端点。

契约（Dify core/mcp/server 对标；MCP streamable http 的最小协议面）：
- POST /mcp：JSON-RPC 2.0 单请求信封
  - initialize → {protocolVersion, capabilities: {tools:{}}, serverInfo}
  - tools/list → {tools: [...]}
  - tools/call → {content: [{type:"text",...}], isError?}
- 鉴权：get_current_user_or_service（平台既有 JWT/服务令牌面）
- 通知请求（无 id）→ 202 空响应（MCP 语义）
- 协议错误 → JSON-RPC error 对象（-32601 method not found 等），不 500
"""

import pytest


@pytest.fixture
def client(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from neurova.api import auth as nf_auth
    from neurova.api.endpoints import mcp_server_api
    from neurova.tool_layers.mcp_server import NeurovaMCPServer

    server = NeurovaMCPServer(storage=None, skill_registry=None)
    monkeypatch.setattr(mcp_server_api, "_get_mcp_server", lambda: server)

    app = FastAPI()
    app.include_router(mcp_server_api.router, prefix="/api/v1/mcp")
    app.dependency_overrides[nf_auth.get_current_user_or_service] = lambda: {
        "user_id": "u1", "username": "u", "role": "user", "neuser_id": "1",
    }
    return TestClient(app)


def _rpc(method, params=None, id_=1):
    return {"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}


class TestMcpHttpFace:
    def test_initialize(self, client):
        r = client.post("/api/v1/mcp", json=_rpc("initialize", {"protocolVersion": "2025-03-26"}))
        assert r.status_code == 200
        body = r.json()
        assert body["jsonrpc"] == "2.0" and body["id"] == 1
        assert body["result"]["protocolVersion"]
        assert "tools" in body["result"]["capabilities"]
        assert body["result"]["serverInfo"]["name"] == "neurova"

    def test_tools_list_empty(self, client):
        r = client.post("/api/v1/mcp", json=_rpc("tools/list"))
        assert r.status_code == 200
        assert r.json()["result"]["tools"] == []

    def test_tools_call_unknown_tool_is_error_content(self, client):
        r = client.post("/api/v1/mcp", json=_rpc("tools/call", {"name": "tool:nope", "arguments": {}}))
        assert r.status_code == 200
        result = r.json()["result"]
        assert result["isError"] is True
        assert "nope" in result["content"][0]["text"]

    def test_notification_returns_202(self, client):
        r = client.post("/api/v1/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert r.status_code == 202

    def test_unknown_method_json_rpc_error(self, client):
        r = client.post("/api/v1/mcp", json=_rpc("bogus/method"))
        assert r.status_code == 200
        err = r.json()["error"]
        assert err["code"] == -32601

    def test_invalid_json_rpc_shape(self, client):
        r = client.post("/api/v1/mcp", json={"nope": 1})
        assert r.status_code == 200
        assert r.json()["error"]["code"] == -32600
