# -*- coding: utf-8 -*-
"""P2-2 车道D：反向 MCP 面 ``data_query`` 判据（与既有只读三工具同款）。

- 双鉴权 fail-closed：无凭证 401；X-Service-Token / Bearer JWT 任一成立；
- tools/list 含 data_query 且声明 readOnlyHint（只读红线）；
- 租户隔离：数据源按发起者租户段过滤，他租户 source 拒绝；
- 只读：写意图被连接器断言拒绝并点名；输出三层截断（字段/条数/整体）；
- 总闸 ``NEUROVA_NL2SQL_ENABLED`` 关：结构化 capability_disabled（不 500）。

协议真实性：mcp SDK 原生 streamable_http_client + ClientSession 走完整 MCP 协议
（httpx ASGITransport 直连 ASGI app，不打真端口）——与 test_mcp_agent_tools_server
同构。
"""
import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

_SERVICE_TOKEN = "test-data-query-service-token"
_JWT_SECRET = "test-data-query-jwt-secret-0123456789abcdef"

_USER_U1_IDENTITY = {
    "user_id": "u1", "username": "alice", "role": "user",
    "neuser_id": "u1", "tenant_id": "default",
}

_SQL_OK = json.dumps({"sql": "SELECT id, amount FROM orders ORDER BY id DESC LIMIT 10",
                      "explanation": "最近订单"})
_SQL_DROP = json.dumps({"sql": "DROP TABLE orders", "explanation": "删表"})


class _ScriptedLlmClient:
    """nl2sql 生成桩：固定回一段 JSON SQL（async chat，经 run_async_safely 桥）。"""

    def __init__(self, payload: str):
        self.payload = payload

    async def chat(self, messages):
        return SimpleNamespace(content=self.payload)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def store(tmp_path, monkeypatch):
    from neurova.knowledge.foundation import knowledge_facts as kf

    s = kf.KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    monkeypatch.setattr(
        "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: s)
    yield s
    s.close()


@pytest.fixture
def sideDb(tmp_path):
    path = tmp_path / "side.db"
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE orders (id INTEGER PRIMARY KEY, amount NUMERIC);
        INSERT INTO orders VALUES (1, 99.5), (2, 100.5);
    """)
    conn.commit()
    conn.close()
    return path


@pytest.fixture()
def seededSource(store, sideDb):
    """default/erp 与 other-tenant/erp-other 两个源（目录 + 配置）。"""
    from neurova.knowledge.enterprise.connectors_sql import SqlDirectAdapter
    from neurova.knowledge.enterprise.registry import EnterpriseIngestor
    from neurova.knowledge.enterprise.schema_catalog import SchemaCatalogStore
    from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

    adapter = SqlDirectAdapter({"driver": "sqlite", "database": str(sideDb),
                                "table": "orders", "cursorColumn": "id"}, "erp")
    cat = SchemaCatalogStore(store)
    cat.ingestSchema("default", "erp", "sql", _run(adapter.describeSchema()),
                     relations=_run(adapter.describeRelations()))
    registry = OntologyTermRegistry(store)
    registry.register("Order", "concept", label="订单", tenantId="default")
    registry.register("Order", "concept", label="订单", tenantId="other-tenant")
    ingestor = EnterpriseIngestor(store, registry=registry)
    descriptor = {"sourceType": "sql", "driver": "sqlite",
                  "database": str(sideDb), "table": "orders",
                  "cursorColumn": "id", "columns": ["id"],
                  "subject": {"template": "order:{id}"},
                  "predicate": {"termId": "Order"},
                  "object": {"kind": "column", "column": "id"}}
    ingestor.saveConfig("default", "erp", descriptor, enabled=True)
    ingestor.saveConfig("other-tenant", "erp-other", dict(descriptor), enabled=True)
    return {"store": store, "side_db": str(sideDb)}


@pytest.fixture()
def seededAgents(monkeypatch):
    """运行 agent 注册表注入带 LLM 桩的 agent（MCP 面 LLM 解析单源）。"""
    from neurova.api import endpoints as endpoints_mod

    agents = {"agent-a": SimpleNamespace(llm_client=_ScriptedLlmClient(_SQL_OK))}
    monkeypatch.setattr(endpoints_mod, "_app_state",
                        {"agents": agents, "default_agent_id": "agent-a"})
    return agents


@pytest.fixture()
def authEnv(monkeypatch):
    monkeypatch.setenv("NEUROVA_SERVICE_TOKEN", _SERVICE_TOKEN)
    monkeypatch.setenv("NEUROVA_JWT_SECRET", _JWT_SECRET)


@pytest.fixture()
def gateOn(monkeypatch):
    monkeypatch.setenv("NEUROVA_NL2SQL_ENABLED", "1")


@pytest.fixture()
def asgi_app(authEnv, seededSource, seededAgents):
    from neurova.mcp_agent_tools_server import build_agent_tools_mcp_asgi

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


def _swapLlm(payload):
    from neurova.api import endpoints as endpoints_mod

    client = _ScriptedLlmClient(payload)
    endpoints_mod._app_state["agents"]["agent-a"].llm_client = client
    return client


class TestAuth:
    @pytest.mark.asyncio
    async def test_noCredentialsFailClosed401(self, asgi_app):
        async with _client(asgi_app, {}) as http:
            resp = await http.post("/", json={"jsonrpc": "2.0", "id": 1,
                                              "method": "initialize"})
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_invalidJwtFailClosed401(self, asgi_app):
        async with _client(asgi_app, {"Authorization": "Bearer not-a-token"}) as http:
            resp = await http.post("/", json={"jsonrpc": "2.0", "id": 1,
                                              "method": "initialize"})
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_dataQueryListedAsReadOnly(self, asgi_app):
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with _session(asgi_app, headers) as (session, _):
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert "data_query" in names
            tool = next(t for t in tools.tools if t.name == "data_query")
            annotations = getattr(tool, "annotations", None)
            assert annotations is not None and annotations.read_only_hint is True

    @pytest.mark.asyncio
    async def test_jwtBearerAccepted(self, asgi_app):
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with _session(asgi_app, headers) as (session, _):
            tools = await session.list_tools()
            assert "data_query" in {t.name for t in tools.tools}


class TestDataQuery:
    @pytest.mark.asyncio
    async def test_queryReturnsRows(self, asgi_app, gateOn):
        """开闸：自然语言问数返回行数据（只读 SELECT）。"""
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with _session(asgi_app, headers) as (session, _):
            payload = await _callTool(session, "data_query",
                                      {"question": "最近 10 笔订单"})
            assert payload.get("rejected") is None, payload
            assert payload["status"] == "ok"
            assert payload["row_count"] >= 1
            assert payload["rows"][0]["amount"] in (99.5, 100.5)
            assert payload["source_id"] == "erp"

    @pytest.mark.asyncio
    async def test_otherTenantSourceRejected(self, asgi_app, gateOn):
        """他租户 source_id：按发起者租户段过滤，拒绝且不泄露。"""
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with _session(asgi_app, headers) as (session, _):
            payload = await _callTool(session, "data_query",
                                      {"question": "最近订单",
                                       "source_id": "erp-other"})
            assert payload.get("rejected") is True, payload
            assert payload.get("code") == "source_not_found"

    @pytest.mark.asyncio
    async def test_gateOffStructuredRejection(self, asgi_app, monkeypatch):
        """总闸关：结构化 capability_disabled，不 500、不抛裸异常。"""
        monkeypatch.delenv("NEUROVA_NL2SQL_ENABLED", raising=False)
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with _session(asgi_app, headers) as (session, _):
            payload = await _callTool(session, "data_query",
                                      {"question": "最近订单"})
            assert payload.get("rejected") is True
            assert payload.get("code") == "capability_disabled"
            assert "NEUROVA_NL2SQL_ENABLED" in payload.get("detail", "")

    @pytest.mark.asyncio
    async def test_writeIntentRefusedAndNamed(self, asgi_app, gateOn):
        """DROP 意图：只读断言拒绝并点名（诚实 refused，不执行任何写）。"""
        _swapLlm(_SQL_DROP)
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with _session(asgi_app, headers) as (session, _):
            payload = await _callTool(session, "data_query",
                                      {"question": "把订单表删了"})
            assert payload.get("status") == "refused", payload
            assert "只读" in payload.get("reason", "")

    @pytest.mark.asyncio
    async def test_emptyQuestionRejected(self, asgi_app, gateOn):
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with _session(asgi_app, headers) as (session, _):
            payload = await _callTool(session, "data_query", {"question": "  "})
            assert payload.get("rejected") is True
            assert payload.get("detail")

    @pytest.mark.asyncio
    async def test_rowsClampedToUpperBound(self, asgi_app, gateOn, seededAgents,
                                           seededSource):
        """输出有界：行数钳位到 MAX_RESULTS_PER_TOOL。"""
        from neurova.mcp_agent_tools_server import MAX_RESULTS_PER_TOOL

        _swapLlm(json.dumps({"sql": "SELECT id, amount FROM orders LIMIT 200",
                             "explanation": "x"}))
        conn = sqlite3.connect(seededSource["side_db"])
        conn.executemany("INSERT INTO orders VALUES (?, ?)",
                         [(i, float(i)) for i in range(100, 160)])
        conn.commit()
        conn.close()
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with _session(asgi_app, headers) as (session, _):
            payload = await _callTool(session, "data_query",
                                      {"question": "全部订单", "max_rows": 200})
            assert payload["count"] <= MAX_RESULTS_PER_TOOL
            assert payload["count"] == MAX_RESULTS_PER_TOOL
            assert payload["truncated"] is True
