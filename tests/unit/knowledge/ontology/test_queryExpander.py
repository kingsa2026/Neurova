# -*- coding: utf-8 -*-
"""B-A3 本体感知查询扩展（升级计划 §3.1 A-3）：语义桥核心。

查询词→别名归一→子类展开→关系邻域→扩展词追加。CQ-01 场景判据。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.query_expander import expandQuery
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    registry = OntologyTermRegistry(s)
    registry.registerMany([
        {"termId": "Order", "kind": "concept", "label": "订单",
         "aliases": ["order"]},
        {"termId": "HighRiskOrder", "kind": "concept", "parentTermId": "Order",
         "label": "高风险订单"},
        {"termId": "Customer", "kind": "concept", "label": "客户"},
        {"termId": "has_status", "kind": "relation", "domain": ["Order"]},
    ])
    gate = productionAdmissionGate(s)
    for subject in ("订单D01", "订单D02"):
        content = "%s is_a Order" % subject
        gate.admit(AdmissionRequest(
            agentId="default", subjectLabel=subject, predicateTermId="is_a",
            objectTerm="Order", content=content,
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test", "statementText": content}]))
        key = s.resolveSubjectKey("default", subject)
        registry.assignSubjectType(key, "Order")
    yield s, registry
    s.close()


class TestQueryExpansion:
    def test_aliasResolvesToCanonical(self, store):
        s, registry = store
        result = expandQuery(registry, "order", agentId="default")
        assert "Order" in result.expandedTerms or "订单" in result.expandedTerms

    def test_subclassExpansionFindsInstances(self, store):
        s, registry = store
        result = expandQuery(registry, "Order", agentId="default")
        assert any("订单D01" in t or "订单D02" in t
                   for t in result.expandedTerms), \
            "子类展开应找到挂 Order 类型的主体实例"

    def test_unknownQueryNoExpansion(self, store):
        s, registry = store
        result = expandQuery(registry, "totally_unrelated_xyz")
        assert len(result.expandedTerms) <= 1

    def test_relationAliasExpands(self, store):
        s, registry = store
        registry.register("has_status", "relation", aliases=["状态"])
        result = expandQuery(registry, "状态", agentId="default")
        assert "has_status" in result.expandedTerms
