"""条件类推导（B1，specs/2026-11-05 §5）：视频同款场景的落地判据。

HighRiskOrder = Order ∩ hasRiskLevel="High"——零显式标注自动归入、
撤规则只撤它自己的结论（原始事实不陪葬）、观察态下推导照常记账。
判据都走真写入口（productionAdmissionGate），不许造裸门绕过咽喉。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine, RuleError
from neurova.knowledge.ontology.term_registry import IS_A_PREDICATE, OntologyTermRegistry


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


@pytest.fixture
def engine(store):
    return ForwardChainingEngine(store, gateFactory=lambda st: productionAdmissionGate(
        st, toolVersion="condition-class"))


def _gate(store):
    return productionAdmissionGate(store, toolVersion="unit")


def _admit(store, subject, predicate, obj):
    content = "%s %s %s" % (subject, predicate, obj)
    return _gate(store).admit(AdmissionRequest(
        agentId="default", subjectLabel=subject, predicateTermId=predicate, objectTerm=obj,
        content=content,
        assertions=[{"actorType": "pipeline", "actorId": "unit", "mediumRef": "unit:test",
                     "statementText": content}],
    ))


def _seedOrders(store):
    """登记类型与谓词，落两笔订单：D01 高风险、D02 低风险。"""
    registry = OntologyTermRegistry(store)
    registry.registerMany([
        {"termId": "Order", "kind": "concept", "label": "订单"},
        {"termId": "HighRiskOrder", "kind": "concept", "label": "高风险订单"},
        {"termId": "hasRiskLevel", "kind": "relation", "label": "风险等级",
         "domain": ["Order"]},
    ])
    for label, level in (("订单D01", "High"), ("订单D02", "Low")):
        _admit(store, label, IS_A_PREDICATE, "Order")
        _admit(store, label, "hasRiskLevel", level)
        key = store.resolveSubjectKey("default", label)
        registry.assignSubjectType(key, "Order")
    return registry


def _conditionRule(engine):
    return engine.registerRule(
        "high_risk_order", IS_A_PREDICATE,
        [{"atom": IS_A_PREDICATE, "subject": "X", "objectConst": "Order"},
         {"atom": "hasRiskLevel", "subject": "X", "objectConst": "High"}],
        headObjectConst="HighRiskOrder",
    )


class TestConditionClassDerivation:
    def test_registeringTheConditionClassDerivesImmediately(self, store, engine):
        """登记即推导：不等到下一条事实落库，存量订单当场归入。"""
        _seedOrders(store)
        assert store.factCount() == 4

        _conditionRule(engine)

        assert store.factCount() == 5, "两笔订单里只有高风险那笔该被归入"
        derived = [f for f in store.searchableFacts(agentId="default")
                   if f["predicate_term_id"] == IS_A_PREDICATE
                   and f["object_term"] == "HighRiskOrder"]
        assert len(derived) == 1
        key = store.resolveSubjectKey("default", "订单D01")
        assert derived[0]["subject_key"] == key
        assert derived[0]["qualifier"].get("derived_by") == "high_risk_order"
        assert derived[0]["qualifier"].get("shape") == "conjunction"

    def test_lowRiskOrderIsNotDerived(self, store, engine):
        _seedOrders(store)
        _conditionRule(engine)

        key = store.resolveSubjectKey("default", "订单D02")
        rows = store._conn.execute(
            "SELECT fact_id FROM knowledge_facts WHERE subject_key = ?"
            " AND predicate_term_id = ? AND object_term = 'HighRiskOrder'",
            (key, IS_A_PREDICATE)).fetchall()
        assert rows == [], "低风险订单不许被归入高风险类"

    def test_secondFireAddsNothing(self, store, engine):
        _seedOrders(store)
        _conditionRule(engine)
        before = store.factCount()

        engine.fireAll(agentId="default")

        assert store.factCount() == before, "推导折回同一行，不动点即停"

    def test_newFactLandsAndDerivesThroughTheGate(self, store, engine):
        _seedOrders(store)
        _conditionRule(engine)
        before = store.factCount()

        _admit(store, "订单D03", IS_A_PREDICATE, "Order")
        _admit(store, "订单D03", "hasRiskLevel", "High")

        assert store.factCount() == before + 3, \
            "D03 两笔原始事实 + 一笔条件类推导，走咽喉落库"

    def test_droppingTheRuleRetractsOnlyItsConclusions(self, store, engine):
        _seedOrders(store)
        _conditionRule(engine)
        derivedId = [f["fact_id"] for f in store.searchableFacts(agentId="default")
                     if f["object_term"] == "HighRiskOrder"][0]
        originalIds = [f["fact_id"] for f in store.searchableFacts(agentId="default")
                       if f["object_term"] != "HighRiskOrder"]

        engine.dropRule("high_risk_order", reason="测试撤规则")

        assert store.fact(derivedId)["status"] == "retracted", \
            "规则退场，它的推导必须退档"
        assert all(store.fact(fid)["status"] == "active" for fid in originalIds), \
            "原始事实不陪葬"
        assert store._derivationLedger.premisesOf(derivedId), "撤了也留账：推导边还在账上"

    def test_derivationLedgerRecordsTwoPremises(self, store, engine):
        _seedOrders(store)
        _conditionRule(engine)
        derivedId = [f["fact_id"] for f in store.searchableFacts(agentId="default")
                     if f["object_term"] == "HighRiskOrder"][0]

        premises = store._derivationLedger.premisesOf(derivedId)

        assert len(premises) == 2, "两条前提：is_a 与 hasRiskLevel 各一条"


class TestConditionClassShapeIsEnforcedAtWrite:
    def test_headMustBeTypeAssertion(self, engine):
        with pytest.raises(RuleError, match="类型断言"):
            engine.registerRule(
                "bad_head", "hasRiskLevel",
                [{"atom": "hasRiskLevel", "subject": "X", "objectConst": "High"}],
                headObjectConst="High", tenantId="default")

    def test_unregisteredConditionClassRefused(self, store, engine):
        OntologyTermRegistry(store)
        with pytest.raises(RuleError, match="未登记"):
            engine.registerRule(
                "bad_term", IS_A_PREDICATE,
                [{"atom": IS_A_PREDICATE, "subject": "X", "objectConst": "Order"}],
                headObjectConst="GhostClass")

    def test_unregisteredBaseTermRefused(self, store, engine):
        OntologyTermRegistry(store)
        with pytest.raises(RuleError, match="未登记"):
            engine.registerRule(
                "bad_base", IS_A_PREDICATE,
                [{"atom": IS_A_PREDICATE, "subject": "X", "objectConst": "GhostBase"},
                 {"atom": "hasRiskLevel", "subject": "X", "objectConst": "High"}],
                headObjectConst="HighRiskOrder")

    def test_variableObjectInConjunctionRefused(self, engine):
        with pytest.raises(RuleError, match="常量"):
            engine.registerRule(
                "bad_var", IS_A_PREDICATE,
                [{"atom": IS_A_PREDICATE, "subject": "X", "object": "Y"},
                 {"atom": "hasRiskLevel", "subject": "X", "objectConst": "High"}],
                headObjectConst="HighRiskOrder")

    def test_relayShapeStillWorksUnchanged(self, store, engine):
        """既有 relay 形状零回归：老签名、老语义一行不动。"""
        _admit(store, "甲", "part_of", "乙")
        _admit(store, "乙", "part_of", "丙")
        engine.registerRule("part_of_transitive", "part_of",
                            [{"atom": "part_of", "subject": "X", "object": "Y"},
                             {"atom": "part_of", "subject": "Y", "object": "Z"}])

        report = engine.fireAll(agentId="default")

        assert len(report["derived"]) == 1
        rule = engine.rule("part_of_transitive")
        assert rule["shape"] == "relay", "存量形状回读默认 relay"
