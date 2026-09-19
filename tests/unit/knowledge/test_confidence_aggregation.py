"""置信度由断言聚合得出（工单 009，G11、§5 段5）。

定义式必须写清它**不是**什么：这个数回答"该来源历史采纳后的支持强度"，
不等于真值度量；没有任何断言时它是 NULL + unevidenced，而不是一个客气的默认值。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import AdmissionRequest, KnowledgeAdmissionGate
from neurova.knowledge.foundation.conflict_judge import KnowledgeConflictJudge
from neurova.knowledge.foundation.credibility import ConfidenceAggregator
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.lineage import KnowledgeLineageLedger


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


def _factWithAssertions(store, obj, assertionSpecs, contradictedBy=None):
    key = store.upsertSubject("a", "神经瓦")
    fid = store.upsertFact("a", key, "version", obj, "正文 " + obj)
    for index, (actorType, actorId) in enumerate(assertionSpecs):
        store.insertAssertion(fid, actorType, actorId, "manual:%d" % index, "陈述 %s %d" % (obj, index),
                              "hash%d_%s" % (index, obj))
    if contradictedBy:
        store.markContradicted(fid, contradictedBy)
    return fid


class TestAggregationDefinition:
    def test_noAssertionsMeansNullNotAPoliteDefault(self, store):
        fid = _factWithAssertions(store, "1.0", [])

        assert store.fact(fid)["confidence"] is None
        assert store.fact(fid)["evidence_state"] == "unevidenced"

    def test_moreIndependentSourcesScoreHigher(self, store):
        one = _factWithAssertions(store, "1.0", [("user", "u1")])
        three = _factWithAssertions(store, "2.0",
                                    [("user", "u1"), ("agent", "u2"), ("pipeline", "u3")])

        assert store.fact(three)["confidence"] > store.fact(one)["confidence"]

    def test_sameActorRepeatDoesNotBuyConfidence(self, store):
        """同一主体从同一来源反复陈述不算互证——否则自说自话就能把置信顶上去。"""
        fid = _factWithAssertions(store, "1.0", [])
        for _ in range(4):
            store.insertAssertion(fid, "user", "u1", "manual:same", "同一句陈述", "same_hash")

        rows = store.assertions(fid)
        assert len(rows) == 1, "同 actor + 同来源 + 同陈述应被唯一索引合成一条"

        agg = ConfidenceAggregator()
        fact = store.fact(fid)
        solo = agg.aggregate(fact, rows)["confidence"]
        secondSource = dict(rows[0], actor_id="u2", medium_ref="manual:other",
                            statement_hash="other_hash")
        pair = agg.aggregate(fact, rows + [secondSource])["confidence"]
        assert pair > solo

    def test_contradictedFactIsPenalised(self, store):
        clean = _factWithAssertions(store, "1.0", [("user", "u1"), ("agent", "u2")])
        hit = _factWithAssertions(store, "2.0", [("user", "u1"), ("agent", "u2")],
                                  contradictedBy=["fact_other"])

        assert store.fact(hit)["confidence"] < store.fact(clean)["confidence"]

    def test_confidenceNeverReachesAbsoluteOne(self, store):
        fid = _factWithAssertions(store, "1.0", [
            ("user", "u1"), ("agent", "u2"), ("pipeline", "u3"), ("importer", "u4"), ("user", "u5"),
        ])

        assert store.fact(fid)["confidence"] <= 0.95

    def test_aggregatorIsPureAndReplayable(self, store):
        agg = ConfidenceAggregator()
        fact = store.fact(_factWithAssertions(store, "1.0", [("user", "u1")]))
        assertions = store.assertions(fact["fact_id"])

        first = agg.aggregate(fact, assertions)
        second = agg.aggregate(fact, assertions)

        assert first == second
        assert first["confidence"] is not None

    def test_definitionIsStatedAsSupportNotTruth(self, store):
        agg = ConfidenceAggregator()

        assert "真值" in agg.__doc__ or "不等于" in agg.definition()


class TestGateSegmentFive:
    def test_admitSetsConfidenceFromItsOwnAssertion(self, store, tmp_path):
        ledger = KnowledgeLineageLedger(store)
        gate = KnowledgeAdmissionGate(store, lineageLedger=ledger,
                                      credibility=ConfidenceAggregator(store))

        receipt = gate.admit(
            AdmissionRequest(agentId="a", subjectLabel="神经瓦", predicateTermId="version",
                             objectTerm="1.0", content="导入路径硬编码的置信度该退休了。",
                             assertions=[{"actorType": "user", "actorId": "u1",
                                          "mediumRef": "manual:x", "statementText": "陈述"}]),
            allowPendingSegments=True,
        )

        fact = store.fact(receipt.factId)
        assert fact["confidence"] is not None and 0 < fact["confidence"] <= 0.95
        assert fact["evidence_state"] == "evidenced"
        assert "credibility_record" not in receipt.pendingSegments

    def test_conflictRecordingMarksBothSidesContradicted(self, store):
        """007 只记冲突账、没回写 contradicted_by —— 本票补上，否则矛盾对读侧永远隐形。"""
        judge = KnowledgeConflictJudge(store)
        a = _factWithAssertions(store, "1.0", [("user", "u1")])
        b = _factWithAssertions(store, "2.0", [("user", "u2")])

        judge.record(subjectLabel="神经瓦", predicateTermId="version")

        assert store.fact(a)["contradicted_by"] and store.fact(b)["contradicted_by"]


class TestContradictionMerge:
    def test_markContradictedMergesInsteadOfOverwriting(self, store):
        """多次标记要累加。曾经 `_requireFact` 只回 status 列，把这里静默变成每次都覆盖。"""
        fid = _factWithAssertions(store, "1.0", [("user", "u1")])

        store.markContradicted(fid, ["fact_a"])
        store.markContradicted(fid, ["fact_b"])

        assert store.fact(fid)["contradicted_by"] == ["fact_a", "fact_b"]

    def test_repeatedSameCounterpartyIsIdempotent(self, store):
        fid = _factWithAssertions(store, "2.0", [("user", "u1")])

        store.markContradicted(fid, ["fact_a"])
        store.markContradicted(fid, ["fact_a"])

        assert store.fact(fid)["contradicted_by"] == ["fact_a"]
