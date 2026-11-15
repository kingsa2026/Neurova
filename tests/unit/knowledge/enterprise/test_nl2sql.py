# -*- coding: utf-8 -*-
"""NL2SQL 批一（P1-4）与历史回灌（P2-3）判据。

- join 路径 BFS 确定性（无 LLM）；只读硬闸：写意图/多语句/目录外表/无上限
  全部显式拒；修复环一轮后诚实拒答；
- 端到端（sqlite 真旁库 + 假 LLM）：答案带 SQL/步骤/行数，历史逐次落账；
- 拒答/执行失败/空结果都如实落 history（P2-3 审计）；
- 高频表组合 → sql_pattern 候选（pending，走 P1-2 审批流），批准后进 prompt；
- REST：env 门控缺省 403 诚实点名；admin 闸；history 登录可读。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.knowledge.enterprise.connectors_sql import SqlDirectAdapter
from neurova.knowledge.enterprise.nl2sql import (
    Nl2SqlService,
    parseLlmSql,
    planJoinPaths,
    tablesInSql,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

ADMIN = {"user_id": "9", "username": "admin", "role": "admin", "tenant_id": "default"}
VIEWER = {"user_id": "5", "username": "viewer", "role": "viewer", "tenant_id": "default"}
PREFIX = "/v1/knowledge"

_EDGES = [
    {"source_table": "customers", "source_column": "id",
     "target_table": "orders", "target_column": "customer_id"},
    {"source_table": "orders", "source_column": "product_id",
     "target_table": "products", "target_column": "id"},
]


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


@pytest.fixture
def sideDb(tmp_path):
    path = tmp_path / "side.db"
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER
            REFERENCES customers(id), amount NUMERIC);
        INSERT INTO customers VALUES (1, 'kowloon');
        INSERT INTO orders VALUES (1, 1, 99.5), (2, 1, 100.5);
    """)
    conn.commit()
    conn.close()
    return path


def _ingestSideDb(store, sideDb):
    adapter = SqlDirectAdapter({"driver": "sqlite", "database": str(sideDb),
                                "table": "orders", "cursorColumn": "id"}, "erp")
    from neurova.knowledge.enterprise.schema_catalog import SchemaCatalogStore

    cat = SchemaCatalogStore(store)
    schema = _run(adapter.describeSchema())
    relations = _run(adapter.describeRelations())
    cat.ingestSchema("default", "erp", "sql", schema, relations=relations)
    return adapter


def _executorFor(adapter):
    return lambda sql, limit: _run(adapter.executeReadonly(sql, limit))


class TestJoinPathsAndValidation:
    def testBfsFindsShortestHops(self):
        paths = planJoinPaths(_EDGES, "customers")
        assert [h["target_table"] for h in paths["products"]] == \
            ["orders", "products"]
        assert paths["orders"][0]["source_table"] == "customers"

    def testBfsUnreachableAbsent(self):
        paths = planJoinPaths([{"source_table": "a", "source_column": "id",
                                "target_table": "b", "target_column": "a_id"}], "c")
        assert paths == {}

    def testTablesInSql(self):
        assert set(tablesInSql("SELECT * FROM orders o JOIN customers c"
                               " ON o.customer_id = c.id")) == {"orders", "customers"}

    def testParseLlmSqlToleratesFence(self):
        assert parseLlmSql('```json\n{"sql": "SELECT 1"}\n```') == {"sql": "SELECT 1"}
        assert parseLlmSql("垃圾") is None

    def testValidateRejectsUnknownTableAndMissingLimit(self):
        from neurova.knowledge.enterprise.nl2sql import Nl2SqlService

        tables = {"orders": {}, "customers": {}}
        with pytest.raises(ValueError, match="目录外表"):
            Nl2SqlService._validateSql("SELECT * FROM secrets LIMIT 5", tables, 200)
        with pytest.raises(ValueError, match="行数上限"):
            Nl2SqlService._validateSql("SELECT id FROM orders", tables, 200)
        with pytest.raises(ValueError, match="只读"):
            Nl2SqlService._validateSql("DELETE FROM orders LIMIT 5", tables, 200)
        Nl2SqlService._validateSql("SELECT id FROM orders LIMIT 5", tables, 200)


class TestAnswerQuestion:
    def testHappyPathWithRowsAndHistory(self, store, sideDb):
        adapter = _ingestSideDb(store, sideDb)
        service = Nl2SqlService(store)

        def llm(_prompt):
            return json.dumps({"sql": "SELECT c.name, SUM(o.amount) AS total"
                                      " FROM orders o JOIN customers c"
                                      " ON o.customer_id = c.id"
                                      " GROUP BY c.name LIMIT 10",
                               "explanation": "按客户汇总订单金额"})

        result = service.answerQuestion("default", "erp", "每个客户的总金额",
                                        llmCall=llm,
                                        executor=_executorFor(adapter),
                                        askedBy="admin")
        assert result["answerable"] is True
        assert result["status"] == "ok"
        assert result["row_count"] == 1
        assert result["rows"][0]["name"] == "kowloon"
        assert any("执行返回" in s for s in result["steps"])
        history = service.listHistory("default", "erp")
        assert history[0]["status"] == "ok"
        assert history[0]["question"] == "每个客户的总金额"

    def testRepairLoopRecoversFromBadFirstAttempt(self, store, sideDb):
        adapter = _ingestSideDb(store, sideDb)
        service = Nl2SqlService(store)
        calls = {"n": 0}

        def llm(_prompt):
            calls["n"] += 1
            if calls["n"] == 1:
                return json.dumps({"sql": "SELECT * FROM secrets LIMIT 5",
                                   "explanation": "坏输出"})
            return json.dumps({"sql": "SELECT id FROM orders LIMIT 5",
                               "explanation": "订单列表"})

        result = service.answerQuestion("default", "erp", "订单列表", llmCall=llm,
                                        executor=_executorFor(adapter))
        assert calls["n"] == 2
        assert result["answerable"] is True
        assert any("校验拒" in s for s in result["steps"])

    def testUnanswerableRefusesWithoutExecution(self, store, sideDb):
        adapter = _ingestSideDb(store, sideDb)
        service = Nl2SqlService(store)
        executed = {"n": 0}

        def executor(sql, limit):
            executed["n"] += 1
            return []

        def llm(_prompt):
            return json.dumps({"unanswerable": True,
                               "reason": "目录没有广告投放数据"})

        result = service.answerQuestion("default", "erp", "广告 ROI 是多少",
                                        llmCall=llm, executor=executor)
        assert executed["n"] == 0
        assert result["answerable"] is False
        assert result["status"] == "refused"
        assert "广告投放" in result["reason"]
        assert service.listHistory("default", "erp")[0]["status"] == "refused"

    def testExecutionErrorGoesHonestAfterRepairRounds(self, store, sideDb):
        adapter = _ingestSideDb(store, sideDb)
        service = Nl2SqlService(store)

        def llm(_prompt):
            return json.dumps({"sql": "SELECT nosuchcol FROM orders LIMIT 5",
                               "explanation": "坏列"})

        result = service.answerQuestion("default", "erp", "坏列查询",
                                        llmCall=llm, executor=_executorFor(adapter))
        assert result["answerable"] is False
        assert result["status"] == "refused"
        assert "nosuchcol" in result["reason"] or "坏列" in result["reason"] or \
            "no such column" in result["reason"].lower() or \
            result["reason"].startswith("连续")

    def testEmptyResultIsOkAndHonest(self, store, sideDb):
        adapter = _ingestSideDb(store, sideDb)
        service = Nl2SqlService(store)

        def llm(_prompt):
            return json.dumps({"sql": "SELECT id FROM orders WHERE id > 999 LIMIT 5",
                               "explanation": "无匹配"})

        result = service.answerQuestion("default", "erp", "不存在的订单",
                                        llmCall=llm, executor=_executorFor(adapter))
        assert result["status"] == "ok"
        assert result["row_count"] == 0
        assert result["answerable"] is True

    def testEmptyCatalogRefuses(self, store):
        service = Nl2SqlService(store)
        result = service.answerQuestion("default", "ghost", "任意",
                                        llmCall=lambda p: "{}", executor=None)
        assert result["answerable"] is False
        assert "目录" in result["reason"]

    def testPlanOnlyWhenNoExecutor(self, store, sideDb):
        _ingestSideDb(store, sideDb)
        service = Nl2SqlService(store)

        def llm(_prompt):
            return json.dumps({"sql": "SELECT id FROM orders LIMIT 5",
                               "explanation": "计划"})

        result = service.answerQuestion("default", "erp", "订单 id",
                                        llmCall=llm, executor=None)
        assert result["answerable"] is True
        assert result["rows"] == []
        assert any("仅返回计划" in s for s in result["steps"])

    def testApprovedPatternFeedsPrompt(self, store, sideDb):
        _ingestSideDb(store, sideDb)
        service = Nl2SqlService(store)
        service._recordHistory("default", "erp", "订单总额", 
                               "SELECT SUM(amount) FROM orders LIMIT 5", "ok", 1,
                               "", "admin")
        outcome = service.suggestPatternsFromHistory("default", "erp")
        assert outcome["patterns_suggested"] == 1
        from neurova.knowledge.ontology.schema_suggester import SchemaSuggester

        suggester = SchemaSuggester(store)
        pending = suggester.listSuggestions("default", kind="sql_pattern")
        assert len(pending) == 1
        suggester.decideSuggestion("default", pending[0]["suggestion_id"],
                                   "approved", reviewedBy="admin")
        captured = {}

        def llm(prompt):
            captured["prompt"] = prompt
            return json.dumps({"sql": "SELECT id FROM orders LIMIT 5",
                               "explanation": "x"})

        service.answerQuestion("default", "erp", "订单 id", llmCall=llm,
                               executor=None)
        assert "订单总额" in captured["prompt"]


# ── REST：env 门控 + 权限 ──────────────────────────────────────────

@pytest.fixture
def restClient(store, sideDb, monkeypatch):
    from neurova.api.endpoints import knowledge_nl2sql

    _ingestSideDb(store, sideDb)
    # ask 端点要经 loadConfig→buildAdapter 造执行器：源配置需在册且合法
    OntologyTermRegistry(store).register("Order", "concept", label="订单")
    from neurova.knowledge.enterprise.registry import EnterpriseIngestor

    ingestor = EnterpriseIngestor(store, registry=OntologyTermRegistry(store))
    ingestor.saveConfig("default", "erp", {
        "sourceType": "sql", "driver": "sqlite", "database": str(sideDb),
        "table": "orders", "cursorColumn": "id", "columns": ["id"],
        "subject": {"template": "order:{id}"},
        "predicate": {"termId": "Order"},
        "object": {"kind": "column", "column": "id"},
    }, enabled=True)
    app = FastAPI()
    app.include_router(knowledge_nl2sql.router, prefix=PREFIX)
    app.dependency_overrides[knowledge_auth.get_current_user_or_service] = \
        lambda: dict(ADMIN)
    yield TestClient(app)


class TestNl2SqlRest:
    def testDisabledByDefaultIsHonest403(self, restClient, monkeypatch):
        monkeypatch.delenv("NEUROVA_NL2SQL_ENABLED", raising=False)
        resp = restClient.post(PREFIX + "/enterprise/sources/erp/nl2sql",
                               json={"question": "订单总额"})
        assert resp.status_code == 403
        assert "NEUROVA_NL2SQL_ENABLED" in resp.json()["detail"]

    def testAskRequiresAdmin(self, restClient, monkeypatch):
        monkeypatch.setenv("NEUROVA_NL2SQL_ENABLED", "1")
        restClient.app.dependency_overrides[
            knowledge_auth.get_current_user_or_service] = lambda: dict(VIEWER)
        resp = restClient.post(PREFIX + "/enterprise/sources/erp/nl2sql",
                               json={"question": "订单总额"})
        assert resp.status_code == 403

    def testAskRoundtripWhenEnabled(self, restClient, store, monkeypatch):
        monkeypatch.setenv("NEUROVA_NL2SQL_ENABLED", "on")
        resp = restClient.post(PREFIX + "/enterprise/sources/erp/nl2sql",
                               json={"question": "订单 id", "use_llm": False})
        # use_llm=False 且无注入 LLM → 诚实拒答（未配置 LLM），门控与权限已过
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "refused"

    def testHistoryReadableByViewer(self, restClient, monkeypatch):
        monkeypatch.setenv("NEUROVA_NL2SQL_ENABLED", "1")
        restClient.app.dependency_overrides[
            knowledge_auth.get_current_user_or_service] = lambda: dict(VIEWER)
        resp = restClient.get(PREFIX + "/enterprise/sources/erp/nl2sql/history")
        assert resp.status_code == 200
        assert resp.json()["data"]["items"] == []
