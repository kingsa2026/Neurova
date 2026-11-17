# -*- coding: utf-8 -*-
"""S18 G2 收尾：MCP 团队/项目工具壳契约测试（工具壳两层、机制单源）。

- 转交同源：经 MCP 调用 team_list/team_dispatch/project_list/project_detail
  与原生 list_teams/dispatch_team/project_* 走**同一条** ToolExecutor.execute
  管道（同工具名同参 ⇒ 同治理三明治/审批链/run 溯源标），壳只做参数适配
  与协议封装，不新建第二套执行逻辑；
- 描述/schema 同源：MCP 工具描述取自原生 builtin schema，不复制两份；
- 双鉴权照旧：无凭据 fail-closed 401；
- 成员工具面剔除（builtin_tools.MAIN_AGENT_ONLY_TOOLS）在 MCP 侧同样生效：
  活动蜂群成员身份不可经 MCP 绕过成员限制。

协议真实性：mcp SDK 原生 streamable_http_client + ClientSession 走完整
MCP 协议（httpx ASGITransport 直连 app，不打真端口）——同 test_mcpOntologyServer。
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from neurova.knowledge.foundation.foundation_schema import applyTo
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

_SERVICE_TOKEN = "test-mcp-service-token"

_TEAM_TOOL_PAIRS = (
    ("team_list", "list_teams"),
    ("team_dispatch", "dispatch_team"),
    ("project_list", "project_list"),
    ("project_detail", "project_detail"),
)


class _FakeExecutor:
    """记录 execute 调用的替身执行器——断言 MCP 壳转交的原生工具名与参数。"""

    def __init__(self):
        self.calls: list = []

    async def execute(self, tool_name, params):
        self.calls.append((tool_name, dict(params or {})))
        return {"success": True, "tool": tool_name, "params": dict(params or {}),
                "marker": "native-pipeline"}


@pytest.fixture()
def mcp_store():
    store = KnowledgeFactStore(":memory:")
    applyTo(store._conn)
    yield store
    store.close()


@pytest.fixture()
def asgi_app(mcp_store, monkeypatch):
    monkeypatch.setenv("NEUROVA_SERVICE_TOKEN", _SERVICE_TOKEN)
    import neurova.mcp_ontology_server as mod

    monkeypatch.setattr(mod, "_store", lambda: mcp_store)
    from neurova.mcp_ontology_server import build_ontology_mcp_asgi

    asgi_entry, lifespan_cm = build_ontology_mcp_asgi()
    return {"asgi": asgi_entry, "lifespan": lifespan_cm, "mod": mod}


def _client(app, headers):
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 9))
    return httpx.AsyncClient(transport=transport, headers=headers,
                             base_url="http://127.0.0.1:9")


@asynccontextmanager
async def _session(app, headers):
    http_client = _client(app, headers)
    async with streamable_http_client("http://127.0.0.1:9/", http_client=http_client) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            yield session, http_client


async def _callTool(session, name, args):
    res = await session.call_tool(name, args)
    return json.loads(res.content[0].text)


class TestTeamToolSurface:
    @pytest.mark.asyncio
    async def test_teamToolsAdvertised(self, asgi_app):
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with asgi_app["lifespan"](asgi_app["asgi"]), \
                _session(asgi_app["asgi"], headers) as (session, _):
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            for mcpName, _native in _TEAM_TOOL_PAIRS:
                assert mcpName in names, f"MCP 面缺少团队工具壳: {mcpName}"

    @pytest.mark.asyncio
    async def test_descriptionsMatchNativeSchema(self, asgi_app):
        """描述与原生 builtin schema 同源（同一份字符串，不复制两份防漂移）。"""
        from neurova.builtin_tools import get_builtin_tool_params

        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with asgi_app["lifespan"](asgi_app["asgi"]), \
                _session(asgi_app["asgi"], headers) as (session, _):
            tools = {t.name: t for t in (await session.list_tools()).tools}
            for mcpName, nativeName in _TEAM_TOOL_PAIRS:
                nativeDesc = str((get_builtin_tool_params(nativeName) or {})
                                 .get("description") or "").strip()
                assert nativeDesc, f"原生工具 {nativeName} 缺描述"
                assert str(tools[mcpName].description or "").strip() == nativeDesc, (
                    f"MCP 工具 {mcpName} 描述与原生 {nativeName} 不同源")

    @pytest.mark.asyncio
    async def test_requiredParamsMatchNativeSchema(self, asgi_app):
        """必填参数与原生 schema 同源（壳不私改参数契约）。"""
        from neurova.builtin_tools import get_builtin_tool_params

        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with asgi_app["lifespan"](asgi_app["asgi"]), \
                _session(asgi_app["asgi"], headers) as (session, _):
            tools = {t.name: t for t in (await session.list_tools()).tools}
            for mcpName, nativeName in _TEAM_TOOL_PAIRS:
                nativeRequired = list(((get_builtin_tool_params(nativeName) or {})
                                       .get("parameters") or {}).get("required") or [])
                advertisedRequired = list((tools[mcpName].input_schema or {})
                                          .get("required") or [])
                assert sorted(advertisedRequired) == sorted(nativeRequired), (
                    f"MCP 工具 {mcpName} 必填参数与原生 {nativeName} 不一致: "
                    f"{advertisedRequired} vs {nativeRequired}")


class TestTeamToolDelegation:
    @pytest.mark.asyncio
    async def test_teamDispatchSamePipelineAsNative(self, asgi_app, monkeypatch):
        """经 MCP 调 team_dispatch 与原生 dispatch_team 走同一执行管道：
        壳转交 executor.execute("dispatch_team", 同参)，结果原样回传——
        同一 run 溯源标/治理计数由单管道保证，壳不旁路。"""
        fake = _FakeExecutor()
        monkeypatch.setattr(asgi_app["mod"], "_resolveAgentForActions",
                            lambda agentId: {"executor": fake, "agent": None})
        params = {"team_id": "team-alpha", "task": "整理季度数据并出报告",
                  "task_unit": {"goal": "出报告"}, "background": False}
        # 原生路径基准：同一执行体的直接调用
        nativeResult = await fake.execute("dispatch_team", dict(params))
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with asgi_app["lifespan"](asgi_app["asgi"]), \
                _session(asgi_app["asgi"], headers) as (session, _):
            payload = await _callTool(session, "team_dispatch", params)
        assert fake.calls[-1] == ("dispatch_team", params), \
            f"MCP 壳未按原生工具名/参数转交: {fake.calls}"
        assert payload == nativeResult, "MCP 调用结果与原生执行体结果不一致"
        assert payload["marker"] == "native-pipeline"

    @pytest.mark.asyncio
    async def test_teamListDelegatesWithEmptyParams(self, asgi_app, monkeypatch):
        fake = _FakeExecutor()
        monkeypatch.setattr(asgi_app["mod"], "_resolveAgentForActions",
                            lambda agentId: {"executor": fake, "agent": None})
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with asgi_app["lifespan"](asgi_app["asgi"]), \
                _session(asgi_app["asgi"], headers) as (session, _):
            payload = await _callTool(session, "team_list", {})
        assert fake.calls == [("list_teams", {})]
        assert payload["tool"] == "list_teams"

    @pytest.mark.asyncio
    async def test_projectDetailDelegates(self, asgi_app, monkeypatch):
        fake = _FakeExecutor()
        monkeypatch.setattr(asgi_app["mod"], "_resolveAgentForActions",
                            lambda agentId: {"executor": fake, "agent": None})
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with asgi_app["lifespan"](asgi_app["asgi"]), \
                _session(asgi_app["asgi"], headers) as (session, _):
            payload = await _callTool(session, "project_detail",
                                      {"project_id": "proj-1"})
        assert fake.calls == [("project_detail", {"project_id": "proj-1"})]
        assert payload["success"] is True

    @pytest.mark.asyncio
    async def test_teamDispatchOmitsUnprovidedTaskUnit(self, asgi_app, monkeypatch):
        """参数适配契约：未提供 task_unit 时壳不传 None 键——原生参数校验
        对 task_unit 要求 object 型，显式 None 会被同管道校验拒收
        （live-verify 实测：task_unit: None is not of type 'object'）。"""
        fake = _FakeExecutor()
        monkeypatch.setattr(asgi_app["mod"], "_resolveAgentForActions",
                            lambda agentId: {"executor": fake, "agent": None})
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with asgi_app["lifespan"](asgi_app["asgi"]), \
                _session(asgi_app["asgi"], headers) as (session, _):
            await _callTool(session, "team_dispatch",
                            {"team_id": "t1", "task": "x"})
        assert fake.calls == [("dispatch_team",
                               {"team_id": "t1", "task": "x", "background": True})]

    @pytest.mark.asyncio
    async def test_agentNotReadyStructuredReject(self, asgi_app, monkeypatch):
        """执行载体不可用时结构化拒绝（不静默、不降级）。"""
        monkeypatch.setattr(asgi_app["mod"], "_resolveAgentForActions",
                            lambda agentId: None)
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with asgi_app["lifespan"](asgi_app["asgi"]), \
                _session(asgi_app["asgi"], headers) as (session, _):
            payload = await _callTool(session, "team_list", {})
        assert payload.get("rejected") is True
        assert "未就绪" in str(payload.get("detail") or "")


class TestTeamToolAuthAndMemberGate:
    @pytest.mark.asyncio
    async def test_noCredentialsFailClosed401(self, asgi_app):
        """双鉴权照旧：无凭据 fail-closed 401（server 既有鉴权谓词覆盖新工具）。"""
        async with asgi_app["lifespan"](asgi_app["asgi"]), \
                _client(asgi_app["asgi"], {}) as http:
            resp = await http.post("/", json={"jsonrpc": "2.0", "id": 1,
                                              "method": "initialize"})
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_swarmMemberCannotUseTeamToolsViaMcp(self, asgi_app, monkeypatch):
        """成员面剔除语义在 MCP 侧同样生效：活动蜂群成员身份调用团队/项目
        工具一律结构化拒绝，且不触达执行体（不可经 MCP 绕过成员限制）。"""
        fake = _FakeExecutor()
        monkeypatch.setattr(asgi_app["mod"], "_resolveAgentForActions",
                            lambda agentId: {"executor": fake, "agent": None})
        monkeypatch.setattr(asgi_app["mod"], "_activeSwarmMemberAgentIds",
                            lambda: {"default"})
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with asgi_app["lifespan"](asgi_app["asgi"]), \
                _session(asgi_app["asgi"], headers) as (session, _):
            payloads = []
            payloads.append(await _callTool(session, "team_list", {}))
            payloads.append(await _callTool(
                session, "team_dispatch", {"team_id": "t1", "task": "x"}))
            payloads.append(await _callTool(session, "project_list", {}))
            payloads.append(await _callTool(session, "project_detail",
                                            {"project_id": "p1"}))
        for payload in payloads:
            assert payload.get("rejected") is True, payload
            assert payload.get("code") == "member_tool_not_allowed", payload
        assert fake.calls == [], "成员身份的 MCP 调用不得触达执行体"

    def test_activeSwarmMemberIdsReadsManagerListActive(self, monkeypatch):
        """成员判定读 SwarmManager.list_active 单源，过滤空 agent_id。"""
        import neurova.mcp_ontology_server as mod

        class _StubSwarm:
            def list_active(self):
                return [{"agent_id": "member-1"}, {"agent_id": ""},
                        {"subagent_id": "swarm_x"}]

        import neurova.agent.swarm as swarmMod

        monkeypatch.setattr(swarmMod, "get_swarm_manager", lambda: _StubSwarm())
        assert mod._activeSwarmMemberAgentIds() == {"member-1"}
