"""咽喉装配口径必须单源（015 判据漏洞的根因位）。

实测取证：同一份旧库、同一份 `_requestsFromRepository` 映射，
`LegacyFactBackfill.run()` 落 88 个主体，`FoundationReconciler.reconcile()` 落 87 个，
两边却都报"自洽"——因为对账只拿"预测 vs 自己的回放"互相作证。

根因不是算法，是**装配**：backfill 造的门没接 `resolver`（身份消解退回精确名），
reconcile 造的门接了 resolver 却没接血缘与置信。同一个"唯一咽喉"被两处各自装配，
就再也不是一个咽喉。所以这里守两件事：造门只有一个入口；两个写入器必须同数。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.backfill import LegacyFactBackfill
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.reconcile import FoundationReconciler
from neurova.knowledge.identity.subject_resolver import SubjectResolver
from neurova.knowledge.repository import KnowledgeRepository

# 一对"精确名不等、但确定性消解该判同一主体"的标题；正文必须不同，
# 否则会在内容去重段就被折叠，走不到身份消解。
_NEAR_A = "知识库统一底座设计"
_NEAR_B = "知识库统一底座设计稿"


@pytest.fixture
def repo(tmp_path) -> KnowledgeRepository:
    kb = KnowledgeRepository(str(tmp_path / "kb"))
    kb.create_knowledge("default", _NEAR_A, "底座把事实与叙述收在同一权威源上",
                        owner_user_id="u1", detect_conflict=False)
    kb.create_knowledge("default", _NEAR_B, "设计稿补了扩展-收缩四阶段的出口判据",
                        owner_user_id="u1", detect_conflict=False)
    kb.create_knowledge("default", "检索评测台架", "先冻结基线再动读路径",
                        owner_user_id="u1", detect_conflict=False)
    return kb


class TestSampleIsSharp:
    def test_titlesMergeOnlyUnderResolver(self, repo):
        """样本不锋利的话，"两个写入器同数"这条判据就是空的。"""
        outcome = SubjectResolver().resolve(_NEAR_B, [
            {"subject_key": "s0", "canonical_label": _NEAR_A, "type_term_id": "", "aliases": []},
        ])
        assert outcome.subjectKey == "s0", "这一对必须被消解合并"
        assert sum(len(v) for v in repo._items.values()) == 3


class TestGateFactoryIsSingleSource:
    def test_factoryWiresEveryImplementedSegment(self, tmp_path):
        store = KnowledgeFactStore(str(tmp_path / "g.db"))
        try:
            gate = productionAdmissionGate(store, toolVersion="unit")
            assert gate.pendingSegments() == [], (
                "工厂必须把已实现的段全部接齐；这里冒出任何名字，"
                "说明工厂又被各自装配绕过了")
            assert gate.plannedSegments() == ["indexing"], (
                "尚未建成的段另立一栏，不进拒写判据")
        finally:
            store.close()

    def test_admitThroughFactoryReportsNoCorePending(self, tmp_path):
        store = KnowledgeFactStore(str(tmp_path / "g.db"))
        try:
            receipt = productionAdmissionGate(store).admit(
                AdmissionRequest(agentId="default", subjectLabel="甲",
                                 predicateTermId="uses", objectTerm="乙", content="甲使用乙",
                                 assertions=[{"actorType": "user", "actorId": "u1",
                                              "mediumRef": "unit", "statementText": "甲使用乙"}]),
                allowPendingSegments=True,
            )
            assert "identity_resolution" not in receipt.pendingSegments
            assert receipt.lineageApplied is True
        finally:
            store.close()

    def test_factoryGateStillDemandsAnActor(self, tmp_path):
        """装配齐了以后，"无主知识"必须在写入前被拒——这条不许为了回填方便而放宽。"""
        store = KnowledgeFactStore(str(tmp_path / "g.db"))
        try:
            with pytest.raises(ValueError, match="actorType"):
                productionAdmissionGate(store).admit(
                    AdmissionRequest(agentId="default", subjectLabel="甲",
                                     predicateTermId="uses", objectTerm="乙", content="甲使用乙"),
                    allowPendingSegments=True,
                )
            assert store.factCount() == 0
        finally:
            store.close()


class TestTwoWritersMustAgree:
    """015 缺的那条判据：backfill 与 reconcile 对同一份旧库必须同数。"""

    def test_backfillAndReconcileAgree(self, repo, tmp_path):
        replayDb = str(tmp_path / "replay.db")
        report = FoundationReconciler.reconcile(repo, replayDb)

        store = KnowledgeFactStore(str(tmp_path / "backfill.db"))
        try:
            backfill = LegacyFactBackfill.run(repo, store)
            facts, subjects = store.factCount(), store.subjectCount()
        finally:
            store.close()

        assert report["actual"]["facts"] == facts
        assert report["actual"]["subjects"] == subjects, (
            "两个写入器对同一份旧库给出不同主体数——咽喉被各自装配，统一底座就是空话")

    def test_reconcileIsSelfConsistentToo(self, repo, tmp_path):
        report = FoundationReconciler.reconcile(repo, str(tmp_path / "replay.db"))
        assert report["ok"], report["diffs"]
