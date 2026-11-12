# -*- coding: utf-8 -*-
"""W2 函数层推导治理（specs/2026-11-12 §4）。

admission dispatch 唯一接线点同时点燃规则与函数引擎；函数结论经咽喉入账，
推导账本 source_kind=function（同批 v43 迁移）；物化档缺省 observe 不进检索
主路、enforce 进主路（复用 v35 语义）；ontology_compute 只读 dry 求值不落库；
MCP 工具在册。
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.foundation_schema import applyTo
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.function_registry import FunctionRegistry
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

_SERVICE_TOKEN = "test-mcp-service-token"


@pytest.fixture
def kb(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "kb.db"))
    registry = OntologyTermRegistry(s)
    registry.register("warehouses", "concept", label="仓库")
    registry.register("stores", "relation",
                      qualifierSchema={"allowed": {"capacity": {"type": "number"}}})
    registry.register("stock_level", "relation")
    registry.register("coverage_days", "relation")
    gate = productionAdmissionGate(s)
    for subject, cap in (("仓库W1", "200M"), ("仓库W2", "0.3G")):
        content = "%s stores 货物" % subject
        gate.admit(AdmissionRequest(
            agentId="default", subjectLabel=subject, predicateTermId="stores",
            objectTerm="货物", content=content, qualifier={"capacity": cap},
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test", "statementText": content}]))
    yield s, registry
    s.close()


def _registerStockLevel(s, materialization="observe"):
    reg = FunctionRegistry(s)
    reg.register(
        functionId="stock_level_fn", tenantId="default",
        exprText='sum(facts("stores", {"subject_key": "$subject"}))',
        outputPredicate="stock_level",
        inputBindings={"subject": "仓库"},
        materialization=materialization)
    return reg


class TestDerivationGovernance:
    def test_dispatchIgnitesBothEngines(self, kb):
        """admission dispatch 唯一接线点：写入 stores 事实同时点燃规则与函数引擎。"""
        s, _registry = kb
        _registerStockLevel(s)
        gate = productionAdmissionGate(s)
        receipt = gate.admit(AdmissionRequest(
            agentId="default", subjectLabel="仓库W3", predicateTermId="stores",
            objectTerm="货物", content="仓库W3 stores 货物",
            qualifier={"capacity": "1"},
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test", "statementText": "仓库W3 stores 货物"}]))
        facts = s.factsForSubject(receipt.subjectKey)
        conclusions = [f for f in facts if f["predicate_term_id"] == "stock_level"]
        assert conclusions, "新写入经 dispatch 应点燃函数引擎产出 stock_level"
        assert conclusions[0]["qualifier"].get("derived_by") == "function:stock_level_fn"

    def test_sourceKindFunctionInLedger(self, kb):
        s, _registry = kb
        _registerStockLevel(s)
        from neurova.knowledge.ontology.function_engine import FunctionEngine

        engine = FunctionEngine(s)
        produced = engine.fireFor("default", "stores")
        with s._lock:
            rows = s._conn.execute(
                "SELECT source_kind, rule_id FROM knowledge_derivation_edges"
                " WHERE derived_fact_id = ?", (produced[0],)).fetchall()
        assert rows, "推导边应记账"
        assert rows[0]["source_kind"] == "function"
        assert rows[0]["rule_id"] == "function:stock_level_fn"
        fires = s._derivationLedger.fires("function:stock_level_fn")
        assert fires, "ontology_rule_fires 同款行（rule_id 位写 function:<id>）"

    def test_observeHiddenFromRetrievalMainPath(self, kb):
        """observe 缺省：函数结论有推导边但不进检索主路（v35 语义复用）。"""
        s, _registry = kb
        _registerStockLevel(s, materialization="observe")
        from neurova.knowledge.ontology.function_engine import FunctionEngine

        FunctionEngine(s).fireFor("default", "stores")
        hidden = s._derivationLedger.hiddenDerivedFactIds("default")
        key = s.resolveSubjectKey("default", "仓库W1")
        fact = [f for f in s.factsForSubject(key)
                if f["predicate_term_id"] == "stock_level"]
        assert fact, "observe 结论应已落库"
        assert fact[0]["fact_id"] in hidden, "observe 函数结论应被主路摘除"

    def test_enforceEntersRetrievalMainPath(self, kb):
        s, _registry = kb
        _registerStockLevel(s, materialization="enforce")
        from neurova.knowledge.ontology.function_engine import FunctionEngine

        FunctionEngine(s).fireFor("default", "stores")
        hidden = s._derivationLedger.hiddenDerivedFactIds("default")
        key = s.resolveSubjectKey("default", "仓库W1")
        fact = [f for f in s.factsForSubject(key)
                if f["predicate_term_id"] == "stock_level"]
        assert fact and fact[0]["fact_id"] not in hidden, "enforce 函数结论进主路"

    def test_dryEvalDoesNotPersist(self, kb):
        """ontology_compute 只读 dry 求值：返回值＋输入快照＋表达式回显，零落库。"""
        s, _registry = kb
        _registerStockLevel(s)
        from neurova.knowledge.ontology.function_engine import FunctionEngine

        engine = FunctionEngine(s)
        key = s.resolveSubjectKey("default", "仓库W1")
        before = s.factsForSubject(key)
        result = engine.dryEval("stock_level_fn", subject="仓库W1", tenantId="default")
        assert result["value"] == pytest.approx(2e8), "主体过滤后只聚合 仓库W1 自己的 200M"
        assert result["expr_text"].startswith("sum("), "表达式回显"
        assert result["inputs"], "输入快照非空"
        assert len(s.factsForSubject(key)) == len(before), "dry 求值零落库"


class TestMcpTool:
    @pytest.fixture()
    def asgi_app(self, kb, monkeypatch):
        s, _registry = kb
        _registerStockLevel(s)
        monkeypatch.setenv("NEUROVA_SERVICE_TOKEN", _SERVICE_TOKEN)
        import neurova.mcp_ontology_server as mod

        monkeypatch.setattr(mod, "_store", lambda: s)
        from neurova.mcp_ontology_server import build_ontology_mcp_asgi

        asgi_entry, lifespan_cm = build_ontology_mcp_asgi()
        return {"asgi": asgi_entry, "lifespan": lifespan_cm}

    def _client(self, app, headers):
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 9))
        return httpx.AsyncClient(transport=transport, headers=headers,
                                 base_url="http://127.0.0.1:9")

    @pytest.mark.asyncio
    async def test_ontologyComputeInRegistry(self, asgi_app):
        headers = {"X-Service-Token": _SERVICE_TOKEN}
        http_client = self._client(asgi_app["asgi"], headers)
        async with asgi_app["lifespan"](asgi_app["asgi"]), \
                streamable_http_client(
                    "http://127.0.0.1:9/", http_client=http_client) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert "ontology_compute" in {t.name for t in tools.tools}
                res = await session.call_tool(
                    "ontology_compute", {"function_id": "stock_level_fn",
                                         "subject": "仓库W1"})
                payload = json.loads(res.content[0].text)
                assert payload.get("value") == pytest.approx(2e8), payload
