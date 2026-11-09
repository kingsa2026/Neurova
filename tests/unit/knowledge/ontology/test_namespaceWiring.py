# -*- coding: utf-8 -*-
"""IRI 命名空间接线契约（GB/T 48000.3 评估档 G4，第 9 章 a) 核验更正版）。

v31 已预留 namespace/iri_base 列（读写通），本批接的是消费面：
- 校验：namespace 非空必须命中 NAMESPACE_REGISTRY 闭集（防任意造前缀），
  iri_base 缺省按注册表自动补（用户不写）；
- 导出：owl/turtle/jsonld 按术语 namespace 取前缀（多行 @prefix 声明），
  空 = 缺省 kbg:（存量零漂移）；
- 解析：iri.py 反查多前缀（{ns}:{termId} → 术语行）。
"""
import json

import pytest

from neurova.knowledge.foundation.foundation_schema import applyTo
from neurova.knowledge.ontology.export.owl import exportOwlAxioms
from neurova.knowledge.ontology.export.jsonld import exportJsonLd
from neurova.knowledge.ontology.term_registry import (
    NAMESPACE_REGISTRY,
    OntologyTermRegistry,
)
from neurova.knowledge.ontology.turtle import serializeAll


@pytest.fixture()
def registry():
    from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

    store = KnowledgeFactStore(":memory:")
    applyTo(store._conn)
    yield OntologyTermRegistry(store)
    store.close()


class TestNamespaceClosure:
    def test_registrySingleSourced(self):
        assert "so" in NAMESPACE_REGISTRY
        assert NAMESPACE_REGISTRY["so"].startswith("https://")

    def test_knownNamespaceAcceptedAndIriBaseAutoFilled(self, registry):
        registry.register("std_term", "concept", label="标准术语", namespace="so")
        term = registry.term("std_term", tenantId="default")
        assert term["namespace"] == "so"
        assert term["iri_base"] == NAMESPACE_REGISTRY["so"]

    def test_unknownNamespaceRejected(self, registry):
        with pytest.raises(ValueError, match="命名空间"):
            registry.register("rogue", "concept", label="R", namespace="zz")


class TestMultiPrefixExport:
    def _seed(self, registry):
        registry.register("std_term", "concept", label="标准术语", namespace="so")
        registry.register("plain", "concept", label="普通")

    def test_owlMultiPrefix(self, registry):
        self._seed(registry)
        text = exportOwlAxioms(registry._store)
        assert "@prefix so: <" in text
        assert "so:std_term rdf:type owl:Class ." in text
        assert "kbg:plain rdf:type owl:Class ." in text

    def test_turtleMultiPrefixAndRoundTrip(self, registry):
        self._seed(registry)
        text = serializeAll(registry._store, tenantId="default")
        assert "@prefix so: <" in text
        assert "so:std_term" in text
        # 读回往返：导出的文本能被自家解析器读回（格式校验唯一判据）
        from neurova.knowledge.ontology.turtle import parseTurtle

        triples = parseTurtle(text)
        subjects = {s for s, _, _ in triples}
        assert any("std_term" in s for s in subjects)

    def test_jsonldMultiPrefix(self, registry):
        self._seed(registry)
        doc = json.loads(exportJsonLd(registry._store))
        ids = {n["@id"] for n in doc["@graph"] if "term_id" in n}
        assert "so:std_term" in ids
        assert "kbg:plain" in ids


class TestNamespaceResolve:
    def test_prefixedIriResolves(self, registry):
        registry.register("std_term", "concept", label="标准术语", namespace="so")
        from neurova.api.endpoints.knowledge_ontology_iri import _resolveIri

        hit = _resolveIri(registry._store, "so:std_term", "default")
        assert hit["term_id"] == "std_term"
