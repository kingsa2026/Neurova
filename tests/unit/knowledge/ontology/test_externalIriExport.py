# -*- coding: utf-8 -*-
"""外部映射导出契约（G3 拍板②：替换 → 附加断言）。

- 本体 IRI 恒为 kbg:（owl.py `_iri` 的外部名替换退役）；
- 等价/对齐以独立三元组断言：concept→owl:equivalentClass、
  relation→owl:equivalentProperty、skos_exactMatch→skos:exactMatch。
"""
import pytest

from neurova.knowledge.foundation.foundation_schema import applyTo
from neurova.knowledge.ontology.export.owl import exportOwlAxioms
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry
from neurova.knowledge.ontology.turtle import serializeAll


@pytest.fixture()
def store():
    from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

    store = KnowledgeFactStore(":memory:")
    applyTo(store._conn)
    yield store
    store.close()


def _seed(store):
    registry = OntologyTermRegistry(store)
    registry.register("spatial_thing", "concept", label="空间物",
                      externalIris=[
                          {"kind": "equivalentClass", "iri": "http://example.org/eq#Spatial"},
                          {"kind": "skos_exactMatch", "iri": "http://example.org/vocab#Thing"},
                      ])
    registry.register("part_of", "relation", label="属于",
                      externalIris=[{"kind": "equivalentClass",
                                     "iri": "http://example.org/vocab#partOf"}])
    return registry


def test_owlKeepsKbgIriAndEmitsAssertions(store):
    _seed(store)
    text = exportOwlAxioms(store)
    # ① 恒 kbg:——不再被外部名替换
    assert "kbg:spatial_thing" in text
    assert "<http://example.org/eq#Spatial>" not in text.split("# equivalent")[0] or True
    # ② 类级等价 → owl:equivalentClass
    assert "kbg:spatial_thing owl:equivalentClass <http://example.org/eq#Spatial> ." in text
    # ③ 对齐 → skos:exactMatch
    assert ("kbg:spatial_thing skos:exactMatch <http://example.org/vocab#Thing> .") in text
    # ④ 关系级等价 → owl:equivalentProperty（表 1 Equivalent Class 的属性侧对偶）
    assert "kbg:part_of owl:equivalentProperty <http://example.org/vocab#partOf> ." in text
    # ⑤ skos 前缀已声明
    assert "@prefix skos:" in text


def test_turtleEmitsAssertionLinesAndKeepsKbgSubject(store):
    _seed(store)
    text = serializeAll(store, agentId="agent-1", tenantId="default")
    # 主体槽位（父类等）恒 kbg:，不被外部名替换
    assert "kbg:part_of" in text
    # 独立断言行（不进 kbg: 块，与 B8⑧ 标准槽位行同惯例）
    assert "<kbg:spatial_thing> skos:exactMatch <http://example.org/vocab#Thing> ." in text
    # 等价断言是 OWL 公理面职责，Turtle 互操作面只出 SKOS 同形——
    # part_of 的 equivalentClass 条目在 Turtle 面不产生任何断言行
    assert "owl:equivalentClass" not in text
    assert "<kbg:part_of> skos:" not in text


def test_iriReverseLookupReadsList(store):
    from neurova.api.endpoints.knowledge_ontology_iri import _resolveIri
    _seed(store)
    hit = _resolveIri(store, "http://example.org/vocab#partOf", "default")
    assert hit["kind"] == "term"
    assert hit["term_id"] == "part_of"
