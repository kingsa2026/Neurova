# -*- coding: utf-8 -*-
"""external_iris 结构化列表契约（GB/T 48000.3 评估档 G3，2026-11-10 拍板）。

拍板：外部映射整体重构为结构化列表——每条 {"kind": <映射语义闭集>, "iri": <IRI>}，
废弃旧 dict（键语义混用：'bfo' 是前缀别名、'skos_exactMatch' 才是映射类型）。
配套两项行为裁定：
  ① 导出「替换」改「附加断言」——本体 IRI 恒为 kbg:，等价/对齐关系以独立
     三元组断言输出（owl:equivalentClass / owl:equivalentProperty / skos:exactMatch）；
  ② 存量 dict 行由 v39 迁移统一转换（非闭集键一律归 skos_exactMatch）。
"""
import json

import pytest

from neurova.knowledge.foundation.foundation_schema import applyTo
from neurova.knowledge.ontology.term_registry import (
    EXTERNAL_IRI_KINDS,
    OntologyTermRegistry,
)


@pytest.fixture()
def store():
    from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

    store = KnowledgeFactStore(":memory:")
    applyTo(store._conn)
    yield store
    store.close()


@pytest.fixture()
def registry(store):
    return OntologyTermRegistry(store)


class TestStructuredListContract:
    def test_kindClosureIsSingleSourced(self):
        assert EXTERNAL_IRI_KINDS == (
            "skos_exactMatch", "skos_closeMatch", "skos_relatedMatch", "equivalentClass")

    def test_registerWithListAndReadBack(self, registry):
        registry.register("part_of", "relation", label="属于",
                          externalIris=[{"kind": "skos_exactMatch",
                                         "iri": "http://example.org/vocab#partOf"}])
        term = registry.term("part_of", tenantId="default")
        assert term["external_iris"] == [
            {"kind": "skos_exactMatch", "iri": "http://example.org/vocab#partOf"}]

    def test_unknownKindRejected(self, registry):
        with pytest.raises(ValueError, match="外部 IRI 映射类型"):
            registry.register("x", "concept", label="X",
                              externalIris=[{"kind": "bfo", "iri": "http://example.org/b"}])

    def test_emptyIriRejected(self, registry):
        with pytest.raises(ValueError, match="iri 不能为空"):
            registry.register("x", "concept", label="X",
                              externalIris=[{"kind": "skos_exactMatch", "iri": " "}])

    def test_emptyListWritesEmptyList(self, registry):
        registry.register("plain", "concept", label="P", externalIris=[])
        assert registry.term("plain", tenantId="default")["external_iris"] == []

    def test_equivalentClassOnRelationStillExportable(self, registry):
        # equivalentClass 语义是类级，但关系侧等价导出 owl:equivalentProperty 同样合法；
        # 注册面不拦（保守写入），导出面按 kind 选谓词。
        registry.register("same_as_rel", "relation", label="同一",
                          externalIris=[{"kind": "equivalentClass",
                                         "iri": "http://example.org/eq"}])
        assert registry.term("same_as_rel", tenantId="default")["external_iris"]


class TestV39Migration:
    def test_dictRowsMigratedToList(self, store):
        conn = store._conn
        # 造 v39 之前的旧格式行（模拟存量）：统一降版本重放不可行，直接手插旧 dict。
        conn.execute(
            "INSERT OR REPLACE INTO ontology_terms(term_id, kind, label, tenant_id,"
            " external_iris_json, version, created_at, updated_at)"
            " VALUES ('legacy_t', 'concept', '旧', 'default', ?, 'v1', '2026', '2026')",
            (json.dumps({"bfo": "http://example.org/BFO_x"}),))
        conn.execute(
            "INSERT OR REPLACE INTO ontology_terms(term_id, kind, label, tenant_id,"
            " external_iris_json, version, created_at, updated_at)"
            " VALUES ('legacy_m', 'relation', '旧映射', 'default', ?, 'v1', '2026', '2026')",
            (json.dumps({"skos_exactMatch": "http://example.org/m"}),))
        # 重放 v39 迁移 SQL（与 foundation_schema 注册的语句同一份事实源）
        from neurova.knowledge.foundation.foundation_schema import _STEPS
        sql = next(s for v, s in _STEPS if v == 39)
        conn.executescript(sql)
        legacy_t = json.loads(conn.execute(
            "SELECT external_iris_json FROM ontology_terms WHERE term_id='legacy_t'"
        ).fetchone()[0])
        legacy_m = json.loads(conn.execute(
            "SELECT external_iris_json FROM ontology_terms WHERE term_id='legacy_m'"
        ).fetchone()[0])
        # 非闭集键（bfo 前缀别名）统一归 skos_exactMatch——附加断言模式下是纯增益
        assert legacy_t == [{"kind": "skos_exactMatch", "iri": "http://example.org/BFO_x"}]
        assert legacy_m == [{"kind": "skos_exactMatch", "iri": "http://example.org/m"}]
        # 幂等：列表行重放不动
        conn.executescript(sql)
        assert json.loads(conn.execute(
            "SELECT external_iris_json FROM ontology_terms WHERE term_id='legacy_t'"
        ).fetchone()[0]) == legacy_t
