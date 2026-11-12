# -*- coding: utf-8 -*-
"""W3 状态机登记与迁移约束（specs/2026-11-12 §5）。

登记闭集校验（states 外名字登记即拒）；转换约束进 validation（主体 term 有
状态机时，新 has_state 值的 from→to 须在 transitions 内；无当前状态只许
initial_state；guardPredicate 可选存在性检查）；admission 校验段自动继承
（不开第二校验口）；无状态机 term 零漂移。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.domain_pack import importDomainPack
from neurova.knowledge.ontology.state_machine_registry import StateMachineRegistry
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


@pytest.fixture
def kb(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "kb.db"))
    registry = OntologyTermRegistry(s)
    registry.register("orders", "concept", label="订单")
    registry.register("has_state", "relation", cardinality=1)
    registry.register("paid", "relation")
    yield s, registry
    s.close()


def _machine(kb, transitions=None, initial="created"):
    s, registry = kb
    reg = StateMachineRegistry(s)
    return reg, reg.register(
        termId="orders", tenantId="default",
        states=["created", "paid", "shipped", "cancelled"],
        transitions=transitions or [
            {"from": "created", "to": "paid"},
            {"from": "paid", "to": "shipped"},
            {"from": "paid", "to": "cancelled"},
        ],
        initialState=initial)


def _typedSubject(kb, label):
    """建主体并挂 orders 类型（状态机按主体类型 term 查找）。"""
    s, registry = kb
    gate = productionAdmissionGate(s)
    content = "%s is_a orders" % label
    gate.admit(AdmissionRequest(
        agentId="default", subjectLabel=label, predicateTermId="is_a",
        objectTerm="orders", content=content,
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": "unit:test", "statementText": content}]))
    key = s.resolveSubjectKey("default", label)
    registry.assignSubjectType(key, "orders")
    return key


class TestRegistration:
    def test_registerAndHydrate(self, kb):
        reg, row = _machine(kb)
        assert row["term_id"] == "orders"
        assert row["initial_state"] == "created"
        assert len(row["transitions"]) == 3
        assert len(StateMachineRegistry(kb[0]).list()) == 1

    def test_transitionOutsideStatesRejected(self, kb):
        s, _registry = kb
        reg = StateMachineRegistry(s)
        with pytest.raises(ValueError, match="闭集"):
            reg.register(termId="orders", tenantId="default",
                         states=["created", "paid"],
                         transitions=[{"from": "created", "to": "ghost"}],
                         initialState="created")

    def test_initialOutsideStatesRejected(self, kb):
        s, _registry = kb
        reg = StateMachineRegistry(s)
        with pytest.raises(ValueError, match="initial"):
            reg.register(termId="orders", tenantId="default",
                         states=["created", "paid"],
                         transitions=[], initialState="ghost")

    def test_hasStateSeedInStandardPack(self, tmp_path):
        """has_state 进 standard_pack（kind=relation、cardinality=1），导入即补缺。"""
        s = KnowledgeFactStore(str(tmp_path / "kb2.db"))
        registry = OntologyTermRegistry(s)
        added = importDomainPack(registry, "standard")
        term = registry.term("has_state")
        assert term is not None, "standard_pack 应含 has_state"
        assert int(term.get("cardinality") or 0) == 1
        assert added >= 1
        # 二次导入幂等
        assert importDomainPack(registry, "standard") == 0
        s.close()


class TestTransitionValidation:
    def test_firstStateMustBeInitial(self, kb):
        s, registry = kb
        _machine(kb)
        gate = productionAdmissionGate(s)
        _typedSubject(kb, "订单O1")
        with pytest.raises(ValueError, match="初始状态"):
            gate.admit(AdmissionRequest(
                agentId="default", subjectLabel="订单O1", predicateTermId="has_state",
                objectTerm="shipped", content="订单O1 has_state shipped",
                assertions=[{"actorType": "pipeline", "actorId": "unit",
                             "mediumRef": "unit:test",
                             "statementText": "订单O1 has_state shipped"}]))

    def test_legalTransitionPasses(self, kb):
        s, _registry = kb
        _machine(kb)
        gate = productionAdmissionGate(s)
        _typedSubject(kb, "订单O2")
        receipt = gate.admit(AdmissionRequest(
            agentId="default", subjectLabel="订单O2", predicateTermId="has_state",
            objectTerm="created", content="订单O2 has_state created",
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test",
                         "statementText": "订单O2 has_state created"}]))
        receipt2 = gate.admit(AdmissionRequest(
            agentId="default", subjectLabel="订单O2", predicateTermId="has_state",
            objectTerm="paid", content="订单O2 has_state paid",
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test",
                         "statementText": "订单O2 has_state paid"}]))
        key = s.resolveSubjectKey("default", "订单O2")
        states = [f["object_term"] for f in s.factsForSubject(key)
                  if f["predicate_term_id"] == "has_state"
                  and f["status"] == "active"]
        assert states == ["paid"], "created→paid 合法迁移，旧状态经 supersede 退场"
        assert receipt.factId != receipt2.factId

    def test_illegalTransitionRejected(self, kb):
        s, _registry = kb
        _machine(kb)
        gate = productionAdmissionGate(s)
        _typedSubject(kb, "订单O3")
        gate.admit(AdmissionRequest(
            agentId="default", subjectLabel="订单O3", predicateTermId="has_state",
            objectTerm="created", content="订单O3 has_state created",
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test",
                         "statementText": "订单O3 has_state created"}]))
        with pytest.raises(ValueError, match="迁移"):
            gate.admit(AdmissionRequest(
                agentId="default", subjectLabel="订单O3", predicateTermId="has_state",
                objectTerm="shipped", content="订单O3 has_state shipped",
                assertions=[{"actorType": "pipeline", "actorId": "unit",
                             "mediumRef": "unit:test",
                             "statementText": "订单O3 has_state shipped"}]))

    def test_noMachineZeroDrift(self, tmp_path):
        """无状态机 term：has_state 照常写（存量零漂移）。"""
        s = KnowledgeFactStore(str(tmp_path / "kb3.db"))
        OntologyTermRegistry(s).register("has_state", "relation", cardinality=1)
        gate = productionAdmissionGate(s)
        receipt = gate.admit(AdmissionRequest(
            agentId="default", subjectLabel="任意X", predicateTermId="has_state",
            objectTerm="任何值", content="任意X has_state 任何值",
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test",
                         "statementText": "任意X has_state 任何值"}]))
        assert receipt.factId
        s.close()

    def test_guardPredicateExistence(self, kb):
        """guardPredicate 可选存在性检查：主体无该谓词 active 事实则迁移拒。"""
        s, registry = kb
        reg, _row = _machine(kb)
        reg.update("orders", tenantId="default",
                   transitions=[{"from": "created", "to": "paid",
                                 "guardPredicate": "paid"}])
        gate = productionAdmissionGate(s)
        _typedSubject(kb, "订单O4")
        gate.admit(AdmissionRequest(
            agentId="default", subjectLabel="订单O4", predicateTermId="has_state",
            objectTerm="created", content="订单O4 has_state created",
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test",
                         "statementText": "订单O4 has_state created"}]))
        with pytest.raises(ValueError, match="guard"):
            gate.admit(AdmissionRequest(
                agentId="default", subjectLabel="订单O4", predicateTermId="has_state",
                objectTerm="paid", content="订单O4 has_state paid",
                assertions=[{"actorType": "pipeline", "actorId": "unit",
                             "mediumRef": "unit:test",
                             "statementText": "订单O4 has_state paid"}]))
        # 补上 guard 事实后迁移放行
        gate.admit(AdmissionRequest(
            agentId="default", subjectLabel="订单O4", predicateTermId="paid",
            objectTerm="yes", content="订单O4 paid yes",
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test",
                         "statementText": "订单O4 paid yes"}]))
        receipt = gate.admit(AdmissionRequest(
            agentId="default", subjectLabel="订单O4", predicateTermId="has_state",
            objectTerm="paid", content="订单O4 has_state paid",
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test",
                         "statementText": "订单O4 has_state paid"}]))
        assert receipt.factId
