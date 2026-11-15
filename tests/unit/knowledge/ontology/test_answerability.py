# -*- coding: utf-8 -*-
"""answerability 预检（P1-3）与复合就绪探针（P2-2）判据。

- 覆盖度：命中实体占比；词面匹配（术语 label/别名 + 事实主体），LLM 抽取
  可选、失败回退确定性分词；无实体诚实低报；
- readiness：knowledge_ready＝术语+事实双非空；data_ready＝目录+启用源；
  全只读零网络；
- 三个面同判据：REST（/ontology/answerability、/ontology/readiness）与
  MCP 工具都转交同一模块，不各写一份。
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from neurova.api import auth as knowledge_auth
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.answerability import assessAnswerability
from neurova.knowledge.ontology.readiness import knowledgeReadiness
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

ADMIN = {"user_id": "9", "username": "admin", "role": "admin", "tenant_id": "default"}
PREFIX = "/v1/knowledge"
_SERVICE_TOKEN = "test-mcp-service-token"


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    monkeypatch.setattr(
        "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: s
    )
    yield s
    s.close()


def _seed(store: KnowledgeFactStore):
    registry = OntologyTermRegistry(store)
    registry.register("Order", "concept", label="订单", aliases=["采购单"])
    registry.register("Customer", "concept", label="客户")
    registry.register("Revenue", "concept", label="收入")
    store.upsertSubject("default", "USB Food Flash Drive", tenantId="default")


# ── 模块判据 ────────────────────────────────────────────────────────

class TestAnswerabilityModule:
    def testCoverageCountsMatchedShare(self, store):
        _seed(store)
        # 空格分隔保证确定性分词（不依赖 jieba 词界）
        result = assessAnswerability(store, "订单 客户 收入", tenantId="default")
        assert result["coverage"] == 1.0
        assert result["answerable"] is True
        assert all(e["matched"] for e in result["entities"])

    def testJiebaSegmentsCjkRuns(self, store):
        from neurova.knowledge.ontology.answerability import extractEntities

        entities = extractEntities("订单和客户的收入")
        assert {"订单", "客户", "收入"} <= set(entities)

    def testUncoveredEntitiesReportedHonestly(self, store):
        _seed(store)
        result = assessAnswerability(store, "订单 广告投放 竞品",
                                     tenantId="default")
        byName = {e["entity"]: e for e in result["entities"]}
        assert byName["订单"]["matched"] is True
        assert any(not e["matched"] for e in result["entities"])
        assert result["coverage"] < 0.5
        assert result["answerable"] is False  # 覆盖不足阈值，诚实低报

    def testThresholdBoundaryIsInclusive(self, store):
        _seed(store)
        first = assessAnswerability(store, "订单 广告投放 竞品",
                                    tenantId="default")
        again = assessAnswerability(store, "订单 广告投放 竞品", tenantId="default",
                                    threshold=first["coverage"])
        assert again["answerable"] is True  # coverage >= threshold 含等号

    def testLlmExtractionUsedAndFallbackOnGarbage(self, store):
        _seed(store)

        def goodLlm(_prompt):
            return '```json\n{"entities": ["订单", "USB Food Flash Drive"]}\n```'

        result = assessAnswerability(store, "任意问题", llmCall=goodLlm)
        assert [e["entity"] for e in result["entities"]] == \
            ["订单", "USB Food Flash Drive"]
        assert result["coverage"] == 1.0

        def badLlm(_prompt):
            return "我不是 JSON"

        fallback = assessAnswerability(store, "订单 status", llmCall=badLlm)
        # 确定性分词兜底：CJK 串「订单」＋拉丁词 status
        assert {e["entity"] for e in fallback["entities"]} >= {"订单"}

    def testSubjectAliasCovers(self, store):
        _seed(store)
        result = assessAnswerability(store, "USB Food Flash Drive 的订单",
                                     tenantId="default")
        assert result["coverage"] == 1.0
        vias = {e["via"] for e in result["entities"]}
        assert "subject" in vias

    def testEmptyQuestionIsHonest(self, store):
        result = assessAnswerability(store, "   ")
        assert result["coverage"] == 0.0
        assert result["answerable"] is False
        assert "未抽到实体" in result.get("note", "")


class TestReadinessModule:
    def testEmptyTenantIsNotReady(self, store):
        reading = knowledgeReadiness(store, "default")
        # 内置种子术语注册期即在场（terms_registered 恒 ≥ 1），但事实为空 → 不 ready
        assert reading["checks"]["terms_registered"] >= 1
        assert reading["checks"]["facts_present"] == 0
        assert reading["knowledge_ready"] is False
        assert reading["data_ready"] is False

    def testKnowledgeReadyNeedsTermsAndFacts(self, store):
        _seed(store)
        reading = knowledgeReadiness(store, "default")
        # 术语有、事实无 → 仍不 ready
        assert reading["checks"]["terms_registered"] >= 3
        assert reading["knowledge_ready"] is False
        store.upsertSubject("default", "订单", tenantId="default")
        # upsertSubject 不产生事实；直接落一条事实
        store.upsertFact("default", store.resolveSubjectKey("default", "订单"),
                         "Order", "测试", "测试内容")
        reading = knowledgeReadiness(store, "default")
        assert reading["knowledge_ready"] is True
        assert reading["data_ready"] is False

    def testDataReadyNeedsCatalogAndEnabledSource(self, store, tmp_path):
        _seed(store)
        store.upsertSubject("default", "订单", tenantId="default")
        store.upsertFact("default", store.resolveSubjectKey("default", "订单"),
                         "Order", "测试", "测试内容")
        cat = _catalog_ingest(store)
        ingestor = _save_enabled_source(store, str(tmp_path / "side.csv"))
        reading = knowledgeReadiness(store, "default")
        assert reading["checks"]["catalog_sources"] == 1
        assert reading["checks"]["enterprise_sources_enabled"] == 1
        assert reading["data_ready"] is True


def _catalog_ingest(store):
    from neurova.knowledge.enterprise.protocols import SourceSchema
    from neurova.knowledge.enterprise.schema_catalog import SchemaCatalogStore

    cat = SchemaCatalogStore(store)
    cat.ingestSchema("default", "erp", "sql", SourceSchema(
        sourceId="erp", sourceType="sql",
        tables=[{"name": "orders", "columns": [{"name": "id", "type": "INTEGER"}]}]))
    return cat


def _save_enabled_source(store, path):
    import pathlib

    pathlib.Path(path).write_text("a\n1\n", encoding="utf-8")
    from neurova.knowledge.enterprise.registry import EnterpriseIngestor
    from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

    ingestor = EnterpriseIngestor(store, registry=OntologyTermRegistry(store))
    ingestor.saveConfig("default", "erp", {
        "sourceType": "file", "format": "csv", "path": path,
        "columns": ["a"], "subject": {"template": "row:{a}"},
        "predicate": {"termId": "Order"}, "object": {"kind": "term",
                                                     "termId": "Order"},
    }, enabled=True)
    return ingestor


# ── REST 面 ─────────────────────────────────────────────────────────

@pytest.fixture
def client(store):
    from neurova.api.endpoints import knowledge_observability

    app = FastAPI()
    app.include_router(knowledge_observability.router, prefix=PREFIX)
    app.dependency_overrides[knowledge_auth.get_current_user_or_service] = \
        lambda: dict(ADMIN)
    return TestClient(app)


class TestReadinessAndAnswerabilityRest:
    def testReadinessEndpoint(self, client, store):
        _seed(store)
        resp = client.get(PREFIX + "/ontology/readiness")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["checks"]["terms_registered"] >= 3
        assert data["knowledge_ready"] is False

    def testAnswerabilityEndpoint(self, client, store):
        _seed(store)
        resp = client.post(PREFIX + "/ontology/answerability",
                           json={"question": "订单和客户的收入"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["coverage"] == 1.0
        assert data["answerable"] is True

    def testAnswerabilityEmptyQuestionRejected(self, client):
        resp = client.post(PREFIX + "/ontology/answerability", json={"question": ""})
        assert resp.status_code == 422


# ── MCP 工具面（复用既有 asgi 范式：env 令牌 + _store 替身 + lifespan 手动驱动）──

_SERVICE_TOKEN = "test-mcp-service-token"


@pytest.fixture()
def asgi_app(store, monkeypatch):
    monkeypatch.setenv("NEUROVA_SERVICE_TOKEN", _SERVICE_TOKEN)
    import neurova.mcp_ontology_server as mod

    monkeypatch.setattr(mod, "_store", lambda: store)
    from neurova.mcp_ontology_server import build_ontology_mcp_asgi

    asgiEntry, lifespanCm = build_ontology_mcp_asgi()
    return {"asgi": asgiEntry, "lifespan": lifespanCm}


def _mcpClient(app, headers):
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 9))
    return httpx.AsyncClient(transport=transport, headers=headers,
                             base_url="http://127.0.0.1:9")


@asynccontextmanager
async def _mcpSession(app, headers):
    http_client = _mcpClient(app, headers)
    async with streamable_http_client("http://127.0.0.1:9/",
                                      http_client=http_client) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            yield session, http_client


class TestMcpReadProbes:
    @pytest.mark.asyncio
    async def testMcpAnswerabilityTool(self, asgi_app, store):
        _seed(store)
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with asgi_app["lifespan"](asgi_app["asgi"]), \
                _mcpSession(asgi_app["asgi"], headers) as (session, _):
            res = await session.call_tool("ontology_answerability",
                                          {"question": "订单和客户的收入"})
            payload = json.loads(res.content[0].text)
            assert payload["coverage"] == 1.0
            assert payload["answerable"] is True

    @pytest.mark.asyncio
    async def testMcpReadinessTool(self, asgi_app, store):
        _seed(store)
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        async with asgi_app["lifespan"](asgi_app["asgi"]), \
                _mcpSession(asgi_app["asgi"], headers) as (session, _):
            tools = await session.list_tools()
            assert "ontology_readiness" in {t.name for t in tools.tools}
            res = await session.call_tool("ontology_readiness", {})
            payload = json.loads(res.content[0].text)
            assert payload["checks"]["terms_registered"] >= 3
            assert payload["knowledge_ready"] is False
