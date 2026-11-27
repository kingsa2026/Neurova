# -*- coding: utf-8 -*-
"""P1-1 三臂对照门禁（对照研究 reference_y 报告 §5，2026-11-19）红灯。

对方 Check 的本仓等价物：候选（术语/规则/事实）上线前，在**克隆副本**里
先演一遍，与基线臂对照：

- 臂1 baseline：现库对候选事实 dry-run（零成本）；
- 臂2 draft：副本内应用术语/规则假设 → 注入候选事实 → 引擎到不动点；
- 臂3 replay：臂1 同参重放（确定性对照，不一致＝环境不稳直接 fail）。

gate 判定：候选在草稿臂出现「基线通过、草稿违规」的倒退、候选/推导写入
被咽喉拒绝，或注入与推导后的 post-state 新增 violation 即 fail；存量违规
不连坐，纯新增合法推导不拦（shifts 如实随报告返回）。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import AdmissionRequest, productionAdmissionGate
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.pipeline import checkGate
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "kb.db"))
    yield s
    s.close()


def _admit(store, subject, predicate, obj, tenantId="default"):
    content = "%s %s %s" % (subject, predicate, obj)
    return productionAdmissionGate(store).admit(AdmissionRequest(
        agentId="default", tenantId=tenantId,
        subjectLabel=subject, predicateTermId=predicate,
        objectTerm=obj, content=content,
        assertions=[{"actorType": "pipeline", "actorId": "test",
                     "mediumRef": "test", "statementText": content}],
        activityKind="admit", activityBasis="test seed"))


def _seedTypedSubject(store):
    """生产库已有带类型主体：客户:甲 is_a company（类型先登记，主体经咽喉写入后挂类型）。"""
    registry = OntologyTermRegistry(store)
    registry.register("company", "concept", label="Company")
    receipt = _admit(store, "客户:甲", "is_a", "company")
    registry.assignSubjectType(receipt.subjectKey, "company")
    return receipt


class TestCheckGate:

    def test_passWhenCandidatesClean(self, store):
        registry = OntologyTermRegistry(store)
        registry.register("located_in", "relation", label="位于")
        out = checkGate(store, "default", "default", factCandidates=[
            {"subjectLabel": "客户:甲", "predicateTermId": "located_in",
             "objectTerm": "shanghai"}])
        assert out["gate"] == "pass"
        assert out["arms"]["baseline"]["violations"] == 0
        # 臂3 重放与臂1 幂等（确定性校验）
        assert out["arms"]["replay"]["verdicts"] == out["arms"]["baseline"]["verdicts"]
        assert out["reasons"] == []

    def test_failWhenDraftRegressesCandidate(self, store):
        # 基线：lives_in 未登记 → unregistered（非 violation，pass）
        # 草稿：登记 lives_in domain=person → 主体类型 company 撞 domain → violation 倒退
        _seedTypedSubject(store)
        out = checkGate(store, "default", "default",
                        termUpserts=[{"termId": "lives_in", "kind": "relation",
                                      "domain": ["person"]}],
                        factCandidates=[
                            {"subjectLabel": "客户:甲", "predicateTermId": "lives_in",
                             "objectTerm": "shanghai"}])
        assert out["gate"] == "fail"
        assert any("regress" in r for r in out["reasons"])
        baselineVerdict = out["arms"]["baseline"]["verdicts"][0]
        draftVerdict = out["arms"]["draft"]["verdicts"][0]
        assert baselineVerdict == "pass" and draftVerdict == "violation"

    def test_failWhenReplayDrifts(self, store, monkeypatch):
        # 臂3 与臂1 不一致＝环境不稳：直接 fail（第二次 dry-run 被篡改一次）
        registry = OntologyTermRegistry(store)
        registry.register("located_in", "relation", label="位于")
        import neurova.knowledge.ontology.pipeline as pipelineModule

        original = pipelineModule.dryRunFactCandidates
        calls = {"n": 0}

        def _flaky(*args, **kwargs):
            calls["n"] += 1
            rows = original(*args, **kwargs)
            if calls["n"] == 2:  # 臂3（重放）被注入漂移
                rows = [dict(r, verdict="violation") for r in rows]
            return rows

        monkeypatch.setattr(pipelineModule, "dryRunFactCandidates", _flaky)
        out = checkGate(store, "default", "default", factCandidates=[
            {"subjectLabel": "客户:甲", "predicateTermId": "located_in",
             "objectTerm": "shanghai"}])
        assert out["gate"] == "fail"
        assert any("replay" in r for r in out["reasons"])

    def test_shiftsReportedOnPass(self, store):
        # 规则假设在草稿臂点燃出新增推导——不拦，但 shifts 如实报
        registry = OntologyTermRegistry(store)
        registry.register("located_in", "relation", label="位于", transitive=True)
        out = checkGate(store, "default", "default",
                        ruleRegistrations=[],
                        factCandidates=[
                            {"subjectLabel": "地点:甲", "predicateTermId": "located_in",
                             "objectTerm": "shanghai"}])
        assert out["gate"] == "pass"
        assert "shifts" in out and "added" in out["shifts"]

    def test_failWhenCandidateBatchIsRejectedByDisjointCheck(self, store):
        registry = OntologyTermRegistry(store)
        registry.registerMany([
            {"termId": "left", "kind": "concept"},
            {"termId": "right", "kind": "concept", "disjointWith": ["left"]},
        ])
        subject = _admit(store, "冲突主体", "is_a", "left").subjectKey
        registry.assignSubjectType(subject, "left")

        out = checkGate(store, "default", "default", factCandidates=[
            {"subjectLabel": "冲突主体", "predicateTermId": "is_a",
             "objectTerm": "right"},
        ])

        assert out["gate"] == "fail"
        assert any("post-state" in reason and "disjoint" in reason
                   for reason in out["reasons"])
        assert out["shifts"]["added"] == 1
        assert store.factCount() == 1
        assert len(registry.assertedTypesOf("default", subject)) == 1

    def test_failWhenCandidateInjectionIsRejectedAfterPrecheck(self, store):
        registry = OntologyTermRegistry(store)
        registry.register("single_value", "relation", cardinality=1)

        out = checkGate(store, "default", "default", factCandidates=[
            {"subjectLabel": "单值主体", "predicateTermId": "single_value",
             "objectTerm": "甲"},
            {"subjectLabel": "单值主体", "predicateTermId": "single_value",
             "objectTerm": "乙"},
        ])

        assert out["arms"]["baseline"]["verdicts"] == ["pass", "pass"]
        assert out["arms"]["draft"]["verdicts"] == ["pass", "pass"]
        assert out["gate"] == "fail"
        assert any("注入被拒" in note for note in out["shifts"]["notes"])
        assert out["shifts"]["added"] == 1
        assert store.factCount() == 0

    def test_failWhenTightenedDomainInvalidatesExistingFact(self, store):
        registry = OntologyTermRegistry(store)
        registry.registerMany([
            {"termId": "person", "kind": "concept"},
            {"termId": "company", "kind": "concept"},
            {"termId": "works_at", "kind": "relation"},
        ])
        receipt = _admit(store, "存量主体", "is_a", "company")
        registry.assignSubjectType(receipt.subjectKey, "company")
        factId = _admit(store, "存量主体", "works_at", "某公司").factId

        out = checkGate(store, "default", "default", termUpserts=[
            {"termId": "works_at", "kind": "relation", "domain": ["person"]},
        ])

        assert out["gate"] == "fail"
        assert any("post-state" in reason and "domain" in reason and factId in reason
                   for reason in out["reasons"])
        assert registry.term("works_at")["domain_terms"] == []
        assert store.fact(factId)["status"] == "active"

    def test_failWhenTightenedRangeInvalidatesExistingFact(self, store):
        registry = OntologyTermRegistry(store)
        registry.registerMany([
            {"termId": "person", "kind": "concept"},
            {"termId": "company", "kind": "concept"},
            {"termId": "works_at", "kind": "relation", "domain": ["person"]},
        ])
        _admit(store, "存量主体", "is_a", "person")
        factId = _admit(store, "存量主体", "works_at", "company").factId

        out = checkGate(store, "default", "default", termUpserts=[
            {"termId": "works_at", "kind": "relation", "domain": ["person"],
             "rangeTerms": ["person"]},
        ])

        assert out["gate"] == "fail"
        assert any("post-state" in reason and "range" in reason and factId in reason
                   for reason in out["reasons"])
        assert registry.term("works_at")["range_terms"] == []
        assert store.fact(factId)["status"] == "active"

    def test_failWhenTightenedCardinalityInvalidatesExistingFacts(self, store):
        registry = OntologyTermRegistry(store)
        registry.register("single_value", "relation")
        subjectKey = store.upsertSubject("default", "单值主体")
        firstId = store.upsertFact("default", subjectKey, "single_value", "甲", "甲")
        secondId = store.upsertFact("default", subjectKey, "single_value", "乙", "乙")

        out = checkGate(store, "default", "default", termUpserts=[
            {"termId": "single_value", "kind": "relation", "cardinality": 1},
        ])

        assert out["gate"] == "fail"
        assert any("post-state" in reason and "cardinality" in reason
                   and firstId in reason for reason in out["reasons"])
        assert any("post-state" in reason and "cardinality" in reason
                   and secondId in reason for reason in out["reasons"])
        assert registry.term("single_value")["cardinality"] is None
        assert store.fact(firstId)["status"] == "active"
        assert store.fact(secondId)["status"] == "active"

    def test_failWhenDerivedFactCreatesDisjointState(self, store):
        registry = OntologyTermRegistry(store)
        registry.registerMany([
            {"termId": "left", "kind": "concept"},
            {"termId": "right", "kind": "concept", "disjointWith": ["left"]},
            {"termId": "qualifies", "kind": "relation"},
        ])
        subject = _admit(store, "推导主体", "is_a", "left").subjectKey
        registry.assignSubjectType(subject, "left")
        _admit(store, "推导主体", "qualifies", "yes")

        out = checkGate(store, "default", "default", ruleRegistrations=[
            {"ruleId": "qualifies_right", "headPredicate": "is_a",
             "headObjectConst": "right",
             "body": [{"atom": "qualifies", "subject": "X", "objectConst": "yes"}]},
        ])

        assert out["gate"] == "fail"
        assert any("post-state" in reason and "disjoint" in reason
                   for reason in out["reasons"])
        assert out["shifts"]["added"] == 1
        assert store.factCount() == 2

    def test_validDerivedFactPassesAndIsReported(self, store):
        registry = OntologyTermRegistry(store)
        registry.registerMany([
            {"termId": "qualified", "kind": "concept"},
            {"termId": "qualifies", "kind": "relation"},
        ])
        _admit(store, "推导主体", "qualifies", "yes")

        out = checkGate(store, "default", "default", ruleRegistrations=[
            {"ruleId": "qualifies_class", "headPredicate": "is_a",
             "headObjectConst": "qualified",
             "body": [{"atom": "qualifies", "subject": "X", "objectConst": "yes"}]},
        ])

        assert out["gate"] == "pass"
        assert out["shifts"]["added"] == 1
        assert store.factCount() == 1

    def test_existingViolationDoesNotFailUnrelatedCleanGate(self, store):
        registry = OntologyTermRegistry(store)
        registry.registerMany([
            {"termId": "left", "kind": "concept"},
            {"termId": "right", "kind": "concept", "disjointWith": ["left"]},
        ])
        _admit(store, "存量冲突", "is_a", "left")
        _admit(store, "存量冲突", "is_a", "right")

        out = checkGate(store, "default", "default")

        assert out["gate"] == "pass"
        assert out["reasons"] == []

    def test_existingViolationDoesNotFailUnrelatedTermChange(self, store):
        registry = OntologyTermRegistry(store)
        registry.registerMany([
            {"termId": "left", "kind": "concept"},
            {"termId": "right", "kind": "concept", "disjointWith": ["left"]},
        ])
        _admit(store, "存量冲突", "is_a", "left")
        _admit(store, "存量冲突", "is_a", "right")

        out = checkGate(store, "default", "default", termUpserts=[
            {"termId": "unrelated", "kind": "concept"},
        ])

        assert out["gate"] == "pass"
        assert out["reasons"] == []

    def test_otherTenantViolationDoesNotFailCurrentTenantGate(self, store):
        registry = OntologyTermRegistry(store)
        registry.ensureSeedPredicates("acme")
        registry.register("person", "concept", tenantId="acme")
        registry.register("company", "concept", tenantId="acme")
        registry.register("works_at", "relation", tenantId="acme")
        receipt = _admit(store, "他租户主体", "is_a", "company", tenantId="acme")
        registry.assignSubjectType(receipt.subjectKey, "company", tenantId="acme")
        _admit(store, "他租户主体", "works_at", "某公司", tenantId="acme")

        out = checkGate(store, "default", "default", termUpserts=[
            {"termId": "unrelated", "kind": "concept"},
        ])

        assert out["gate"] == "pass"
        assert out["reasons"] == []
