"""记录种类进咽喉（工单 019b-1，设计文档 §5）。

条目走咽喉不是为了多一张表，是为了立刻拿到它以前没有的四件东西：
内容身份、消解后的主体、断言与活动、由断言聚合出的置信度。

一条贯穿全片的纪律：**正文的唯一副本留在叙述层**。事实行只存指纹与治理字段——
在同一个库里再抄一份正文，就是这次改造要消灭的那个病。
"""

from __future__ import annotations

import pytest

from neurova.core.content_identity import normalized_key
from neurova.knowledge.foundation.admission import (
    NARRATIVE_PREDICATE,
    RECORD_KINDS,
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.backfill import LegacyFactBackfill
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.reconcile import FoundationReconciler
from neurova.knowledge.repository import KnowledgeRepository

_BODY = "蜂群并发成本护栏要限流与记账两段，护栏落在 spawn 上。" * 6
_OTHER_BODY = "先冻结基线再动读路径；尺子换了就得重跑，不能拿旧读数说新链路。"


def _assertion(actorId: str = "u1", actorType: str = "user") -> dict:
    return {"actorType": actorType, "actorId": actorId,
            "mediumRef": "unit:test", "statementText": "一条条目"}


def _triple(content: str = "甲使用乙", **over) -> AdmissionRequest:
    payload = dict(agentId="default", subjectLabel="甲", predicateTermId="uses",
                   objectTerm="乙", content=content, assertions=[_assertion()])
    payload.update(over)
    return AdmissionRequest(**payload)


def _narrative(knowledgeId: str = "k-1", content: str = _BODY, **over) -> AdmissionRequest:
    payload = dict(agentId="default", subjectLabel="蜂群并发成本护栏", recordKind="narrative",
                   objectTerm=knowledgeId, content=content, assertions=[_assertion()])
    payload.update(over)
    return AdmissionRequest(**payload)


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "facts.db"))
    yield s
    s.close()


@pytest.fixture
def gate(store):
    return productionAdmissionGate(store, toolVersion="unit")


class TestSchemaAndContract:
    def test_recordKindColumnLandsAtVersionFive(self, store):
        """新列必须走新版本号——加进已发布的 v1，老库永远不会重放它。"""
        cols = {r[1] for r in store._conn.execute("PRAGMA table_info(knowledge_facts)")}
        assert "record_kind" in cols
        assert int(store._conn.execute("PRAGMA user_version").fetchone()[0]) == 5

    def test_DefaultStaysTripleForExistingCallers(self, store, gate):
        receipt = gate.admit(_triple(), allowPendingSegments=True)
        assert store.fact(receipt.factId)["record_kind"] == "triple"

    def test_RecordKindsAreAnExplicitEnum(self):
        assert RECORD_KINDS == ("triple", "narrative")

    def test_UnknownRecordKindIsRefused(self, gate):
        with pytest.raises(ValueError, match="record_kind"):
            gate.admit(_narrative(recordKind="poem"), allowPendingSegments=True)


class TestNarrativeRecordShape:
    def test_FingerprintNotBody(self, store, gate):
        receipt = gate.admit(_narrative(), allowPendingSegments=True)
        fact = store.fact(receipt.factId)
        assert fact["content"] == "", "正文不得在事实行再抄一份"
        assert fact["content_key"] == normalized_key(_BODY)
        assert fact["predicate_term_id"] == NARRATIVE_PREDICATE
        assert fact["relation_kind"] == "document"
        # 有内容身份的叙述行以内容键立身：条目 id 编辑前后不变，拿它当客体
        # 就会让每次正文改写被三元组唯一索引吞回同一行，旧说法永不退场。
        assert fact["object_term"] == normalized_key(_BODY)
        assert fact["record_kind"] == "narrative"

    def test_EntryWithoutContentIdentityKeepsItsOwnKey(self, store, gate):
        """纯标点正文没有内容身份——这种条目仍以 knowledge_id 立身，否则客体为空。"""
        receipt = gate.admit(_narrative("k-punct", content="!!!"), allowPendingSegments=True)
        assert store.fact(receipt.factId)["object_term"] == "k-punct"
        assert store.fact(receipt.factId)["content_key"] is None

    def test_PredicateIsNotCallersToInvent(self, store, gate):
        """叙述记录的谓词由咽喉固定；调用方自带一个就是拿治理身份当自由文本。"""
        with pytest.raises(ValueError, match="谓词"):
            gate.admit(_narrative(predicateTermId="made_up"), allowPendingSegments=True)
        assert store.factCount() == 0

    def test_ObjectTermIsRequiredForNarrative(self, gate):
        with pytest.raises(ValueError, match="objectTerm"):
            gate.admit(_narrative(objectTerm=""), allowPendingSegments=True)

    def test_SubjectComesFromResolution(self, store, gate):
        first = gate.admit(_narrative("k-1"), allowPendingSegments=True)
        second = gate.admit(_narrative("k-2", subjectLabel="蜂群并发成本护栏稿",
                                       content="另一段完全不同的正文内容，长度也够。"),
                            allowPendingSegments=True)
        assert first.subjectKey == second.subjectKey

    def test_AnonymousNarrativeRefusedBeforeWrite(self, store):
        gate = productionAdmissionGate(store, toolVersion="unit")
        with pytest.raises(ValueError, match="actorType"):
            gate.admit(_narrative(assertions=[]), allowPendingSegments=True)
        assert store.factCount() == 0

    def test_ConfidenceIsAggregatedNotPassedIn(self, store, gate):
        """G11：0.7 那种硬编码从此没有落点——置信只能由断言结构算出来。"""
        with pytest.raises(TypeError):
            AdmissionRequest(agentId="default", subjectLabel="甲", objectTerm="乙",
                             content="乙", confidence=0.7)
        one = gate.admit(_narrative("k-1"), allowPendingSegments=True)
        assert store.fact(one.factId)["confidence"] == pytest.approx(0.45)

        second = gate.admit(_narrative("k-2", subjectLabel="另一个条目主体名称",
                                       content=_OTHER_BODY,
                                       assertions=[_assertion("u1"), _assertion("u2")]),
                            allowPendingSegments=True)
        assert store.fact(second.factId)["confidence"] == pytest.approx(0.60)


class TestReadSurfaceGuard:
    def test_NarrativeRowsStayOutOfSearchPoolByDefault(self, store, gate):
        """事实行没正文。默认放它进池子，读面就成了一池空文本。"""
        gate.admit(_narrative(), allowPendingSegments=True)
        gate.admit(_triple(), allowPendingSegments=True)
        assert [f["record_kind"] for f in store.searchableFacts()] == ["triple"]
        assert len(store.searchableFacts(includeNarratives=True)) == 2

    def test_SameContentAcrossKindsFoldsOntoFirstWriter(self, store, gate):
        """内容身份优先于三元组：同内容只有一条知识，谁先来谁的定义就成立。"""
        triple = gate.admit(_triple(content=_BODY), allowPendingSegments=True)
        dupe = gate.admit(_narrative(content=_BODY), allowPendingSegments=True)
        assert dupe.factId == triple.factId
        assert store.factCount() == 1
        assert store.fact(triple.factId)["record_kind"] == "triple"


class TestLegacyMappingBecomesHonest:
    """旧条目本来就是文档，回填却把它们伪造成三元组——表示法改对，数字不许动。"""

    def test_BackfilledRowsAreNarrative(self, store, tmp_path):
        repo = KnowledgeRepository(str(tmp_path / "kb"))
        repo.create_knowledge("default", "蜂群并发成本护栏", _BODY,
                              owner_user_id="u1", source="import:note.txt")
        repo.create_knowledge("default", "检索评测台架", _OTHER_BODY, owner_user_id="u1")
        before = FoundationReconciler.reconcile(repo, str(tmp_path / "replay.db"))

        LegacyFactBackfill.run(repo, store)
        kinds = {r[0] for r in store._conn.execute(
            "SELECT DISTINCT record_kind FROM knowledge_facts")}
        assert kinds == {"narrative"}
        withBody = store._conn.execute(
            "SELECT COUNT(*) FROM knowledge_facts WHERE content != ''").fetchone()[0]
        assert withBody == 0
        keyed = store._conn.execute(
            "SELECT COUNT(*) FROM knowledge_facts WHERE content_key IS NOT NULL").fetchone()[0]
        assert keyed == store.factCount() == before["actual"]["facts"]
        assert store.subjectCount() == before["actual"]["subjects"]

    def test_DeletedEntriesAreNotBackfilled(self, store, tmp_path):
        repo = KnowledgeRepository(str(tmp_path / "kb"))
        item = repo.create_knowledge("default", "会被删掉的条目", "正文足够长以产生内容身份键值",
                                     owner_user_id="u1")
        repo.delete_knowledge("default", item["knowledge_id"], deleted_by="u1")
        LegacyFactBackfill.run(repo, store)
        assert store.factCount() == 0
