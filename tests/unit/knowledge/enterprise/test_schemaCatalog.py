# -*- coding: utf-8 -*-
"""schema 目录自动摄取（对照研究 P1-1，2026-11-15）。

判据（报告 §6 P1-1）：
- describeSchema() 的结果落 ontology_catalog_tables / ontology_catalog_columns，
  外键/主键来自 describeRelations()（SQL 适配器可选能力）；
- 同源重复摄取是整体替换（陈旧列不残留），租户之间互不可见；
- 只读 SELECT 执行面：写意图/多语句显式拒绝，LIMIT 强制收敛；
- sqlite 真实旁库端到端（stdlib，零网络）：真 FK 进目录边表；
- REST：目录读面登录可读，刷新是治理动作（仅管理员）。
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.knowledge.enterprise.connectors_sql import (
    SqlDirectAdapter,
    assertReadonlySelect,
)
from neurova.knowledge.enterprise.protocols import (
    ChangeBatch,
    SourceHealth,
    SourceSchema,
)
from neurova.knowledge.enterprise.schema_catalog import SchemaCatalogStore
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

ADMIN = {"user_id": "9", "username": "admin", "role": "admin", "tenant_id": "default"}
VIEWER = {"user_id": "5", "username": "viewer", "role": "viewer", "tenant_id": "default"}
PREFIX = "/v1/knowledge"


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class FakeSchemaAdapter:
    """只实现 schema 面的假适配器（零网络、零驱动）。"""

    def __init__(self, schema: SourceSchema, relations=None, health="ok"):
        self._schema = schema
        self._relations = relations or {"foreign_keys": [], "primary_keys": {}}
        self._health = health

    async def describeSchema(self) -> SourceSchema:
        return self._schema

    async def describeRelations(self):
        return self._relations

    async def fetchBatch(self, cursor, limit) -> ChangeBatch:
        return ChangeBatch()

    async def health(self) -> SourceHealth:
        return SourceHealth(status=self._health)

    async def close(self):
        return None


def _sampleSchema() -> SourceSchema:
    return SourceSchema(sourceId="erp", sourceType="sql", tables=[
        {"name": "customers", "columns": [
            {"name": "id", "type": "INTEGER"},
            {"name": "name", "type": "TEXT"},
        ]},
        {"name": "orders", "columns": [
            {"name": "id", "type": "INTEGER"},
            {"name": "customer_id", "type": "INTEGER"},
            {"name": "amount", "type": "NUMERIC"},
        ]},
    ])


def _sampleRelations() -> dict:
    return {
        "foreign_keys": [{"source_table": "orders", "source_column": "customer_id",
                          "target_table": "customers", "target_column": "id"}],
        "primary_keys": {"customers": ["id"], "orders": ["id"]},
    }


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    monkeypatch.setattr(
        "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: s
    )
    yield s
    s.close()


# ── 存储层 ──────────────────────────────────────────────────────────

class TestSchemaCatalogStore:
    def testIngestAndReadRoundtrip(self, store):
        cat = SchemaCatalogStore(store)
        result = cat.ingestSchema("default", "erp", "sql", _sampleSchema(),
                                   relations=_sampleRelations())
        assert result["tables"] == 2
        tables = cat.listTables("default", sourceId="erp")
        assert [t["table_name"] for t in tables] == ["customers", "orders"]
        assert tables[1]["column_count"] == 3
        detail = cat.tableDetail("default", tables[1]["catalog_table_id"])
        assert detail is not None
        columns = {c["column_name"]: c for c in detail["columns"]}
        assert columns["customer_id"]["is_foreign_key"] == 1
        assert columns["customer_id"]["foreign_key_target"] == "customers.id"
        assert columns["id"]["is_primary_key"] == 1
        assert columns["amount"]["is_foreign_key"] == 0
        edges = cat.foreignKeyEdges("default", sourceId="erp")
        assert edges == [{"source_id": "erp",
                          "source_table": "orders", "source_column": "customer_id",
                          "target_table": "customers", "target_column": "id"}]

    def testReingestReplacesStaleColumns(self, store):
        cat = SchemaCatalogStore(store)
        v1 = SourceSchema(sourceId="erp", sourceType="sql", tables=[
            {"name": "orders", "columns": [{"name": "old_col", "type": "TEXT"}]}])
        v2 = SourceSchema(sourceId="erp", sourceType="sql", tables=[
            {"name": "orders", "columns": [{"name": "new_col", "type": "TEXT"}]}])
        cat.ingestSchema("default", "erp", "sql", v1)
        cat.ingestSchema("default", "erp", "sql", v2)
        detail = cat.tableDetail("default", cat.listTables("default")[0]["catalog_table_id"])
        names = [c["column_name"] for c in detail["columns"]]
        assert names == ["new_col"]
        assert cat.counts("default")["tables"] == 1

    def testReingestPreservesApprovedTermsAndDropsStaleObjects(self, store):
        cat = SchemaCatalogStore(store)
        cat.ingestSchema("default", "erp", "sql", _sampleSchema())
        before = cat.listTables("default", sourceId="erp")
        customers = next(t for t in before if t["table_name"] == "customers")
        customerDetail = cat.tableDetail("default", customers["catalog_table_id"])
        customerId = next(c for c in customerDetail["columns"]
                          if c["column_name"] == "id")
        cat.linkTableTerm("default", customers["catalog_table_id"], "customer_term")
        cat.linkColumnTerm("default", customers["catalog_table_id"], "id",
                           "customer_identifier")

        refreshed = SourceSchema(sourceId="erp", sourceType="sql", tables=[
            {"name": "customers", "description": "客户主数据", "columns": [
                {"name": "id", "type": "BIGINT", "description": "客户标识"}]},
        ])
        cat.ingestSchema("default", "erp", "sql", refreshed)

        after = cat.listTables("default", sourceId="erp")
        assert [t["table_name"] for t in after] == ["customers"]
        assert after[0]["catalog_table_id"] == customers["catalog_table_id"]
        assert after[0]["term_id"] == "customer_term"
        assert after[0]["description"] == "客户主数据"
        detail = cat.tableDetail("default", after[0]["catalog_table_id"])
        assert len(detail["columns"]) == 1
        assert detail["columns"][0]["catalog_column_id"] == customerId["catalog_column_id"]
        assert detail["columns"][0]["term_id"] == "customer_identifier"
        assert detail["columns"][0]["data_type"] == "BIGINT"
        assert detail["columns"][0]["description"] == "客户标识"

    def testTenantIsolation(self, store):
        cat = SchemaCatalogStore(store)
        cat.ingestSchema("default", "erp", "sql", _sampleSchema())
        cat.ingestSchema("tenant-b", "erp", "sql", _sampleSchema())
        assert cat.counts("default")["tables"] == 2
        assert cat.counts("tenant-b")["tables"] == 2
        for row in cat.listTables("tenant-b"):
            assert row["tenant_id"] == "tenant-b"
        # 改 A 租户目录不波及 B 租户
        cat.ingestSchema("default", "erp", "sql", SourceSchema(
            sourceId="erp", sourceType="sql",
            tables=[{"name": "only_default", "columns": []}]))
        assert "only_default" not in [t["table_name"] for t in cat.listTables("tenant-b")]

    def testSearchMatchesTableAndColumn(self, store):
        cat = SchemaCatalogStore(store)
        cat.ingestSchema("default", "erp", "sql", _sampleSchema())
        hits = cat.search("default", "customer")
        tables = {h["kind"]: h["name"] for h in hits if h["kind"] == "table"}
        assert tables.get("table") == "customers"
        assert any(h["kind"] == "column" and h["name"] == "customer_id" for h in hits)

    def testEmptySchemaIsHonestNoOp(self, store):
        cat = SchemaCatalogStore(store)
        result = cat.ingestSchema("default", "erp", "sql",
                                  SourceSchema(sourceId="erp", sourceType="sql", tables=[]))
        assert result == {"tables": 0, "columns": 0, "foreign_keys": 0}
        assert cat.listTables("default") == []


# ── SQL 适配器：关系自省与只读执行 ────────────────────────────────

class TestSqlAdapterRelationsAndReadonly:
    def testSqliteRealFileEndToEnd(self, tmp_path):
        sidePath = tmp_path / "side.db"
        conn = sqlite3.connect(str(sidePath))
        conn.executescript("""
            CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER
                REFERENCES customers(id), amount NUMERIC);
        """)
        conn.commit()
        conn.close()
        adapter = SqlDirectAdapter({
            "driver": "sqlite", "database": str(sidePath),
            "table": "orders", "cursorColumn": "id",
        }, "erp")
        schema = _run(adapter.describeSchema())
        relations = _run(adapter.describeRelations())
        assert {t["name"] for t in schema.tables} == {"customers", "orders"}
        fk = {(r["source_table"], r["source_column"], r["target_table"], r["target_column"])
              for r in relations["foreign_keys"]}
        assert ("orders", "customer_id", "customers", "id") in fk
        assert relations["primary_keys"]["orders"] == ["id"]

    def testAssertReadonlySelectRejectsWriteShapes(self):
        assert assertReadonlySelect("SELECT 1").lower().startswith("select")
        assert assertReadonlySelect("WITH x AS (SELECT 1) SELECT * FROM x")
        for bad in ("INSERT INTO t VALUES (1)", "UPDATE t SET a=1", "DELETE FROM t",
                    "DROP TABLE t", "PRAGMA foreign_keys=on", "SELECT 1; DROP TABLE t",
                    "SELECT * FROM t -- comment", "SELECT * INTO x FROM t", ""):
            with pytest.raises(ValueError):
                assertReadonlySelect(bad)

    def testExecuteReadonlyEnforcesLimitAndShape(self, tmp_path):
        sidePath = tmp_path / "side.db"
        conn = sqlite3.connect(str(sidePath))
        conn.executescript("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT);"
                           + "".join("INSERT INTO t VALUES (%d, 'x');" % i
                                     for i in range(10)))
        conn.commit()
        conn.close()
        adapter = SqlDirectAdapter({
            "driver": "sqlite", "database": str(sidePath),
            "table": "t", "cursorColumn": "id",
        }, "erp")
        rows = _run(adapter.executeReadonly("SELECT id, v FROM t ORDER BY id", limit=3))
        assert [r["id"] for r in rows] == [0, 1, 2]
        with pytest.raises(ValueError):
            _run(adapter.executeReadonly("DELETE FROM t"))
        with pytest.raises(ValueError):
            _run(adapter.executeReadonly("SELECT 1; SELECT 2"))


# ── REST 面 ────────────────────────────────────────────────────────

@pytest.fixture
def client(store, monkeypatch):
    from neurova.api.endpoints import knowledge_enterprise

    app = FastAPI()
    app.include_router(knowledge_enterprise.router, prefix=PREFIX)
    app.dependency_overrides[knowledge_auth.get_current_user_or_service] = \
        lambda: dict(ADMIN)
    yield TestClient(app)


class TestCatalogRest:
    def testCatalogReadRequiresLogin(self, client):
        client.app.dependency_overrides[knowledge_auth.get_current_user_or_service] = \
            lambda: dict(VIEWER)
        resp = client.get(PREFIX + "/enterprise/catalog/tables")
        assert resp.status_code == 200
        assert resp.json()["data"]["items"] == []

    def testRefreshAndListRoundtrip(self, client, store, monkeypatch, tmp_path):
        from neurova.api.endpoints import knowledge_enterprise as ke
        from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

        # 映射描述符合法（编译期校验：谓词先登记），文件放 tmp_path 不污染仓库根
        OntologyTermRegistry(store).register("has_value", "relation", label="有值")
        csvPath = tmp_path / "x.csv"
        csvPath.write_text("a,b\n1,2\n", encoding="utf-8")
        ingestor, _adapters, _s = ke._parts()
        ingestor.saveConfig("default", "erp", {
            "sourceType": "file", "format": "csv", "path": str(csvPath),
            "columns": ["a", "b"],
            "subject": {"template": "row:{a}"},
            "predicate": {"termId": "has_value"},
            "object": {"kind": "column", "column": "b"},
        }, enabled=False)
        resp = client.post(PREFIX + "/enterprise/sources/erp/catalog/refresh")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["ingested"]["tables"] == 1

        listing = client.get(PREFIX + "/enterprise/catalog/tables").json()["data"]
        assert listing["total"] == 1
        assert listing["items"][0]["source_id"] == "erp"
        detail = client.get(PREFIX + "/enterprise/catalog/tables/"
                            + listing["items"][0]["catalog_table_id"]).json()["data"]
        assert [c["column_name"] for c in detail["columns"]] == ["a", "b"]

    def testRefreshUnknownSourceIs404(self, client):
        resp = client.post(PREFIX + "/enterprise/sources/nope/catalog/refresh")
        assert resp.status_code == 404

    def testViewerCannotRefresh(self, client):
        client.app.dependency_overrides[knowledge_auth.get_current_user_or_service] = \
            lambda: dict(VIEWER)
        resp = client.post(PREFIX + "/enterprise/sources/erp/catalog/refresh")
        assert resp.status_code == 403
