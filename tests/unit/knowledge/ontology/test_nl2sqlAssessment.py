# -*- coding: utf-8 -*-
"""P1-3 本体贡献度评估（对照研究 reference_y 报告 §5，2026-11-19）红灯。

对方 Assess 的本仓批一等价物（确定性规则版，零额外模型成本）：nl2sql 每次
回答随结果返回 `assessment`——

- essential：grounding 的术语映射/join 路径实际进入了最终 SQL（首轮即成）；
- helpful：grounding 参与了修复（修复轮后成功，或拦下越界 SQL）；
- marginal：成功但 grounding 零命中（单表自明）；
- 拒答不硬评分：verdict="not_assessed"，gaps 按拒因归类
  （missing_catalog / missing_model / missing_term / invalid_sql）。

misleading 档留名常量（确定性 grounding 下不可判定，待模型评估批）。
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from neurova.knowledge.enterprise.nl2sql import Nl2SqlService
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    monkeypatch.setattr(
        "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: s)
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


def _ingestCatalog(store, sideDb, source="s1"):
    from neurova.knowledge.enterprise.schema_catalog import SchemaCatalogStore

    adapter_rows = sqlite3.connect(str(sideDb)).execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    tables = []
    conn = sqlite3.connect(str(sideDb))
    for (tableName,) in adapter_rows:
        columns = [{"name": r[1], "type": r[2]}
                   for r in conn.execute("PRAGMA table_info(%s)" % tableName)]
        tables.append({"name": tableName, "columns": columns})
    conn.close()
    relations = {"foreign_keys": [
        {"source_table": "orders", "source_column": "customer_id",
         "target_table": "customers", "target_column": "id"}],
        "primary_keys": {}}
    catalog = SchemaCatalogStore(store)
    catalog.ingestSchema("default", source, "sql",
                         type("S", (), {"tables": tables})(), relations=relations)
    return catalog


def _llmSql(sql):
    return lambda prompt: json.dumps({"sql": sql, "explanation": "ok",
                                      "unanswerable": False, "reason": ""})


def _executor(sideDb):
    def _run(sql, limit):
        conn = sqlite3.connect(str(sideDb))
        try:
            cur = conn.execute(sql)
            return [dict(zip([d[0] for d in cur.description], row))
                    for row in cur.fetchmany(limit)]
        finally:
            conn.close()
    return _run


class TestAssessment:

    def test_essentialWhenTermHintUsed(self, store, sideDb):
        catalog = _ingestCatalog(store, sideDb)
        tables = catalog.listTables("default")
        for table in tables:
            if table["table_name"] == "customers":
                catalog.linkTableTerm("default", table["catalog_table_id"], "Customer")
        registry = OntologyTermRegistry(store)
        registry.register("Customer", "concept", label="Customer")
        service = Nl2SqlService(store)
        out = service.answerQuestion(
            "default", "s1", "列出客户", _llmSql(
                "SELECT id, name FROM customers ORDER BY id LIMIT 10"),
            _executor(sideDb))
        assert out["answerable"] is True
        assert out["assessment"]["verdict"] == "essential"
        assert "customers" in out["assessment"]["grounds"]["tables"]

    def test_marginalWhenGroundingUnused(self, store, sideDb):
        _ingestCatalog(store, sideDb)
        service = Nl2SqlService(store)
        out = service.answerQuestion(
            "default", "s1", "orders", _llmSql(
                "SELECT id FROM orders WHERE amount > 1 ORDER BY id LIMIT 5"),
            _executor(sideDb))
        assert out["answerable"] is True
        assert out["assessment"]["verdict"] == "marginal"
        assert out["assessment"]["grounds"]["terms"] == []

    def test_refusedCarriesGaps(self, store, sideDb):
        service = Nl2SqlService(store)  # 目录为空
        out = service.answerQuestion(
            "default", "s1", "任意", _llmSql("SELECT 1"), _executor(sideDb))
        assert out["answerable"] is False
        assert out["assessment"]["verdict"] == "not_assessed"
        assert "missing_catalog" in out["assessment"]["gaps"]

    def test_refusedUnanswerableCarriesMissingTerm(self, store, sideDb):
        _ingestCatalog(store, sideDb)
        service = Nl2SqlService(store)

        def _llm(prompt):
            return json.dumps({"unanswerable": True, "reason": "无广告投放概念"})

        out = service.answerQuestion("default", "s1", "广告 ROI 是多少",
                                     _llm, _executor(sideDb))
        assert out["answerable"] is False
        assert "missing_term" in out["assessment"]["gaps"]

    def test_helpfulAfterRepair(self, store, sideDb):
        _ingestCatalog(store, sideDb)
        service = Nl2SqlService(store)
        calls = {"n": 0}

        def _llm(prompt):
            calls["n"] += 1
            if calls["n"] == 1:
                # 首轮越界（目录外表）——被只读/白名单闸拦下，grounding 参与修复
                return json.dumps({"sql": "SELECT secret FROM vault LIMIT 1",
                                   "explanation": "", "unanswerable": False,
                                   "reason": ""})
            return json.dumps({"sql": "SELECT id FROM customers LIMIT 1",
                               "explanation": "", "unanswerable": False,
                               "reason": ""})

        out = service.answerQuestion("default", "s1", "客户", _llm,
                                     _executor(sideDb))
        assert out["answerable"] is True
        assert out["assessment"]["verdict"] == "helpful"
        assert "out_of_catalog_attempt" in out["assessment"]["gaps"]


class TestCitations:
    """P3-1c 答案逐论断强制引用（血缘差距三）：可答结果必须带 citations
    （目录表/术语映射/join 路径/已批准模式四型），缺失即内部不一致；
    拒答结果 citations 恒空（没有产出就没有可引用的论断）。"""

    def test_answerCarriesTableCitation(self, store, sideDb):
        _ingestCatalog(store, sideDb)
        service = Nl2SqlService(store)
        out = service.answerQuestion(
            "default", "s1", "orders", _llmSql(
                "SELECT id FROM orders WHERE amount > 1 ORDER BY id LIMIT 5"),
            _executor(sideDb))
        assert out["answerable"] is True
        citations = out["citations"]
        assert {"kind": "catalog_table", "ref": "orders"} in citations

    def test_answerCarriesTermAndJoinCitations(self, store, sideDb):
        catalog = _ingestCatalog(store, sideDb)
        for table in catalog.listTables("default"):
            if table["table_name"] == "customers":
                catalog.linkTableTerm("default", table["catalog_table_id"],
                                      "Customer")
        registry = OntologyTermRegistry(store)
        registry.register("Customer", "concept", label="Customer")
        service = Nl2SqlService(store)
        out = service.answerQuestion(
            "default", "s1", "orders customers", _llmSql(
                "SELECT o.id FROM orders o JOIN customers c "
                "ON o.customer_id = c.id ORDER BY o.id LIMIT 5"),
            _executor(sideDb))
        assert out["answerable"] is True
        citations = out["citations"]
        assert {"kind": "term", "ref": "Customer"} in citations
        assert any(c["kind"] == "join_path" for c in citations)

    def test_refusalHasEmptyCitations(self, store, sideDb):
        service = Nl2SqlService(store)  # 目录为空
        out = service.answerQuestion("default", "s1", "任意",
                                     _llmSql("SELECT 1"), _executor(sideDb))
        assert out["answerable"] is False
        assert out["citations"] == []
