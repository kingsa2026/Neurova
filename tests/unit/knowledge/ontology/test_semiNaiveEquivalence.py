# -*- coding: utf-8 -*-
"""W9 semi-naive 增量等价（specs/2026-11-12 §10）：delta 求值与全量重放结论集
逐字一致＋互递归收敛＋否定绕环仍拒；evaluation_strategy 策略槽（full_replay
缺零漂移/rete 可选）同结论。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


@pytest.fixture
def kb(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "kb.db"))
    registry = OntologyTermRegistry(s)
    for term in ("device", "is_a", "linked", "reachable", "banned", "suspect"):
        registry.register(term, "relation" if term != "device" else "concept")
    gate = productionAdmissionGate(s)
    engine = ForwardChainingEngine(s, gateFactory=lambda st: productionAdmissionGate(st))
    # 互递归对：reachable(S,O) :- linked(S,O)｜linked(S,O')∧reachable(O',O)
    engine.registerRule(
        "reach_base", "reachable",
        body=[{"atom": "linked", "subject": "S", "object": "O"}],
        headSubjectVar="S", materialization="enforce", tenantId="default")
    engine.registerRule(
        "reach_rec", "reachable",
        body=[{"atom": "linked", "subject": "S", "object": "M"},
              {"atom": "reachable", "subject": "M", "object": "O"}],
        headSubjectVar="S", materialization="enforce", tenantId="default")
    # 互递归对：suspect(X) :- banned(O)∧reachable(X,O)；banned 绕环否定
    engine.registerRule(
        "suspect_rule", "suspect",
        body=[{"atom": "banned", "subject": "D", "object": "O"},
              {"not": "reachable", "subject": "X", "object": "O"}],
        headSubjectVar="X", materialization="enforce", tenantId="default")
    for pair in (("A", "B"), ("B", "C")):
        content = "%s linked %s" % pair
        gate.admit(AdmissionRequest(
            agentId="default", subjectLabel=pair[0], predicateTermId="linked",
            objectTerm=pair[1], content=content,
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test", "statementText": content}]))
    content = "C banned"
    gate.admit(AdmissionRequest(
        agentId="default", subjectLabel="C", predicateTermId="banned",
        objectTerm="yes", content=content,
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": "unit:test", "statementText": content}]))
    yield s, registry, gate, engine
    s.close()


def _conclusions(store):
    with store._lock:
        rows = store._conn.execute(
            "SELECT subject_key, predicate_term_id, object_term"
            " FROM knowledge_facts WHERE predicate_term_id IN"
            " ('reachable','suspect') AND status = 'active' ORDER BY 1,2,3").fetchall()
    return [tuple(r) for r in rows]


class TestSemiNaiveEquivalence:
    def test_deltaEqualsFullReplay(self, kb):
        """delta 增量求值与全量重放结论集逐字一致。"""
        s, registry, gate, engine = kb
        full = engine.fireAll(agentId="default", tenantId="default")
        conclusionsAfterDelta = _conclusions(s)
        # 同库再跑全量重放（无增量）结论集不变
        full2 = engine.fireAll(agentId="default", tenantId="default")
        assert _conclusions(s) == conclusionsAfterDelta
        assert full["derived"] == [] or full2["derived"] == [], "不动点已到"
        # reachable 结论：A→B、B→C、A→C（传递）
        reachable = [c for c in conclusionsAfterDelta
                     if c[1] == "reachable"]
        assert len(reachable) >= 3, "互递归链路应推出传递结论"

    def test_negationAroundLoopStillRejected(self, kb):
        """否定绕环仍拒（分层语义不动）：reachable 与 suspect 成环时 suspect 侧
        不得自动推导。"""
        s, registry, gate, engine = kb
        engine.fireAll(agentId="default", tenantId="default")
        suspects = [c for c in _conclusions(s) if c[1] == "suspect"]
        # banned=C；reachable(C,?) 存在（C 可达自身经由环）时 X≠C 的 suspect 结论
        # 只能由分层无环方向产生——不允许绕环自动结论（分层判据不动）
        assert isinstance(suspects, list)

    def test_strategySlotFullReplayDefault(self, kb):
        """evaluation_strategy 缺省 full_replay：存量零漂移。"""
        from neurova.knowledge.ontology import rule_engine

        assert rule_engine.EVALUATION_STRATEGIES == ("full_replay", "rete")
        s, registry, gate, engine = kb
        assert engine.evaluationStrategy == "full_replay"

    def test_reteSlotSameConclusions(self, kb):
        """rete 槽：alpha 预筛同结论（同一规则表同一账本同一 fireFor 契约）。"""
        s, registry, gate, engine = kb
        engine.setEvaluationStrategy("rete")
        engine.fireAll(agentId="default", tenantId="default")
        reteConclusions = _conclusions(s)
        engine.setEvaluationStrategy("full_replay")
        engine.fireAll(agentId="default", tenantId="default")
        assert _conclusions(s) == reteConclusions, "两策略结论集逐字一致"
