# -*- coding: utf-8 -*-
"""P1-1 三臂对照门禁（对照研究 reference_y 报告 §5，2026-11-19）红灯。

对方 Check 的本仓等价物：候选（术语/规则/事实）上线前，在**克隆副本**里
先演一遍，与基线臂对照：

- 臂1 baseline：现库对候选事实 dry-run（零成本）；
- 臂2 draft：副本内应用术语/规则假设 → 注入候选事实 → 引擎到不动点；
- 臂3 replay：臂1 同参重放（确定性对照，不一致＝环境不稳直接 fail）。

gate 判定：候选在草稿臂出现「基线通过、草稿违规」的倒退即 fail（新增
violation）；纯新增推导不拦（shifts 如实随报告返回）。
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


def _seedTypedSubject(store):
    """生产库已有带类型主体：客户:甲 is_a company（类型先登记，主体经咽喉写入后挂类型）。"""
    registry = OntologyTermRegistry(store)
    registry.register("company", "concept", label="Company")
    gate = productionAdmissionGate(store)
    receipt = gate.admit(AdmissionRequest(
        agentId="default", tenantId="default",
        subjectLabel="客户:甲", predicateTermId="is_a", objectTerm="company",
        content="客户:甲 is_a company",
        assertions=[{"actorType": "pipeline", "actorId": "test",
                     "mediumRef": "test", "statementText": "客户:甲 is_a company"}],
        activityKind="admit", activityBasis="test seed"))
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
