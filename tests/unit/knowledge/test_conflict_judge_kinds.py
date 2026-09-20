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


def _doc(store, agent, label, kid, obj=None, predicate="documented_as"):
    """条目库搬进来的形状：叙述记录，谓词固定 documented_as，客体是内容键，条目 id 在溯源上。

    直插 SQL 不走咽喉，所以要手工补 `evidence_state`——真叙述行带着断言进来，
    不会停在列默认值 `unevidenced`（那会被裁决判成"无据可依，不许自动取代"）。
    """
    key = store.upsertSubject(agent, label)
    factId = store.upsertFact(agent, key, predicate, obj or ("key-" + kid), "正文 %s" % kid,
                              relationKind="document", recordKind="narrative",
                              sourceTurnId="entry:%s" % kid)
    store.setEvidenceState(factId, "evidenced")
    return factId


class TestNarrativeConflictScope:
    """叙述行的分歧范围是"同一条目的先后说法"，不是"同一个标题下的所有正文"。

    真数据取证（019b-4b）：生产 130 条搬进底座后，5 行叙述被"最新正文"裁决成
    superseded，10 条条目因此永远查不到 active 治理行——装载即报投影分叉且永不收敛，
    因为 admit 按内容键折回的还是那条非活动行。三条都叫 `note` 的条目是三份文档，
    不是同一说法的三个值；而条目改正文必须留下被取代的旧说法（019b-2 判据，不能松）。
    """

    def test_distinctBodiesUnderOneTitleAreNotAConflict(self, store, judge):
        older = _doc(store, "default", "note", "k1")
        _doc(store, "default", "note", "k2")

        assert judge.detect(subjectLabel="note", predicateTermId="documented_as") == []
        assert judge.record(subjectLabel="note", predicateTermId="documented_as") == []
        assert store.fact(older)["status"] == "active"
        assert store.pendingConflictCount() == 0

    def test_editOfTheSameEntryIsJudgedAndOldRowSuperseded(self, store, judge):
        """同一条目的两版正文才是分歧：新说法胜出，旧说法留痕。"""
        old = _doc(store, "default", "反思反哺链", "k9", obj="key-v1")
        new = _doc(store, "default", "反思反哺链", "k9", obj="key-v2")

        conflicts = judge.detect(subjectLabel="反思反哺链", predicateTermId="documented_as")

        assert [c["kind"] for c in conflicts] == ["value"]
        assert set(conflicts[0]["member_fact_ids"]) == {old, new}
        judge.record(subjectLabel="反思反哺链", predicateTermId="documented_as")
        assert store.fact(old)["status"] == "superseded"
        assert store.fact(new)["status"] == "active"

    def test_scopeIsTheEntryIdNotTheProvenancePrefix(self, store, judge):
        """回填写 `legacy:<kid>`、账本写 `entry:<kid>`，同一条目不能因前缀不同分家。"""
        key = store.upsertSubject("default", "带前缀的条目")
        backfilled = store.upsertFact("default", key, "documented_as", "key-v1", "正文一",
                                      relationKind="document", recordKind="narrative",
                                      sourceTurnId="legacy:k7")
        edited = store.upsertFact("default", key, "documented_as", "key-v2", "正文二",
                                  relationKind="document", recordKind="narrative",
                                  sourceTurnId="entry:k7")

        conflicts = judge.detect(subjectLabel="带前缀的条目", predicateTermId="documented_as")

        assert set(conflicts[0]["member_fact_ids"]) == {backfilled, edited}

    def test_triplesAreNotAffectedByTheNarrativeScope(self, store, judge):
        """过滤认的是记录身份，不是 relation_kind 那个字面：三元组即便自称 document 照旧判。"""
        key = store.upsertSubject("a", "神经瓦")
        store.upsertFact("a", key, "version", "1.0", "正文一", relationKind="document")
        store.upsertFact("a", key, "version", "2.0", "正文二", relationKind="document")

        conflicts = judge.detect(subjectLabel="神经瓦", predicateTermId="version")

        assert [c["kind"] for c in conflicts] == ["value"]

    def test_narrativeIsNotCarriedIntoATripleConflict(self, store, judge):
        """同一 (主体, 谓词) 上若混进叙述行，它既不当成员也不被牵连取代。

        生产不会出现这种混群（叙述只走 documented_as），但规则要写成"按条目划范围"，
        而不是"整组放行"或"整组送进取代"。
        """
        key = store.upsertSubject("a", "神经瓦")
        docId = store.upsertFact("a", key, "documented_as", "k1", "正文一",
                                 relationKind="document", recordKind="narrative",
                                 sourceTurnId="entry:k1")
        _fact(store, "a", "神经瓦", "documented_as", "k2")
        _fact(store, "a", "神经瓦", "documented_as", "k3")

        conflicts = judge.detect(subjectLabel="神经瓦", predicateTermId="documented_as")

        assert [c["kind"] for c in conflicts] == ["value"]
        members = conflicts[0]["member_fact_ids"]
        assert docId not in members and len(members) == 2
        judge.record(subjectLabel="神经瓦", predicateTermId="documented_as")
        assert store.fact(docId)["status"] == "active", "裁决不许顺手把条目正文取代掉"

    def test_narrativeWithoutProvenanceCannotConflictWithAnything(self, store, judge):
        """溯源为空的叙述行没有条目归属——按客体自锁，不并进来也不被顶掉。"""
        key = store.upsertSubject("a", "无溯源条目")
        first = store.upsertFact("a", key, "documented_as", "o1", "正文一",
                                 relationKind="document", recordKind="narrative")
        second = store.upsertFact("a", key, "documented_as", "o2", "正文二",
                                  relationKind="document", recordKind="narrative")

        assert judge.detect(subjectLabel="无溯源条目", predicateTermId="documented_as") == []
        assert store.fact(first)["status"] == "active" and store.fact(second)["status"] == "active"
