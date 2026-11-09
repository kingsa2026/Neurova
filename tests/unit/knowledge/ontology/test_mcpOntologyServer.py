# -*- coding: utf-8 -*-
"""本体 MCP server 契约测试（Ontology 接入 Agent 补全设计 M0/A1/A2）。

- M0：streamable-http 端点挂 ASGI；鉴权双支持（X-Service-Token/X-API-Key/
  Bearer JWT）全不成立 fail-closed 401；
- A1：list_tools 见 ontology_query/ontology_validate；call 与 REST 同源；
- A2：fact_submit 经 admission 咽喉——evidence 缺失被逐字可核闸拒、正常写入
  返回 fact_id（默认直写拍板）。

协议真实性：用 mcp SDK 原生 `streamable_http_client` + `ClientSession` 走完整
MCP 协议（httpx ASGITransport 直连 app，不打真端口）。
"""
import json

import httpx
from contextlib import asynccontextmanager
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from neurova.knowledge.foundation.foundation_schema import applyTo
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

_SERVICE_TOKEN = "test-mcp-service-token"


@pytest.fixture()
def store():
    store = KnowledgeFactStore(":memory:")
    applyTo(store._conn)
    yield store


@pytest.fixture()
def asgi_app(store, monkeypatch):
    monkeypatch.setenv("NEUROVA_SERVICE_TOKEN", _SERVICE_TOKEN)
    import neurova.mcp_ontology_server as mod

    monkeypatch.setattr(mod, "_store", lambda: store)
    registry = OntologyTermRegistry(store)
    registry.register("Order", "concept", label="订单")
    registry.register("vip_level", "relation", label="VIP 等级", domain=["Order"])
    from neurova.mcp_ontology_server import build_ontology_mcp_asgi

    asgi_entry, lifespan_cm = build_ontology_mcp_asgi()
    return {"asgi": asgi_entry, "lifespan": lifespan_cm}





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


class TestM0Auth:
    @pytest.mark.asyncio
    async def test_noCredentialsFailClosed401(self, asgi_app, store):
        async with asgi_app["lifespan"](asgi_app["asgi"]), _client(asgi_app["asgi"], {}) as http:
            resp = await http.post("/", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_serviceTokenAccepted(self, asgi_app, store):
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with asgi_app["lifespan"](asgi_app["asgi"]), _session(asgi_app["asgi"], headers) as (session, _):
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert {"ontology_query", "ontology_validate", "fact_submit"} <= names


class TestA1Tools:
    @pytest.mark.asyncio
    async def test_ontologyQueryMatchesByLabel(self, asgi_app, store):
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with asgi_app["lifespan"](asgi_app["asgi"]), _session(asgi_app["asgi"], headers) as (session, _):
            res = await session.call_tool("ontology_query", {"query": "订单"})
            payload = json.loads(res.content[0].text)
            assert payload["count"] >= 1
            assert any(m["term_id"] == "Order" for m in payload["matches"])

    @pytest.mark.asyncio
    async def test_ontologyValidateDryRun(self, asgi_app, store):
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with asgi_app["lifespan"](asgi_app["asgi"]), _session(asgi_app["asgi"], headers) as (session, _):
            res = await session.call_tool(
                "ontology_validate",
                {"subject_label": "订单D01", "predicate_term_id": "is_a",
                 "object_term": "Order"})
            payload = json.loads(res.content[0].text)
            assert payload["verdict"] in ("pass", "violation")
            assert isinstance(payload["findings"], list)


class TestA2FactSubmit:
    @pytest.mark.asyncio
    async def test_unverifiableIdentifierRejected(self, asgi_app, store):
        """admission 逐字可核闸契约继承：断言里的精确标识符不在证据原文中
        （编造 URL/编号类）→ AdmissionError 结构化回显。"""
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with asgi_app["lifespan"](asgi_app["asgi"]), _session(asgi_app["asgi"], headers) as (session, _):
            res = await session.call_tool(
                "fact_submit",
                {"subject_label": "https://cdn.example.org/pkg-9f7a.whl",
                 "predicate_term_id": "is_a",
                 "object_term": "Order",
                 "evidence_text": "这段证据里没有任何可核的标识符原文"})
            payload = json.loads(res.content[0].text)
            assert payload.get("rejected") is True, payload
            assert payload.get("detail")

    @pytest.mark.asyncio
    async def test_submitWithEvidenceWritesFact(self, asgi_app, store):
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with asgi_app["lifespan"](asgi_app["asgi"]), _session(asgi_app["asgi"], headers) as (session, _):
            res = await session.call_tool(
                "fact_submit",
                {"subject_label": "订单D01", "predicate_term_id": "is_a",
                 "object_term": "Order", "evidence_text": "订单D01 is_a Order"})
            payload = json.loads(res.content[0].text)
            assert payload.get("fact_id"), payload
            assert "adoption_hint" in payload

    @pytest.mark.asyncio
    async def test_idempotentResubmit(self, asgi_app, store):
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with asgi_app["lifespan"](asgi_app["asgi"]), _session(asgi_app["asgi"], headers) as (session, _):
            body = {"subject_label": "订单D02", "predicate_term_id": "is_a",
                    "object_term": "Order", "evidence_text": "订单D02 is_a Order"}
            r1 = json.loads((await session.call_tool("fact_submit", body)).content[0].text)
            r2 = json.loads((await session.call_tool("fact_submit", body)).content[0].text)
            # 二次提交要么同 fact（去重）要么如实报状态——不得产生孤儿第二行
            assert r1.get("fact_id") == r2.get("fact_id") or r2.get("deduplicated")
