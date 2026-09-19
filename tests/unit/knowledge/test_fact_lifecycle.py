"""事实生命周期（工单 008，设计文档 §4.2 事实层、G06）。

示踪弹：一条事实被取代 / 到期 / 撤销之后，检索候选里不能再看到它，
但溯源查询必须还能读到它——可撤销，不可遗忘。
命名口径：方法 camelCase，落库列名与返回行 dict 保持 snake_case。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

AGENT = "bench"


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "lifecycle.db"))
    yield s
    s.close()


def _subject(store, label="神经瓦") -> str:
    return store.upsertSubject(AGENT, label)


def _fact(store, subjectKey: str, objectTerm: str, predicateTermId: str = "has_component") -> str:
    return store.upsertFact(AGENT, subjectKey, predicateTermId, objectTerm,
                            "神经瓦含有%s。" % objectTerm)


def _retire(store, state: str, subjectKey: str) -> str:
    """把一条事实送进指定的非 active 态，返回该 fact_id。"""
    if state == "active":
        return _fact(store, subjectKey, "在位说法")
    if state == "superseded":
        old = _fact(store, subjectKey, "旧说法")
        store.supersede(_fact(store, subjectKey, "新说法"), old)
        return old
    if state == "expired":
        due = _fact(store, subjectKey, "已过时效的说法")
        store.setValidUntil(due, "2026-09-01T00:00:00+00:00")
        store.expireDueFacts(now="2026-09-20T00:00:00+00:00")
        return due
    if state == "retracted":
        gone = _fact(store, subjectKey, "被撤回的说法")
        store.retract(gone, reason="008 用例")
        return gone
    raise AssertionError("未知状态: %s" % state)


class TestSupersede:
    def test_supersededFactLeavesRetrievalCandidates(self, store):
        key = _subject(store)
        old = _fact(store, key, "旧说法")
        new = _fact(store, key, "新说法")

        store.supersede(new, old, reason="口径更新")

        candidates = store.factsForSubject(key)
        assert [f["fact_id"] for f in candidates] == [new]
        assert store.fact(old)["status"] == "superseded"

    def test_supersededFactStaysReadableForLineage(self, store):
        key = _subject(store)
        old = _fact(store, key, "旧说法")
        new = _fact(store, key, "新说法")

        store.supersede(new, old)

        traceable = store.factsForSubject(key, includeInactive=True)
        assert {f["fact_id"] for f in traceable} == {old, new}
        assert store.fact(old) is not None

    def test_newFactRecordsItsPredecessor(self, store):
        key = _subject(store)
        old = _fact(store, key, "旧说法")
        new = _fact(store, key, "新说法")

        store.supersede(new, old)

        assert store.fact(new)["supersedes_fact_id"] == old
        assert store.fact(old)["supersedes_fact_id"] is None

    def test_supersedeRefusesSelfReference(self, store):
        key = _subject(store)
        only = _fact(store, key, "唯一说法")

        with pytest.raises(ValueError, match="自身"):
            store.supersede(only, only)

    @pytest.mark.parametrize("which", ["new", "old"])
    def test_supersedeRequiresBothFactsToExist(self, store, which):
        key = _subject(store)
        real = _fact(store, key, "真事实")
        args = (real, "fact_missing") if which == "new" else ("fact_missing", real)

        with pytest.raises(LookupError, match="fact_missing"):
            store.supersede(*args)

    def test_supersedeRefusesAlreadyRetiredOldFact(self, store):
        key = _subject(store)
        old = _fact(store, key, "旧说法")
        store.retract(old)

        with pytest.raises(ValueError, match="retracted"):
            store.supersede(_fact(store, key, "新说法"), old)

    def test_supersedeRefusesAlreadySupersededNewFact(self, store):
        """取代关系是"活着的说法接管"——已被取代的初代没有承接班资格。"""
        key = _subject(store)
        first = _fact(store, key, "初代")
        second = _fact(store, key, "二代")
        store.supersede(second, first)

        with pytest.raises(ValueError, match="superseded"):
            store.supersede(first, _fact(store, key, "三代"))


class TestExpiry:
    def test_expireDueFactsFlipsOnlyOverdueActive(self, store):
        key = _subject(store)
        due = _fact(store, key, "到期说法")
        future = _fact(store, key, "未到期说法")
        undated = _fact(store, key, "无时效说法")
        store.setValidUntil(due, "2026-09-01T00:00:00+00:00")
        store.setValidUntil(future, "2099-01-01T00:00:00+00:00")

        expiredCount = store.expireDueFacts(now="2026-09-20T00:00:00+00:00")

        assert expiredCount == 1
        assert store.fact(due)["status"] == "expired"
        assert store.fact(future)["status"] == "active"
        assert store.fact(undated)["status"] == "active"

    def test_expiryIsDrivenByExplicitCallNotByReading(self, store):
        """到期靠显式调用，不靠隐式扫描：账上状态在调用前不得被偷偷改写。"""
        key = _subject(store)
        due = _fact(store, key, "到期说法")
        store.setValidUntil(due, "2026-09-01T00:00:00+00:00")

        assert store.fact(due)["status"] == "active"

        store.expireDueFacts(now="2026-09-20T00:00:00+00:00")
        assert store.fact(due)["status"] == "expired"

    def test_expiredFactLeavesCandidatesButStaysTraceable(self, store):
        key = _subject(store)
        due = _fact(store, key, "到期说法")
        live = _fact(store, key, "在位说法")
        store.setValidUntil(due, "2026-09-01T00:00:00+00:00")

        store.expireDueFacts(now="2026-09-20T00:00:00+00:00")

        assert [f["fact_id"] for f in store.factsForSubject(key)] == [live]
        assert due in {f["fact_id"] for f in store.factsForSubject(key, includeInactive=True)}

    def test_expireDueFactsIsRepeatable(self, store):
        key = _subject(store)
        due = _fact(store, key, "到期说法")
        store.setValidUntil(due, "2026-09-01T00:00:00+00:00")

        store.expireDueFacts(now="2026-09-20T00:00:00+00:00")
        again = store.expireDueFacts(now="2026-09-21T00:00:00+00:00")

        assert again == 0

    def test_validUntilIsComparedAsInstantNotAsText(self, store):
        """+08:00 的 05:00 早于 UTC 的 00:00 —— 按字面比会把已到期读成未到期。"""
        key = _subject(store)
        due = _fact(store, key, "带时区的到期说法")
        store.setValidUntil(due, "2026-09-20T05:00:00+08:00")

        assert store.expireDueFacts(now="2026-09-20T00:00:00+00:00") == 1
        assert store.fact(due)["status"] == "expired"

    def test_validUntilAcceptsZSuffixAndNaiveStamp(self, store):
        key = _subject(store)
        dueZ = _fact(store, key, "Z 后缀说法")
        dueNaive = _fact(store, key, "无时区说法")
        store.setValidUntil(dueZ, "2026-09-01T00:00:00Z")
        store.setValidUntil(dueNaive, "2026-09-01T00:00:00")

        assert store.expireDueFacts(now="2026-09-20T00:00:00Z") == 2

    def test_expireDueFactsWithoutExplicitNowUsesCurrentInstant(self, store):
        key = _subject(store)
        due = _fact(store, key, "过去说法")
        future = _fact(store, key, "将来说法")
        store.setValidUntil(due, "2000-01-01T00:00:00+00:00")
        store.setValidUntil(future, "2099-01-01T00:00:00+00:00")

        assert store.expireDueFacts() == 1
        assert store.fact(future)["status"] == "active"

    def test_expireDueFactsRejectsUnparsableInstant(self, store):
        with pytest.raises(ValueError):
            store.expireDueFacts(now="不是时间")

    def test_setValidUntilGuardsItsOwnInputs(self, store):
        key = _subject(store)
        factId = _fact(store, key, "说法")

        with pytest.raises(LookupError, match="fact_missing"):
            store.setValidUntil("fact_missing", "2026-09-01T00:00:00+00:00")
        with pytest.raises(ValueError):
            store.setValidUntil(factId, "不是时间")


class TestRetract:
    def test_retractSetsStatusAndTimestamp(self, store):
        key = _subject(store)
        factId = _fact(store, key, "撤回说法")

        store.retract(factId, reason="来源被证伪")

        row = store.fact(factId)
        assert row["status"] == "retracted"
        assert row["retracted_at"]

    def test_retractedFactLeavesCandidatesButIsNeverForgotten(self, store):
        """可撤销不可遗忘：撤回只出候选，不出账。"""
        key = _subject(store)
        gone = _fact(store, key, "撤回说法")
        _fact(store, key, "在位说法")

        store.retract(gone)

        assert [f["fact_id"] for f in store.factsForSubject(key)] != []
        assert gone not in {f["fact_id"] for f in store.factsForSubject(key)}
        traceable = store.factsForSubject(key, includeInactive=True)
        assert gone in {f["fact_id"] for f in traceable}
        assert store.fact(gone)["content"]

    def test_retractKeepsTheFactRow(self, store):
        key = _subject(store)
        factId = _fact(store, key, "撤回说法")
        before = store.factCount()

        store.retract(factId)

        assert store.factCount() == before

    def test_retractRequiresExistingFact(self, store):
        with pytest.raises(LookupError, match="fact_missing"):
            store.retract("fact_missing")


class TestStatusCandidateDiscipline:
    @pytest.mark.parametrize("state", ["superseded", "expired", "retracted"])
    def test_inactiveStatesNeverEnterDefaultCandidates(self, store, state):
        key = _subject(store)
        retired = _retire(store, state, key)
        live = _fact(store, key, "在位说法")

        candidates = {f["fact_id"] for f in store.factsForSubject(key)}

        assert retired not in candidates
        assert live in candidates
        assert store.fact(retired)["status"] == state

    @pytest.mark.parametrize("state", ["active", "superseded", "expired", "retracted"])
    def test_allStatesVisibleToLineageQuery(self, store, state):
        key = _subject(store)
        retired = _retire(store, state, key)

        traceable = {f["fact_id"] for f in store.factsForSubject(key, includeInactive=True)}

        assert retired in traceable


class TestEvidenceStateDiscipline:
    def test_newFactStartsUnevidencedNotEvidenced(self, store):
        """默认值不能是 evidenced——没回写过就不得算作通过（ADR 0016 三态纪律）。"""
        key = _subject(store)
        factId = _fact(store, key, "无证据说法")

        assert store.fact(factId)["evidence_state"] == "unevidenced"

    @pytest.mark.parametrize("state", ["evidenced", "failed", "unevidenced"])
    def test_threeStatesAreDistinctlyStorable(self, store, state):
        key = _subject(store)
        factId = _fact(store, key, "说法")

        store.setEvidenceState(factId, state)

        assert store.fact(factId)["evidence_state"] == state

    def test_failedIsNotCollapsedIntoUnevidenced(self, store):
        key = _subject(store)
        failed = _fact(store, key, "被证伪说法")
        blind = _fact(store, key, "无回执说法")

        store.setEvidenceState(failed, "failed")

        assert store.fact(failed)["evidence_state"] == "failed"
        assert store.fact(blind)["evidence_state"] == "unevidenced"

    @pytest.mark.parametrize("illegal", [None, "", "passed", "success", "EVIDENCED"])
    def test_illegalEvidenceStateIsRefused(self, store, illegal):
        key = _subject(store)
        factId = _fact(store, key, "说法")

        with pytest.raises(ValueError):
            store.setEvidenceState(factId, illegal)

    def test_evidenceStateRequiresExistingFact(self, store):
        with pytest.raises(LookupError, match="fact_missing"):
            store.setEvidenceState("fact_missing", "evidenced")

    def test_lifecycleTransitionsDoNotTouchEvidenceState(self, store):
        key = _subject(store)
        old = _fact(store, key, "旧说法")
        store.setEvidenceState(old, "failed")

        store.retract(_fact(store, key, "撤回说法"))
        store.supersede(_fact(store, key, "新说法"), old)

        assert store.fact(old)["evidence_state"] == "failed"


class TestLifecycleAcrossSubjects:
    def test_expireDueFactsSweepsEverySubject(self, store):
        """到期巡检是全局动作：各主体的事实按各自的时效窗判定。"""
        keyA = _subject(store, "主体甲")
        keyB = _subject(store, "主体乙")
        dueA = _fact(store, keyA, "甲到期说法")
        liveB = _fact(store, keyB, "乙未到期说法")
        store.setValidUntil(dueA, "2026-09-01T00:00:00+00:00")
        store.setValidUntil(liveB, "2099-01-01T00:00:00+00:00")

        store.expireDueFacts(now="2026-09-20T00:00:00+00:00")

        assert store.factsForSubject(keyA) == []
        assert [f["fact_id"] for f in store.factsForSubject(keyB)] == [liveB]
