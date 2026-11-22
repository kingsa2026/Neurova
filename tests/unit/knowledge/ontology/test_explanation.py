"""解释生成器（升级卡 U13）：把推导账本与证明树投影成统一解释结构。

真装配：真 KnowledgeFactStore + 真生产咽喉 gate + 真前向链引擎，不打桩业务
对象——解释读的是账本里真实落库的推导边，不是 mock 出来的血缘。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
from neurova.knowledge.ontology.explanation import explainDerivation, explainProof

PART_OF = [{"atom": "part_of", "subject": "X", "object": "Y"},
           {"atom": "part_of", "subject": "Y", "object": "Z"}]


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


@pytest.fixture
def engine(store):
    return ForwardChainingEngine(store, gateFactory=lambda st: productionAdmissionGate(
        st, toolVersion="rule-engine"))


def _admit(store, subject, predicate, obj):
    content = "%s %s %s" % (subject, predicate, obj)
    return productionAdmissionGate(store, toolVersion="unit").admit(AdmissionRequest(
        agentId="default", subjectLabel=subject, predicateTermId=predicate, objectTerm=obj,
        content=content,
        assertions=[{"actorType": "pipeline", "actorId": "unit", "mediumRef": "unit:test",
                     "statementText": content}],
    ), allowPendingSegments=True).factId


def _derivationFixture(store, engine):
    """登记传递规则 → 两条基础事实 → 前向推出唯一结论 甲 part_of 丙。"""
    fidA = _admit(store, "甲", "part_of", "乙")
    fidB = _admit(store, "乙", "part_of", "丙")
    engine.registerRule("part_of_transitive", "part_of", PART_OF)
    derived = engine.fireAll(agentId="default")["derived"]
    assert len(derived) == 1, "fixture 本身必须先绿：两条前提恰好推出一条结论"
    return fidA, fidB, derived[0]


def _flatten(steps):
    """嵌套 steps 树拍平：判据数「2 条事实步 + 1 条规则步」用。"""
    out = []
    for step in steps:
        out.append(step)
        out.extend(_flatten(step.get("steps") or []))
    return out


class TestExplainDerivation:
    def test_derivedFactProjectsRuleStepAndFactSteps(self, store, engine):
        fidA, fidB, fidDerived = _derivationFixture(store, engine)

        out = explainDerivation(store, fidDerived)

        assert out["conclusion"] == {"subject": "甲", "predicate": "part_of",
                                     "object": "丙"}
        flat = _flatten(out["steps"])
        kinds = sorted(s["kind"] for s in flat)
        assert kinds == ["fact", "fact", "rule"], "2 条事实步 + 1 条规则步"
        ruleSteps = [s for s in flat if s["kind"] == "rule"]
        assert len(ruleSteps) == 1
        assert ruleSteps[0]["ref"] == "part_of_transitive"
        assert sorted(ruleSteps[0]["premiseIds"]) == sorted([fidA, fidB])
        ledgerPremises = sorted(p["premise_fact_id"] for p in
                                store._derivationLedger.premisesOf(fidDerived))
        assert sorted(ruleSteps[0]["premiseIds"]) == ledgerPremises, \
            "premiseIds 必须与账本记录逐条一致"
        factRefs = sorted(s["ref"] for s in flat if s["kind"] == "fact")
        assert factRefs == sorted([fidA, fidB])
        assert out["missing"] == []

    def test_textNamesRuleAndBothPremiseTriples(self, store, engine):
        _, _, fidDerived = _derivationFixture(store, engine)

        text = explainDerivation(store, fidDerived)["text"]

        assert "part_of_transitive" in text, "text 必须含规则 id"
        assert "甲 part_of 乙" in text, "text 必须含前提一的三元组文本"
        assert "乙 part_of 丙" in text, "text 必须含前提二的三元组文本"
        assert "由规则" in text and "从前提" in text and "推出" in text

    def test_assertedFactIsSingleFactStep(self, store):
        fidA = _admit(store, "甲", "part_of", "乙")

        out = explainDerivation(store, fidA)

        assert out["conclusion"] == {"subject": "甲", "predicate": "part_of",
                                     "object": "乙"}
        assert len(out["steps"]) == 1
        step = out["steps"][0]
        assert step["kind"] == "fact"
        assert step["ref"] == fidA
        assert step["premiseIds"] == []
        assert out["missing"] == []
        assert "事实" in out["text"], "断言事实的解释要落在「事实」语义上"
        assert "甲 part_of 乙" in out["text"]

    def test_unknownFactRaisesHonestly(self, store):
        with pytest.raises(ValueError):
            explainDerivation(store, "fact_not_there")

    def test_maxDepthTruncatesIntoMissing(self, store, engine):
        _admit(store, "甲", "part_of", "乙")
        _admit(store, "乙", "part_of", "丙")
        _admit(store, "丙", "part_of", "丁")
        engine.registerRule("part_of_transitive", "part_of", PART_OF)
        engine.fireAll(agentId="default")
        # report["derived"] 只含末轮新增；二级结论从账本全量取
        top = None
        for fid in store._derivationLedger.derivedFactIds():
            f = store.fact(fid)
            label = (store.subjectFor(f["subject_key"]) or {}).get("canonical_label")
            if f["object_term"] == "丁" and label == "甲":
                top = fid
        assert top is not None, "fixture 本身必须先绿：应推出二级结论 甲 part_of 丁"

        out = explainDerivation(store, top, maxDepth=1)

        assert out["steps"] and out["steps"][0]["kind"] == "rule", \
            "顶层规则步仍要展开"
        assert any(m.get("reason") == "depth" for m in out["missing"]), \
            "深层派生前提被截断时必须显式记入 missing"

        full = explainDerivation(store, top)
        assert "其中" in full["text"], "多级推导的 text 用「；其中」逐级衔接"


class TestExplainDerivationCycle:
    def test_cycleIsPrunedIntoMissing(self, store):
        """手工往账本插成环边（账本 API 允许，推理层不会产出）：解释器必须剪枝并点名。"""
        fidA = _admit(store, "甲", "part_of", "乙")
        fidB = _admit(store, "乙", "part_of", "甲")
        rule = {"rule_id": "cycle_rule", "version": "v1", "stratification_level": 0}
        ledger = store._derivationLedger
        ledger.recordDerivation(fidA, [fidB], rule)
        ledger.recordDerivation(fidB, [fidA], rule)

        out = explainDerivation(store, fidA)

        assert out["steps"] and out["steps"][0]["kind"] == "rule"
        assert any(m.get("reason") == "cycle" for m in out["missing"]), \
            "成环前提必须剪枝并显式记入 missing（reason=cycle）"


class TestExplainProof:
    def test_twoLevelTreeProjectsWithSameShape(self):
        tree = {
            "goal": {"subject": "甲", "predicate": "part_of", "object": "丙"},
            "steps": [{
                "kind": "rule", "ref": "part_of_transitive",
                "binding": {"X": "甲", "Y": "乙", "Z": "丙"},
                "premiseIds": ["f1", "f2"],
                "sub": [
                    {"kind": "fact", "ref": "f1",
                     "goal": {"subject": "甲", "predicate": "part_of", "object": "乙"}},
                    {"kind": "fact", "ref": "f2",
                     "goal": {"subject": "乙", "predicate": "part_of", "object": "丙"}},
                ],
            }],
            "missing": [],
        }

        out = explainProof(tree)

        assert out["conclusion"] == {"subject": "甲", "predicate": "part_of",
                                     "object": "丙"}
        assert len(out["steps"]) == 1
        step = out["steps"][0]
        assert step["kind"] == "rule"
        assert step["ref"] == "part_of_transitive"
        assert step["premiseIds"] == ["f1", "f2"]
        assert step["binding"] == {"X": "甲", "Y": "乙", "Z": "丙"}
        assert [s["kind"] for s in step["steps"]] == ["fact", "fact"]
        assert [s["ref"] for s in step["steps"]] == ["f1", "f2"]
        assert out["missing"] == []
        assert "part_of_transitive" in out["text"]
        assert "甲 part_of 乙" in out["text"]
        assert "乙 part_of 丙" in out["text"]
        assert "由规则" in out["text"] and "推出" in out["text"]

    def test_missingCarriesThrough(self):
        tree = {
            "goal": {"subject": "甲", "predicate": "part_of", "object": "丙"},
            "steps": [],
            "missing": [{"goal": {"subject": "甲", "predicate": "part_of",
                                  "object": "乙"}, "reason": "no_rule"}],
        }

        out = explainProof(tree)

        assert out["missing"] == [{"goal": {"subject": "甲", "predicate": "part_of",
                                            "object": "乙"}, "reason": "no_rule"}]
        assert out["steps"] == []
