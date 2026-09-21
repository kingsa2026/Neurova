"""Issue #72 附带根因 · 构造期播种不许抹掉已登记的类型属性（红绿灯 TDD）。

发现方式：给 `depends_on` 登记定义域之后，抽取链上的本体硬拒**不响**。追下去看到
`OntologyTermRegistry.__init__` 每次都调 `seedBuiltinTerms`，而播种走的是
`register`（INSERT OR REPLACE）——于是每造一次注册表，就把这一行的
`domain_terms` / `range_terms` / `cardinality` / `required_props` 覆盖回枚举的裸值。

这是"第二份定义悄悄盖掉权威"：登记是写入方的意图，播种只是**补齐缺的行**。
本文件锁定：播种只补缺，不动已有行；显式 `register` 仍然是"更新"那个动词。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


@pytest.fixture()
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


class TestSeedingIsAdditiveOnly:
    def test_newRegistryDoesNotWipeRegisteredDomain(self, store):
        first = OntologyTermRegistry(store)
        first.register("depends_on", "relation", label="依赖", domain=["vessel"],
                       rangeTerms=["vessel"], cardinality=2)

        second = OntologyTermRegistry(store)

        assert second.term("depends_on")["domain_terms"] == ["vessel"]
        assert second.term("depends_on")["range_terms"] == ["vessel"]
        assert second.term("depends_on")["cardinality"] == 2
        assert second.term("depends_on")["label"] == "依赖"

    def test_missingTermsAreStillSeeded(self, store):
        """只补缺不等于不补：新库该有的一条都不能少。"""
        registry = OntologyTermRegistry(store)

        for termId in ("is_a", "documented_as", "concept", "related_to"):
            assert registry.term(termId) is not None, "%s 没被播种" % termId

    def test_explicitRegisterStillUpdates(self, store):
        """`register` 是"更新"那个动词，播种只补缺——两个语义不能混成一个。"""
        registry = OntologyTermRegistry(store)
        registry.register("depends_on", "relation", domain=["a"])

        registry.register("depends_on", "relation", domain=["b"])

        assert registry.term("depends_on")["domain_terms"] == ["b"]
