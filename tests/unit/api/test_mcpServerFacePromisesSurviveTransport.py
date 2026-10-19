# -*- coding: utf-8 -*-
"""Neurova 导出 MCP 面的四条对外承诺——运输层换实现时不许变的那一面。

为什么单开一档（而不是靠既有几档凑数）：`tests/unit/workflow/test_mcp_server_face.py`
钉的是**核心**（list_tools/call_tool 的聚合与分派），`tests/unit/api/test_mcp_server_http.py`
与 `test_mcpServerFaceNegotiation.py` 钉的是**协议信封**。中间缺一层——
「HTTP 面有没有把请求交给那个核心」。这一层空着，换传输实现时最容易出的事是
在端点里另起一套鉴权/一套分派/一份工具清单，核心全绿而对外行为已换。

四格各钉一条承诺，都是**现场量过**的现值（匿名确实 401、导出清单确实等于核心返回值），
不是按想象写的期望：

1. 匿名必须被拒——且不是"什么都拒"造成的假绿（配一枚带真 token 的控制格）。
2. tools/list 的清单必须由核心给出，端点不自己拼。
3. tools/call 必须原样落到 `NeurovaMCPServer.call_tool`（名字与参数都不许被端点改写）。
4. CUA 未启用时的拒绝文案必须来自核心那一份（开关语义不许在传输层重述）。
"""

import pytest
from fastapi.testclient import TestClient

from neurova.api.endpoints import mcp_server_api
from neurova.tool_layers.mcp_server import NeurovaMCPServer

ENDPOINT = "/api/v1/mcp"

_CORE_TOOLS = [
    {"name": "workflow:demo", "description": "示例工作流", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "skill:summarize", "description": "技能", "inputSchema": {"type": "object", "properties": {}}},
]


def _rpc(method, params=None, id_=1):
    return {"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}


@pytest.fixture
def recordingServer(monkeypatch):
    """把核心换成"记调用参数、回固定清单"的替身——钉的是**接线**，不是核心的业务能力
    （业务能力由 tests/unit/workflow/test_mcp_server_face.py 那档钉，别在这里重述）。"""

    class _Recording(NeurovaMCPServer):
        def __init__(self):
            super().__init__(storage=None, skill_registry=None)
            self.calls = []

        def list_tools(self):
            return list(_CORE_TOOLS)

        async def call_tool(self, name, arguments=None):
            self.calls.append((name, dict(arguments or {})))
            if name == "skill:summarize":
                return {"success": True, "result": "ok"}
            return await super().call_tool(name, arguments)

    server = _Recording()
    monkeypatch.setattr(mcp_server_api, "_get_mcp_server", lambda: server)
    return server


@pytest.fixture
def face(monkeypatch, recordingServer):
    from fastapi import FastAPI

    from neurova.api import auth as nf_auth

    app = FastAPI()
    app.include_router(mcp_server_api.router, prefix=ENDPOINT)
    monkeypatch.setitem(
        app.dependency_overrides, nf_auth.get_current_user_or_service,
        lambda: {"user_id": "u1", "username": "u", "role": "user", "neuser_id": "1"},
    )
    return TestClient(app), recordingServer


class TestAnonymousGate:
    def test_anonymousRequestsAreRefused(self):
        """不打任何凭证时，握手与清单都必须被拒——这条是平台既有身份通道的入口。

        注意这里**不设** dependency_overrides：用的就是端点自己声明的那个依赖。
        """
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(mcp_server_api.router, prefix=ENDPOINT)
        client = TestClient(app)
        for method in ("initialize", "tools/list"):
            resp = client.post(ENDPOINT, json=_rpc(method, {"protocolVersion": "2025-11-25"}))
            assert resp.status_code == 401, f"{method} 匿名可得 {resp.status_code}：身份闸没了"

    def test_platformTokenStillGetsServed(self):
        """控制格：真签发的平台令牌必须能过——否则上面那条 401 只是"谁都拒"。"""
        from fastapi import FastAPI

        from neurova.api.auth import create_access_token

        app = FastAPI()
        app.include_router(mcp_server_api.router, prefix=ENDPOINT)
        token = create_access_token({"sub": "face-probe", "neuser_id": "face-probe"})
        resp = TestClient(app).post(
            ENDPOINT,
            json=_rpc("initialize", {"protocolVersion": "2025-11-25"}),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["result"]["protocolVersion"] == "2025-11-25"


class TestFaceDelegatesToCore:
    def testToolsListComesFromCore(self, face):
        client, server = face
        body = client.post(ENDPOINT, json=_rpc("tools/list")).json()
        assert body["result"]["tools"] == _CORE_TOOLS, (
            "HTTP 面报的工具清单与核心返回值不等——端点在另拼一份清单（第二个事实源）"
        )

    def testToolCallReachesCoreUnchanged(self, face):
        client, server = face
        body = client.post(
            ENDPOINT,
            json=_rpc("tools/call", {"name": "skill:summarize", "arguments": {"task": "整理论文"}}),
        ).json()
        assert server.calls == [("skill:summarize", {"task": "整理论文"})], (
            f"核心收到的分派与请求不一致：{server.calls}"
        )
        # 现契约：成功响应不带 isError 键（端点只在真错时补这个键），别把它写成 is False
        assert "isError" not in body["result"], body["result"]

    def testUnknownToolErrorEnvelopeSurvives(self, face):
        """不认识的名字 → 核心那份「未知 MCP 工具」必须走 MCP 错误信封。

        刻意不用 `workflow:*` 测：那条走 `execute_workflow_as_tool`，工作流不存在时
        返回 `success=False` 的业务体而**不是** MCP isError——这是现存的语义分叉，
        登记台账等裁，本档不把它锁成正确行为。
        """
        client, _server = face
        body = client.post(
            ENDPOINT, json=_rpc("tools/call", {"name": "totally-unknown-tool", "arguments": {}})
        ).json()
        result = body["result"]
        assert result["isError"] is True, "未知工具被换成协议级异常：MCP 语义要求错误走响应体"
        assert "totally-unknown-tool" in result["content"][0]["text"]

    def testCuaSwitchRefusalComesFromCore(self, face, monkeypatch):
        """导出开关的拒绝文案必须由核心给（`NEUROVA_CUA_MCP_EXPORT`），端点不重述。"""
        client, _server = face
        monkeypatch.delenv("NEUROVA_CUA_MCP_EXPORT", raising=False)
        body = client.post(
            ENDPOINT, json=_rpc("tools/call", {"name": "computer_screenshot", "arguments": {}})
        ).json()
        text = body["result"]["content"][0]["text"]
        assert "NEUROVA_CUA_MCP_EXPORT" in text, f"开关语义没走核心那份：{text!r}"
