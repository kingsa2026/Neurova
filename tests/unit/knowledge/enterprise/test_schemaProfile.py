# -*- coding: utf-8 -*-
"""U10 连接器列画像（2026-11-23）判据：

- 画像 = distinct 数 / null 率 / min / max / 样例值（≤5），在源表**采样**上计算，
  采样上限 NEUROVA_SCHEMA_PROFILE_SAMPLE（默认 1000 行）；
- 画像落 `ontology_catalog_columns` 既有表（v59 只增列，不建第二套目录），
  既有读面 tableDetail 原样透出（只增不改）；
- suggester 关系候选评分纳入画像证据（高唯一性 +0.08、值域重叠 +0.07，只上调
  命名规约推断边）：命名规约 0.4 < 命名+画像 ≤0.55 < 声明外键 0.6 < 探针 0.75，
  既有三类证据相对权重不倒挂。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest

from neurova.knowledge.enterprise.connectors_sql import (
    DEFAULT_SCHEMA_PROFILE_SAMPLE,
    SqlDirectAdapter,
    computeColumnProfiles,
    schemaProfileSampleLimit,
)
from neurova.knowledge.enterprise.protocols import SourceSchema
from neurova.knowledge.enterprise.schema_catalog import SchemaCatalogStore
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.schema_suggester import SchemaSuggester


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


def _profile(distinct, nullRate, minValue, maxValue, samples, sampleRows):
    """构造与目录列同形的画像载荷（键 = ontology_catalog_columns 新列名）。"""
    return {
        "profile_distinct": distinct,
        "profile_null_rate": nullRate,
        "profile_min": minValue,
        "profile_max": maxValue,
        "profile_samples_json": json.dumps(samples, ensure_ascii=False),
        "profile_sample_rows": sampleRows,
    }


# ── 画像计算（纯函数）───────────────────────────────────────────────

class TestComputeColumnProfiles:
    def testDistinctNullRateMinMaxSamples(self):
        rows = [
            {"id": 1, "name": "a", "score": 3.5},
            {"id": 2, "name": "b", "score": None},
            {"id": 1, "name": "a", "score": 1.0},
            {"id": None, "name": "c", "score": 2.0},
        ]
        profiles = computeColumnProfiles(rows)
        pid = profiles["id"]
        assert pid["profile_distinct"] == 2
        assert pid["profile_null_rate"] == pytest.approx(0.25)
        assert pid["profile_min"] == "1"
        assert pid["profile_max"] == "2"
        assert pid["profile_sample_rows"] == 4
        pname = profiles["name"]
        assert pname["profile_distinct"] == 3
        assert pname["profile_null_rate"] == 0.0
        assert json.loads(pname["profile_samples_json"]) == ["a", "b", "c"]
        pscore = profiles["score"]
        assert pscore["profile_min"] == "1.0"
        assert pscore["profile_max"] == "3.5"
        assert pscore["profile_null_rate"] == pytest.approx(0.25)
        assert pscore["profile_distinct"] == 3

    def testSamplesCapAtFiveKeepFirstSeenOrder(self):
        rows = [{"v": i} for i in range(10)]
        profiles = computeColumnProfiles(rows)
        samples = json.loads(profiles["v"]["profile_samples_json"])
        assert samples == ["0", "1", "2", "3", "4"]

    def testEmptyTableIsHonestZeroNotFabricated(self):
        profiles = computeColumnProfiles([])
        assert profiles == {}

    def testEmptyRowsAllNull(self):
        profiles = computeColumnProfiles([{"v": None}, {"v": None}])
        pv = profiles["v"]
        assert pv["profile_distinct"] == 0
        assert pv["profile_null_rate"] == pytest.approx(1.0)
        assert pv["profile_min"] is None
        assert pv["profile_max"] is None
        assert json.loads(pv["profile_samples_json"]) == []

    def testMixedTypeColumnDoesNotCrash(self):
        rows = [{"v": 1}, {"v": "a"}, {"v": 2}]
        profiles = computeColumnProfiles(rows)
        assert profiles["v"]["profile_distinct"] == 3
        assert profiles["v"]["profile_min"] is not None
        assert profiles["v"]["profile_max"] is not None


# ── 采样上限 ────────────────────────────────────────────────────────

class TestSampleLimit:
    def testDefaultIs1000(self):
        assert DEFAULT_SCHEMA_PROFILE_SAMPLE == 1000
        assert schemaProfileSampleLimit() == 1000

    def testEnvOverrideAndClamp(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_SCHEMA_PROFILE_SAMPLE", "50")
        assert schemaProfileSampleLimit() == 50
        monkeypatch.setenv("NEUROVA_SCHEMA_PROFILE_SAMPLE", "0")
        assert schemaProfileSampleLimit() == 1
        monkeypatch.setenv("NEUROVA_SCHEMA_PROFILE_SAMPLE", "-5")
        assert schemaProfileSampleLimit() == 1
        monkeypatch.setenv("NEUROVA_SCHEMA_PROFILE_SAMPLE", "not-a-number")
        assert schemaProfileSampleLimit() == 1000

    def testAdapterProfileColumnsRespectSampleSize(self, tmp_path):
        sidePath = tmp_path / "side.db"
        conn = sqlite3.connect(str(sidePath))
        conn.executescript(
            "CREATE TABLE t (id INTEGER PRIMARY KEY, grp INTEGER);"
            + "".join("INSERT INTO t VALUES (%d, %d);" % (i, i % 7)
                      for i in range(2500)))
        conn.commit()
        conn.close()
        adapter = SqlDirectAdapter({
            "driver": "sqlite", "database": str(sidePath),
            "table": "t", "cursorColumn": "id",
        }, "erp")
        profiles = _run(adapter.profileColumns(["t"], sampleSize=100))
        pt = profiles["t"]
        assert pt["id"]["profile_sample_rows"] == 100
        assert pt["id"]["profile_distinct"] == 100  # 样本内高唯一
        assert pt["grp"]["profile_sample_rows"] == 100
        assert pt["grp"]["profile_distinct"] == 7  # 前 100 行 grp=0..6 循环
        assert pt["grp"]["profile_min"] == "0"
        assert pt["grp"]["profile_max"] == "6"

    def testAdapterSkipsNonIdentifierTableNames(self, tmp_path):
        adapter = SqlDirectAdapter({
            "driver": "sqlite", "database": str(tmp_path / "x.db"),
            "table": "t", "cursorColumn": "id",
        }, "erp")
        profiles = _run(adapter.profileColumns(["ok_table", "bad; drop"]))
        assert "ok_table" not in profiles  # 库不存在也如实缺席（不冒充空画像）
        assert "bad; drop" not in profiles  # 非法标识符不进 SQL，宁可漏不注入


# ── 目录落账与读面（v59 只增列）─────────────────────────────────────

class TestCatalogProfilePersistence:
    def testMigrationAddsProfileColumnsToExistingTable(self, store):
        SchemaCatalogStore(store)  # 构造即应用迁移链
        cols = {r["name"] for r in store._conn.execute(
            "PRAGMA table_info(ontology_catalog_columns)").fetchall()}
        assert {"profile_distinct", "profile_null_rate", "profile_min",
                "profile_max", "profile_samples_json",
                "profile_sample_rows"} <= cols

    def testIngestWithProfilesRoundtripThroughReadFace(self, store):
        cat = SchemaCatalogStore(store)
        schema = SourceSchema(sourceId="erp", sourceType="sql", tables=[
            {"name": "orders", "columns": [
                {"name": "id", "type": "INTEGER"},
                {"name": "customer_id", "type": "INTEGER"}]}])
        profiles = {"orders": {"customer_id": _profile(
            42, 0.1, "1", "99", ["1", "2", "3"], 500)}}
        cat.ingestSchema("default", "erp", "sql", schema, profiles=profiles)
        detail = cat.tableDetail("default", cat.listTables("default")[0]["catalog_table_id"])
        columns = {c["column_name"]: c for c in detail["columns"]}
        pc = columns["customer_id"]
        assert pc["profile_distinct"] == 42
        assert pc["profile_null_rate"] == pytest.approx(0.1)
        assert pc["profile_min"] == "1"
        assert pc["profile_max"] == "99"
        assert json.loads(pc["profile_samples_json"]) == ["1", "2", "3"]
        assert pc["profile_sample_rows"] == 500
        # 未采样列：诚实缺省（distinct 为 NULL、行数 0、样例空表）
        pid = columns["id"]
        assert pid["profile_distinct"] is None
        assert pid["profile_sample_rows"] == 0
        assert json.loads(pid["profile_samples_json"]) == []

    def testIngestWithoutProfilesKeepsLegacyShape(self, store):
        cat = SchemaCatalogStore(store)
        schema = SourceSchema(sourceId="erp", sourceType="sql", tables=[
            {"name": "t", "columns": [{"name": "v", "type": "TEXT"}]}])
        cat.ingestSchema("default", "erp", "sql", schema)
        detail = cat.tableDetail("default", cat.listTables("default")[0]["catalog_table_id"])
        col = detail["columns"][0]
        assert col["profile_distinct"] is None
        assert col["profile_sample_rows"] == 0


# ── 刷新链路端到端（真 sqlite 旁库）────────────────────────────────

class TestRefreshProfilesEndToEnd:
    def _makeSideDb(self, sidePath):
        conn = sqlite3.connect(str(sidePath))
        conn.executescript(
            "CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT);"
            "CREATE TABLE orders (id INTEGER PRIMARY KEY,"
            " customer_id INTEGER REFERENCES customers(id), note TEXT);")
        for i in range(1, 601):
            conn.execute("INSERT INTO customers VALUES (?, ?)", (i, "n%d" % i))
            conn.execute("INSERT INTO orders VALUES (?, ?, ?)",
                         (i, (i % 50) + 1, "note%02d" % (i % 10)))
        conn.commit()
        conn.close()

    def testRefreshProfilesSqliteSourceAndReadFace(self, store, tmp_path):
        from neurova.api.endpoints.knowledge_enterprise import refreshSchemaCatalog
        from neurova.knowledge.enterprise.registry import EnterpriseIngestor
        from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

        OntologyTermRegistry(store).register("has_value", "relation", label="有值")
        sidePath = tmp_path / "side.db"
        self._makeSideDb(sidePath)
        EnterpriseIngestor(store).saveConfig("default", "erp", {
            "sourceType": "sql", "driver": "sqlite", "database": str(sidePath),
            "table": "orders", "cursorColumn": "id",
            "columns": ["id", "customer_id", "note"],
            "subject": {"template": "order:{id}"},
            "predicate": {"termId": "has_value"},
            "object": {"kind": "column", "column": "note"},
        }, enabled=False)
        result = refreshSchemaCatalog("default", "erp")
        assert result["tables"] == 2
        cat = SchemaCatalogStore(store)
        orders = [t for t in cat.listTables("default", sourceId="erp")
                  if t["table_name"] == "orders"][0]
        detail = cat.tableDetail("default", orders["catalog_table_id"])
        columns = {c["column_name"]: c for c in detail["columns"]}
        # 主键 id：采样内高唯一；外键 customer_id：distinct 远小于行数
        assert columns["id"]["profile_sample_rows"] == 600
        assert columns["id"]["profile_distinct"] == 600
        assert columns["customer_id"]["profile_distinct"] == 50
        assert columns["customer_id"]["profile_min"] == "1"
        assert columns["customer_id"]["profile_max"] == "50"
        # 样例值 ≤5
        assert len(json.loads(columns["note"]["profile_samples_json"])) == 5
        # 同一读面经 REST 端点透出（只增不改）
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from neurova.api import auth as knowledge_auth
        from neurova.api.endpoints import knowledge_enterprise

        app = FastAPI()
        app.include_router(knowledge_enterprise.router, prefix="/v1/knowledge")
        app.dependency_overrides[knowledge_auth.get_current_user_or_service] = \
            lambda: {"user_id": "9", "username": "admin", "role": "admin",
                     "tenant_id": "default"}
        resp = TestClient(app).get(
            "/v1/knowledge/enterprise/catalog/tables/%s" % orders["catalog_table_id"])
        assert resp.status_code == 200, resp.text
        restColumns = {c["column_name"]: c
                       for c in resp.json()["data"]["columns"]}
        assert restColumns["customer_id"]["profile_distinct"] == 50
        assert restColumns["id"]["profile_sample_rows"] == 600

    def testRefreshRespectsEnvSampleLimit(self, store, tmp_path, monkeypatch):
        from neurova.api.endpoints.knowledge_enterprise import refreshSchemaCatalog
        from neurova.knowledge.enterprise.registry import EnterpriseIngestor
        from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

        OntologyTermRegistry(store).register("has_value", "relation", label="有值")
        sidePath = tmp_path / "side.db"
        self._makeSideDb(sidePath)
        EnterpriseIngestor(store).saveConfig("default", "erp", {
            "sourceType": "sql", "driver": "sqlite", "database": str(sidePath),
            "table": "orders", "cursorColumn": "id",
            "columns": ["id", "customer_id", "note"],
            "subject": {"template": "order:{id}"},
            "predicate": {"termId": "has_value"},
            "object": {"kind": "column", "column": "note"},
        }, enabled=False)
        monkeypatch.setenv("NEUROVA_SCHEMA_PROFILE_SAMPLE", "100")
        refreshSchemaCatalog("default", "erp")
        cat = SchemaCatalogStore(store)
        orders = [t for t in cat.listTables("default", sourceId="erp")
                  if t["table_name"] == "orders"][0]
        columns = {c["column_name"]: c
                   for c in cat.tableDetail("default", orders["catalog_table_id"])["columns"]}
        assert columns["id"]["profile_sample_rows"] == 100
        assert columns["id"]["profile_distinct"] == 100

    def testFileSourceRefreshSkipsProfilesHonestly(self, store, tmp_path):
        """无 profileColumns 能力的源型（file）：目录照常落账，画像列诚实缺省。"""
        from neurova.api.endpoints.knowledge_enterprise import refreshSchemaCatalog
        from neurova.knowledge.enterprise.registry import EnterpriseIngestor
        from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

        OntologyTermRegistry(store).register("has_value", "relation", label="有值")
        csvPath = tmp_path / "x.csv"
        csvPath.write_text("a,b\n1,2\n", encoding="utf-8")
        EnterpriseIngestor(store).saveConfig("default", "filesrc", {
            "sourceType": "file", "format": "csv", "path": str(csvPath),
            "columns": ["a", "b"],
            "subject": {"template": "row:{a}"},
            "predicate": {"termId": "has_value"},
            "object": {"kind": "column", "column": "b"},
        }, enabled=False)
        result = refreshSchemaCatalog("default", "filesrc")
        assert result["tables"] == 1
        cat = SchemaCatalogStore(store)
        detail = cat.tableDetail("default", cat.listTables("default")[0]["catalog_table_id"])
        for col in detail["columns"]:
            assert col["profile_distinct"] is None
            assert col["profile_sample_rows"] == 0


# ── suggester 消费：画像证据上调命名推断边，权重不倒挂 ──────────────

class TestSuggesterProfileEvidence:
    def _ingestProfiled(self, store, sourceId="erp", aIdProfile=None,
                        aIdRange=("1", "500"), extraRelations=None):
        cat = SchemaCatalogStore(store)
        schema = SourceSchema(sourceId=sourceId, sourceType="sql", tables=[
            {"name": "a", "columns": [{"name": "id", "type": "INTEGER"}]},
            {"name": "a2", "columns": [{"name": "id", "type": "INTEGER"}]},
            {"name": "b", "columns": [{"name": "id", "type": "INTEGER"},
                                      {"name": "a_id", "type": "INTEGER"},
                                      {"name": "a2_id", "type": "INTEGER"}]},
        ])
        relations = {"foreign_keys": list(extraRelations or []),
                     "primary_keys": {"a": ["id"], "a2": ["id"], "b": ["id"]}}
        highUnique = _profile(500, 0.0, aIdRange[0], aIdRange[1],
                              ["1", "2", "3", "4", "5"], 500)
        lowUnique = _profile(1, 0.0, "7", "7", ["7"], 500)
        profiles = {
            "a": {"id": _profile(500, 0.0, "1", "500",
                                 ["1", "2", "3", "4", "5"], 500)},
            "a2": {"id": _profile(500, 0.0, "1", "500",
                                  ["1", "2", "3", "4", "5"], 500)},
            "b": {"id": _profile(500, 0.0, "1", "500",
                                 ["1", "2", "3", "4", "5"], 500),
                  "a_id": aIdProfile or highUnique,
                  "a2_id": lowUnique},
        }
        cat.ingestSchema("default", sourceId, "sql", schema,
                         relations=relations, profiles=profiles)
        return cat

    def testHighUniquenessPlusRangeOverlapBoostsInferredEdge(self, store):
        cat = self._ingestProfiled(store)
        suggester = SchemaSuggester(store, catalog=cat)
        suggester.runForSource("default", "erp")
        byEntry = {c["source_entry_id"]: c
                   for c in suggester._relations.list("default", status="pending")}
        # a_id：高唯一性（500/500）＋值域重叠（[1,500]∩[1,500]）→ 0.4+0.08+0.07=0.55
        aid = byEntry["catalog:erp:b:a_id"]
        assert aid["confidence"] == pytest.approx(0.55)
        assert "高唯一性" in aid["source_text"]
        assert "值域重叠" in aid["source_text"]
        # a2_id：低唯一（1/500）仅值域重叠 → 0.4+0.07=0.47
        a2id = byEntry["catalog:erp:b:a2_id"]
        assert a2id["confidence"] == pytest.approx(0.47)
        assert "高唯一性" not in a2id["source_text"]
        assert "值域重叠" in a2id["source_text"]

    def testRangeNonOverlapGetsUniquenessBoostOnly(self, store):
        disjoint = _profile(500, 0.0, "900", "999", ["900", "999"], 500)
        cat = self._ingestProfiled(store, sourceId="erp3", aIdProfile=disjoint)
        suggester = SchemaSuggester(store, catalog=cat)
        suggester.runForSource("default", "erp3")
        byEntry = {c["source_entry_id"]: c
                   for c in suggester._relations.list("default", status="pending")}
        aid = byEntry["catalog:erp3:b:a_id"]
        assert aid["confidence"] == pytest.approx(0.48)  # 0.4+0.08
        assert "高唯一性" in aid["source_text"]
        assert "值域重叠" not in aid["source_text"]

    def testDeclaredForeignKeyStillOutranksProfileBoostedHeuristic(self, store):
        """声明外键 0.6 > 命名+画像上限 0.55：画像不倒挂既有证据序。"""
        cat = SchemaCatalogStore(store)
        schema = SourceSchema(sourceId="erp2", sourceType="sql", tables=[
            {"name": "customers", "columns": [{"name": "id", "type": "INTEGER"}]},
            {"name": "orders", "columns": [{"name": "id", "type": "INTEGER"},
                                           {"name": "customer_id",
                                            "type": "INTEGER"}]},
        ])
        relations = {"foreign_keys": [{"source_table": "orders",
                                       "source_column": "customer_id",
                                       "target_table": "customers",
                                       "target_column": "id"}],
                     "primary_keys": {"customers": ["id"], "orders": ["id"]}}
        profiles = {
            "customers": {"id": _profile(500, 0.0, "1", "500",
                                         ["1", "2", "3", "4", "5"], 500)},
            "orders": {"id": _profile(500, 0.0, "1", "500",
                                      ["1", "2", "3", "4", "5"], 500),
                       "customer_id": _profile(500, 0.0, "1", "500",
                                               ["1", "2", "3", "4", "5"], 500)},
        }
        cat.ingestSchema("default", "erp2", "sql", schema,
                         relations=relations, profiles=profiles)
        suggester = SchemaSuggester(store, catalog=cat)
        suggester.runForSource("default", "erp2")
        pending = suggester._relations.list("default", status="pending")
        assert len(pending) == 1
        assert pending[0]["confidence"] == pytest.approx(0.6)  # 声明边不吃画像加成
        assert "画像证据" not in pending[0]["source_text"]

    def testMissingProfileLeavesNamingHeuristicUntouched(self, store):
        cat = SchemaCatalogStore(store)
        schema = SourceSchema(sourceId="erp4", sourceType="sql", tables=[
            {"name": "a", "columns": [{"name": "id", "type": "INTEGER"}]},
            {"name": "b", "columns": [{"name": "id", "type": "INTEGER"},
                                      {"name": "a_id", "type": "INTEGER"}]},
        ])
        cat.ingestSchema("default", "erp4", "sql", schema, relations={
            "foreign_keys": [], "primary_keys": {"a": ["id"], "b": ["id"]}})
        suggester = SchemaSuggester(store, catalog=cat)
        suggester.runForSource("default", "erp4")
        pending = suggester._relations.list("default", status="pending")
        assert len(pending) == 1
        assert pending[0]["confidence"] == pytest.approx(0.4)  # 无画像不冒充加成
        assert "画像证据" not in pending[0]["source_text"]

    def testProbeConfirmedStaysTopAndDoesNotStack(self, store, tmp_path):
        """探针证实 0.75 仍居首；画像不叠加（探针已是数据级证实）。"""
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
        adapter = SqlDirectAdapter({"driver": "sqlite", "database": str(sidePath),
                                    "table": "b", "cursorColumn": "id"}, "erp")
        cat = SchemaCatalogStore(store)
        cat.ingestSchema("default", "erp5", "sql", SourceSchema(
            sourceId="erp5", sourceType="sql",
            tables=[{"name": "a", "columns": [{"name": "id", "type": "INTEGER"}]},
                    {"name": "b", "columns": [{"name": "id", "type": "INTEGER"},
                                              {"name": "a_id", "type": "INTEGER"}]}]),
            relations={"foreign_keys": [],
                       "primary_keys": {"a": ["id"], "b": ["id"]}},
            profiles={
                "a": {"id": _profile(2, 0.0, "1", "2", ["1", "2"], 2)},
                "b": {"id": _profile(2, 0.0, "1", "2", ["1", "2"], 2),
                      "a_id": _profile(2, 0.0, "1", "2", ["1", "2"], 2)},
            })
        suggester = SchemaSuggester(store, catalog=cat)
        summary = suggester.runForSource("default", "erp5", probeRunner=(
            lambda sql: _run(adapter.executeReadonly(sql))))
        assert summary["probes_confirmed"] == 1
        pending = suggester._relations.list("default", status="pending")
        assert len(pending) == 1
        assert pending[0]["confidence"] == pytest.approx(0.75)

    def testWeightLadderNeverInverted(self, store):
        """权重全序：命名 0.4 < 命名+单证据 0.47/0.48 < 命名+双证据 0.55
        < 声明外键 0.6 < 探针证实 0.75。"""
        cat = self._ingestProfiled(store)
        suggester = SchemaSuggester(store, catalog=cat)
        suggester.runForSource("default", "erp")
        confidences = sorted(c["confidence"] for c in
                             suggester._relations.list("default", status="pending"))
        assert confidences == pytest.approx([0.47, 0.55])
        # 声明与探针档位由上方两个用例钉住（0.6 / 0.75），此处汇总口径：
        assert 0.4 < 0.47 < 0.48 < 0.55 < 0.6 < 0.75
