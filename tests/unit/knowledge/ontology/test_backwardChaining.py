# -*- coding: utf-8 -*-
"""反向链证明器（本体域升级卡 U12）：从目标三元组反向搜索证明。

判据与 test_forward_chaining 同源：真 store + 真咽喉（productionAdmissionGate）装配，
前向链经咽喉落库推导事实；proveGoal 只读规则登记表与已证事实集，给出证明树与缺口。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.backward_chaining import proveGoal
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


def _admit(gate, subject, predicate, obj):
    """经真咽喉写入一条原始断言（与 test_forward_chaining 同一口径）。"""
    content = "%s %s %s" % (subject, predicate, obj)
    return gate.admit(AdmissionRequest(
        agentId="default", subjectLabel=subject, predicateTermId=predicate,
        objectTerm=obj, content=content,
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": "unit:test", "statementText": content}],
    ), allowPendingSegments=True).factId


@pytest.fixture
def kb(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "prove.db"))
    registry = OntologyTermRegistry(s)
    for term in ("instance_of", "part_of", "excluded_from", "linked", "reachable",
                 "a_rel", "b_rel"):
        registry.register(term, "relation")
    gate = productionAdmissionGate(s)
    engine = ForwardChainingEngine(s, gateFactory=lambda st: productionAdmissionGate(st))
    yield s, registry, gate, engine
    s.close()


_IS_A_VIA_INSTANCE = [{"atom": "instance_of", "subject": "X", "object": "Z"},
                      {"atom": "is_a", "subject": "Z", "object": "Y"}]


class TestRelayChain:
    def test_relayConclusionProvesWithRuleAndFactSteps(self, kb):
        """前向链推出的 relay 结论：反向证明树含规则步与事实步。"""
        s, registry, gate, engine = kb
        _admit(gate, "甲", "instance_of", "丙")
        _admit(gate, "丙", "is_a", "乙")
        engine.registerRule("is_a_via_instance", "is_a", _IS_A_VIA_INSTANCE)
        derived = engine.fireAll(agentId="default")["derived"]
        assert len(derived) == 1, "前向链应恰好推出 甲 is_a 乙 一条"

        result = proveGoal(s, "甲", "is_a", "乙")

        assert result["proved"] is True
        assert result["missing"] == []
        assert result["goal"] == {"subject": "甲", "predicate": "is_a", "object": "乙"}
        root = result["steps"][0]
        assert root["kind"] == "rule"
        assert root["ref"] == "is_a_via_instance"
        factSteps = [sub for sub in root["sub"] if sub["kind"] == "fact"]
        assert len(factSteps) == 2, "两个 body 前提都应落在事实步"

    def test_assertedFactProvesDirectlyAsFactStep(self, kb):
        """已证事实命中的目标直接返回 fact 步骤。"""
        s, registry, gate, engine = kb
        factId = _admit(gate, "甲", "instance_of", "丙")

        result = proveGoal(s, "甲", "instance_of", "丙")

        assert result["proved"] is True
        assert result["steps"][0]["kind"] == "fact"
        assert result["steps"][0]["ref"] == factId
        assert result["steps"][0]["sub"] == []

    def test_unprovableGoalNamesTheMissingPremise(self, kb):
        """缺一个前提：proved=False，missing 指到缺的那条 body 原子。"""
        s, registry, gate, engine = kb
        _admit(gate, "甲", "instance_of", "丙")   # 只有第一跳，丙 is_a 乙 缺席
        engine.registerRule("is_a_via_instance", "is_a", _IS_A_VIA_INSTANCE)
        assert engine.fireAll(agentId="default")["derived"] == []

        result = proveGoal(s, "甲", "is_a", "乙")

        assert result["proved"] is False
        assert result["steps"] == []
        assert result["missing"], "不可证目标必须给出缺口"
        missingGoals = [(m["goal"]["subject"], m["goal"]["predicate"],
                         m["goal"]["object"]) for m in result["missing"]]
        assert ("丙", "is_a", "乙") in missingGoals, "缺的前提是 丙 is_a 乙"


class TestStratifiedNegation:
    def test_negatedPremiseBlocksBranch(self, kb):
        """否定原子=该目标在事实集中无证明：事实存在则分支不成立。"""
        s, registry, gate, engine = kb
        _admit(gate, "甲", "part_of", "乙")
        _admit(gate, "乙", "part_of", "丙")
        _admit(gate, "甲", "excluded_from", "丙")
        engine.registerRule(
            "part_of_transitive", "part_of",
            [{"atom": "part_of", "subject": "X", "object": "Y"},
             {"atom": "part_of", "subject": "Y", "object": "Z"},
             {"not": "excluded_from", "subject": "X", "object": "Z"}])
        engine.fireAll(agentId="default")

        result = proveGoal(s, "甲", "part_of", "丙")

        assert result["proved"] is False, "否定原子命中事实，分支不得成立"
        assert any(m["reason"] == "negation_blocked" for m in result["missing"])

    def test_negationWithoutFactAllowsDerivation(self, kb):
        """否定原子在事实集中无证明：分支照常成立。"""
        s, registry, gate, engine = kb
        _admit(gate, "甲", "part_of", "乙")
        _admit(gate, "乙", "part_of", "丙")
        engine.registerRule(
            "part_of_transitive", "part_of",
            [{"atom": "part_of", "subject": "X", "object": "Y"},
             {"atom": "part_of", "subject": "Y", "object": "Z"},
             {"not": "excluded_from", "subject": "X", "object": "Z"}])
        engine.fireAll(agentId="default")

        result = proveGoal(s, "甲", "part_of", "丙")

        assert result["proved"] is True


class TestGoalCycle:
    def test_mutualRulesTerminateAndReportCycle(self, kb):
        """A⇒B、B⇒A 规则对在深度上限内终止，环剪枝记 reason=cycle。"""
        s, registry, gate, engine = kb
        engine.registerRule("a_from_b", "a_rel",
                            [{"atom": "b_rel", "subject": "X", "object": "Y"}])
        engine.registerRule("b_from_a", "b_rel",
                            [{"atom": "a_rel", "subject": "X", "object": "Y"}])

        result = proveGoal(s, "u", "a_rel", "v", maxDepth=8)

        assert result["proved"] is False
        assert "cycle" in {m["reason"] for m in result["missing"]}

    def test_depthLimitPrunesBranches(self, kb):
        """maxDepth 不足时超限分支剪枝并记 reason=depth。"""
        s, registry, gate, engine = kb
        _admit(gate, "甲", "a_rel", "乙")
        engine.registerRule("a_from_b", "a_rel",
                            [{"atom": "b_rel", "subject": "X", "object": "Y"}])
        engine.registerRule("b_from_a", "b_rel",
                            [{"atom": "a_rel", "subject": "X", "object": "Y"}])

        result = proveGoal(s, "乙", "a_rel", "丙", maxDepth=1)

        assert result["proved"] is False
        assert "depth" in {m["reason"] for m in result["missing"]}


class TestParityWithForwardChain:
    def test_everyForwardConclusionIsBackwardProvable(self, kb):
        """对拍：同一规则集+事实集，前向链（经真咽喉）推出的每个结论，
        proveGoal 均 proved=True（结论集包含关系）。

        真咽喉语义下推导发生在写入首跳（admit 即 fireFor），所以结论集从
        事实表读（与 test_semiNaiveEquivalence 的 _conclusions 同一口径），
        不看 fireAll 的增量报告。"""
        s, registry, gate, engine = kb
        engine.registerRule(
            "reach_base", "reachable",
            [{"atom": "linked", "subject": "S", "object": "O"}],
            headSubjectVar="S")
        engine.registerRule(
            "reach_rec", "reachable",
            [{"atom": "linked", "subject": "S", "object": "M"},
             {"atom": "reachable", "subject": "M", "object": "O"}],
            headSubjectVar="S")
        for pair in (("A", "B"), ("B", "C")):
            _admit(gate, pair[0], "linked", pair[1])
        engine.fireAll(agentId="default")   # 幂等对齐到不动点
        with s._lock:
            conclusions = [tuple(r) for r in s._conn.execute(
                "SELECT subject_key, predicate_term_id, object_term"
                " FROM knowledge_facts WHERE predicate_term_id = 'reachable'"
                " AND status = 'active' ORDER BY 1, 3").fetchall()]
        assert len(conclusions) >= 3, "互递归应推出 A/B/C 的 reachable 传递结论"

        for subjectKey, predicate, objectTerm in conclusions:
            label = s.subjectFor(subjectKey)["canonical_label"]
            result = proveGoal(s, label, predicate, objectTerm)
            assert result["proved"] is True, \
                "前向结论 %s %s %s 应可反向证明，缺口：%s" % (
                    label, predicate, objectTerm, result["missing"])


class TestReadOnly:
    def test_proveGoalLeavesNoTrace(self, kb):
        """严格只读：证明前后 facts/derivation 相关表计数不变。"""
        s, registry, gate, engine = kb
        _admit(gate, "甲", "instance_of", "丙")
        _admit(gate, "丙", "is_a", "乙")
        engine.registerRule("is_a_via_instance", "is_a", _IS_A_VIA_INSTANCE)
        engine.fireAll(agentId="default")
        tables = ("knowledge_facts", "knowledge_subjects", "knowledge_derivation_edges",
                  "ontology_rule_fires", "ontology_rules")

        def counts():
            return tuple(s.queryReadOnly("SELECT COUNT(*) AS n FROM %s" % t)[0]["n"]
                         for t in tables)

        before = counts()
        proveGoal(s, "甲", "is_a", "乙")
        proveGoal(s, "不存在", "is_a", "乙")
        assert counts() == before, "proveGoal 不得写任何表"
