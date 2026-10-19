# -*- coding: utf-8 -*-
"""`/api/v1/mcp` 的运输层改由官方 SDK 的 streamable-http 承载（§6-339 乙案，两裁已落 §6-340）。

本档审的是**换面之后对外承诺的形状**，一格都不假设运输是谁：请求一律经
`mcp_server_api.mountFace()` 挂出来的真面打进去，鉴权用真令牌，不走依赖覆盖
（覆盖在 ASGI 挂载下会静默失效——那正是 §6-340 读数②点名的形态，故本档从建起就不用它）。

七格里三格是**现在就红的红灯**（裁定甲、裁定乙、运输形态），四格是**现在就绿的锁**
（写清"设计成现在就该绿"的根据，不留恒真空守卫）：

| 格 | 现在 | 钉的是 |
| --- | --- | --- |
| `test_initializeWithoutCapabilitiesIsRejected` | 红（现面回 result） | 裁定甲：params 三件齐是新语义 |
| `test_nonEnvelopeBodyIs400InvalidRequestCode` | 红（现面回 200） | 裁定乙：400 配 -32600，不是 -32602 |
| `test_transportIsSdkSessionManagerNotHandRolledDispatch` | 红（现面是手写分派） | 运输真换了，且手写那份退役（教义 7） |
| `test_getIsRejectedRatherThanHeldOpen` | 绿（FastAPI 天然 405） | 换面后 GET 不许变成"流不结束的挂起面"（§6-339 读数③） |
| `test_fullParamsNegotiationSurvivesTheSwap` | 绿 | §6-302 的协商承诺没被换面换掉 |
| `test_toolsListEqualsTheCoreSingleton` | 绿 | 清单仍由 `NeurovaMCPServer` 单源产出，运输侧不另起一份 |
| `test_callToolReachesTheCoreSingleSource` | 绿 | 调用真落到核心的 `call_tool`，信封形状不变 |
"""

import ast
import inspect
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as nf_auth
from neurova.api.endpoints import mcp_server_api
from neurova.tool_layers.mcp_server import NeurovaMCPServer

ENDPOINT = "/api/v1/mcp"
SOURCE = Path(inspect.getsourcefile(mcp_server_api)).resolve()


def _rpc(method, params=None, id_=1):
    return {"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}


def _initializeParams(version: str, **omit):
    """spec 要求的三件齐：protocolVersion + capabilities + clientInfo。"""
    params = {
        "protocolVersion": version,
        "capabilities": {},
        "clientInfo": {"name": "neurova-judge", "version": "1"},
    }
    for key in omit:
        params.pop(key, None)
    return params


def _faceClient() -> TestClient:
    """真挂载入口 + 真 lifespan（`mountFace` 自带启停），鉴权用真令牌。"""
    app = FastAPI()
    mcp_server_api.mountFace(app, ENDPOINT, "Neurova MCP Server Face")
    return TestClient(app)


def _hdr(sub: str = "judge-sender"):
    token = nf_auth.create_access_token({"sub": sub, "neuser_id": sub, "role": "user"})
    return {"Authorization": f"Bearer {token}"}


class TestRuledRejections:
    """两裁的落点：裁定甲（缺件即拒）与裁定乙（400 配正码）。"""

    def test_initializeWithoutCapabilitiesIsRejected(self):
        """裁定甲：缺 `capabilities` 的 initialize 必须 -32602，不再是"什么形状都收"。"""
        with _faceClient() as client:
            resp = client.post(
                ENDPOINT,
                headers=_hdr(),
                json=_rpc("initialize", {"protocolVersion": "2025-11-25"}),
            )
        body = resp.json()
        assert body.get("error", {}).get("code") == -32602, (
            f"读数={body}——现面把 params 形状当不存在（缺 capabilities 也回 result）。"
            "裁定甲采的是 SDK 口径：initialize 的三件齐是协议要求，不是本仓可选项。"
        )

    def test_nonEnvelopeBodyIs400InvalidRequestCode(self):
        """裁定乙：不是 JSON-RPC 信封的体 → HTTP 跟 SDK 的 400，但码收成 -32600。

        两格同钉的理由（§6-340 读数③）：params 类 -32602 实测**全部走 HTTP 200**，
        只有信封类失败才是 400——所以"400→-32600"的改写不可能误伤裁定甲那条 -32602。
        只钉一格等于把"把改写条件从 status 放宽到 code"的口子留着。
        """
        with _faceClient() as client:
            resp = client.post(ENDPOINT, headers=_hdr(), json={"foo": 1})
        assert resp.status_code == 400, f"状态读数={resp.status_code} body={resp.text[:200]}"
        body = resp.json()
        assert body["error"]["code"] == -32600, (
            f"读数={body.get('error')}——-32602 是 Invalid params，这条请求根本没构成信封，"
            '正码是 -32600 "Invalid Request"'
        )


class TestTransportOwnership:
    """运输归 SDK，手写那份退役（教义 7：该功能仓内只剩一处实现被消费）。"""

    def test_transportIsSdkSessionManagerNotHandRolledDispatch(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        calleeNames = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        attrCallees = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert "StreamableHTTPSessionManager" in calleeNames, (
            "本面没有实例化 SDK 的 session manager——运输仍由仓内手写分派承担"
        )
        assert "Server" in calleeNames, "低层 Server 未装配：on_list_tools/on_call_tool 无处落地"
        assert "include_router" not in (calleeNames | attrCallees), (
            "路由登记与 ASGI 挂载并存＝同一张面两种挂载形态，装配层重新长出第二个事实源"
        )

    def test_statelessAndJsonResponseAreExplicit(self):
        """两条开关是本面承诺"单请求单 JSON 响应"的根据，不许靠 SDK 默认值。"""
        source = SOURCE.read_text(encoding="utf-8")
        tree = ast.parse(source)
        kwargs = {
            kw.arg: ast.unparse(kw.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", "") == "StreamableHTTPSessionManager"
            for kw in node.keywords
        }
        assert kwargs.get("stateless") == "True", f"stateless 读数={kwargs!r}"
        assert kwargs.get("json_response") == "True", f"json_response 读数={kwargs!r}"

    def test_getIsRejectedRatherThanHeldOpen(self):
        """这一格**设计成现在就绿**：现面由路由表只登记 POST 天然拿 405。

        它锁的是换面后——§6-339 实测 stateless+json_response 下 GET 该路径**不返回**
        （SSE 流不结束，线程 5s join 仍活着）。挂起面从"没有"变成"有一条"就是新缺陷，
        故换面必须自己把它拒掉，本格负责在它变成挂起时红。
        """
        with _faceClient() as client:
            resp = client.get(ENDPOINT, headers=_hdr())
        assert resp.status_code == 405, f"GET 读数={resp.status_code} body={resp.text[:160]!r}"


class TestPromisesSurviveTheSwap:
    """§6-302 那份对外承诺由新运输继续兑付——四格都是现在就绿的锁。"""

    def test_fullParamsNegotiationSurvivesTheSwap(self):
        with _faceClient() as client:
            echoed = client.post(
                ENDPOINT, headers=_hdr(), json=_rpc("initialize", _initializeParams("2025-06-18"))
            ).json()["result"]
            counter = client.post(
                ENDPOINT, headers=_hdr(), json=_rpc("initialize", _initializeParams("2099-01-01"))
            ).json()["result"]
        assert echoed["protocolVersion"] == "2025-06-18", f"支持的版本没回声：{echoed}"
        assert counter["protocolVersion"] == mcp_server_api.LATEST_HANDSHAKE_VERSION, (
            f"不支持的版本没反提案最新：{counter}"
        )
        assert counter["serverInfo"]["name"] == "neurova", f"serverInfo 换了名字：{counter}"

    def test_toolsListEqualsTheCoreSingleton(self, monkeypatch):
        """面上的清单必须**逐字段等于**核心那份——运输侧不许自己攒一份。

        取值用 stub 核心而不是现役核心：现役那份的内容随 storage/skill_registry 实况变，
        而本格要问的是"清单从哪来"，不是"清单里有几条"。
        """
        stub = [
            {"name": "workflow:alpha", "description": "A", "inputSchema": {"type": "object"}},
            {"name": "skill:beta", "description": "B", "inputSchema": {"type": "object", "properties": {"t": {"type": "string"}}}},
        ]

        class _Stub(NeurovaMCPServer):
            def list_tools(self):
                return list(stub)

        monkeypatch.setattr(mcp_server_api, "_get_mcp_server", lambda: _Stub())
        with _faceClient() as client:
            listed = client.post(ENDPOINT, headers=_hdr(), json=_rpc("tools/list")).json()
        onFace = [
            {k: tool[k] for k in ("name", "description", "inputSchema")}
            for tool in listed["result"]["tools"]
        ]
        assert onFace == stub, f"面上清单与核心那份不等值：\n  面={onFace}\n  核心={stub}"

    def test_callToolReachesTheCoreSingleSource(self, monkeypatch):
        """tools/call 必须落到核心的 `call_tool`，且信封形状（content[0].text + isError）不变。"""
        seen = {}

        class _Spy(NeurovaMCPServer):
            async def call_tool(self, name, arguments=None):
                seen["name"] = name
                seen["arguments"] = dict(arguments or {})
                return {"success": True, "result": {"echo": name}}

        monkeypatch.setattr(mcp_server_api, "_get_mcp_server", lambda: _Spy())
        with _faceClient() as client:
            body = client.post(
                ENDPOINT,
                headers=_hdr(),
                json=_rpc("tools/call", {"name": "skill:x", "arguments": {"k": "v"}}),
            ).json()
        assert seen == {"name": "skill:x", "arguments": {"k": "v"}}, f"核心读数={seen}"
        content = body["result"]["content"]
        assert content[0]["type"] == "text" and "isError" not in content[0], f"信封形状变了：{body}"
        assert '"echo"' in content[0]["text"], f"结果没交给调用方：{content}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
