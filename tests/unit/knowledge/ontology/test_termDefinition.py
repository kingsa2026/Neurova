# -*- coding: utf-8 -*-
"""术语 Definition（定义）描述项契约（GB/T 48000.3 评估档 G1，表 1/表 2 第 4 项）。

- 数据面：ontology_terms.definition 列（v40），空 = 「这一维没依据」（保守写入，
  不算违规——与注册表既有哲学一致，quality.py 的「缺定义」判据消费它）；
- 导出面：definition 非空才出断言（owl.py `rdfs:comment`、jsonld `definition`
  字段、turtle kbg: 块 `definition` 谓词行）——空值零漂移，golden 稳定；
- API 面：TermWriteRequest.definition（None = PUT 保留现值）。
"""
import pytest

from neurova.knowledge.foundation.foundation_schema import applyTo
from neurova.knowledge.ontology.export.owl import exportOwlAxioms
from neurova.knowledge.ontology.export.jsonld import exportJsonLd
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry
from neurova.knowledge.ontology.turtle import serializeAll


@pytest.fixture()
def registry():
    from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

    store = KnowledgeFactStore(":memory:")
    applyTo(store._conn)
    yield OntologyTermRegistry(store)
    store.close()


class TestDefinitionColumn:
    def test_registerAndReadBack(self, registry):
        registry.register("spatial_thing", "concept", label="空间物",
                          definition="占据空间区域的连续体子类")
        term = registry.term("spatial_thing", tenantId="default")
        assert term["definition"] == "占据空间区域的连续体子类"

    def test_emptyDefault(self, registry):
        registry.register("plain", "concept", label="P")
        assert registry.term("plain", tenantId="default")["definition"] == ""

    def test_putPartialKeepsDefinition(self, registry):
        """PUT 只改 label 时 definition 保留现值（declarePartial 合并语义）。"""
        registry.register("t1", "concept", label="旧名", definition="原定义")
        registry.declarePartial("t1", "concept", {"label": "新名"})
        term = registry.term("t1", tenantId="default")
        assert term["label"] == "新名"
        assert term["definition"] == "原定义"


class TestDefinitionExport:
    def _seed(self, registry):
        registry.register("defined", "concept", label="有定义",
                          definition="这是一条定义文本")
        registry.register("undefined", "concept", label="无定义")

    def test_owlEmitsRdfsCommentOnlyWhenPresent(self, registry):
        self._seed(registry)
        text = exportOwlAxioms(registry._store)
        assert 'kbg:defined rdfs:comment "这是一条定义文本"@zh .' in text
        # 无定义术语零漂移：不出空 comment 行
        assert 'kbg:undefined rdfs:comment' not in text

    def test_jsonldCarriesDefinitionField(self, registry):
        self._seed(registry)
        import json

        doc = json.loads(exportJsonLd(registry._store))
        nodes = {n["term_id"]: n for n in doc["@graph"] if "term_id" in n}
        assert nodes["defined"]["definition"] == "这是一条定义文本"
        assert "definition" not in nodes["undefined"]

    def test_turtleEmitsDefinitionPredicate(self, registry):
        self._seed(registry)
        text = serializeAll(registry._store, tenantId="default")
        assert '"这是一条定义文本"' in text
