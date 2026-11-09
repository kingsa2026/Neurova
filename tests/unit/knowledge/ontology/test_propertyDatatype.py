# -*- coding: utf-8 -*-
"""数据属性基本数据类型契约（GB/T 48000.3 评估档 G2，5.5 表 3）。

- 闭集五类：boolean/date/number/text/url（单点常量 DATA_TYPES）；
- 校验（注册表写入处硬拒，与 kind 闭集/值域类别同款 ValueError）：
  kind='property' 且 datatype 非法 → 拒；kind≠'property' 且 datatype 非空 → 拒；
  kind='property' 声明关系三性质（symmetric/transitive/inverse_of）→ 拒（7.2.2 d)）；
- 导出面：property 分支落 OWL 公理（owl:DatatypeProperty ＋ rdfs:range xsd:*，
  消 G6——此前声明循环缺 property 分支，property 术语在 export.owl 不可见）。
"""
import pytest

from neurova.knowledge.foundation.foundation_schema import applyTo
from neurova.knowledge.ontology.export.owl import exportOwlAxioms
from neurova.knowledge.ontology.term_registry import DATA_TYPES, OntologyTermRegistry


@pytest.fixture()
def registry():
    from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

    store = KnowledgeFactStore(":memory:")
    applyTo(store._conn)
    yield OntologyTermRegistry(store)
    store.close()


class TestDatatypeClosure:
    def test_closureSingleSourced(self):
        assert DATA_TYPES == ("boolean", "date", "number", "text", "url")

    def test_registerAndReadBack(self, registry):
        registry.register("created_at", "property", label="创建于",
                          datatype="date")
        assert registry.term("created_at", tenantId="default")["datatype"] == "date"

    def test_unknownDatatypeRejected(self, registry):
        with pytest.raises(ValueError, match="数据类型"):
            registry.register("x", "property", label="X", datatype="float64")

    def test_nonPropertyDatatypeRejected(self, registry):
        with pytest.raises(ValueError, match="只有 property"):
            registry.register("y", "concept", label="Y", datatype="date")

    def test_propertyForbiddenRelationalTraits(self, registry):
        """7.2.2 d)：数据属性不应具传递/对称/互逆性——写入处拒。"""
        for kwargs in ({"symmetric": True}, {"transitive": True},
                       {"inverseOf": "other_prop"}):
            with pytest.raises(ValueError, match="数据属性不应具传递/对称/互逆性"):
                registry.register("p1", "property", label="P", **kwargs)


class TestPropertyOwlExport:
    def test_datatypePropertyDeclarationAndRange(self, registry):
        """消 G6：property 术语在 export.owl 中可见（此前声明循环缺分支）。"""
        registry.register("created_at", "property", label="创建于", datatype="date")
        registry.register("score", "property", label="分数", datatype="number")
        registry.register("homepage", "property", label="主页", datatype="url")
        registry.register("tag_text", "property", label="标签文本", datatype="text")
        registry.register("is_active", "property", label="激活", datatype="boolean")
        text = exportOwlAxioms(registry._store)
        assert "kbg:created_at rdf:type owl:DatatypeProperty ." in text
        assert "kbg:created_at rdfs:range xsd:date ." in text
        assert "kbg:score rdfs:range xsd:decimal ." in text
        assert "kbg:homepage rdfs:range xsd:anyURI ." in text
        assert "kbg:tag_text rdfs:range xsd:string ." in text
        assert "kbg:is_active rdfs:range xsd:boolean ." in text

    def test_noDatatypeStillDeclared(self, registry):
        """datatype 缺省（未约束态）仍出 DatatypeProperty 声明，只是无 range 行。"""
        registry.register("loose", "property", label="宽松")
        text = exportOwlAxioms(registry._store)
        assert "kbg:loose rdf:type owl:DatatypeProperty ." in text
        assert "kbg:loose rdfs:range" not in text
