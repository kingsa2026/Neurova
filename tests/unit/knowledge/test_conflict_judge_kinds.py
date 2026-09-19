"""冲突一等对象化 · 分类（工单 007，设计文档 §4.2 治理层、§5 段4、G03）。

要灭的病：`repository.py:1106` 只会比标题（difflib ≥0.9、仅同 agent、只记账不阻断），
而 `temporal_knowledge_graph.py:439` 与 `temporal_reasoner.py:471` 各有一套。本票先把
"分歧"升成一等对象并跨 agent，三套合一的删除动作在 017。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.conflict_judge import KnowledgeConflictJudge
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


@pytest.fixture
def judge(store):
    return KnowledgeConflictJudge(store)


def _fact(store, agent, label, predicate, obj, *, validUntil=None, evidence="evidenced", qualifier=None):
    key = store.upsertSubject(agent, label)
    fid = store.upsertFact(agent, key, predicate, obj, "正文 %s %s" % (label, obj), qualifier=qualifier)
    if validUntil:
        store.setValidUntil(fid, validUntil)
    if evidence != "evidenced":
        store.setEvidenceState(fid, evidence)
    return fid


class TestConflictKinds:
    def test_sameSubjectPredicateDifferentObjectIsValueConflict(self, store, judge):
        _fact(store, "a", "神经瓦", "version", "1.0")
        _fact(store, "a", "神经瓦", "version", "2.0")

        conflicts = judge.detect(subjectLabel="神经瓦", predicateTermId="version")

        assert len(conflicts) == 1
        assert conflicts[0]["kind"] == "value"
        assert len(conflicts[0]["member_fact_ids"]) == 2

    def test_nonOverlappingWindowsAreTemporalNotValue(self, store, judge):
        """有明确时效边界且不相交 = 事实随时间变了，不是两个值打架。"""
        _fact(store, "a", "神经瓦", "version", "1.0", validUntil="2026-01-01T00:00:00+00:00")
        _fact(store, "a", "神经瓦", "version", "2.0")

        kinds = [c["kind"] for c in judge.detect(subjectLabel="神经瓦", predicateTermId="version")]

        assert kinds == ["temporal"]

    def test_qualifierDifferenceIsNotAConflict(self, store, judge):
        """限定条件不同 = 两条各自成立的事实，不是分歧。"""
        _fact(store, "a", "记忆层", "uses", "onnx", qualifier={"env": "prod"})
        _fact(store, "a", "记忆层", "uses", "faiss", qualifier={"env": "dev"})

        assert judge.detect(subjectLabel="记忆层", predicateTermId="uses") == []

    def test_sameQualifierDifferentValueStillConflicts(self, store, judge):
        _fact(store, "a", "记忆层", "uses", "onnx", qualifier={"env": "prod"})
        _fact(store, "a", "记忆层", "uses", "faiss", qualifier={"env": "prod"})

        conflicts = judge.detect(subjectLabel="记忆层", predicateTermId="uses")

        assert [c["kind"] for c in conflicts] == ["qualifier"]

    def test_cardinalityNeedsRegistryAndSkipsWithoutIt(self, store, judge):
        """没有本体注册表就不假装会判基数——缺依据的分类会伪装成确定性。"""
        _fact(store, "a", "神经瓦", "founder", "甲")
        _fact(store, "a", "神经瓦", "founder", "乙")

        conflicts = judge.detect(subjectLabel="神经瓦", predicateTermId="founder")

        assert conflicts[0]["kind"] in ("value", "cardinality")
        assert conflicts[0]["kind"] == "value", "无注册表时按 value 报，不冒充基数判定"

    def test_crossAgentSameLabelIsCompared(self, store, judge):
        """旧实现只在同 agent 桶内比对（repository.py:1119），这是它从未报出冲突的根因之一。"""
        _fact(store, "a", "共享主题", "version", "1.0")
        _fact(store, "b", "共享主题", "version", "2.0")

        conflicts = judge.record(subjectLabel="共享主题", predicateTermId="version")

        assert len(conflicts) == 1
        assert {f["agent_id"] for f in store.conflictMembers(conflicts[0]["conflict_id"])} == {"a", "b"}


class TestConflictPersistence:
    def test_detectPersistsAndDeduplicates(self, store, judge):
        _fact(store, "a", "神经瓦", "version", "1.0")
        _fact(store, "a", "神经瓦", "version", "2.0")

        first = judge.record(subjectLabel="神经瓦", predicateTermId="version")
        second = judge.record(subjectLabel="神经瓦", predicateTermId="version")

        assert len(first) == 1 and second == [], "同一组成员重复检测不得再开一条账"
        assert store.pendingConflictCount() == 1

    def test_resolvedConflictIsQueryableByStatus(self, store, judge):
        _fact(store, "a", "神经瓦", "version", "1.0")
        _fact(store, "a", "神经瓦", "version", "2.0")
        conflict = judge.record(subjectLabel="神经瓦", predicateTermId="version")[0]

        ok = store.resolveConflict(conflict["conflict_id"], "keep_both", resolvedBy="u1")

        assert ok
        assert store.pendingConflictCount() == 0
        assert len(store.conflicts(status="resolved")) == 1

    def test_unknownResolutionValueIsRejected(self, store, judge):
        _fact(store, "a", "神经瓦", "version", "1.0")
        _fact(store, "a", "神经瓦", "version", "2.0")
        conflict = judge.record(subjectLabel="神经瓦", predicateTermId="version")[0]

        with pytest.raises(ValueError, match="未知裁决"):
            store.resolveConflict(conflict["conflict_id"], "delete_everything")
