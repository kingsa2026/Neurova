# -*- coding: utf-8 -*-
"""`/api/v1/mcp` 必须自己写一次身份通道（§6-334 裁定甲：把这一面补成请求边界）。

现装的坏法：这一面有 401 闸（`get_current_user_or_service`）却**从不写身份通道**。
写方登记表（`tests/unit/agent/test_requestUserIdEntryConsistency.py` 的 `ENTRY_POINTS`）
里原本有七行，其中真正站在**请求边界**上的是 chat / console / mobile_pairing /
channel_router / computer 五处，另两行（`tool_executor`、`tool_layers/mcp_server`）
是从门面或那条通道**读数转写**，不建身份。MCP 的 HTTP 入口恰好两头都不占：
于是核心那头 `NeurovaMCPServer._current_user_id()` 恒取空——工作流调用带
`user_id=None` 落库、CUA 那条 `if uid:` 的身份透传恒假。按 §3，缺的不是"下游补个
判空"，而是**请求边界少了一次写入**。

取值口径与 chat 边界同源（`current_user["user_id"]`，即令牌 sub），不新造第二条通道；
最后一格按 AST 钉这一点：只许调用既有 setter，另立 ContextVar 即红。
"""

import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from neurova.api.endpoints import mcp_server_api
from neurova.core.identity_context import get_request_user_id
from neurova.tool_layers.mcp_server import NeurovaMCPServer

ENDPOINT = "/api/v1/mcp"


def _rpc(method, params=None, id_=1):
    return {"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}


@pytest.fixture
def spy(monkeypatch):
    """捕获工作流那条腿实际收到的 user_id（生产取用点），不如实地 mock 业务结果。"""
    captured: dict = {}

    async def _fakeExecute(workflow_id, inputs, storage=None, user_id=None):
        captured["workflow_id"] = workflow_id
        captured["user_id"] = user_id
        captured["identity_at_call"] = get_request_user_id()
        return {"success": True, "result": {"ran": workflow_id}}

    monkeypatch.setattr(
        "neurova.collaboration.neurflow.workflow_as_tool.execute_workflow_as_tool",
        _fakeExecute,
    )
    return captured


def _faceFor(monkeypatch, user_id: str, workflowName: str):
    from fastapi import FastAPI

    from neurova.api import auth as nf_auth

    class _Server(NeurovaMCPServer):
        def __init__(self):
            super().__init__(storage=None)

        def list_tools(self, caller=None):
            return [{"name": workflowName, "description": "w", "inputSchema": {"type": "object"}}]

    monkeypatch.setattr(mcp_server_api, "_get_mcp_server", lambda: _Server())
    app = FastAPI()
    # 走真挂载入口 + 真令牌：`dependency_overrides` 对 `app.mount()` 出来的 ASGI 应用不生效，
    # 留着它这一档就会在换运输后"照样绿"，而那绿没有依据。
    mcp_server_api.mountFace(app, ENDPOINT, "Neurova MCP Server Face")
    token = nf_auth.create_access_token({"sub": user_id, "neuser_id": user_id, "role": "user"})
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


class TestIdentityWrittenAtBoundary:
    def test_workflowLegReceivesTheSender(self, monkeypatch, spy):
        with _faceFor(monkeypatch, "mcp-sender-1", "workflow:demo") as client:
            resp = client.post(
                ENDPOINT, json=_rpc("tools/call", {"name": "workflow:demo", "arguments": {}})
            )
        assert resp.status_code == 200, resp.text
        assert spy["user_id"] == "mcp-sender-1", (
            f"工作流那一条腿收到的 user_id={spy['user_id']!r}——这一面没写身份通道，"
            "于是 MCP 触发的会话与记账全部落在无主桶"
        )
        assert spy["identity_at_call"] == "mcp-sender-1"

    def test_eachRequestCarriesItsOwnSender(self, monkeypatch, spy):
        """两发不同身份的请求各自看到自己那条——钉的是"请求级"，不是"进程级烘一次"。"""
        with _faceFor(monkeypatch, "sender-A", "workflow:a") as first:
            first.post(ENDPOINT, json=_rpc("tools/call", {"name": "workflow:a", "arguments": {}}))
        assert spy["user_id"] == "sender-A", spy
        with _faceFor(monkeypatch, "sender-B", "workflow:b") as second:
            second.post(ENDPOINT, json=_rpc("tools/call", {"name": "workflow:b", "arguments": {}}))
        assert spy["user_id"] == "sender-B", (
            f"第二发拿到 {spy['user_id']!r}——身份被烘进了长期对象（跨请求泄漏）"
        )


class TestNoSecondIdentityChannel:
    def test_boundaryUsesTheExistingSetter(self):
        """§3 身份只有一条通道：这一面必须调用既有 setter，且不自立第二条。"""
        source = Path(mcp_server_api.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "set_request_user_id" in called, (
            "mcp_server_api 未调用 set_request_user_id——这一面仍然不带身份"
        )
        assert "ContextVar" not in source, (
            "端点里新立了 ContextVar＝第二条身份通道，§6-163 裁定甲禁止"
        )
