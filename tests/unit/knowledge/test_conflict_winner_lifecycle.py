"""冲突胜出必须在落账时仍是 active 事实，退休事实不能接管矛盾说法。"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.conflict_judge import KnowledgeConflictJudge
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

PAST = "2020-01-01T00:00:00+00:00"
OLD = "2026-01-01T00:00:00+00:00"
NEW = "2026-06-01T00:00:00+00:00"


@pytest.fixture
def store(tmp_path):
    instance = KnowledgeFactStore(str(tmp_path / "conflict_winners.db"))
    yield instance
    instance.close()


def _facts(store):
    subjectKey = store.upsertSubject("default", "神经瓦")
    older = store.upsertFact(
        "default", subjectKey, "version", "1.0", "旧说法", recordedAt=OLD)
    newer = store.upsertFact(
        "default", subjectKey, "version", "2.0", "新说法", recordedAt=NEW)
    return older, newer


def _pendingConflict(store, *factIds):
    return store.insertConflict(
        kind="value", subjectKey=store.resolveSubjectKey("default", "神经瓦"),
        predicateTermId="version", memberFactIds=list(factIds), severity=0.6,
        recommendedPolicy="manual", policyBasis="等待人工裁决")


def _retire(store, factId, state):
    if state == "superseded":
        replacement = store.upsertFact(
            "default", store.fact(factId)["subject_key"], "version", "3.0", "替代说法")
        store.supersede(replacement, factId, reason="测试退休")
        return
    if state == "expired":
        store.setValidUntil(factId, PAST)
        store.expireDueFacts(now=NEW)
        return
    if state == "retracted":
        store.retract(factId, reason="测试退休")
        return
    raise AssertionError("未知退休状态: %s" % state)


@pytest.mark.parametrize("state", ["superseded", "expired", "retracted"])
def test_manualSupersedeRejectsRetiredWinnerBeforeClosingConflict(store, state):
    older, newer = _facts(store)
    conflictId = _pendingConflict(store, older, newer)
    _retire(store, newer, state)
    store.retract(older, reason="让旧实现跳过败方状态迁移")
    winnerHistory = store.history(newer)
    loserHistory = store.history(older)

    with pytest.raises(ValueError, match="active"):
        store.resolveConflict(
            conflictId, "supersede_old", resolvedBy="admin", winnerFactId=newer)

    pending = store.conflicts("pending")
    assert [row["conflict_id"] for row in pending] == [conflictId]
    assert pending[0]["winner_fact_id"] is None
    assert store.conflicts("resolved") == []
    assert store.history(newer) == winnerHistory
    assert store.history(older) == loserHistory


@pytest.mark.parametrize("state", ["superseded", "expired", "retracted"])
def test_autoConflictInsertRejectsRetiredWinner(store, state):
    older, newer = _facts(store)
    _retire(store, newer, state)

    with pytest.raises(ValueError, match="active"):
        store.insertConflict(
            kind="value", subjectKey=store.resolveSubjectKey("default", "神经瓦"),
            predicateTermId="version", memberFactIds=[older, newer], severity=0.6,
            recommendedPolicy="most_recent", policyBasis="新说法更新",
            status="auto_resolved", winnerFactId=newer)

    assert store.conflicts("auto_resolved") == []


def test_autoConflictInsertRejectsWinnerOutsideMembers(store):
    older, newer = _facts(store)
    outsider = store.upsertFact(
        "default", store.resolveSubjectKey("default", "神经瓦"),
        "version", "3.0", "冲突外说法")

    with pytest.raises(ValueError, match="成员"):
        store.insertConflict(
            kind="value", subjectKey=store.resolveSubjectKey("default", "神经瓦"),
            predicateTermId="version", memberFactIds=[older, newer], severity=0.6,
            recommendedPolicy="most_recent", policyBasis="错误胜出",
            status="auto_resolved", winnerFactId=outsider)

    assert store.conflicts("auto_resolved") == []


def test_nonSupersedeResolutionCannotPersistWinner(store):
    older, newer = _facts(store)
    conflictId = _pendingConflict(store, older, newer)
    store.retract(newer, reason="测试退休")

    with pytest.raises(ValueError, match="supersede_old"):
        store.resolveConflict(
            conflictId, "dismiss", resolvedBy="admin", winnerFactId=newer)

    assert [row["conflict_id"] for row in store.conflicts("pending")] == [conflictId]


def test_manualSupersedeRollsBackWhenDerivedRetirementFails(store, monkeypatch):
    older, newer = _facts(store)
    third = store.upsertFact(
        "default", store.resolveSubjectKey("default", "神经瓦"),
        "version", "3.0", "第三个说法", recordedAt="2026-07-01T00:00:00+00:00")
    conflictId = _pendingConflict(store, older, newer, third)
    histories = {factId: store.history(factId) for factId in (older, newer, third)}
    calls = []

    def failSecondRetirement(factId, reason):
        calls.append(factId)
        if len(calls) == 2:
            raise RuntimeError("测试推导退休失败")
        return 0

    monkeypatch.setattr(store, "_retireDerived", failSecondRetirement)

    with pytest.raises(RuntimeError, match="推导退休失败"):
        store.resolveConflict(
            conflictId, "supersede_old", resolvedBy="admin", winnerFactId=newer)

    assert [row["conflict_id"] for row in store.conflicts("pending")] == [conflictId]
    assert store.conflict(conflictId)["winner_fact_id"] is None
    assert all(store.fact(factId)["status"] == "active" for factId in (older, third))
    assert store.fact(newer)["status"] == "active"
    assert {factId: store.history(factId) for factId in histories} == histories


def test_activeWinnerStillRetiresActiveLoser(store):
    older, newer = _facts(store)
    conflictId = _pendingConflict(store, older, newer)

    assert store.resolveConflict(
        conflictId, "supersede_old", resolvedBy="admin", winnerFactId=newer) is True

    resolved = store.conflicts("resolved")
    assert len(resolved) == 1 and resolved[0]["winner_fact_id"] == newer
    assert store.fact(newer)["status"] == "active"
    assert store.fact(older)["status"] == "superseded"


def test_nestedBatchFailureRollsBackOnlyInnerScope(store):
    with store.batchScope():
        outerKey = store.upsertSubject("default", "外层主体")
        with pytest.raises(RuntimeError, match="内层失败"):
            with store.batchScope():
                innerKey = store.upsertSubject("default", "内层主体")
                raise RuntimeError("内层失败")
        afterKey = store.upsertSubject("default", "内层之后主体")

    assert store.subjectFor(outerKey) is not None
    assert store.subjectFor(innerKey) is None
    assert store.subjectFor(afterKey) is not None
    assert store.connection.scopeDepth == 0
    assert store.connection.in_transaction is False


def test_batchScopeDoesNotCommitCallerTransaction(store):
    subjectKey = store.upsertSubject("default", "外层事务主体")

    with pytest.raises(RuntimeError, match="调用方回滚"):
        with store.connection:
            store.connection.execute(
                "UPDATE knowledge_subjects SET canonical_label = ? WHERE subject_key = ?",
                ("外层改动", subjectKey),
            )
            with store.batchScope():
                store.connection.execute(
                    "UPDATE knowledge_subjects SET canonical_label = ? WHERE subject_key = ?",
                    ("嵌套改动", subjectKey),
                )
            raise RuntimeError("调用方回滚")

    assert store.subjectFor(subjectKey)["canonical_label"] == "外层事务主体"
    assert store.connection.scopeDepth == 0
    assert store.connection.in_transaction is False


def test_autoConflictRecordDoesNotCommitOuterBatch(store):
    older, newer = _facts(store)
    for factId in (older, newer):
        store.setEvidenceState(factId, "evidenced")

    with pytest.raises(RuntimeError, match="外层批次失败"):
        with store.batchScope():
            KnowledgeConflictJudge(store).record("神经瓦", "version")
            assert len(store.conflicts("auto_resolved")) == 1
            raise RuntimeError("外层批次失败")

    assert store.conflicts("auto_resolved") == []
    assert store.fact(older)["status"] == "active"
    assert store.fact(newer)["status"] == "active"


def test_autoResolutionRollsBackWhenDerivedRetirementFails(store, monkeypatch):
    older, newer = _facts(store)
    for factId in (older, newer):
        store.setEvidenceState(factId, "evidenced")
    histories = {factId: store.history(factId) for factId in (older, newer)}

    def failRetirement(factId, reason):
        raise RuntimeError("测试自动裁决推导退休失败")

    monkeypatch.setattr(store, "_retireDerived", failRetirement)

    with pytest.raises(RuntimeError, match="自动裁决推导退休失败"):
        KnowledgeConflictJudge(store).record("神经瓦", "version")

    assert store.conflicts("auto_resolved") == []
    assert store.conflicts("pending") == []
    assert all(store.fact(factId)["status"] == "active" for factId in (older, newer))
    assert {factId: store.history(factId) for factId in histories} == histories
    assert all(not store.fact(factId)["contradicted_by"] for factId in (older, newer))


def test_autoResolutionRevalidatesWinnerAtConflictWrite(store, monkeypatch):
    older, newer = _facts(store)
    for factId in (older, newer):
        store.setEvidenceState(factId, "evidenced")
    originalInsert = store.insertConflict
    histories = {factId: store.history(factId) for factId in (older, newer)}

    def retireWinnerAtWrite(**kwargs):
        store.retract(kwargs["winnerFactId"], reason="模拟裁决写入前退休")
        return originalInsert(**kwargs)

    monkeypatch.setattr(store, "insertConflict", retireWinnerAtWrite)

    with pytest.raises(ValueError, match="active"):
        KnowledgeConflictJudge(store).record("神经瓦", "version")

    assert store.conflicts("auto_resolved") == []
    assert store.fact(newer)["status"] == "active"
    assert store.fact(older)["status"] == "active"
    assert {factId: store.history(factId) for factId in histories} == histories
