# -*- coding: utf-8 -*-
"""W0-1 双时态消费面收口（specs/2026-11-12 §2，CQ-10 转 implemented）。

现状复核（2026-11-13）：REST body 通道已通（KnowledgeSearchRequest.as_of/
known_at → search_knowledge → factsBitemporal），断点在探针判据窄于接线面
——cq_matrix 按 accessQuery 函数签名判（单符号探针，现读数 planned），且
MCP ontology_query 无同名参数透传、不可解析时间无显式 4xx。本档钉三件事：
① accessQuery 签名含 asOf/knownAt（探针翻绿判据，显式参数覆盖 body 同名字段）；
② MCP ontology_query 带 as_of/known_at 时透传 factsBitemporal 返回时点事实集；
③ 非法时间显式 400（REST）/结构化拒绝（MCP），不静默忽略。
"""

from __future__ import annotations

import inspect
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import HTTPException
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from neurova.api.endpoints.knowledge_common import KnowledgeSearchRequest
from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.foundation_schema import applyTo
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

_SERVICE_TOKEN = "test-mcp-service-token"


def _admit(store, subject, predicate, obj, validFrom=None, recordedAt=None):
    content = "%s %s %s" % (subject, predicate, obj)
    request = AdmissionRequest(
        agentId="default", subjectLabel=subject, predicateTermId=predicate,
        objectTerm=obj, content=content, validFrom=validFrom,
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": "unit:test", "statementText": content}])
    receipt = productionAdmissionGate(store).admit(request)
    if recordedAt:
        # 事务时间回拨是测试口径（真实写入 recorded_at 恒为 now）：
        # 直接 UPDATE 该行——被测的是查询，不是写入。
        with store._lock, store._conn:
            store._conn.execute(
                "UPDATE knowledge_facts SET recorded_at = ? WHERE fact_id = ?",
                (recordedAt, receipt.factId))
    return receipt


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


@pytest.fixture
def mcp_store():
    s = KnowledgeFactStore(":memory:")
    applyTo(s._conn)
    yield s
    s.close()


@pytest.fixture()
def asgi_app(mcp_store, monkeypatch):
    monkeypatch.setenv("NEUROVA_SERVICE_TOKEN", _SERVICE_TOKEN)
    import neurova.mcp_ontology_server as mod

    monkeypatch.setattr(mod, "_store", lambda: mcp_store)
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


class TestSignatureProbe:
    def test_accessQuerySignatureHasBothParams(self):
        """CQ-10 探针判据：accessQuery 签名含 asOf/knownAt 两参数（现 planned）。"""
        from neurova.api.endpoints.knowledge_access_facade import accessQuery

        params = inspect.signature(accessQuery).parameters
        missing = [name for name in ("asOf", "knownAt") if name not in params]
        assert missing == [], "CQ-10：accessQuery 签名缺双时态参数 %r" % missing


class TestRestFace:
    @pytest.mark.asyncio
    async def test_facadeExplicitParamsOverrideBody(self, monkeypatch):
        """显式查询参数优先于 body 同名字段，经同一 search_knowledge 单管道转发。"""
        import neurova.api.endpoints.knowledge_access_facade as facade

        captured: dict = {}

        async def fake_search(**kwargs):
            captured.update(kwargs)
            return []

        monkeypatch.setattr(
            "neurova.api.endpoints.knowledge_core.search_knowledge", fake_search)
        await facade.accessQuery(
            request=None, body=KnowledgeSearchRequest(query="订单", as_of="2020-01-01"),
            current_user={"tenant_id": "default"}, agent_id=None, scope="all",
            asOf="2026-11-10", knownAt=None)
        assert captured["body"].as_of == "2026-11-10", "显式 asOf 应覆盖 body 同名字段"

    @pytest.mark.asyncio
    async def test_bodyChannelTimePointDifference(self, monkeypatch, store):
        """回归守卫：body 通道时点差异（现状可能已绿，转正为守卫）。"""
        receiptB = _admit(store, "订单B", "assigned_to", "张三",
                          validFrom="2026-11-01T00:00:00+00:00")
        receiptA = _admit(store, "订单A", "assigned_to", "李四",
                          validFrom="2026-11-20T00:00:00+00:00")
        monkeypatch.setattr("neurova.knowledge.foundation.get_knowledge_fact_store",
                            lambda: store)
        from neurova.api.endpoints.knowledge_core import search_knowledge

        items = await search_knowledge(
            request=None,
            body=KnowledgeSearchRequest(query="", as_of="2026-11-10"),
            current_user={"tenant_id": "default"}, agent_id=None, scope="all")
        ids = [i["knowledge_id"] for i in items]
        assert receiptB.factId in ids and receiptA.factId not in ids, ids

    @pytest.mark.asyncio
    async def test_invalidAsOfExplicit400(self, monkeypatch, store):
        """非法时间显式 4xx，不静默忽略（现状静默空集即红）。"""
        _admit(store, "订单B", "assigned_to", "张三")
        monkeypatch.setattr("neurova.knowledge.foundation.get_knowledge_fact_store",
                            lambda: store)
        from neurova.api.endpoints.knowledge_core import search_knowledge

        with pytest.raises(HTTPException) as excinfo:
            await search_knowledge(
                request=None,
                body=KnowledgeSearchRequest(query="", as_of="not-a-time"),
                current_user={"tenant_id": "default"}, agent_id=None, scope="all")
        assert excinfo.value.status_code == 400
        # 判据单源在存储层 parseBitemporalStamp，字段名以存储层签名（asOf）回显
        assert "不可解析" in str(excinfo.value.detail)


class TestMcpTimePointQuery:
    @pytest.mark.asyncio
    async def test_asOfReturnsPointInTimeFacts(self, asgi_app, mcp_store):
        """MCP ontology_query 带 as_of 透传 factsBitemporal（现参数面缺如即红）。"""
        receiptB = _admit(mcp_store, "订单B", "assigned_to", "张三",
                          validFrom="2026-11-01T00:00:00+00:00")
        receiptA = _admit(mcp_store, "订单A", "assigned_to", "李四",
                          validFrom="2026-11-20T00:00:00+00:00")
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with asgi_app["lifespan"](asgi_app["asgi"]), \
                _session(asgi_app["asgi"], headers) as (session, _):
            res = await session.call_tool(
                "ontology_query", {"query": "订单", "as_of": "2026-11-10"})
            payload = json.loads(res.content[0].text)
            facts = payload.get("facts")
            assert facts is not None, "as_of 应切换到时点事实模式：%s" % payload
            ids = [f["fact_id"] for f in facts]
            assert receiptB.factId in ids and receiptA.factId not in ids, ids

    @pytest.mark.asyncio
    async def test_knownAtReturnsTransactionTimeFacts(self, asgi_app, mcp_store):
        receiptOld = _admit(mcp_store, "订单O", "assigned_to", "张三",
                            recordedAt="2026-11-01T00:00:00+00:00")
        receiptNew = _admit(mcp_store, "订单N", "assigned_to", "李四",
                            recordedAt="2026-11-12T00:00:00+00:00")
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with asgi_app["lifespan"](asgi_app["asgi"]), \
                _session(asgi_app["asgi"], headers) as (session, _):
            res = await session.call_tool(
                "ontology_query", {"query": "订单", "known_at": "2026-11-05"})
            payload = json.loads(res.content[0].text)
            facts = payload.get("facts")
            assert facts is not None, "known_at 应切换到时点事实模式：%s" % payload
            ids = [f["fact_id"] for f in facts]
            assert receiptOld.factId in ids and receiptNew.factId not in ids, ids

    @pytest.mark.asyncio
    async def test_invalidTimeStructuredReject(self, asgi_app, mcp_store):
        """非法时间结构化拒绝（诚实形态），不静默空集。"""
        _admit(mcp_store, "订单B", "assigned_to", "张三")
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with asgi_app["lifespan"](asgi_app["asgi"]), \
                _session(asgi_app["asgi"], headers) as (session, _):
            res = await session.call_tool(
                "ontology_query", {"query": "订单", "as_of": "not-a-time"})
            payload = json.loads(res.content[0].text)
            assert payload.get("rejected") is True and payload.get("detail"), payload
