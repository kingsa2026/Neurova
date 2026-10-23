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

§6-339 换运输后本档跟改的两处，都是把"依据"换硬而不是放宽断言：
① 挂载改走 `mcp_server_api.mountFace`——`app.dependency_overrides` 对 `app.mount()` 出来的
   ASGI 应用**根本不生效**，留着它只会得到"覆盖没生效却照样绿"的假事实源；三处一律改真令牌
   （`create_access_token`），承诺 1 那句"用的就是面自己声明的那条鉴权"从此字面成立。
② `initialize` 的 params 补成 spec 要求的三件齐（§6-340 裁定甲）；本档审的是接线，
   不是协商，补全取样即可，语义由 `test_McpFaceRidesSdkTransport.py` 那档钉。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as nf_auth
from neurova.api.endpoints import mcp_server_api
from neurova.tool_layers.mcp_server import NeurovaMCPServer

ENDPOINT = "/api/v1/mcp"


def _token(sub: str) -> dict:
    return {"Authorization": f"Bearer {nf_auth.create_access_token({'sub': sub, 'neuser_id': sub, 'role': 'user'})}"}


def _initializeParams(version: str) -> dict:
    return {
        "protocolVersion": version,
        "capabilities": {},
        "clientInfo": {"name": "neurova-promises-judge", "version": "1"},
    }

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
            super().__init__(storage=None)
            self.calls = []

        def list_tools(self, caller=None):
            return list(_CORE_TOOLS)

        async def call_tool(self, name, arguments=None, caller=None):
            self.calls.append((name, dict(arguments or {})))
            if name == "skill:summarize":
                return {"success": True, "result": "ok"}
            return await super().call_tool(name, arguments, caller=caller)

    server = _Recording()
    monkeypatch.setattr(mcp_server_api, "_get_mcp_server", lambda: server)
    return server


@pytest.fixture
def face(recordingServer):
    app = FastAPI()
    mcp_server_api.mountFace(app, ENDPOINT, "Neurova MCP Server Face")
    with TestClient(app) as entered:
        entered.headers.update(_token("u1"))
        yield entered, recordingServer


class TestAnonymousGate:
    def test_anonymousRequestsAreRefused(self):
        """不打任何凭证时，握手与清单都必须被拒——这条是平台既有身份通道的入口。

        注意这里**不设**任何覆盖：用的就是面自己声明的那条鉴权（现在那条在 ASGI 包装层里，
        与平台共用 `security` ＋ `get_current_user_or_service` 同一对原语）。
        """
        app = FastAPI()
        mcp_server_api.mountFace(app, ENDPOINT, "Neurova MCP Server Face")
        with TestClient(app) as client:
            for method, params in (
                ("initialize", _initializeParams("2025-11-25")),
                ("tools/list", None),
            ):
                resp = client.post(ENDPOINT, json=_rpc(method, params))
                assert resp.status_code == 401, f"{method} 匿名可得 {resp.status_code}：身份闸没了"

    def test_platformTokenStillGetsServed(self):
        """控制格：真签发的平台令牌必须能过——否则上面那条 401 只是"谁都拒"。"""
        app = FastAPI()
        mcp_server_api.mountFace(app, ENDPOINT, "Neurova MCP Server Face")
        with TestClient(app) as client:
            resp = client.post(
                ENDPOINT,
                json=_rpc("initialize", _initializeParams("2025-11-25")),
                headers=_token("face-probe"),
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
        # 换运输后的读数：SDK 的 `CallToolResult` **总是**序列化 `isError`，成功时是显式 false，
        # 而旧手写面是"只在真错时补这个键"。两种写法对客户端读的是同一个真假（schema 里
        # isError 本就带默认值 false），所以本格的判据从"键不存在"改成"显式为假"——
        # 这是 §6-339 那份清单漏记的一条分叉，随本批落台账（此处不预占号）。
        assert body["result"]["isError"] is False, body["result"]

    def testUnknownToolErrorEnvelopeSurvives(self, face):
        """不认识的名字 → 核心那份「未知 MCP 工具」必须走 MCP 错误信封。"""
        client, _server = face
        body = client.post(
            ENDPOINT, json=_rpc("tools/call", {"name": "totally-unknown-tool", "arguments": {}})
        ).json()
        result = body["result"]
        assert result["isError"] is True, "未知工具被换成协议级异常：MCP 语义要求错误走响应体"
        assert "totally-unknown-tool" in result["content"][0]["text"]

    def testWorkflowFailureReachesClientAsTheSameEnvelope(self, face):
        """§6-334 的 B 票裁甲在**运输侧**的落点：工作流那条腿的失败也必须是 isError。

        这一格原先是**故意空着**的——本档那时写道"workflow:* 不存在走 `success=False`
        业务体而不是 isError，这是现存语义分叉，登记等裁，不锁成正确行为"。裁定已下
        （统一成 isError），所以分叉的两条腿现在都要出声：不补这一格，核心侧改对了
        而 HTTP 面仍回旧形状也不会有人知道。
        """
        client, _server = face
        body = client.post(
            ENDPOINT,
            json=_rpc("tools/call", {"name": "workflow:没有这条流", "arguments": {}}),
        ).json()
        result = body["result"]
        assert result["isError"] is True, (
            f"运输侧又给出了第二种失败信封：{result}"
        )
        assert "没有这条流" in result["content"][0]["text"], result

    def testCuaSwitchRefusalComesFromCore(self, face, monkeypatch):
        """导出开关的拒绝文案必须由核心给（`NEUROVA_CUA_MCP_EXPORT`），端点不重述。"""
        client, _server = face
        monkeypatch.delenv("NEUROVA_CUA_MCP_EXPORT", raising=False)
        body = client.post(
            ENDPOINT, json=_rpc("tools/call", {"name": "computer_screenshot", "arguments": {}})
        ).json()
        text = body["result"]["content"][0]["text"]
        assert "NEUROVA_CUA_MCP_EXPORT" in text, f"开关语义没走核心那份：{text!r}"
