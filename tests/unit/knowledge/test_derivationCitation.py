"""推导事实读侧治理（B1 观察态＋B4 溯源标注，specs/2026-11-05 §5）。

判据：条件类推导在观察态下不进检索主路（账本照记）；
溯源标注让"这是推出来的"在对话里可辨，不伪装成观察事实。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.derivation_citation import (
    annotateDerivations,
    conditionClassRouteOn,
    derivationSummary,
    filterConditionClassFacts,
)
from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
from neurova.knowledge.ontology.term_registry import IS_A_PREDICATE, OntologyTermRegistry


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


def _admit(store, subject, predicate, obj):
    content = "%s %s %s" % (subject, predicate, obj)
    return productionAdmissionGate(store).admit(AdmissionRequest(
        agentId="default", subjectLabel=subject, predicateTermId=predicate, objectTerm=obj,
        content=content,
        assertions=[{"actorType": "pipeline", "actorId": "unit", "mediumRef": "unit:test",
                     "statementText": content}],
    ))


@pytest.fixture
def seeded(store):
    """B1 同款最小场景：Order/HighRiskOrder/hasRiskLevel + 两笔订单 + 条件类规则。"""
    registry = OntologyTermRegistry(store)
    registry.registerMany([
        {"termId": "Order", "kind": "concept", "label": "订单"},
        {"termId": "HighRiskOrder", "kind": "concept", "label": "高风险订单"},
        {"termId": "hasRiskLevel", "kind": "relation", "label": "风险等级",
         "domain": ["Order"]},
    ])
    _admit(store, "订单D01", IS_A_PREDICATE, "Order")
    _admit(store, "订单D01", "hasRiskLevel", "High")
    key = store.resolveSubjectKey("default", "订单D01")
    registry.assignSubjectType(key, "Order")
    ForwardChainingEngine(store, gateFactory=lambda st: productionAdmissionGate(st)).registerRule(
        "high_risk_order", IS_A_PREDICATE,
        [{"atom": IS_A_PREDICATE, "subject": "X", "objectConst": "Order"},
         {"atom": "hasRiskLevel", "subject": "X", "objectConst": "High"}],
        headObjectConst="HighRiskOrder")
    derivedId = [f["fact_id"] for f in store.searchableFacts(agentId="default")
                 if f["object_term"] == "HighRiskOrder"][0]
    explicitId = [f["fact_id"] for f in store.searchableFacts(agentId="default")
                  if f["predicate_term_id"] == "hasRiskLevel"][0]
    return {"store": store, "derivedId": derivedId, "explicitId": explicitId,
            "entryId": "entry:doc1"}


class TestObserveStateFilter:
    def test_conditionClassFactsFilteredByDefault(self, seeded):
        items = [{"knowledge_id": "k1", "lineage_id": seeded["derivedId"]},
                 {"knowledge_id": "k2", "lineage_id": seeded["explicitId"]},
                 {"knowledge_id": "k3"}]
        kept, filtered = filterConditionClassFacts(items, seeded["store"])

        assert filtered == 1 and [i["knowledge_id"] for i in kept] == ["k2", "k3"], \
            "观察态下条件类推导不进检索主路；显式事实与无血缘条目照常"

    def test_routeFlagLetsEverythingThrough(self, seeded, monkeypatch):
        monkeypatch.setenv("NEUROVA_CONDITION_CLASSES_ROUTE", "1")
        assert conditionClassRouteOn() is True
        items = [{"knowledge_id": "k1", "lineage_id": seeded["derivedId"]}]
        kept, filtered = filterConditionClassFacts(items, seeded["store"])

        assert filtered == 0 and kept == items, "翻主路开关后放行（双向可回滚）"

    def test_entriesWithoutLineagePassThrough(self, seeded):
        items = [{"knowledge_id": "k3"}]
        kept, filtered = filterConditionClassFacts(items, seeded["store"])

        assert filtered == 0 and kept == items

    def test_storeFailureFailsSoft(self, seeded):
        class Boom:
            def fact(self, factId):
                raise RuntimeError("库暂时不可用")

        items = [{"knowledge_id": "k1", "lineage_id": seeded["derivedId"]}]
        kept, filtered = filterConditionClassFacts(items, Boom())

        assert filtered == 0 and kept == items, "读侧治理失败让路，检索主路不陪葬"


class TestDerivationCitation:
    def test_derivedFactIsAnnotatedWithRuleAndPremises(self, seeded):
        items = [{"knowledge_id": "k1", "lineage_id": seeded["derivedId"]}]
        annotated = annotateDerivations(items, seeded["store"])

        info = annotated[0]["derivation"]
        assert info["derived"] is True
        assert info["ruleId"] == "high_risk_order"
        assert info["premiseCount"] == 2, "两条前提：is_a 与 hasRiskLevel"

    def test_explicitFactAndPlainEntryAreNotDerived(self, seeded):
        items = [{"knowledge_id": "k2", "lineage_id": seeded["explicitId"]},
                 {"knowledge_id": "k3"}]
        annotated = annotateDerivations(items, seeded["store"])

        assert all(i["derivation"] == {"derived": False} for i in annotated), \
            "观察事实不许被标成推导——溯源失去区分力等于没有溯源"

    def test_summaryCountsDerivedHits(self, seeded):
        items = [{"knowledge_id": "k1", "lineage_id": seeded["derivedId"]},
                 {"knowledge_id": "k2", "lineage_id": seeded["explicitId"]}]
        annotated = annotateDerivations(items, seeded["store"])

        assert derivationSummary(annotated) == {"hits": 2, "derived_hits": 1}
