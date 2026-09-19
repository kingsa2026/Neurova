"""冲突解决策略与依据（工单 007，G04）。

判据：任何 auto_resolved 的冲突都能读出 `policy_basis`；读不出的必须留在 pending。
"后写的悄悄赢"是知识库质量的主要杀手，自动裁决要么带依据，要么不动手。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.conflict_judge import (
    RESOLUTION_POLICIES,
    KnowledgeConflictJudge,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


def _fact(store, obj, *, recordedAt=None, evidence="evidenced", confidence=None, assertions=1):
    key = store.upsertSubject("a", "神经瓦")
    fid = store.upsertFact("a", key, "version", obj, "正文 " + obj,
                           confidence=confidence, recordedAt=recordedAt)
    store.setEvidenceState(fid, evidence)
    for i in range(assertions):
        store.insertAssertion(fid, "user", "u%d" % i, "manual:%d" % i, "陈述" + obj, "h%d" % i)
    return fid


def _judge(store):
    return KnowledgeConflictJudge(store)


def _record(store):
    judge = _judge(store)
    conflicts = judge.record(subjectLabel="神经瓦", predicateTermId="version")
    return judge, conflicts


class TestPolicies:
    def test_policySetIsClosed(self):
        assert set(RESOLUTION_POLICIES) == {
            "most_recent", "highest_confidence", "credibility_weighted", "keep_both", "manual",
        }

    def test_mostRecentAutoResolvesWithBasisAndSupersedesOlder(self, store):
        old = _fact(store, "1.0", recordedAt="2026-01-01T00:00:00+00:00")
        new = _fact(store, "2.0", recordedAt="2026-06-01T00:00:00+00:00")

        judge, conflicts = _record(store)
        conflict = conflicts[0]

        assert conflict["status"] == "auto_resolved"
        assert conflict["recommended_policy"] == "most_recent"
        assert "2026-06-01" in conflict["policy_basis"], "依据必须写清凭什么这条作数"
        assert store.fact(old)["status"] == "superseded"
        assert store.fact(new)["status"] == "active"

    def test_unevidencedMemberBlocksAutoResolution(self, store):
        """无证据成员在场 ⇒ 不自动裁决，且写明是哪个成员缺哪样。"""
        _fact(store, "1.0", recordedAt="2026-01-01T00:00:00+00:00")
        _fact(store, "2.0", recordedAt="2026-06-01T00:00:00+00:00", evidence="unevidenced")

        conflict = _record(store)[1][0]

        assert conflict["status"] == "pending"
        assert conflict["recommended_policy"] == "manual"
        assert "unevidenced" in conflict["policy_basis"]

    def test_confidenceTieDoesNotSilentlyPick(self, store):
        """置信相同 ⇒ 无法用 highest_confidence 定胜负，留人工而不是猜。"""
        tie = "2026-04-01T00:00:00+00:00"
        _fact(store, "1.0", confidence=0.8, recordedAt=tie)
        _fact(store, "2.0", confidence=0.8, recordedAt=tie)

        conflict = _record(store)[1][0]

        assert conflict["status"] == "pending"
        assert conflict["recommended_policy"] == "manual"

    def test_credibilityWeightedUsesAssertionSupport(self, store):
        """同记录时间时用断言支持数定胜负，依据里要出现那个数。"""
        same = "2026-03-01T00:00:00+00:00"
        _fact(store, "1.0", recordedAt=same, evidence="evidenced", assertions=3)
        _fact(store, "2.0", recordedAt=same, evidence="evidenced", assertions=1)

        conflict = _record(store)[1][0]

        assert conflict["recommended_policy"] == "credibility_weighted"
        assert "assertion" in conflict["policy_basis"] or "断言" in conflict["policy_basis"]
        assert store.fact(store.conflictWinner(conflict["conflict_id"]))["object_term"] == "1.0"

    def test_severityRisesWithBothSidesEvidenced(self, store):
        """两侧都有证据的真分歧，比一侧无据的更该被优先处理。"""
        _fact(store, "1.0", evidence="evidenced")
        _fact(store, "2.0", evidence="evidenced")
        judge = _judge(store)
        evidenced = judge.record(subjectLabel="神经瓦", predicateTermId="version")[0]["severity"]

        # 换一组主体再测，不复用同一冲突账本——避免"必须先清空账本"这种测试专用后门
        key = store.upsertSubject("a", "另一主题")
        store.upsertFact("a", key, "version", "9.0", "正文 9.0")
        store.upsertFact("a", key, "version", "8.0", "正文 8.0")
        blindFacts = store.factsForSubject(key, includeInactive=True)
        store.setEvidenceState(blindFacts[-1]["fact_id"], "unevidenced")
        blind = judge.record(subjectLabel="另一主题", predicateTermId="version")[0]["severity"]

        assert evidenced > blind


class TestStoreGuards:
    def test_autoResolveWithoutBasisIsRefusedAtStoreLevel(self, store):
        """拦在落库处而不是调用方：谁都能忘传 basis，库不能让它过。"""
        with pytest.raises(ValueError, match="policy_basis"):
            store.insertConflict(
                kind="value", subjectKey="subj_x", predicateTermId="version",
                memberFactIds=["f1", "f2"], severity=0.5,
                recommendedPolicy="most_recent", policyBasis="", status="auto_resolved",
            )
