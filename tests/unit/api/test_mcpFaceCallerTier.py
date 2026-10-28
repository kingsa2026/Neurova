# -*- coding: utf-8 -*-
"""MCP 导出面的调用方层级：这一发能不能驱动这个 agent，由**属主判定单源**说。

台账 §6-355 末那张票裁乙（按身份收口）后落_here_的两件事：

1. 判定不许在这道边界里重写一遍。口径的唯一出处是 `neurova/api/agent_access.py`
   （admin 全量／owner 匹配／无主仅 admin），`chat` 的执行门读的也是它——两处各写一份
   就必然漂移（教义 第 6 条）。这里有一格按 AST 认这一档确实调了那个函数。
2. `caller` 是**按请求**传的，不挂跨请求共享的核心单例。§6-352 实测到的形状就是
   "任何持平台令牌者可对默认 agent 的执行池任意点名"，修法不能顺手再造一个
   "上一发的授权漏进下一发"的新洞（同一族见那条 cancel scope 跨 task 的实测）。

本机现网读数（活体复跑可得）：默认 agent **无属主**（`resolve_agent_owner("default") is None`），
所以按这条口径，普通用户令牌落到窄层、admin 令牌落到全开层——这两格各取一个真令牌实测。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as nf_auth
from neurova.api.endpoints import mcp_server_api
from neurova.tool_layers.mcp_server import NeurovaMCPServer
from tests.ast_scan import parseSource

ENDPOINT = "/api/v1/mcp"


def _token(sub: str, role: str) -> dict:
    claims = {"sub": sub, "neuser_id": sub, "role": role}
    return {"Authorization": "Bearer " + nf_auth.create_access_token(claims)}


def _rpc(method, params=None, id_=1):
    return {"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}


def _initialize() -> dict:
    return _rpc("initialize", {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "caller-tier-judge", "version": "1"},
    })


class _SpyCore(NeurovaMCPServer):
    """记下 handler 递进来的 caller，并回一份固定清单——这档审的是边界**递了什么**，
    技能面本身由 `tests/unit/workflow/test_mcp_server_face.py` 那档钉，不在这里重述。"""

    def __init__(self):
        super().__init__(storage=None)
        self.seen = []

    def list_tools(self, caller=None):
        self.seen.append(caller)
        return []

    async def call_tool(self, name, arguments=None, caller=None):
        self.seen.append(caller)
        return {"success": True, "result": {"name": name}}


@pytest.fixture
def spy(monkeypatch):
    core = _SpyCore()
    monkeypatch.setattr(mcp_server_api, "_get_mcp_server", lambda: core)
    app = FastAPI()
    mcp_server_api.mountFace(app, ENDPOINT, "Neurova MCP Server Face")
    with TestClient(app) as client:
        yield client, core


class TestCallerCarriesTheAgentAccessRuling:
    def testOrdinaryUserTokenLandsOnTheNarrowTier(self, spy):
        """默认 agent 无属主 ⇒ 普通用户令牌**不该**拿到驱动权（现口径：无主仅 admin）。

        要先打一发 `tools/list` 才有读数：`initialize` 不触达那两个 handler
        （第一版就据此打红过一回，红的是我的取数点，不是实现）。
        """
        client, core = spy
        client.post(ENDPOINT, json=_initialize(), headers=_token("alice", "user"))
        client.post(ENDPOINT, json=_rpc("tools/list"), headers=_token("alice", "user"))
        caller = core.seen[0]
        assert caller is not None, "边界没把 caller 递给核心——那核心只能按最窄层猜"
        assert caller.mayDriveAgent is False, "普通用户被判成可驱动该 agent，属主口径在这道门上失效"

    def testAdminTokenLandsOnTheFullTier(self, spy):
        """控制格：窄层不是一刀切——admin 按同一条口径必须落到全开层。"""
        client, core = spy
        client.post(ENDPOINT, json=_initialize(), headers=_token("root", "admin"))
        client.post(ENDPOINT, json=_rpc("tools/list"), headers=_token("root", "admin"))
        caller = core.seen[0]
        assert caller is not None and caller.mayDriveAgent is True, caller

    def testCallerUserIdIsTheTokenSubject(self, spy):
        """身份从令牌到执行链只有那一条通道：caller 里的 userId 必须就是令牌的 user_id，
        这道门不许再解一次 Authorization（§3 身份单通道，与 `auth.py` 那段"同求异解"旧病同族）。"""
        client, core = spy
        client.post(ENDPOINT, json=_initialize(), headers=_token("carol", "user"))
        client.post(ENDPOINT, json=_rpc("tools/list"), headers=_token("carol", "user"))
        listed = [c for c in core.seen if c is not None]
        assert listed and all(c.userId == "carol" for c in listed), [c.userId for c in listed]

    def testRulingIsDelegatedToTheSingleSourceNotRewrittenHere(self):
        """按 AST 认：本模块把判定**委托**给 `agent_access`，没有自己比对 owner_user_id。

        按词扫会被 docstring 里的同名说明骗到（形态集 241/268 那一族），所以按 import 语句
        与属性访问的节点形态判，而不是数子串。
        """
        import ast
        from pathlib import Path

        source = Path(mcp_server_api.__file__).read_text(encoding="utf-8")
        imported = set()
        for node in ast.walk(parseSource(source)):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        assert "neurova.api.agent_access" in imported, (
            "边界没有从属主判定单源取口径——那这里就是第二份实现"
        )
        assert "owner_user_id" not in source, (
            "本模块自己读了 owner_user_id：口径已经从单源漏出第二份"
        )
