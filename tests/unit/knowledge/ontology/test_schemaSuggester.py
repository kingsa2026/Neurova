# -*- coding: utf-8 -*-
"""schema 建议器（P1-2）判据（报告 §6）：

- 术语建议落 ontology_schema_suggestions（pending），同目标幂等不重复生成；
- LLM 精化成功用 LLM 结果（basis=llm），失败/畸形回退确定性基线（basis=rule）；
- 外键关系候选进既有 relation-candidates 审批流（声明键 + 命名规约推断）；
- join 探针证实上调置信度、payload 记 confirmed_by；探针失败如实未证实；
- 审批通过才登记术语并回填目录 term_id；被拒目标不再重生；
- runForAllSources 多源并行逐项隔离。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest

from neurova.knowledge.enterprise.schema_catalog import SchemaCatalogStore
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.compile_kit import runBounded
from neurova.knowledge.ontology.schema_suggester import (
    SchemaSuggester,
    humanizeTableName,
    parseLlmJson,
)
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    monkeypatch.setattr(
        "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: s
    )
    yield s
    s.close()


def _ingestSample(store: KnowledgeFactStore, sourceId: str = "erp",
                  tenantId: str = "default") -> SchemaCatalogStore:
    cat = SchemaCatalogStore(store)
    from neurova.knowledge.enterprise.protocols import SourceSchema

    schema = SourceSchema(sourceId=sourceId, sourceType="sql", tables=[
        {"name": "customers", "columns": [{"name": "id", "type": "INTEGER"},
                                          {"name": "name", "type": "TEXT"}]},
        {"name": "sales_orders", "columns": [{"name": "id", "type": "INTEGER"},
                                             {"name": "customer_id", "type": "INTEGER"},
                                             {"name": "total_amount", "type": "NUMERIC"}]},
        {"name": "products", "columns": [{"name": "id", "type": "INTEGER"},
                                         {"name": "title", "type": "TEXT"}]},
    ])
    relations = {"foreign_keys": [{"source_table": "sales_orders",
                                   "source_column": "customer_id",
                                   "target_table": "customers",
                                   "target_column": "id"}],
                 "primary_keys": {"customers": ["id"], "sales_orders": ["id"],
                                  "products": ["id"]}}
    cat.ingestSchema(tenantId, sourceId, "sql", schema, relations=relations)
    return cat


class TestSchemaSuggester:
    def testRunForSourceCreatesPendingTermSuggestionsIdempotent(self, store):
        cat = _ingestSample(store)
        suggester = SchemaSuggester(store, catalog=cat)
        first = suggester.runForSource("default", "erp")
        assert first["term_suggestions"] == 3
        pending = suggester.listSuggestions("default", status="pending")
        targets = {s["target"] for s in pending}
        assert "term:erp:sales_orders" in targets
        sales = [s for s in pending if s["target"] == "term:erp:sales_orders"][0]
        assert sales["payload"]["name"] == "Sales Orders"
        assert {c["column"] for c in sales["payload"]["columns"]} == \
            {"id", "customer_id", "total_amount"}
        # 幂等：重跑不重复生成
        second = suggester.runForSource("default", "erp")
        assert second["term_suggestions"] == 0
        assert len(suggester.listSuggestions("default", status="pending")) == 3

    def testLlmEnrichmentUsedWhenHealthyFallbackWhenBroken(self, store):
        cat = _ingestSample(store)
        suggester = SchemaSuggester(store, catalog=cat)

        def goodLlm(_prompt):
            return '```json\n{"name": "销售订单", "description": "客户购买记录", ' \
                   '"synonyms": ["订单"], "columns": ' \
                   '[{"column": "total_amount", "display_name": "订单金额"}]}\n```'

        suggester.runForSource("default", "erp", llmCall=goodLlm)
        sales = [s for s in suggester.listSuggestions("default")
                 if s["target"] == "term:erp:sales_orders"][0]
        assert sales["basis"] == "llm"
        assert sales["payload"]["name"] == "销售订单"
        assert sales["confidence"] == 0.7

        suggester2 = SchemaSuggester(store, catalog=cat)

        def badLlm(_prompt):
            return "不是 JSON 的回答"

        # 另摄一个 erp2 源再跑坏 LLM：回退确定性基线
        from neurova.knowledge.enterprise.protocols import SourceSchema

        SchemaCatalogStore(store).ingestSchema("default", "erp2", "sql", SourceSchema(
            sourceId="erp2", sourceType="sql",
            tables=[{"name": "invoices", "columns": [{"name": "id", "type": "INTEGER"}]}]))
        suggester2.runForSource("default", "erp2", llmCall=badLlm)
        invoice = [s for s in suggester2.listSuggestions("default")
                   if s["source_id"] == "erp2"][0]
        assert invoice["basis"] == "rule"
        assert invoice["payload"]["name"] == "Invoices"

    def testDeclaredAndInferredFkEdgesBecomeRelationCandidates(self, store):
        cat = _ingestSample(store)
        suggester = SchemaSuggester(store, catalog=cat)
        suggester.runForSource("default", "erp")
        pending = suggester._relations.list("default", status="pending")
        byText = {c["source_text"]: c for c in pending}
        # 声明外键
        declared = [t for t in byText if "声明外键" in t and "customer_id" in t]
        assert declared
        # 命名规约推断：sales_orders.product_id？本目录没有 product_id 列——
        # 改用 customers 表无外键；推断边为 0，声明边为 1
        assert len(pending) == 1
        assert pending[0]["confidence"] == 0.6

    def testInferredFkEdgeAndProbeConfirmation(self, store, tmp_path):
        # 旁库：b.a_id 值域确实对上 a.id（无声明外键）→ 命名规约推断 + 探针证实
        sidePath = tmp_path / "side.db"
        conn = sqlite3.connect(str(sidePath))
        conn.executescript("""
            CREATE TABLE a (id INTEGER PRIMARY KEY);
            CREATE TABLE b (id INTEGER PRIMARY KEY, a_id INTEGER);
            INSERT INTO a VALUES (1), (2);
            INSERT INTO b VALUES (1, 1), (2, 2);
        """)
        conn.commit()
        conn.close()
        from neurova.knowledge.enterprise.connectors_sql import SqlDirectAdapter
        from neurova.knowledge.enterprise.protocols import SourceSchema

        adapter = SqlDirectAdapter({"driver": "sqlite", "database": str(sidePath),
                                    "table": "b", "cursorColumn": "id"}, "erp")
        cat = SchemaCatalogStore(store)
        cat.ingestSchema("default", "erp", "sql", SourceSchema(
            sourceId="erp", sourceType="sql",
            tables=[{"name": "a", "columns": [{"name": "id", "type": "INTEGER"}]},
                    {"name": "b", "columns": [{"name": "id", "type": "INTEGER"},
                                              {"name": "a_id", "type": "INTEGER"}]}]))
        suggester = SchemaSuggester(store, catalog=cat)
        summary = suggester.runForSource("default", "erp", probeRunner=(
            lambda sql: _run(adapter.executeReadonly(sql))))
        assert summary["probes_confirmed"] == 1
        pending = suggester._relations.list("default", status="pending")
        assert len(pending) == 1
        assert pending[0]["confidence"] == 0.75
        assert "join 探针证实" in pending[0]["source_text"]

    def testApproveTermSuggestionRegistersTermAndLinksCatalog(self, store):
        cat = _ingestSample(store)
        suggester = SchemaSuggester(store, catalog=cat)
        suggester.runForSource("default", "erp")
        sales = [s for s in suggester.listSuggestions("default")
                 if s["target"] == "term:erp:sales_orders"][0]
        result = suggester.decideSuggestion("default", sales["suggestion_id"],
                                            "approved", reviewedBy="admin",
                                            evidenceHash=sales["evidence_hash"])
        assert result["term_id"] == "SalesOrders"
        assert cat.tableDetail("default", sales["payload"]["table_id"])["term_id"] \
            == "SalesOrders"
        registry = OntologyTermRegistry(store)
        term = registry.term("SalesOrders", tenantId="default")
        assert term is not None and term["label"] == "Sales Orders"
        # 已批准后再跑：同目标不重复生成（pending/approved 均视为活跃）
        again = suggester.runForSource("default", "erp")
        assert again["term_suggestions"] == 0
        assert len(suggester.listSuggestions("default", status="approved")) == 1

    def testRejectedSuggestionIsNotRegenerated(self, store):
        cat = _ingestSample(store)
        suggester = SchemaSuggester(store, catalog=cat)
        suggester.runForSource("default", "erp")
        first = suggester.listSuggestions("default")[0]
        suggester.decideSuggestion("default", first["suggestion_id"], "rejected",
                                   reviewedBy="admin",
                                   evidenceHash=first["evidence_hash"])
        again = suggester.runForSource("default", "erp")
        # 被拒目标不再重生（尊重人工否决），其余保持 pending 不重复生成
        assert again["term_suggestions"] == 0
        assert len(suggester.listSuggestions("default", status="pending")) == 2
        rejected = suggester.listSuggestions("default", status="rejected")
        assert [s["target"] for s in rejected] == [first["target"]]

    def testRunForAllSourcesIsolatesErrors(self, store):
        cat = _ingestSample(store)
        from neurova.knowledge.enterprise.protocols import SourceSchema

        cat.ingestSchema("default", "bad", "sql", SourceSchema(
            sourceId="bad", sourceType="sql",
            tables=[{"name": "t1", "columns": [{"name": "id", "type": "INTEGER"}]}]))
        suggester = SchemaSuggester(store, catalog=cat)
        # monkeypatch 单源跑批：对 bad 源抛错，验证逐项隔离
        original = suggester.runForSource

        def flaky(tenantId, sourceId, **kwargs):
            if sourceId == "bad":
                raise RuntimeError("源坏了")
            return original(tenantId, sourceId, **kwargs)

        suggester.runForSource = flaky  # type: ignore[method-assign]
        outcome = suggester.runForAllSources("default")
        assert len(outcome["errors"]) == 1
        assert outcome["errors"][0]["item"] == "bad"
        assert {s["source_id"] for s in outcome["sources"]} == {"erp"}


class TestHelpers:
    def testHumanizeAndSlug(self):
        assert humanizeTableName("sales_orders") == "Sales Orders"
        assert humanizeTableName("ORDERS") == "ORDERS"
        from neurova.knowledge.ontology.schema_suggester import _slugTermId

        assert _slugTermId("Sales Orders") == "SalesOrders"

    def testParseLlmJsonToleratesFence(self):
        assert parseLlmJson('```json\n{"a": 1}\n```') == {"a": 1}
        assert parseLlmJson('前缀 {"a": {"b": 2}} 后缀') == {"a": {"b": 2}}
        assert parseLlmJson("no json") is None
        assert parseLlmJson("") is None

    def testRunBoundedSmoke(self):
        outcome = runBounded([1, 2, 3], lambda item, _p: item * 2, maxWorkers=2)
        assert outcome["results"] == [2, 4, 6]
        assert outcome["errors"] == []


# ── REST 面（挂载走 knowledge.py 聚合器，此处按域直挂同款前缀）──────────

ADMIN = {"user_id": "9", "username": "admin", "role": "admin", "tenant_id": "default"}
VIEWER = {"user_id": "5", "username": "viewer", "role": "viewer", "tenant_id": "default"}
PREFIX = "/v1/knowledge"


class TestSchemaSuggestionRest:
    @pytest.fixture
    def restClient(self, store, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from neurova.api import auth as knowledge_auth
        from neurova.api.endpoints import knowledge_schema_suggester

        app = FastAPI()
        app.include_router(knowledge_schema_suggester.router, prefix=PREFIX)
        app.dependency_overrides[knowledge_auth.get_current_user_or_service] = \
            lambda: dict(ADMIN)
        yield TestClient(app)

    def testRunListApproveRejectRoundtrip(self, restClient, store):
        _ingestSample(store)
        runResp = restClient.post(PREFIX + "/ontology/schema-suggestions/run",
                                  json={"source_id": "erp"})
        assert runResp.status_code == 200, runResp.text
        assert runResp.json()["data"]["sources"][0]["term_suggestions"] == 3

        listing = restClient.get(
            PREFIX + "/ontology/schema-suggestions?status=pending").json()["data"]
        assert listing["total"] == 3
        target = [s for s in listing["items"]
                  if s["target"] == "term:erp:sales_orders"][0]

        approve = restClient.post(PREFIX + "/ontology/schema-suggestions/"
                                  + target["suggestion_id"] + "/approve",
                                  params={"evidence_hash": target["evidence_hash"]})
        assert approve.status_code == 200, approve.text
        assert approve.json()["data"]["term_id"] == "SalesOrders"

        reject = restClient.post(PREFIX + "/ontology/schema-suggestions/"
                                 + listing["items"][0]["suggestion_id"] + "/reject",
                                 params={"evidence_hash":
                                         listing["items"][0]["evidence_hash"]})
        assert reject.status_code == 200

    def testRunIsAdminOnly(self, restClient):
        from neurova.api import auth as knowledge_auth

        restClient.app.dependency_overrides[
            knowledge_auth.get_current_user_or_service] = lambda: dict(VIEWER)
        resp = restClient.post(PREFIX + "/ontology/schema-suggestions/run", json={})
        assert resp.status_code == 403

    def testListRejectsUnknownStatus(self, restClient):
        resp = restClient.get(PREFIX + "/ontology/schema-suggestions?status=bogus")
        assert resp.status_code == 400
