# -*- coding: utf-8 -*-
"""外部编码代理只读 MCP 工具面（ACP P2 卡 C2）契约测试。

- 鉴权：无凭证 fail-closed 401；X-Service-Token / Bearer JWT 任一成立即可过；
- tools/list：只读三件套 team_list / knowledge_search / memory_search 全量在册，
  且逐工具声明 readOnlyHint；
- team_list 与 teams 单源（GET /v1/teams 的 list_teams）读数一致，跨租户不可见；
- knowledge_search 走知识仓库单源（search_visible_items）的租户/可见性过滤；
- memory_search 走运行 agent 注册表的 recall 引擎，他人 agent 的记忆不可见；
- 超大/非法入参：诚实结构化拒绝（rejected + detail），输出体有界（截断留痕）。

协议真实性：mcp SDK 原生 streamable_http_client + ClientSession 走完整 MCP 协议
（httpx ASGITransport 直连 ASGI app，不打真端口）。
"""
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

_SERVICE_TOKEN = "test-agent-tools-service-token"
_JWT_SECRET = "test-agent-tools-jwt-secret-0123456789abcdef"

_SERVICE_IDENTITY = {
    "user_id": "system", "username": "service", "role": "admin",
    "neuser_id": "system", "tenant_id": "default",
    "auth_source": "service_token",
}
_USER_U1_IDENTITY = {
    "user_id": "u1", "username": "alice", "role": "user",
    "neuser_id": "u1", "tenant_id": "default",
}


@pytest.fixture()
def authEnv(monkeypatch):
    monkeypatch.setenv("NEUROVA_SERVICE_TOKEN", _SERVICE_TOKEN)
    monkeypatch.setenv("NEUROVA_JWT_SECRET", _JWT_SECRET)


@pytest.fixture()
def seededTeams(monkeypatch):
    """teams 单源库直注两租户各一队（list_teams 的过滤口径就是被测对象）。"""
    from neurova.api.endpoints import teams_api

    now = 1700000000.0
    store = {
        "team-default": {
            "id": "team-default", "name": "默认租户团队", "description": "d",
            "project_id": None, "owner_id": "u1", "tenant_id": "default",
            "members_detail": [{"user_id": "u1", "name": "alice", "role": "member",
                                "prompt": "干活的", "joined_at": now}],
            "created_at": now, "updated_at": now, "origin": "manual",
            "approved_by": "", "promoted_from_run": "",
        },
        "team-other": {
            "id": "team-other", "name": "别的租户团队", "description": "o",
            "project_id": None, "owner_id": "u9", "tenant_id": "other-tenant",
            "members_detail": [],
            "created_at": now, "updated_at": now, "origin": "manual",
            "approved_by": "", "promoted_from_run": "",
        },
    }
    monkeypatch.setattr(teams_api, "_teams_store", store)
    return store


@pytest.fixture()
def seededKnowledge(monkeypatch, tmp_path):
    """真知识仓库（tmp 目录）+ 单源接管：跨租户条目必须不可见。"""
    import neurova.knowledge.repository as repo_mod
    from neurova.knowledge.repository import KnowledgeRepository

    repo = KnowledgeRepository(str(tmp_path / "kb"))
    monkeypatch.setattr(repo_mod, "get_knowledge_repository", lambda: repo)
    repo.create_knowledge("agent-a", "部署手册", "部署手册：先装依赖再起服务",
                          visibility="public", owner_user_id="u1",
                          tenant_id="default", detect_conflict=False)
    repo.create_knowledge("agent-a", "U1 私有笔记", "U1 私有部署手册：密钥轮换",
                          visibility="private", owner_user_id="u1",
                          tenant_id="default", detect_conflict=False)
    repo.create_knowledge("agent-a", "别家租户手册", "别家租户的部署手册：不应可见",
                          visibility="public", owner_user_id="u9",
                          tenant_id="other-tenant", detect_conflict=False)
    return repo


class _FakeRecallEngine:
    """确定性假召回引擎：只实现被测壳真正消费的 recall_flat 面，
    行对象用真 RecalledMemory 数据类（to_dict 与生产同形）。"""

    def __init__(self, rows):
        self._rows = rows
        self.queries = []

    def recall_flat(self, query, limit=20, **_kwargs):
        from neurova.cognitive_layers.memory_layer.neurova_recall import RecalledMemory

        self.queries.append(query)
        return [RecalledMemory(**row) for row in self._rows][:limit]


def _fakeAgent(owner, engine):
    return SimpleNamespace(
        config=SimpleNamespace(owner_user_id=owner),
        memory_agent=SimpleNamespace(recall_engine=engine))


@pytest.fixture()
def seededAgents(monkeypatch):
    """运行 agent 注册表（endpoints._app_state）注入两个属主不同的假 agent。"""
    from neurova.api import endpoints as endpoints_mod

    engineA = _FakeRecallEngine([
        {"memory_id": "m-a1", "content": "agent-a 的记忆", "score": 0.9},
    ])
    engineB = _FakeRecallEngine([
        {"memory_id": "m-b1", "content": "agent-b 的记忆", "score": 0.8},
    ])
    agents = {
        "agent-a": _fakeAgent("u1", engineA),
        "agent-b": _fakeAgent("someone-else", engineB),
    }
    monkeypatch.setattr(endpoints_mod, "_app_state",
                        {"agents": agents, "default_agent_id": "agent-a"})
    return agents


@pytest.fixture()
def asgi_app(authEnv, seededTeams, seededKnowledge, seededAgents):
    from neurova.mcp_agent_tools_server import build_agent_tools_mcp_asgi

    # 每请求独立运输（stateless），无 app 级 lifespan 需要进入
    return build_agent_tools_mcp_asgi()


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


def _jwtHeaders(monkeypatch, identity):
    from neurova.api.auth import create_access_token

    token = create_access_token({
        "sub": identity["user_id"], "username": identity["username"],
        "role": identity["role"], "tenant_id": identity["tenant_id"],
        "neuser_id": identity["neuser_id"],
    })
    return {"Authorization": "Bearer %s" % token}


async def _callTool(session, name, arguments):
    res = await session.call_tool(name, arguments)
    assert res.content, "工具响应缺 content"
    return json.loads(res.content[0].text)


class TestAuth:
    @pytest.mark.asyncio
    async def test_noCredentialsFailClosed401(self, asgi_app):
        async with _client(asgi_app, {}) as http:
            resp = await http.post("/", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_serviceTokenAcceptedAndToolsListed(self, asgi_app):
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with _session(asgi_app, headers) as (session, _):
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert {"team_list", "knowledge_search", "memory_search"} <= names
            # 只读红线：每个工具都向客户端声明 read_only_hint（MCP 字段名 readOnlyHint）
            byName = {t.name: t for t in tools.tools}
            for name in ("team_list", "knowledge_search", "memory_search"):
                annotations = getattr(byName[name], "annotations", None)
                assert annotations is not None and annotations.read_only_hint is True, name

    @pytest.mark.asyncio
    async def test_jwtBearerAccepted(self, asgi_app, monkeypatch):
        headers = _jwtHeaders(monkeypatch, _USER_U1_IDENTITY)
        async with _session(asgi_app, headers) as (session, _):
            tools = await session.list_tools()
            assert {"team_list", "knowledge_search", "memory_search"} <= {t.name for t in tools.tools}

    @pytest.mark.asyncio
    async def test_invalidJwtFailClosed401(self, asgi_app):
        async with _client(asgi_app, {"Authorization": "Bearer not-a-token"}) as http:
            resp = await http.post("/", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
            assert resp.status_code == 401


class TestTeamList:
    @pytest.mark.asyncio
    async def test_teamListMatchesTeamsSingleSource(self, asgi_app):
        """team_list 与 teams 单源同读数：直接对拍 list_teams 同身份返回。"""
        from neurova.api.endpoints import teams_api

        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with _session(asgi_app, headers) as (session, _):
            payload = await _callTool(session, "team_list", {})
            single = await teams_api.list_teams(current_user=_SERVICE_IDENTITY)
            assert [t["id"] for t in payload["teams"]] == [t.id for t in single]
            assert payload["count"] == len(single)

    @pytest.mark.asyncio
    async def test_teamListTenantFiltered(self, asgi_app):
        """跨租户团队不可见（§6.4 红线）。"""
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with _session(asgi_app, headers) as (session, _):
            payload = await _callTool(session, "team_list", {})
            ids = {t["id"] for t in payload["teams"]}
            assert "team-default" in ids
            assert "team-other" not in ids
            assert payload["tenant_id"] == "default"


class TestKnowledgeSearch:
    @pytest.mark.asyncio
    async def test_searchHitsVisibleOnly(self, asgi_app, monkeypatch):
        """属主检索：public + 自己私库命中；跨租户条目不可见。"""
        headers = _jwtHeaders(monkeypatch, _USER_U1_IDENTITY)
        async with _session(asgi_app, headers) as (session, _):
            payload = await _callTool(session, "knowledge_search", {"query": "部署手册"})
            titles = " ".join(r["title"] for r in payload["results"])
            assert "部署手册" in titles
            assert "U1 私有笔记" in titles
            assert "别家租户手册" not in titles

    @pytest.mark.asyncio
    async def test_searchMatchesRepositorySingleSource(self, asgi_app):
        """与知识仓库单源直接检索同读数（同一过滤口径，防壳层私改）。"""
        from neurova.knowledge.repository import get_knowledge_repository

        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with _session(asgi_app, headers) as (session, _):
            payload = await _callTool(session, "knowledge_search", {"query": "部署手册"})
            direct = get_knowledge_repository().search_visible_items(
                _SERVICE_IDENTITY, "部署手册", limit=10)
            assert payload["count"] == len(direct)
            assert [r["knowledge_id"] for r in payload["results"]] == \
                [d["knowledge_id"] for d in direct]

    @pytest.mark.asyncio
    async def test_emptyQueryRejected(self, asgi_app):
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with _session(asgi_app, headers) as (session, _):
            payload = await _callTool(session, "knowledge_search", {"query": "   "})
            assert payload.get("rejected") is True
            assert payload.get("detail")

    @pytest.mark.asyncio
    async def test_oversizedQueryRejected(self, asgi_app):
        from neurova.mcp_agent_tools_server import MAX_QUERY_CHARS

        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with _session(asgi_app, headers) as (session, _):
            payload = await _callTool(session, "knowledge_search",
                                      {"query": "x" * (MAX_QUERY_CHARS + 1)})
            assert payload.get("rejected") is True
            assert "query" in payload.get("detail", "")

    @pytest.mark.asyncio
    async def test_limitClampedToUpperBound(self, asgi_app, seededKnowledge):
        """limit 超大被钳位：返回条数不超过 MAX_RESULTS_PER_TOOL。"""
        from neurova.mcp_agent_tools_server import MAX_RESULTS_PER_TOOL

        for i in range(MAX_RESULTS_PER_TOOL + 5):
            seededKnowledge.create_knowledge(
                "agent-a", "批量条目 %d" % i, "批量部署手册 %d" % i,
                visibility="public", owner_user_id="u1",
                tenant_id="default", detect_conflict=False)
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with _session(asgi_app, headers) as (session, _):
            payload = await _callTool(session, "knowledge_search",
                                      {"query": "批量部署手册", "limit": 100000})
            assert payload["count"] <= MAX_RESULTS_PER_TOOL
            assert payload["count"] == MAX_RESULTS_PER_TOOL


class TestMemorySearch:
    @pytest.mark.asyncio
    async def test_ownerSeesOwnAgentMemoryOnly(self, asgi_app, monkeypatch):
        """非 admin 只见自己属主 agent 的记忆（can_access_agent 单源门）。"""
        headers = _jwtHeaders(monkeypatch, _USER_U1_IDENTITY)
        async with _session(asgi_app, headers) as (session, _):
            payload = await _callTool(session, "memory_search", {"query": "记忆"})
            ids = [r["memory_id"] for r in payload["results"]]
            assert "m-a1" in ids
            assert "m-b1" not in ids
            assert payload["engines_queried"] == 1

    @pytest.mark.asyncio
    async def test_adminSeesAllAgents(self, asgi_app):
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with _session(asgi_app, headers) as (session, _):
            payload = await _callTool(session, "memory_search", {"query": "记忆"})
            ids = {r["memory_id"] for r in payload["results"]}
            assert {"m-a1", "m-b1"} <= ids
            assert payload["engines_queried"] == 2

    @pytest.mark.asyncio
    async def test_agentFilterRespectsOwnership(self, asgi_app, monkeypatch):
        """指名他人 agent：不产生读数也不泄露内容，诚实报零引擎。"""
        headers = _jwtHeaders(monkeypatch, _USER_U1_IDENTITY)
        async with _session(asgi_app, headers) as (session, _):
            payload = await _callTool(session, "memory_search",
                                      {"query": "记忆", "agent_id": "agent-b"})
            assert payload["results"] == []
            assert payload["engines_queried"] == 0
            assert payload.get("detail")

    @pytest.mark.asyncio
    async def test_hugeContentClipped(self, asgi_app, seededAgents):
        """超大单条内容被截断留痕，整体输出有界。"""
        from neurova.mcp_agent_tools_server import MAX_TEXT_CHARS

        huge = "x" * (MAX_TEXT_CHARS * 10)
        seededAgents["agent-a"].memory_agent.recall_engine = _FakeRecallEngine([
            {"memory_id": "m-huge", "content": huge, "score": 1.0},
        ])
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with _session(asgi_app, headers) as (session, _):
            payload = await _callTool(session, "memory_search", {"query": "记忆"})
            row = next(r for r in payload["results"] if r["memory_id"] == "m-huge")
            assert len(row["content"]) < MAX_TEXT_CHARS * 2
            assert "截断" in row["content"]

    @pytest.mark.asyncio
    async def test_emptyQueryRejected(self, asgi_app):
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with _session(asgi_app, headers) as (session, _):
            payload = await _callTool(session, "memory_search", {"query": ""})
            assert payload.get("rejected") is True
            assert payload.get("detail")


class TestDeviceStatus:
    """设备桥批三 B6：device_status 只读工具——属主过滤与 REST /pairing/list
    同一单源（listDevicesForUser），跨属主设备不可见，在线态叠活连接。"""

    @pytest.fixture()
    def seededDevices(self, monkeypatch, tmp_path):
        from neurova.api.endpoints import mobile_pairing
        from neurova.core.mobile_device_store import MobileDeviceStore

        store = MobileDeviceStore(str(tmp_path / "devices.db"))
        store.register(pairingId="pair-u1", userId="u1", deviceName="U1 手机",
                       deviceType="mobile", deviceSecret="secret-1")
        store.recordHello("pair-u1", platform="android", protocolVersion=1,
                          capabilities=["open_url", "device_env"],
                          appState="foreground")
        store.register(pairingId="pair-u9", userId="u9", deviceName="U9 手机",
                       deviceType="mobile", deviceSecret="secret-9")
        monkeypatch.setattr(mobile_pairing, "getDeviceRegistry", lambda: store)
        monkeypatch.setattr(mobile_pairing, "_ws_connections", {"pair-u1": object()})
        return store

    @pytest.mark.asyncio
    async def test_deviceStatusListedAndReadOnly(self, asgi_app, seededDevices):
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with _session(asgi_app, headers) as (session, _):
            tools = await session.list_tools()
            byName = {t.name: t for t in tools.tools}
            assert "device_status" in byName
            annotations = getattr(byName["device_status"], "annotations", None)
            assert annotations is not None and annotations.read_only_hint is True

    @pytest.mark.asyncio
    async def test_deviceStatusOwnerScoped(self, asgi_app, seededDevices, monkeypatch):
        """u1 只见自己名下设备，能力目录与在线态随 hello/活连接如实反映。"""
        headers = _jwtHeaders(monkeypatch, _USER_U1_IDENTITY)
        async with _session(asgi_app, headers) as (session, _):
            payload = await _callTool(session, "device_status", {})
            ids = [d["pairing_id"] for d in payload["devices"]]
            assert ids == ["pair-u1"]
            row = payload["devices"][0]
            assert row["is_online"] is True and row["state"] == "online"
            assert row["capabilities"] == ["open_url", "device_env"]
            assert row["platform"] == "android"

    @pytest.mark.asyncio
    async def test_deviceStatusPairingIdFilterNoLeak(self, asgi_app, seededDevices, monkeypatch):
        """指名他人设备：空结果 + 诚实说明，不泄露存在性。"""
        headers = _jwtHeaders(monkeypatch, _USER_U1_IDENTITY)
        async with _session(asgi_app, headers) as (session, _):
            other = await _callTool(session, "device_status", {"pairing_id": "pair-u9"})
            assert other["devices"] == [] and other["count"] == 0
            assert other.get("detail")
            own = await _callTool(session, "device_status", {"pairing_id": "pair-u1"})
            assert own["count"] == 1

    @pytest.mark.asyncio
    async def test_deviceStatusOfflineProjected(self, asgi_app, seededDevices, monkeypatch):
        """不在活连接里的设备如实报 offline（同一投影单源）。"""
        u9 = dict(_USER_U1_IDENTITY, user_id="u9", username="bob", neuser_id="u9")
        headers = _jwtHeaders(monkeypatch, u9)
        async with _session(asgi_app, headers) as (session, _):
            payload = await _callTool(session, "device_status", {})
            assert [d["pairing_id"] for d in payload["devices"]] == ["pair-u9"]
            assert payload["devices"][0]["is_online"] is False
            assert payload["devices"][0]["state"] == "offline"


class TestAppWiring:
    """真装配（create_app）里的挂载事实：深路径先注册、无尾斜杠归一。"""

    def test_mountedBeforeOntologyBody(self):
        from neurova.api.app import create_app

        app = create_app(enable_memory=False, enable_channels=False)
        paths = [getattr(r, "path", "") for r in app.router.routes
                 if type(r).__name__ == "Mount" and "mcp" in getattr(r, "path", "")]
        assert "/v1/mcp/agent-tools" in paths, paths
        # 深路径必须先于 /v1/mcp 本体注册（Starlette Mount 先命中），否则被吞
        assert paths.index("/v1/mcp/agent-tools") < paths.index("/v1/mcp"), paths

    @pytest.mark.asyncio
    async def test_noSlashFormRedirectsToCanonical(self):
        """无尾斜杠写法 307 归一（否则被 /v1/mcp 本体 Mount 截走后 404）。"""
        from neurova.api.app import create_app

        app = create_app(enable_memory=False, enable_channels=False)
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 9))
        async with httpx.AsyncClient(transport=transport, base_url="http://t",
                                     follow_redirects=False) as http:
            body = {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
            r = await http.post("/v1/mcp/agent-tools", json=body)
            assert r.status_code == 307, (r.status_code, r.text[:80])
            assert r.headers["location"].endswith("/v1/mcp/agent-tools/")
            r2 = await http.post("/v1/mcp/agent-tools/", json=body)
            assert r2.status_code == 401


class TestIdentityFailClosed:
    """修复计划 M2：MCP 工具上下文身份读取缺失时必须 fail-closed，
    不得回落 admin/service 视角（缺省即 admin 是权限面 fail-open）。"""

    def _ctx(self, withUser=None):
        state = SimpleNamespace(**({"neurova_user": withUser} if withUser is not None else {}))
        request = SimpleNamespace(state=state)
        return SimpleNamespace(request_context=SimpleNamespace(request=request))

    def test_missing_identity_raises(self):
        from neurova.mcp_ontology_server import _currentUserFromContext

        with pytest.raises(Exception) as ei:
            _currentUserFromContext(self._ctx())
        assert "identity" in str(ei.value).lower() or "身份" in str(ei.value)

    def test_broken_context_raises_not_admin(self):
        from neurova.mcp_ontology_server import _currentUserFromContext

        class _Boom:
            request_context = property(lambda self: (_ for _ in ()).throw(RuntimeError("broken")))

        with pytest.raises(Exception):
            _currentUserFromContext(_Boom())

    def test_present_identity_returned_unchanged(self):
        from neurova.mcp_ontology_server import _currentUserFromContext

        user = {"user_id": "u1", "role": "user", "tenant_id": "t1"}
        assert _currentUserFromContext(self._ctx(withUser=user)) is user


class TestApiKeyTenantIdentity:
    """M3：MCP 面 API-key 身份的租户段取自密钥本体（不再硬编码 default）。"""

    def test_api_key_identity_carries_key_tenant(self, monkeypatch):
        from types import SimpleNamespace as NS
        from neurova.api import api_key_manager as akm
        from neurova.mcp_ontology_server import _resolveIdentityFromHeaders

        key = NS(user_id="u9", name="部门钥", agent_id="agent_9", key_id="k9",
                 tenant_id="dept_z")
        monkeypatch.setattr(akm, "get_api_key_manager",
                            lambda: NS(validate_key=lambda raw: key if raw == "RAW9" else None))

        from neurova.api.auth import _API_KEY_HEADER

        ident = _resolveIdentityFromHeaders({_API_KEY_HEADER.lower(): "RAW9"})
        assert ident is not None
        assert ident["tenant_id"] == "dept_z", "API-key 身份租户必须取自密钥本体"
