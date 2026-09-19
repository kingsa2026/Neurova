"""溯源段：断言与活动记账（工单 005，设计文档 §4.2 溯源层、§5 段6、G01）。

核心判据：任一事实能回答"谁、何时、经哪条管线、依据什么原始陈述进来"，
且**匿名知识进不了咽喉**——不接受降级、不补默认断言。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import AdmissionRequest, KnowledgeAdmissionGate
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.lineage import (
    ACTIVITY_KINDS,
    ACTOR_TYPES,
    KnowledgeLineageLedger,
)


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


@pytest.fixture
def ledger(store):
    return KnowledgeLineageLedger(store, toolVersion="005-test")


def _assertion(**overrides):
    payload = dict(
        actorType="user", actorId="u1", mediumRef="manual:知识页",
        statementText="记忆层含时序事实底座",
    )
    payload.update(overrides)
    return payload


def _request(**overrides):
    payload = dict(
        agentId="bench", subjectLabel="神经瓦", predicateTermId="describes",
        objectTerm="记忆层", content="神经瓦的记忆层含时序事实底座。",
        assertions=[_assertion()],
    )
    payload.update(overrides)
    return AdmissionRequest(**payload)


class TestActivityLedger:
    def test_activityRoundTripRecordsKindAndBasis(self, store, ledger):
        activityId = ledger.openActivity("import", inputs={"file": "note.txt"}, basis="005 用例")

        ledger.closeActivity(activityId, outputs={"facts": 1})

        row = store.activity(activityId)
        assert row["activity_kind"] == "import"
        assert row["basis"] == "005 用例"
        assert row["finished_at"]
        assert row["tool_version"] == "005-test"

    def test_unknownActivityKindIsRejected(self, ledger):
        with pytest.raises(ValueError, match="activity_kind"):
            ledger.openActivity("teleport")

    def test_everyDeclaredKindIsUsable(self, ledger):
        for kind in ACTIVITY_KINDS:
            assert ledger.openActivity(kind)


class TestAssertionLedger:
    @pytest.mark.parametrize("missing", ["actorType", "actorId", "statementText"])
    def test_incompleteAssertionIsRejectedNamingTheDimension(self, store, ledger, missing):
        factId = store.upsertFact("bench", "subj_x", "describes", "记忆层", "正文甲")
        assertion = _assertion()
        assertion[missing] = ""

        with pytest.raises(ValueError) as exc:
            ledger.attach(factId, [assertion])

        assert missing in str(exc.value), "错误信息必须指名缺哪一维"

    def test_unknownActorTypeIsRejected(self, store, ledger):
        factId = store.upsertFact("bench", "subj_y", "describes", "记忆层", "正文乙")

        with pytest.raises(ValueError, match="actor_type"):
            ledger.attach(factId, [_assertion(actorType="ghost")])

    def test_assertionsAccumulateAcrossSources(self, store, ledger):
        """一事实多来源：同一条事实可被不同主体各自断言，不互相覆盖。"""
        factId = store.upsertFact("bench", "subj_z", "describes", "记忆层", "正文丙")

        ledger.attach(factId, [_assertion(actorId="u1")])
        ledger.attach(factId, [_assertion(actorId="u2", mediumRef="manual:API")])

        rows = ledger.assertionsFor(factId)
        assert [r["actor_id"] for r in rows] == ["u1", "u2"]
        assert store.fact(factId)["assertion_count"] == 2

    def test_identicalAssertionIsNotDuplicated(self, store, ledger):
        factId = store.upsertFact("bench", "subj_w", "describes", "记忆层", "正文丁")

        ledger.attach(factId, [_assertion()])
        ledger.attach(factId, [_assertion()])

        assert len(ledger.assertionsFor(factId)) == 1

    def test_traceLineageWalksAssertionToActivity(self, store, ledger):
        factId = store.upsertFact("bench", "subj_v", "describes", "记忆层", "正文戊")
        activityId = ledger.openActivity("extract", inputs={"from": "会话 turn-9"}, basis="NER 抽取")
        ledger.attach(factId, [_assertion(actorType="pipeline", actorId="extractor-1")],
                      activityId=activityId)
        ledger.closeActivity(activityId)

        chain = ledger.traceLineage(factId)

        assert len(chain) == 1
        hop = chain[0]
        assert hop["actor_type"] == "pipeline" and hop["medium_ref"] == "manual:知识页"
        assert hop["activity_kind"] == "extract"
        assert hop["statement_text"] == "记忆层含时序事实底座"

    def test_traceLineageOnUnknownFactIsEmptyNotCrash(self, ledger):
        assert ledger.traceLineage("fact_nope") == []


class TestAdmissionEnforcesProvenance:
    def test_admitWithoutAssertionsIsRefusedOnceLineageIsWired(self, store, ledger):
        gate = KnowledgeAdmissionGate(store, lineageLedger=ledger)

        with pytest.raises(ValueError, match="断言") as exc:
            gate.admit(_request(assertions=[]), allowPendingSegments=True)

        assert store.factCount() == 0, "拒绝必须在写入之前，不是写完再回滚"
        assert "actor" in str(exc.value).lower() or "actorType" in str(exc.value)

    def test_admitWritesAssertionAndActivity(self, store, ledger):
        gate = KnowledgeAdmissionGate(store, lineageLedger=ledger)

        receipt = gate.admit(_request(), allowPendingSegments=True)

        rows = ledger.assertionsFor(receipt.factId)
        assert len(rows) == 1 and rows[0]["actor_id"] == "u1"
        assert receipt.lineageApplied is True
        assert "lineage" not in receipt.pendingSegments

    def test_gateWithoutLedgerStillReportsLineagePending(self, store):
        gate = KnowledgeAdmissionGate(store)

        receipt = gate.admit(_request(), allowPendingSegments=True)

        assert "lineage" in receipt.pendingSegments
        assert receipt.lineageApplied is False

    def test_sourceTurnIdIsCarriedOntoTheFact(self, store, ledger):
        gate = KnowledgeAdmissionGate(store, lineageLedger=ledger)

        receipt = gate.admit(_request(sourceTurnId="turn-42"), allowPendingSegments=True)

        assert store.fact(receipt.factId)["source_turn_id"] == "turn-42"
