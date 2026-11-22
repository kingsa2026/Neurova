# -*- coding: utf-8 -*-
"""U6 冲突消解只读建议面：adviseConflict 只查不写。

判据（真实 store 装配）：
- 同 (subject_key, predicate_term_id) 出现 ≥2 个不同 object 值才给建议；
- 策略闭集 latest/highest_confidence/majority_vote/source_credibility/manual_review，
  缺省按内置优先级自动选（置信可量化→highest_confidence，票数差明显→majority_vote，
  否则 manual_review）；
- 单值/无事实回 strategy="none" 的诚实形态，不造冲突；
- 严格只读：调用前后 knowledge_facts/knowledge_conflicts 逐行不变。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

T1 = "2026-11-01T10:00:00+00:00"
T2 = "2026-11-02T10:00:00+00:00"
T3 = "2026-11-03T10:00:00+00:00"


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


@pytest.fixture
def storeWithPredicate(store):
    registry = OntologyTermRegistry(store)
    registry.register("Order", "concept", label="订单")
    registry.register("hasRiskLevel", "relation", label="有风险等级",
                      domain=["Order"])
    return store


def _advise(store, *args, **kw):
    from neurova.knowledge.ontology.conflict_advice import adviseConflict

    return adviseConflict(store, *args, **kw)


def _addFact(store, subjectKey, objectTerm, confidence=None, recordedAt=None,
             agentId="default", tenantId="default", predicate="hasRiskLevel"):
    return store.upsertFact(
        agentId=agentId, subjectKey=subjectKey, predicateTermId=predicate,
        objectTerm=objectTerm,
        content="%s %s %s" % (subjectKey, predicate, objectTerm),
        confidence=confidence, recordedAt=recordedAt, tenantId=tenantId)


def _conflictedStore(store):
    """双源冲突：同一主体同谓词，高置信 '高'（旧） vs 低置信 '低'（新）。"""
    key = store.upsertSubject("default", "订单D01")
    factHigh = _addFact(store, key, "高", confidence=0.9, recordedAt=T1)
    factLow = _addFact(store, key, "低", confidence=0.4, recordedAt=T2)
    return key, factHigh, factLow


class TestAdviseConflict:
    def test_twoSourceConflictPicksHighestConfidence(self, storeWithPredicate):
        """双源冲突（0.9 vs 0.4）：自动选 highest_confidence，选中 0.9 一方并给理由。"""
        store = storeWithPredicate
        key, factHigh, factLow = _conflictedStore(store)
        result = _advise(store, "default", key, "hasRiskLevel")
        assert result["strategy"] == "highest_confidence"
        assert result["suggestedValue"] == "高"
        assert result["evidence"] == [factHigh]
        assert result["reason"], "必须带可读理由"
        assert {c["value"] for c in result["candidates"]} == {"高", "低"}
        for cand in result["candidates"]:
            assert set(cand) == {"value", "factId", "confidence", "recordedAt"}

    def test_autoMajorityVoteWhenConfidenceTied(self, storeWithPredicate):
        """置信全并列而票数 2:1 → 自动选 majority_vote，证据=赢得票值的全部事实。"""
        store = storeWithPredicate
        key = store.upsertSubject("default", "订单M")
        f1 = _addFact(store, key, "高", confidence=0.5, recordedAt=T1)
        f2 = _addFact(store, key, "高", confidence=0.5, recordedAt=T2, agentId="second")
        _addFact(store, key, "低", confidence=0.5, recordedAt=T3)
        result = _advise(store, "default", key, "hasRiskLevel")
        assert result["strategy"] == "majority_vote"
        assert result["suggestedValue"] == "高"
        assert sorted(result["evidence"]) == sorted([f1, f2])

    def test_autoManualReviewWhenNoSignal(self, storeWithPredicate):
        """置信并列且票数 1:1 → 无区分依据，显式转 manual_review。"""
        store = storeWithPredicate
        key = store.upsertSubject("default", "订单N")
        _addFact(store, key, "高", confidence=0.5, recordedAt=T1)
        _addFact(store, key, "低", confidence=0.5, recordedAt=T2)
        result = _advise(store, "default", key, "hasRiskLevel")
        assert result["strategy"] == "manual_review"
        assert result["suggestedValue"] is None
        assert len(result["evidence"]) == 2

    def test_explicitLatestWinsByRecordedAt(self, storeWithPredicate):
        """显式 latest：不论置信，取 recorded_at 最新一方。"""
        store = storeWithPredicate
        key, _factHigh, factLow = _conflictedStore(store)
        result = _advise(store, "default", key, "hasRiskLevel", strategy="latest")
        assert result["strategy"] == "latest"
        assert result["suggestedValue"] == "低"
        assert result["evidence"] == [factLow]

    def test_explicitManualReview(self, storeWithPredicate):
        store = storeWithPredicate
        key, _factHigh, _factLow = _conflictedStore(store)
        result = _advise(store, "default", key, "hasRiskLevel", strategy="manual_review")
        assert result["strategy"] == "manual_review"
        assert result["suggestedValue"] is None

    def test_sourceCredibilityWeightsBySource(self, storeWithPredicate):
        """一期以来源（agent_id）候选的平均 confidence 代理一致率：
        来源A 自相矛盾（0.9/0.1，均分 0.5），来源B 稳定（0.8）→ 采信来源B。"""
        store = storeWithPredicate
        key = store.upsertSubject("default", "订单S")
        _addFact(store, key, "高", confidence=0.9, recordedAt=T1, agentId="srcA")
        _addFact(store, key, "低", confidence=0.1, recordedAt=T2, agentId="srcA")
        factB = _addFact(store, key, "低", confidence=0.8, recordedAt=T3, agentId="srcB")
        result = _advise(store, "default", key, "hasRiskLevel",
                         strategy="source_credibility")
        assert result["strategy"] == "source_credibility"
        assert result["suggestedValue"] == "低"
        assert result["evidence"] == [factB]
        assert "confidence" in result["reason"], "代理口径必须注明"

    def test_singleValueIsHonestNone(self, storeWithPredicate):
        """单值不造冲突：strategy=none，suggestedValue=唯一值。"""
        store = storeWithPredicate
        key = store.upsertSubject("default", "订单U")
        factId = _addFact(store, key, "高", confidence=0.9, recordedAt=T1)
        result = _advise(store, "default", key, "hasRiskLevel")
        assert result["strategy"] == "none"
        assert result["suggestedValue"] == "高"
        assert result["evidence"] == [factId]
        assert len(result["candidates"]) == 1

    def test_noFactsReturnsHonestEmpty(self, storeWithPredicate):
        store = storeWithPredicate
        key = store.upsertSubject("default", "订单空")
        result = _advise(store, "default", key, "hasRiskLevel")
        assert result["strategy"] == "none"
        assert result["suggestedValue"] is None
        assert result["candidates"] == [] and result["evidence"] == []

    def test_supersededFactLeavesAdvice(self, storeWithPredicate):
        """已被取代的事实不再参与建议：取代后只剩单值 → none。"""
        store = storeWithPredicate
        key, factHigh, factLow = _conflictedStore(store)
        store.supersede(factLow, factHigh, reason="测试取代")
        result = _advise(store, "default", key, "hasRiskLevel")
        assert result["strategy"] == "none"
        assert result["suggestedValue"] == "低"

    def test_tenantScoped(self, storeWithPredicate):
        store = storeWithPredicate
        key = store.upsertSubject("default", "订单T", tenantId="t1")
        _addFact(store, key, "高", confidence=0.9, recordedAt=T1, tenantId="t1")
        seen = _advise(store, "t1", key, "hasRiskLevel")
        assert seen["strategy"] == "none" and seen["suggestedValue"] == "高"
        other = _advise(store, "t2", key, "hasRiskLevel")
        assert other["strategy"] == "none" and other["candidates"] == []

    def test_unknownStrategyRejected(self, storeWithPredicate):
        store = storeWithPredicate
        key = store.upsertSubject("default", "订单X")
        with pytest.raises(ValueError, match="未知策略"):
            _advise(store, "default", key, "hasRiskLevel", strategy="nope")

    def test_strictlyReadOnly(self, storeWithPredicate):
        """严格只读：调用前后事实表逐行不变，冲突账零新增。"""
        store = storeWithPredicate
        key, _factHigh, _factLow = _conflictedStore(store)

        def snapshot():
            return store.queryReadOnly(
                "SELECT * FROM knowledge_facts ORDER BY fact_id")

        before = snapshot()
        conflictsBefore = store.queryReadOnly(
            "SELECT COUNT(*) AS n FROM knowledge_conflicts")[0]["n"]
        _advise(store, "default", key, "hasRiskLevel")
        _advise(store, "default", key, "hasRiskLevel", strategy="manual_review")
        assert snapshot() == before
        assert store.queryReadOnly(
            "SELECT COUNT(*) AS n FROM knowledge_conflicts")[0]["n"] == conflictsBefore
