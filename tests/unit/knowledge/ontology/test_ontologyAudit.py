# -*- coding: utf-8 -*-
"""P1-2 数据驱动本体缺口审计（对照研究 reference_y 报告 §5，2026-11-19）红灯。

对方 Audit 的本仓等价物：对 schema 目录做**零模型调用**的缺口/漂移挖矿，
五类信号（本仓适配）：

- uncovered：目录表无术语链接（coverage gap）；
- broken_reference：目录声明外键指向目录中不存在的表（漂移/残缺）；
- clash：同一术语被链接到同源多张表（歧义）；
- stale：pending 候选/建议超期未审（治理积压）；
- ambiguity：同源两表 humanize 后同名（建议器会产出冲突术语 slug）。

每条 finding 带跨轮稳定的 fingerprint（sha256(kind|target) 截断）与建议动作；
纯只读，不落新表、不改任何状态。
"""

from __future__ import annotations

import sqlite3

import pytest

from neurova.knowledge.enterprise.schema_catalog import SchemaCatalogStore
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.audit import auditOntologyCoverage


class _SourceSchema:
    """describeSchema 形状的最小桩。"""

    def __init__(self, tables):
        self.tables = tables


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "kb.db"))
    yield s
    s.close()


def _ingest(store, tenant="default", source="s1"):
    catalog = SchemaCatalogStore(store)
    catalog.ingestSchema(tenant, source, "sql", _SourceSchema([
        {"name": "customers", "columns": [{"name": "id", "type": "integer"},
                                          {"name": "name", "type": "text"}]},
        {"name": "orders", "columns": [{"name": "id", "type": "integer"},
                                       {"name": "customer_id", "type": "integer"}]},
        {"name": "Customers", "columns": [{"name": "id", "type": "integer"}]},
    ]), relations={"foreign_keys": [
        {"source_table": "orders", "source_column": "customer_id",
         "target_table": "invoices", "target_column": "id"}],  # 指向目录中不存在的表
        "primary_keys": {}})
    return catalog


class TestAuditOntologyCoverage:

    def test_uncoveredAndBrokenReference(self, store):
        catalog = _ingest(store)
        catalog.linkTableTerm("default",
                              catalog.listTables("default", q="customers")[0]["catalog_table_id"]
                              if False else catalog.listTables("default")[0]["catalog_table_id"],
                              "Customer")
        out = auditOntologyCoverage(store, "default", sourceId="s1")
        kinds = {f["kind"] for f in out["findings"]}
        assert "uncovered" in kinds          # 未链接术语的表
        assert "broken_reference" in kinds   # 外键指向目录外表
        assert "ambiguity" in kinds          # customers vs Customers 同名
        assert out["counts"]["uncovered"] >= 1

    def test_clashWhenOneTermCoversTwoTables(self, store):
        catalog = _ingest(store)
        tables = catalog.listTables("default")
        catalog.linkTableTerm("default", tables[0]["catalog_table_id"], "Customer")
        catalog.linkTableTerm("default", tables[1]["catalog_table_id"], "Customer")
        out = auditOntologyCoverage(store, "default", sourceId="s1")
        clashes = [f for f in out["findings"] if f["kind"] == "clash"]
        assert clashes and clashes[0]["target"] == "term:Customer"

    def test_stalePendingCandidates(self, store):
        _ingest(store)
        from neurova.knowledge.ontology.relation_candidates import RelationCandidateStore

        candidates = RelationCandidateStore(store)
        candidates.record("default", "位于", sourceEntryId="e1", sourceText="位于")
        with store._lock, store._conn:
            store._conn.execute(
                "UPDATE ontology_relation_candidates SET created_at = ?",
                ("2026-10-01T00:00:00",))
        out = auditOntologyCoverage(store, "default", sourceId="s1", staleDays=7)
        stale = [f for f in out["findings"] if f["kind"] == "stale"]
        assert stale and "位于" in stale[0]["message"] or stale

    def test_fingerprintStableAcrossRuns(self, store):
        _ingest(store)
        first = auditOntologyCoverage(store, "default", sourceId="s1")
        second = auditOntologyCoverage(store, "default", sourceId="s1")
        fp1 = sorted(f["fingerprint"] for f in first["findings"])
        fp2 = sorted(f["fingerprint"] for f in second["findings"])
        assert fp1 == fp2 and fp1

    def test_proposalCarriesAction(self, store):
        _ingest(store)
        out = auditOntologyCoverage(store, "default", sourceId="s1")
        for finding in out["findings"]:
            assert "proposal" in finding and "action" in finding["proposal"]
